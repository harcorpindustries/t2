"""End-of-day feature panel for every NSE equity, built from the bhavcopy and delivery tables.

Split/bonus safe without a corporate-actions table: each day's return is close / prev_close, and NSE adjusts
prev_close on ex-dates. Summing log returns gives an adjusted log-price index per symbol.

Timing rule (no look-ahead): a feature row for date t uses only data up to and including t's close.
Targets start at the next session's open, which is the earliest we can act on a decision taken after t's close.
"""

from __future__ import annotations

import os
from pathlib import Path

import polars as pl

from t2.data.hf_store import DATASET_REPO

SERIES = ("EQ",)  # BE/BZ are trade-for-trade (no intraday), SME series are illiquid
MIN_TURNOVER = 5e7  # Rs 5 crore 20-day median turnover
MIN_PRICE = 20.0
MIN_HISTORY = 120

RANKED = ["lr", "r5", "r20", "r60", "r120", "vol20", "turn_ratio", "deliv_pct", "deliv_z", "gap", "oc", "hl", "dd60"]
FEATURES = [
    "lr",
    "r5",
    "r20",
    "r60",
    "r120",
    "vol20",
    "vol60",
    "hl",
    "hl20",
    "gap",
    "oc",
    "dd60",
    "lturn",
    "turn_ratio",
    "deliv_pct",
    "deliv_z",
    "mkt_r1",
    "mkt_r5",
    "mkt_r20",
    "mkt_vol20",
    "breadth",
    "dow",
    *[f"{c}_rk" for c in RANKED],
]
TARGETS = ["y1", "y5"]


def fetch(dest: Path) -> Path:
    """Download the daily equity and delivery tables (cached by the hub client)."""
    from huggingface_hub import snapshot_download

    snapshot_download(
        DATASET_REPO,
        repo_type="dataset",
        local_dir=dest,
        allow_patterns=["eq_daily/**", "eq_delivery/**"],
        token=os.environ.get("HF_TOKEN"),
        max_workers=16,
    )
    return dest


def load(root: Path) -> pl.DataFrame:
    eq = (
        pl.scan_parquet(root / "eq_daily" / "**" / "*.parquet")
        .filter(pl.col("series").is_in(SERIES))
        .select("date", "symbol", "open", "high", "low", "close", "prev_close", "volume", "turnover")
    )
    dl = pl.scan_parquet(root / "eq_delivery" / "**" / "*.parquet").filter(pl.col("series").is_in(SERIES))
    dl = dl.select("date", "symbol", "deliverable_pct").unique(["date", "symbol"])
    return eq.join(dl, on=["date", "symbol"], how="left").unique(["date", "symbol"]).collect()


def build(raw: pl.DataFrame) -> pl.DataFrame:
    """Raw daily rows -> one row per (symbol, date) with features, universe flag and forward targets."""
    good = (pl.col("prev_close") > 0) & (pl.col("close") > 0) & (pl.col("open") > 0) & (pl.col("low") > 0)
    df = raw.filter(good).sort("symbol", "date")

    cal = df.select(pl.col("date").unique().sort()).with_row_index("di")
    df = df.join(cal, on="date").sort("symbol", "date")  # rolling/shift below need this order

    lr = (pl.col("close") / pl.col("prev_close")).log()
    df = df.with_columns(
        pl.when(lr.abs() < 1.0).then(lr).otherwise(None).alias("lr"),  # |move| > 170% in a day is bad data
        (pl.col("open") / pl.col("prev_close")).log().alias("gap"),
        (pl.col("close") / pl.col("open")).log().alias("oc"),
        (pl.col("high") / pl.col("low")).log().alias("hl"),
        pl.col("turnover").clip(lower_bound=1).log().alias("lturn"),
        pl.col("deliverable_pct").alias("deliv_pct"),
    )
    s = "symbol"
    df = df.with_columns(
        pl.col("lr").fill_null(0).cum_sum().over(s).alias("L"), pl.int_range(pl.len()).over(s).alias("n")
    )
    df = df.with_columns(
        *[(pl.col("L") - pl.col("L").shift(k).over(s)).alias(f"r{k}") for k in (5, 20, 60, 120)],
        pl.col("lr").rolling_std(20, min_samples=15).over(s).alias("vol20"),
        pl.col("lr").rolling_std(60, min_samples=40).over(s).alias("vol60"),
        pl.col("hl").rolling_mean(20, min_samples=15).over(s).alias("hl20"),
        (pl.col("L") - pl.col("L").rolling_max(60, min_samples=20).over(s)).alias("dd60"),
        (
            pl.col("turnover").rolling_mean(5, min_samples=3).over(s)
            / pl.col("turnover").rolling_mean(60, min_samples=20).over(s)
        ).alias("turn_ratio"),
        pl.col("turnover").rolling_median(20, min_samples=15).over(s).alias("liq"),
        (
            (pl.col("deliv_pct") - pl.col("deliv_pct").rolling_mean(20, min_samples=10).over(s))
            / pl.col("deliv_pct").rolling_std(20, min_samples=10).over(s)
        ).alias("deliv_z"),
        # forward targets, only when the next rows are the next sessions (no suspension gaps)
        pl.when(pl.col("di").shift(-1).over(s) == pl.col("di") + 1).then(pl.col("oc").shift(-1).over(s)).alias("y1"),
        pl.when(pl.col("di").shift(-5).over(s) == pl.col("di") + 5)
        .then(pl.col("L").shift(-5).over(s) - pl.col("L") - pl.col("gap").shift(-1).over(s))
        .alias("y5"),
    )
    df = df.with_columns(
        (
            (pl.col("liq") >= MIN_TURNOVER)
            & (pl.col("close") >= MIN_PRICE)
            & (pl.col("n") >= MIN_HISTORY)
            & pl.col("lr").is_not_null()
        ).alias("universe")
    )

    mkt = (
        df.filter("universe")
        .group_by("date")
        .agg(pl.col("lr").mean().alias("mkt_r1"), (pl.col("lr") > 0).mean().alias("breadth"))
        .sort("date")
        .with_columns(pl.col("mkt_r1").cum_sum().alias("M"))
        .with_columns(
            (pl.col("M") - pl.col("M").shift(5)).alias("mkt_r5"),
            (pl.col("M") - pl.col("M").shift(20)).alias("mkt_r20"),
            pl.col("mkt_r1").rolling_std(20, min_samples=15).alias("mkt_vol20"),
        )
        .drop("M")
    )
    df = df.join(mkt, on="date", how="left").with_columns(pl.col("date").dt.weekday().alias("dow"))

    uni = df.filter("universe")
    ranks = uni.select(
        "date", "symbol", *[(pl.col(c).rank() / pl.col(c).count()).over("date").alias(f"{c}_rk") for c in RANKED]
    )
    return uni.join(ranks, on=["date", "symbol"]).select("date", "symbol", "close", "liq", *FEATURES, *TARGETS)
