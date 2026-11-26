"""LightGBM baseline: walk-forward, cross-sectional ranking of next-session returns. The bar every model must beat.

For each test year Y: train on the previous `train_years` years (ending `embargo_days` sessions before Y, so no
training target overlaps the test period), predict every day of Y, then score:
- IC: daily Spearman correlation between the prediction and the realised return
- portfolio: each day go long the top K and short the bottom K at the next open, exit at that day's close
  (intraday product), with Indian charges and slippage. Benchmark is the equal-weight universe (open-to-close).

    python -m t2.models.baseline run --from-year 2008 --out reports/baseline
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

from t2.brokers.base import Kind, Product, Side
from t2.features import eod, extra
from t2.trader.costs import charges

PARAMS = {
    "objective": "regression",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 2000,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.7,
    "bagging_freq": 1,
    "lambda_l2": 10.0,
    "verbosity": -1,
    "num_threads": os.cpu_count() or 4,
}


@dataclass
class Config:
    target: str = "y1"
    train_years: int = 6
    embargo_days: int = 10
    rounds: int = 300
    top_k: int = 20
    position_rs: float = 50_000.0
    slippage_bps: float = 5.0
    extras: tuple[str, ...] = ()  # extra feature groups: "fno", "news"
    universe: str = "all"  # stocks the portfolio trades: all liquid EQ, or point-in-time F&O stocks
    train_universe: str = "all"


def with_label(df: pl.DataFrame, target: str) -> pl.DataFrame:
    """Train on the cross-sectional rank of the target: the model learns which stocks beat the others today."""
    return df.filter(pl.col(target).is_not_null()).with_columns(
        ((pl.col(target).rank() / pl.col(target).count()).over("date") - 0.5).alias("label")
    )


def round_trip_cost_frac(price: float, cfg: Config, d: date) -> float:
    """Charges + slippage for one intraday buy and sell of `position_rs`, as a fraction of the position."""
    qty = max(1, int(cfg.position_rs // price))
    notional = qty * price
    ch = charges(Kind.EQ, Product.INTRADAY, Side.BUY, qty, price, d).total
    ch += charges(Kind.EQ, Product.INTRADAY, Side.SELL, qty, price, d).total
    return ch / notional + 2 * cfg.slippage_bps / 1e4


def evaluate(pred: pl.DataFrame, cfg: Config) -> dict[str, float]:
    """`pred` has date, symbol, close, score and the target. Returns IC and portfolio stats for that period."""
    t = cfg.target
    ic = (
        pred.group_by("date")
        .agg(pl.corr(pl.col("score").rank(), pl.col(t).rank()).alias("ic"))
        .get_column("ic")
        .fill_nan(None)
        .drop_nulls()
    )
    ranked = pred.with_columns(
        pl.col("score").rank("ordinal", descending=True).over("date").alias("top"),
        pl.col("score").rank("ordinal").over("date").alias("bottom"),
        (pl.col(t).exp() - 1).alias("ret"),
    )
    bench = ranked.group_by("date").agg(pl.col("ret").mean().alias("bench"))
    picks = ranked.filter((pl.col("top") <= cfg.top_k) | (pl.col("bottom") <= cfg.top_k))
    if t == "y1":
        costs = [round_trip_cost_frac(p, cfg, d) for p, d in zip(picks["close"], picks["date"], strict=True)]
        picks = picks.with_columns(pl.Series("cost", costs, dtype=pl.Float64))
    else:  # multi-day holds are not scored as a daily portfolio here
        picks = picks.with_columns(pl.lit(0.0).alias("cost"))
    daily = (
        picks.group_by("date")
        .agg(
            pl.col("ret").filter(pl.col("top") <= cfg.top_k).mean().alias("long"),
            pl.col("ret").filter(pl.col("bottom") <= cfg.top_k).mean().alias("short"),
            pl.col("cost").filter(pl.col("top") <= cfg.top_k).mean().alias("long_cost"),
            pl.col("cost").filter(pl.col("bottom") <= cfg.top_k).mean().alias("short_cost"),
        )
        .join(bench, on="date")
        .sort("date")
        .with_columns(
            (pl.col("long") - pl.col("long_cost")).alias("long_net"),
            ((pl.col("long") - pl.col("short")) / 2 - (pl.col("long_cost") + pl.col("short_cost")) / 2).alias("ls_net"),
        )
    )

    def stats(x: pl.Series) -> tuple[float, float]:
        m, sd = _num(x.mean()), _num(x.std())
        return m, (m / sd * math.sqrt(252) if sd > 0 else 0.0)

    long_m, long_sr = stats(daily["long_net"])
    ls_m, ls_sr = stats(daily["ls_net"])
    bench_m, bench_sr = stats(daily["bench"])
    ic_m, ic_sd = _num(ic.mean()), _num(ic.std())
    return {
        "days": daily.height,
        "ic_mean": ic_m,
        "ic_ir": ic_m / ic_sd * math.sqrt(252) if ic_sd > 0 else 0.0,
        "ic_hit": _num((ic > 0).mean()),
        "long_gross_bps": _num(daily["long"].mean()) * 1e4,
        "long_net_bps": long_m * 1e4,
        "long_net_sharpe": long_sr,
        "long_hit": _num((daily["long_net"] > 0).mean()),
        "ls_net_bps": ls_m * 1e4,
        "ls_net_sharpe": ls_sr,
        "bench_bps": bench_m * 1e4,
        "bench_sharpe": bench_sr,
        "cost_bps": _num(daily["long_cost"].mean()) * 1e4,
    }


def _num(x: object) -> float:
    return float(x) if isinstance(x, int | float) else 0.0


def features(cfg: Config) -> list[str]:
    groups = {"fno": extra.FNO, "news": extra.NEWS}
    return eod.FEATURES + [c for g in cfg.extras for c in groups[g]]


def train(df: pl.DataFrame, cfg: Config) -> lgb.Booster:
    data = with_label(df, cfg.target)
    ds = lgb.Dataset(data.select(features(cfg)).to_numpy(), label=data["label"].to_numpy(), free_raw_data=True)
    return lgb.train(PARAMS, ds, num_boost_round=cfg.rounds)


def walk_forward(
    panel: pl.DataFrame, years: list[int], cfg: Config, train_panel: pl.DataFrame | None = None
) -> tuple[list[dict], pl.DataFrame]:
    """Test on `panel`, train on `train_panel` (defaults to the same panel)."""
    train_panel = panel if train_panel is None else train_panel
    sessions = panel.select(pl.col("date").unique().sort()).get_column("date")
    folds, preds = [], []
    for y in years:
        test = panel.filter(pl.col("date").dt.year() == y)
        if test.is_empty():
            continue
        start = test["date"].min()
        before = sessions.filter(sessions < start)
        if before.len() <= cfg.embargo_days:
            continue
        train_end = before[-cfg.embargo_days - 1]
        train_start = date(y - cfg.train_years, 1, 1)
        tr = train_panel.filter(pl.col("date").is_between(train_start, train_end))
        t0 = time.time()
        model = train(tr, cfg)
        test = test.filter(pl.col(cfg.target).is_not_null())
        scored = test.with_columns(pl.Series("score", np.asarray(model.predict(test.select(features(cfg)).to_numpy()))))
        m = {"year": y, "train_rows": tr.height, "train_end": str(train_end), "secs": round(time.time() - t0, 1)}
        m |= evaluate(scored, cfg)
        print(json.dumps({k: round(v, 4) if isinstance(v, float) else v for k, v in m.items()}), flush=True)
        folds.append(m)
        preds.append(scored.select("date", "symbol", "score", cfg.target))
    return folds, pl.concat(preds) if preds else pl.DataFrame()


def summary_md(folds: list[dict], overall: dict, cfg: Config) -> str:
    cols = ["year", "days", "ic_mean", "ic_hit", "long_gross_bps", "long_net_bps", "long_net_sharpe", "ls_net_bps"]
    cols += ["ls_net_sharpe", "bench_bps", "cost_bps"]
    lines = [
        f"## LightGBM baseline ({cfg.target}, trade {cfg.universe}, train {cfg.train_universe}, "
        f"top/bottom {cfg.top_k}, Rs {cfg.position_rs:,.0f} per position)",
        "",
        "| " + " | ".join(cols) + " |",
        "|" + "---|" * len(cols),
    ]
    for f in [*folds, overall]:
        lines.append(
            "| "
            + " | ".join(f"{f.get(c, ''):.3f}" if isinstance(f.get(c), float) else str(f.get(c, "")) for c in cols)
            + " |"
        )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> None:
    cfg = Config(
        target=args.target,
        train_years=args.train_years,
        rounds=args.rounds,
        top_k=args.top_k,
        universe=args.universe,
        train_universe=args.train_universe,
        extras=tuple(x for x in args.extras.split(",") if x),
    )
    fno = "fno" in (cfg.universe, cfg.train_universe) or "fno" in cfg.extras
    root = eod.fetch(Path(args.data), fno=fno, offline=args.offline)
    t0 = time.time()
    full = eod.build(eod.load(root))
    if "fno" in cfg.extras:
        full = extra.add_fno(full, root)
    if "news" in cfg.extras:
        full = extra.add_news(full, extra.fetch_news(root, offline=args.offline))
    members = eod.fno_members(root) if fno else None
    pick = {"all": full, "fno": full.join(members, on=["date", "symbol"]) if members is not None else full}
    panel, train_panel = pick[cfg.universe], pick[cfg.train_universe]
    print(
        f"panel {full.height:,} rows; trade universe {cfg.universe}: {panel.height:,} rows, "
        f"{panel['symbol'].n_unique()} symbols; train universe {cfg.train_universe} ({time.time() - t0:.0f}s)",
        flush=True,
    )
    last = panel["date"].max()
    assert isinstance(last, date)
    folds, preds = walk_forward(panel, list(range(args.from_year, last.year + 1)), cfg, train_panel)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    overall = {"year": "all"} | evaluate(
        preds.join(panel.select("date", "symbol", "close"), on=["date", "symbol"]), cfg
    )
    report = {"config": asdict(cfg), "params": PARAMS, "data_last_date": str(last), "folds": folds, "overall": overall}
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    preds.select("date", "symbol", "score").write_parquet(out / "preds.parquet")  # input for the sandbox replay
    md = summary_md(folds, overall, cfg)
    (out / "report.md").write_text(md)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as fh:
            fh.write(md)
    print(md)
    # the live candidate: same recipe trained on the most recent window
    final = train(train_panel.filter(pl.col("date") >= date(last.year - cfg.train_years, 1, 1)), cfg)
    final.save_model(str(out / "model.txt"))
    (out / "features.json").write_text(json.dumps(features(cfg)))
    imp = sorted(zip(features(cfg), final.feature_importance("gain").tolist(), strict=True), key=lambda x: -x[1])
    (out / "importance.json").write_text(json.dumps(imp, indent=2))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--from-year", type=int, default=2008)
    r.add_argument("--target", choices=eod.TARGETS, default="y1")
    r.add_argument("--train-years", type=int, default=6)
    r.add_argument("--rounds", type=int, default=300)
    r.add_argument("--top-k", type=int, default=20)
    r.add_argument("--extras", default="", help="comma list of extra feature groups: fno,news")
    r.add_argument("--universe", choices=["all", "fno"], default="all")
    r.add_argument("--train-universe", choices=["all", "fno"], default="all")
    r.add_argument("--data", default="data/hf")
    r.add_argument("--offline", action="store_true", help="use data already in --data, skip the hub")
    r.add_argument("--out", default="reports/baseline")
    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
