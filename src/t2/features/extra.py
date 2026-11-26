"""Extra point-in-time features joined onto the EOD panel: stock F&O positioning and news flow.

F&O (from the daily F&O bhavcopy, one row per stock per day):
  fut_oi_chg1/5   log change in total stock-futures open interest (all expiries: no rollover jumps)
  basis_ann       near-month futures premium over the cash close, annualised
  fo_turn_ratio   log(futures turnover / cash turnover)
  pcr             log(put OI / call OI) on stock options, and its 5-day change pcr_chg5
News (from GDELT articles tagged with the stock):
  an article counts for session t if published before t's close (15:30 IST = 10:00 UTC), else the next session
  news_n1/5       log(1 + articles) over 1 and 5 sessions
  news_tone1/5    mean article tone over 1 and 5 sessions (null when there is no news)
  news_z          today's count against the stock's own 60-session norm
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, time
from pathlib import Path

import polars as pl

from t2.data.hf_store import DATASET_REPO
from t2.features.eod import table

FNO = ["fut_oi_chg1", "fut_oi_chg5", "basis_ann", "fo_turn_ratio", "pcr", "pcr_chg5"]
NEWS = ["news_n1", "news_n5", "news_tone1", "news_tone5", "news_z"]
CLOSE_UTC = time(10, 0)


def fno_daily(root: Path) -> pl.DataFrame:
    """One row per (date, symbol) for stocks with F&O, from fo_daily."""
    fo = table(root, "fo_daily").filter(pl.col("instrument").is_in(["FUTSTK", "OPTSTK"]))
    fut = fo.filter(pl.col("instrument") == "FUTSTK")
    near = (
        # near month = first contract with 3+ days left (on expiry day the annualised premium is pure noise)
        fut.filter((pl.col("expiry") - pl.col("date")).dt.total_days() >= 3)
        .sort("expiry")
        .group_by("date", "symbol")
        .agg(pl.col("close").first().alias("near_close"), pl.col("expiry").first().alias("near_expiry"))
    )
    fut_tot = fut.group_by("date", "symbol").agg(
        pl.col("oi").sum().alias("fut_oi"), pl.col("turnover").sum().alias("fut_turn")
    )
    opt = (
        fo.filter(pl.col("instrument") == "OPTSTK")
        .group_by("date", "symbol")
        .agg(
            pl.col("oi").filter(pl.col("option_type") == "CE").sum().alias("call_oi"),
            pl.col("oi").filter(pl.col("option_type") == "PE").sum().alias("put_oi"),
        )
    )
    out = fut_tot.join(near, on=["date", "symbol"], how="left").join(opt, on=["date", "symbol"], how="left")
    return out.collect()


def add_fno(panel: pl.DataFrame, root: Path) -> pl.DataFrame:
    f = fno_daily(root)
    df = panel.join(f, on=["date", "symbol"], how="left").sort("symbol", "date")
    s = "symbol"
    lo = (pl.col("fut_oi").clip(lower_bound=1)).log()
    pcr = (pl.col("put_oi").clip(lower_bound=1) / pl.col("call_oi").clip(lower_bound=1)).log()
    days = (pl.col("near_expiry") - pl.col("date")).dt.total_days().clip(lower_bound=1)
    df = df.with_columns(
        (lo - lo.shift(1).over(s)).alias("fut_oi_chg1"),
        (lo - lo.shift(5).over(s)).alias("fut_oi_chg5"),
        ((pl.col("near_close") / pl.col("close")).log() * 365 / days).clip(-1, 1).alias("basis_ann"),
        (pl.col("fut_turn").clip(lower_bound=1).log() - pl.col("lturn")).alias("fo_turn_ratio"),
        pcr.alias("pcr"),
        (pcr - pcr.shift(5).over(s)).alias("pcr_chg5"),
    )
    return df.drop("fut_oi", "fut_turn", "near_close", "near_expiry", "call_oi", "put_oi")


def fetch_news(dest: Path, offline: bool = False) -> Path:
    if not offline:
        from huggingface_hub import snapshot_download

        snapshot_download(
            DATASET_REPO,
            repo_type="dataset",
            local_dir=dest,
            allow_patterns=["news_gdelt/**"],
            token=os.environ.get("HF_TOKEN"),
            max_workers=8,
        )
    return dest


def news_by_session(root: Path, sessions: list) -> pl.DataFrame:
    """(date, symbol, n, tone_sum): articles assigned to the first session whose close is at or after publication."""
    arts = (
        pl.scan_parquet(root / "news_gdelt" / "**" / "*.parquet")
        .select("published_at", "tone", "tickers")
        .filter(pl.col("tickers").list.len() > 0)
        .explode("tickers")
        .rename({"tickers": "symbol"})
        .unique(["published_at", "symbol", "tone"])
        .sort("published_at")
        .collect()
    )
    closes = pl.DataFrame(
        {
            "date": sessions,
            "close_ts": [datetime.combine(d, CLOSE_UTC, tzinfo=UTC) for d in sessions],
        }
    ).sort("close_ts")
    arts = arts.with_columns(pl.col("published_at").dt.convert_time_zone("UTC"))
    tagged = arts.join_asof(closes, left_on="published_at", right_on="close_ts", strategy="forward")
    return (
        tagged.filter(pl.col("date").is_not_null())
        .group_by("date", "symbol")
        .agg(pl.len().alias("n"), pl.col("tone").sum().alias("tone_sum"))
    )


def add_news(panel: pl.DataFrame, root: Path) -> pl.DataFrame:
    sessions = panel.select(pl.col("date").unique().sort())["date"].to_list()
    nb = news_by_session(root, sessions)
    first_news = nb["date"].min()
    df = panel.join(nb, on=["date", "symbol"], how="left").sort("symbol", "date")
    df = df.with_columns(pl.col("n").fill_null(0), pl.col("tone_sum").fill_null(0.0))
    s = "symbol"
    n5 = pl.col("n").rolling_sum(5, min_samples=1).over(s)
    t5 = pl.col("tone_sum").rolling_sum(5, min_samples=1).over(s)
    n1 = (pl.col("n") + 1).log()
    df = df.with_columns(
        n1.alias("news_n1"),
        (n5 + 1).log().alias("news_n5"),
        pl.when(pl.col("n") > 0).then(pl.col("tone_sum") / pl.col("n")).alias("news_tone1"),
        pl.when(n5 > 0).then(t5 / n5).alias("news_tone5"),
        (
            (n1 - n1.rolling_mean(60, min_samples=20).over(s))
            / n1.rolling_std(60, min_samples=20).over(s).clip(lower_bound=0.1)
        ).alias("news_z"),
    )
    # before the archive starts there is no news signal at all: null, not zero
    df = df.with_columns(
        *[pl.when(pl.col("date") >= first_news).then(pl.col(c)).alias(c) for c in NEWS],
    )
    return df.drop("n", "tone_sum")
