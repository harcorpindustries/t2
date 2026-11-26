"""One parquet file per table per year, for fast reads (the daily tables are one small file per day).

    python -m t2.data.compact run --from-year 1994 --to-year 2026   # one-time backfill
    python -m t2.data.compact run --current                         # daily: this year (and last, in January)

Writes compact/<table>/<YYYY>.parquet. The per-day files stay the source of truth; these are rebuilt from them.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from datetime import date
from pathlib import Path

import polars as pl
from huggingface_hub import snapshot_download

from t2.data import hf_store

TABLES = ("eq_daily", "eq_delivery", "fo_daily")


def compact_year(src: Path, table: str, year: int) -> pl.DataFrame | None:
    files = sorted((src / table / f"year={year}").glob("*.parquet"))
    if not files:
        return None
    frames = [pl.read_parquet(f) for f in files]
    keys = ["date", "symbol"] if "symbol" in frames[0].columns else ["date"]
    return pl.concat(frames, how="diagonal_relaxed").sort(keys)


def run(years: list[int], tables: tuple[str, ...] = TABLES) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src, stage = Path(tmp) / "src", Path(tmp) / "stage"
        snapshot_download(
            hf_store.DATASET_REPO,
            repo_type="dataset",
            local_dir=src,
            allow_patterns=[f"{t}/year={y}/*" for t in tables for y in years],
            token=os.environ.get("HF_TOKEN"),
            max_workers=16,
        )
        written = []
        for t in tables:
            for y in years:
                df = compact_year(src, t, y)
                if df is None:
                    continue
                out = stage / "compact" / t / f"{y}.parquet"
                out.parent.mkdir(parents=True, exist_ok=True)
                df.write_parquet(out, compression="zstd")
                written.append(f"{t}/{y}: {df.height:,} rows")
                print(written[-1], flush=True)
        if written:
            hf_store.upload_folder(stage, f"compact: {len(written)} table-years ({years[0]}-{years[-1]})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--from-year", type=int)
    r.add_argument("--to-year", type=int)
    r.add_argument("--current", action="store_true", help="this year, plus last year during January")
    a = ap.parse_args(argv)
    today = date.today()
    if a.current:
        years = [today.year - 1, today.year] if today.month == 1 else [today.year]
    else:
        years = list(range(a.from_year or 1994, (a.to_year or today.year) + 1))
    run(years)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
