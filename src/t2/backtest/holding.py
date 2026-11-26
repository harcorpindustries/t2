"""Multi-day long/short portfolio on stock futures, with a hold buffer to cut turnover.

Each evening (after day t's close) the model ranks the F&O stocks. The book holds K longs and K shorts:
a held long stays while it ranks inside the top `exit_k` (a buffer), and empty slots are refilled from the top K.
Orders go at day t+1's open. Returns per position for day t+1:
- new entries: open-to-close (y1)
- positions kept: close-to-close (next_lr)
- exits: close-to-open (next_gap), i.e. held overnight and closed at the open
Costs are charged only when a position is opened or closed, at stock-futures rates (STT on the sell side only),
plus slippage per side. Futures prices are proxied by the cash stock (basis moves are small day to day).

    python -m t2.backtest.holding run --preds reports/fno_train_fno/preds.parquet --offline
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import polars as pl

from t2.brokers.base import Kind, Product, Side
from t2.features import eod
from t2.trader.costs import charges


@dataclass
class HoldConfig:
    k: int = 10
    exit_k: int = 30
    notional: float = 500_000.0  # per position (roughly one stock-futures lot)
    slippage_bps: float = 5.0
    min_hold_names: int = 40  # skip days with fewer ranked names than this


def side_cost(price: float, side: Side, d: date, cfg: HoldConfig) -> float:
    qty = max(1, int(cfg.notional // price))
    ch = charges(Kind.FUT, Product.CARRY, side, qty, price, d).total
    return ch / (qty * price) + cfg.slippage_bps / 1e4


def run_book(df: pl.DataFrame, cfg: HoldConfig) -> pl.DataFrame:
    """df: date, symbol, close, score, y1, next_gap, next_lr. One output row per decision date t (P&L on t+1)."""
    longs: set[str] = set()
    shorts: set[str] = set()
    rows = []
    for (d,), day in sorted(df.partition_by("date", as_dict=True).items(), key=lambda kv: kv[0][0]):
        day = day.filter(pl.col("y1").is_not_null()).sort("score", descending=True)
        if day.height < cfg.min_hold_names:
            continue
        syms = day["symbol"].to_list()
        rank = {s: i for i, s in enumerate(syms)}
        n = len(syms)
        info = {r["symbol"]: r for r in day.iter_rows(named=True)}

        keep_l = {s for s in longs if s in rank and rank[s] < cfg.exit_k}
        keep_s = {s for s in shorts if s in rank and rank[s] >= n - cfg.exit_k}
        new_l = [s for s in syms if s not in keep_l and s not in keep_s][: cfg.k - len(keep_l)]
        new_s = [s for s in reversed(syms) if s not in keep_s and s not in keep_l and s not in new_l]
        new_s = new_s[: cfg.k - len(keep_s)]
        exit_l, exit_s = longs - keep_l, shorts - keep_s

        def ret(s: str, col: str, info: dict = info) -> float:
            v = info[s][col] if s in info else None
            return math.exp(v) - 1 if v is not None else 0.0  # vanished name: closed flat

        def price(s: str, info: dict = info) -> float:
            return info[s]["close"] if s in info else 100.0

        pnl = sum(ret(s, "next_lr") for s in keep_l) + sum(ret(s, "y1") for s in new_l)
        pnl += sum(ret(s, "next_gap") for s in exit_l)
        pnl -= sum(ret(s, "next_lr") for s in keep_s) + sum(ret(s, "y1") for s in new_s)
        pnl -= sum(ret(s, "next_gap") for s in exit_s)
        cost = sum(side_cost(price(s), Side.BUY, d, cfg) for s in new_l)
        cost += sum(side_cost(price(s), Side.SELL, d, cfg) for s in exit_l)
        cost += sum(side_cost(price(s), Side.SELL, d, cfg) for s in new_s)
        cost += sum(side_cost(price(s), Side.BUY, d, cfg) for s in exit_s)
        slots = 2 * cfg.k
        rows.append(
            {
                "date": d,
                "gross": pnl / slots,
                "cost": cost / slots,
                "ret": (pnl - cost) / slots,
                "trades": len(new_l) + len(new_s) + len(exit_l) + len(exit_s),
            }
        )
        longs, shorts = keep_l | set(new_l), keep_s | set(new_s)
    return pl.DataFrame(rows)


def stats(daily: pl.DataFrame) -> dict[str, float]:
    def f(x: object) -> float:
        return float(x) if isinstance(x, int | float) else 0.0

    r = daily["ret"]
    m, sd = f(r.mean()), f(r.std())
    eq = r.cum_sum()
    return {
        "days": daily.height,
        "annual_return": m * 252,
        "sharpe": m / sd * math.sqrt(252) if sd > 0 else 0.0,
        "max_drawdown": f((eq - eq.cum_max()).min()),
        "hit_rate": f((r > 0).mean()),
        "gross_bps": f(daily["gross"].mean()) * 1e4,
        "cost_bps": f(daily["cost"].mean()) * 1e4,
        "net_bps": m * 1e4,
        "trades_per_day": f(daily["trades"].mean()),
    }


def yearly(daily: pl.DataFrame) -> list[dict]:
    out = []
    by_year = daily.with_columns(pl.col("date").dt.year().alias("year"))
    for (y,), g in sorted(by_year.partition_by("year", as_dict=True).items(), key=lambda kv: kv[0][0]):
        out.append({"year": y} | stats(g))
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--preds", required=True)
    r.add_argument("--k", type=int, default=10)
    r.add_argument("--exit-k", type=int, nargs="+", default=[10, 20, 30, 50])
    r.add_argument("--notional", type=float, default=500_000.0)
    r.add_argument("--data", default="data/hf")
    r.add_argument("--offline", action="store_true")
    r.add_argument("--out", default="reports/holding")
    a = p.parse_args()
    preds = pl.read_parquet(a.preds)
    root = eod.fetch(Path(a.data), offline=a.offline)
    panel = eod.build(eod.load(root)).select("date", "symbol", "close", "y1", *eod.NEXT)
    df = preds.select("date", "symbol", "score").join(panel, on=["date", "symbol"])
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    results = {}
    for ek in a.exit_k:
        cfg = HoldConfig(k=a.k, exit_k=ek, notional=a.notional)
        daily = run_book(df, cfg)
        results[ek] = {"config": asdict(cfg), "overall": stats(daily), "yearly": yearly(daily)}
        o = results[ek]["overall"]
        print(
            f"exit_k={ek:3d}  annual {o['annual_return']:+.1%}  sharpe {o['sharpe']:+.2f}"
            f"  gross {o['gross_bps']:.1f}bps  cost {o['cost_bps']:.1f}bps  net {o['net_bps']:+.1f}bps"
            f"  trades/day {o['trades_per_day']:.1f}",
            flush=True,
        )
        recent = [y for y in results[ek]["yearly"] if y["year"] >= 2019]
        print("   " + "  ".join(f"{y['year']}:{y['annual_return']:+.0%}" for y in recent), flush=True)
    (out / "report.json").write_text(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
