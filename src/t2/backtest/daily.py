"""Daily sandbox replay: model scores -> risk manager -> PaperBroker, one trading day at a time.

Each evening after the close of day t, the strategy reads that day's scores and plans for day t+1:
long the top K and short the bottom K, intraday product, limit orders `entry_band` from t's close
(a gap past the band means no fill, like a real limit order). At 09:15 on t+1 every order goes through the
risk manager, then to the PaperBroker, which fills it against t+1's daily bar (open if the open is inside the
limit). Positions are squared off at the close. Equity, charges, fills and blocks are recorded per day.

This uses daily bars, so the fill is the opening price: optimistic. The 1-minute replay replaces this once
the Breeze intraday history is in.

    python -m t2.backtest.daily run --preds reports/baseline/preds.parquet --out reports/replay
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import polars as pl

from t2.brokers.base import Contract, Order, Product, Side, Status
from t2.brokers.paper import Bar, PaperBroker
from t2.features import eod
from t2.trader.risk import Book, Limits, RiskManager


@dataclass
class Strategy:
    top_k: int = 10
    position_rs: float = 50_000.0
    entry_band: float = 0.01
    short: bool = True
    capital: float = 1_000_000.0
    limits: Limits = field(
        default_factory=lambda: Limits(
            capital=2_000_000.0,
            max_order_value=100_000.0,
            max_position_value=100_000.0,
            max_open_positions=40,
            max_daily_loss=30_000.0,
        )
    )


def tick_round(price: float, side: Side, tick: float = 0.05) -> float:
    """Round a limit onto the tick grid, never past the intended price (buy rounds down, sell rounds up)."""
    steps = price / tick
    steps = math.floor(steps + 1e-9) if side == Side.BUY else math.ceil(steps - 1e-9)
    return round(steps * tick, 2)


def plan_orders(scores: pl.DataFrame, closes: dict[str, float], day: date, s: Strategy) -> list[Order]:
    """Orders for `day` from the previous evening's scores (highest score = long)."""
    ranked = scores.sort("score", descending=True)
    picks = [(sym, Side.BUY) for sym in ranked["symbol"].head(s.top_k)]
    if s.short:
        picks += [(sym, Side.SELL) for sym in ranked["symbol"].tail(s.top_k)]
    out, t0 = [], datetime.combine(day, time(9, 15))
    for i, (sym, side) in enumerate(picks):
        c = closes[sym]
        limit = tick_round(c * (1 + s.entry_band) if side == Side.BUY else c * (1 - s.entry_band), side)
        qty = int(s.position_rs // limit)
        if qty <= 0:
            continue
        # spaced 250 ms apart: under both the risk manager's and the broker's per-second order caps
        out.append(Order(Contract(sym), side, qty, limit, Product.INTRADAY, t0 + timedelta(milliseconds=250 * i)))
    return out


def book_of(b: PaperBroker, day_start_equity: float, last: dict[str, float]) -> Book:
    pos = {(p.contract.key, p.product.value): (p.qty, last.get(p.contract.key, p.avg_price)) for p in b.positions()}
    return Book(pos, b.equity() - day_start_equity, last)


def replay(preds: pl.DataFrame, bars: pl.DataFrame, s: Strategy) -> tuple[pl.DataFrame, dict]:
    """`preds`: date, symbol, score (decided after that date's close). `bars`: daily OHLCV per date and symbol."""
    b = PaperBroker(s.capital)
    risk = RiskManager(s.limits)
    days = bars.select(pl.col("date").unique().sort())["date"].to_list()
    next_day = dict(itertools.pairwise(days))
    by_day = {d: g for (d,), g in bars.partition_by("date", as_dict=True).items()}
    rows: list[dict] = []
    kill_days = 0
    fills_seen = 0
    for d, sc in sorted(preds.partition_by("date", as_dict=True).items(), key=lambda kv: kv[0][0]):
        today = d[0]
        nd = next_day.get(today)
        if nd is None or nd not in by_day or today not in by_day:
            continue
        closes = dict(zip(by_day[today]["symbol"], by_day[today]["close"], strict=True))
        sc = sc.filter(pl.col("symbol").is_in(list(closes)))
        start_eq = b.equity()
        if risk.kill:  # the owner reviews and releases it each morning in this simulation; counted below
            kill_days += 1
            risk.release_kill(datetime.combine(nd, time(9, 0)), by="replay")
        orders = plan_orders(sc, closes, nd, s)
        placed = blocked = rejected = 0
        for o in orders:
            decision = risk.check(o, book_of(b, start_eq, closes))
            if not decision.ok:
                blocked += 1
                continue
            b.place(o)
            if o.status == Status.REJECTED:
                rejected += 1
            else:
                placed += 1
        wanted = {o.contract.key for o in orders}
        nb = by_day[nd].filter(pl.col("symbol").is_in(list(wanted)))
        bar_ts = datetime.combine(nd, time(9, 16))  # after every order (they go out 250 ms apart from 09:15)
        for r in nb.iter_rows(named=True):
            if r["open"] and r["close"]:
                b.on_bar(r["symbol"], Bar(bar_ts, r["open"], r["high"], r["low"], r["close"], int(r["volume"] or 0)))
        for o in b.open_orders():  # whatever did not fill by the close is cancelled
            b.cancel(o.id)
        filled = sum(1 for o in orders if o.filled > 0)
        b.square_off(datetime.combine(nd, time(15, 15)))
        day_fills = b.fills_since(fills_seen)
        fills_seen += len(day_fills)
        end_eq = b.equity()
        if end_eq - start_eq <= -s.limits.max_daily_loss:
            risk.engage_kill("daily loss", datetime.combine(nd, time(15, 15)))
        rows.append(
            {
                "date": nd,
                "equity": end_eq,
                "pnl": end_eq - start_eq,
                "ret": (end_eq - start_eq) / start_eq,
                "charges": sum(f.charges for f in day_fills),
                "orders": len(orders),
                "placed": placed,
                "filled": filled,
                "blocked": blocked,
                "rejected": rejected,
            }
        )
    daily = pl.DataFrame(rows)
    return daily, summarize(daily, s, kill_days)


def summarize(daily: pl.DataFrame, s: Strategy, kill_days: int = 0) -> dict:
    if daily.is_empty():
        return {}
    r = daily["ret"]
    eq = daily["equity"]
    years = daily.height / 252
    total = _f(eq[-1]) / s.capital
    sd = _f(r.std())
    dd = _f((eq / eq.cum_max() - 1).min())
    return {
        "days": daily.height,
        "final_equity": _f(eq[-1]),
        "cagr": total ** (1 / years) - 1 if total > 0 and years > 0 else -1.0,
        "sharpe": _f(r.mean()) / sd * math.sqrt(252) if sd > 0 else 0.0,
        "max_drawdown": dd,
        "hit_rate": _f((r > 0).mean()),
        "avg_daily_bps": _f(r.mean()) * 1e4,
        "charges_total": _f(daily["charges"].sum()),
        "fill_rate": _f(daily["filled"].sum()) / max(1.0, _f(daily["placed"].sum())),
        "blocked_orders": int(_f(daily["blocked"].sum())),
        "rejected_orders": int(_f(daily["rejected"].sum())),
        "kill_days": kill_days,
    }


def _f(x: object) -> float:
    return float(x) if isinstance(x, int | float) else 0.0


def yearly(daily: pl.DataFrame) -> pl.DataFrame:
    return (
        daily.group_by(pl.col("date").dt.year().alias("year"))
        .agg(
            ((pl.col("ret") + 1).product() - 1).alias("return"),
            (pl.col("ret").mean() / pl.col("ret").std() * math.sqrt(252)).alias("sharpe"),
            (pl.col("ret") > 0).mean().alias("hit_rate"),
            pl.col("charges").sum().alias("charges"),
            (pl.col("filled").sum() / pl.col("placed").sum()).alias("fill_rate"),
        )
        .sort("year")
    )


def run(args: argparse.Namespace) -> None:
    s = Strategy(top_k=args.top_k, position_rs=args.position_rs, entry_band=args.entry_band, short=not args.long_only)
    preds = pl.read_parquet(args.preds)
    root = eod.fetch(Path(args.data), offline=args.offline)
    bars = (
        pl.scan_parquet(Path(root) / "eq_daily" / "**" / "*.parquet")
        .filter(pl.col("series").is_in(eod.SERIES) & (pl.col("date") >= preds["date"].min()))
        .select("date", "symbol", "open", "high", "low", "close", "volume")
        .unique(["date", "symbol"])
        .collect()
    )
    daily, summary = replay(preds, bars, s)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    daily.write_parquet(out / "daily.parquet")
    yr = yearly(daily)
    report = {"strategy": asdict(s), "summary": summary, "yearly": yr.to_dicts()}
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    lines = [f"## Sandbox replay (top/bottom {s.top_k}, Rs {s.position_rs:,.0f}/position, band {s.entry_band:.1%})", ""]
    lines += [f"- {k}: {v:,.4f}" if isinstance(v, float) else f"- {k}: {v}" for k, v in summary.items()]
    lines += ["", "| year | return | sharpe | hit_rate | charges | fill_rate |", "|---|---|---|---|---|---|"]
    for row in yr.iter_rows(named=True):
        lines.append(
            f"| {row['year']} | {row['return']:.2%} | {row['sharpe']:.2f} | {row['hit_rate']:.2%} | "
            f"{row['charges']:,.0f} | {row['fill_rate']:.2%} |"
        )
    md = "\n".join(lines) + "\n"
    (out / "report.md").write_text(md)
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary_path, "a") as fh:
            fh.write(md)
    print(md)


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--preds", required=True)
    r.add_argument("--top-k", type=int, default=10)
    r.add_argument("--position-rs", type=float, default=50_000.0)
    r.add_argument("--entry-band", type=float, default=0.01)
    r.add_argument("--long-only", action="store_true")
    r.add_argument("--data", default="data/hf")
    r.add_argument("--offline", action="store_true", help="use data already in --data, skip the hub")
    r.add_argument("--out", default="reports/replay")
    run(p.parse_args())


if __name__ == "__main__":
    main()
