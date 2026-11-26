"""The champion model: train it weekly, score every F&O stock daily.

Recipe (chosen by walk-forward experiments, see the experiment workflow): 5-day target, F&O stocks only, base EOD
features + F&O positioning + news flow, LightGBM, trained on the latest 6 years.

    python -m t2.models.champion train     # weekly on Actions -> HF model repo champion/ (+ history/<date>/)
    python -m t2.models.champion signals   # daily on Actions  -> HF dataset signals/date=<session>.parquet
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from dataclasses import asdict
from datetime import date
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl
from huggingface_hub import HfApi, hf_hub_download

from t2.data import hf_store
from t2.features import eod, extra
from t2.models.baseline import Config, features, train

MODEL_REPO = os.environ.get("HF_MODEL_REPO", "harcorp/t2-models")
RECIPE = Config(target="y5", train_years=6, rounds=300, universe="fno", train_universe="fno", extras=("fno", "news"))
BOOK = {"k": 10, "exit_k": 50, "notional_per_position": 500_000.0}


def panel(data: Path) -> pl.DataFrame:
    """Feature panel for F&O stocks (point-in-time membership), with every feature group of the recipe."""
    root = eod.fetch(data, fno=True)
    full = eod.build(eod.load(root))
    full = extra.add_fno(full, root)
    full = extra.add_news(full, extra.fetch_news(root))
    return full.join(eod.fno_members(root), on=["date", "symbol"])


def git_sha() -> str:
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def cmd_train(data: Path) -> None:
    p = panel(data)
    last = p["date"].max()
    assert isinstance(last, date)
    window = p.filter(pl.col("date") >= date(last.year - RECIPE.train_years, 1, 1))
    model = train(window, RECIPE)
    info = hf_store.api().dataset_info(hf_store.DATASET_REPO)
    meta = {
        "trained_on": str(date.today()),
        "data_last_date": str(last),
        "train_rows": window.filter(pl.col(RECIPE.target).is_not_null()).height,
        "recipe": asdict(RECIPE),
        "book": BOOK,
        "features": features(RECIPE),
        "code_commit": git_sha(),
        "data_commit": info.sha,
    }
    with tempfile.TemporaryDirectory() as tmp:
        for sub in ("champion", f"history/{last}"):
            d = Path(tmp) / sub
            d.mkdir(parents=True)
            model.save_model(str(d / "model.txt"))
            (d / "meta.json").write_text(json.dumps(meta, indent=2))
        HfApi(token=os.environ.get("HF_TOKEN")).upload_folder(
            repo_id=MODEL_REPO, folder_path=tmp, commit_message=f"champion: trained to {last}"
        )
    print(json.dumps(meta, indent=2))


def load_champion() -> tuple[lgb.Booster, dict]:
    token = os.environ.get("HF_TOKEN")
    mp = hf_hub_download(MODEL_REPO, "champion/model.txt", token=token)
    meta = json.loads(Path(hf_hub_download(MODEL_REPO, "champion/meta.json", token=token)).read_text())
    return lgb.Booster(model_file=mp), meta


def score_latest(p: pl.DataFrame, model: lgb.Booster, feats: list[str]) -> pl.DataFrame:
    last = p["date"].max()
    day = p.filter(pl.col("date") == last)
    scores = np.asarray(model.predict(day.select(feats).to_numpy()))
    return (
        day.select("date", "symbol", "close")
        .with_columns(pl.Series("score", scores))
        .sort("score", descending=True)
        .with_row_index("rank", offset=1)
    )


def lots(root: Path, session: date) -> pl.DataFrame:
    """Near-month stock futures for the session: expiry and lot size per symbol (rolled 3+ days before expiry)."""
    fo = eod.table(root, "fo_daily").filter((pl.col("date") == session) & (pl.col("instrument") == "FUTSTK"))
    return (
        fo.filter((pl.col("expiry") - pl.col("date")).dt.total_days() >= 3)
        .sort("expiry")
        .group_by("symbol")
        .agg(
            pl.col("expiry").first().alias("fut_expiry"),
            pl.col("lot_size").first(),
            pl.col("close").first().alias("fut_close"),
        )
        .collect()
    )


def cmd_signals(data: Path, max_age_days: int) -> None:
    model, meta = load_champion()
    p = panel(data)
    sig = score_latest(p, model, meta["features"])
    session = sig["date"][0]
    age = (date.today() - session).days
    if age > max_age_days:
        raise SystemExit(f"stale data: latest session {session} is {age} days old (max {max_age_days})")
    sig = sig.join(lots(data, session), on="symbol", how="left").with_columns(
        pl.lit(meta["data_last_date"]).alias("model_data_last_date"), pl.lit(meta["code_commit"]).alias("model_commit")
    )
    missing = sig.filter(pl.col("lot_size").is_null()).height
    print(f"signals for {session}: {sig.height} stocks ({missing} without a futures lot)")
    print(sig.head(10).select("rank", "symbol", "score", "close", "lot_size"))
    print(sig.tail(10).select("rank", "symbol", "score", "close", "lot_size"))
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "signals" / f"date={session}.parquet"
        out.parent.mkdir(parents=True)
        sig.write_parquet(out)
        hf_store.upload_folder(Path(tmp), f"signals for {session} ({sig.height} stocks)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--data", default="data/hf")
    s = sub.add_parser("signals")
    s.add_argument("--data", default="data/hf")
    s.add_argument("--max-age-days", type=int, default=4, help="fail if the latest session is older (weekends+holiday)")
    a = ap.parse_args(argv)
    if a.cmd == "train":
        cmd_train(Path(a.data))
    else:
        cmd_signals(Path(a.data), a.max_age_days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
