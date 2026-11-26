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
import os
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
    long_only: bool = False  # small accounts: no shorts
    vehicle: str = "fut"  # "fut" (stock futures, carry) or "delivery" (cash stock, fully paid)


def side_cost(price: float, side: Side, d: date, cfg: HoldConfig) -> float:
    qty = max(1, int(cfg.notional // price))
    kind, product = (Kind.FUT, Product.CARRY) if cfg.vehicle == "fut" else (Kind.EQ, Product.DELIVERY)
    ch = charges(kind, product, side, qty, price, d).total
    return ch / (qty * price) + cfg.slippage_bps / 1e4


def rebalance(
    longs: set[str], shorts: set[str], ranked: list[str], k: int, exit_k: int
) -> tuple[set[str], set[str], list[str], list[str]]:
    """The book's one rule, shared by the backtest and the live trader.

    `ranked` is best-first. A held long stays while inside the top `exit_k`, a held short while inside the bottom
    `exit_k`; free slots are filled from the top / bottom. Returns (keep_long, keep_short, new_long, new_short).
    """
    rank = {s: i for i, s in enumerate(ranked)}
    n = len(ranked)
    keep_l = {s for s in longs if s in rank and rank[s] < exit_k}
    keep_s = {s for s in shorts if s in rank and rank[s] >= n - exit_k}
    new_l = [s for s in ranked if s not in keep_l and s not in keep_s][: k - len(keep_l)]
    new_s = [s for s in reversed(ranked) if s not in keep_s and s not in keep_l and s not in new_l]
    return keep_l, keep_s, new_l, new_s[: k - len(keep_s)]


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
        info = {r["symbol"]: r for r in day.iter_rows(named=True)}

        keep_l, keep_s, new_l, new_s = rebalance(longs, shorts, syms, cfg.k, cfg.exit_k)
        if cfg.long_only:
            keep_s, new_s = set(), []
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
        slots = cfg.k if cfg.long_only else 2 * cfg.k
        bench = sum(ret(s, "next_lr") for s in syms) / len(syms)  # equal-weight universe, close to close
        rows.append(
            {
                "date": d,
                "bench": bench,
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
        "bench_annual": f(daily["bench"].mean()) * 252 if "bench" in daily.columns else 0.0,
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
    r.add_argument("--long-only", action="store_true")
    r.add_argument("--vehicle", choices=["fut", "delivery"], default="fut")
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
        cfg = HoldConfig(k=a.k, exit_k=ek, notional=a.notional, long_only=a.long_only, vehicle=a.vehicle)
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
    lines = [
        "| exit_k | annual | sharpe | max_dd | cost bps/day | trades/day | "
        + " | ".join(str(y["year"]) for y in results[a.exit_k[0]]["yearly"] if y["year"] >= 2016)
        + " |"
    ]
    lines.append("|" + "---|" * (6 + sum(1 for y in results[a.exit_k[0]]["yearly"] if y["year"] >= 2016)))
    for ek, res in results.items():
        o = res["overall"]
        yrs = " | ".join(f"{y['annual_return']:+.0%}" for y in res["yearly"] if y["year"] >= 2016)
        lines.append(
            f"| {ek} | {o['annual_return']:+.1%} | {o['sharpe']:.2f} | {o['max_drawdown']:.1%} | "
            f"{o['cost_bps']:.1f} | {o['trades_per_day']:.1f} | {yrs} |"
        )
    first = results[a.exit_k[0]]
    bench_yrs = " | ".join(f"{y['bench_annual']:+.0%}" for y in first["yearly"] if y["year"] >= 2016)
    lines.append(f"| market (equal-weight) | {first['overall']['bench_annual']:+.1%} | | | | | {bench_yrs} |")
    mode = f"{'long-only' if a.long_only else 'long/short'} {a.vehicle}, k={a.k}, Rs {a.notional:,.0f}/position"
    md = f"### Holding book ({Path(a.preds).parent.name}; {mode})\n\n" + "\n".join(lines) + "\n"
    (out / "report.md").write_text(md)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as fh:
            fh.write(md)


if __name__ == "__main__":
    main()
