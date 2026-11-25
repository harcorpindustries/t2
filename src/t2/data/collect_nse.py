"""Collect NSE end-of-day archives into the HF dataset without gaps.

Every calendar day is checked for every kind. Results go to a per-year ledger:
  _ledger/nse/year=YYYY.parquet  (date, kind, status, http_status, format, url, bytes, sha256, rows, attempts,
                                  fetched_at)
Raw files are kept unchanged under raw/nse/<kind>/<YYYY>/<file>, parsed tables under
  eq_daily/year=YYYY/<date>.parquet, fo_daily/year=YYYY/<date>.parquet, eq_delivery/year=YYYY/<date>.parquet

Commands:
  backfill --year YYYY        fetch every day of a year (resumes: skips days already ok in the ledger)
  daily --lookback N          re-check the last N days plus every non-ok day of the current year
  audit                       report gaps across all ledgers (exit 1 if any)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from t2.data import hf_store
from t2.data.nse_archive import FIRST_DATE, KINDS, fetch, make_client, parse

IST = ZoneInfo("Asia/Kolkata")
TABLE = {"cm": "eq_daily", "fo": "fo_daily", "mto": "eq_delivery"}
LEDGER_SCHEMA = {
    "date": pl.Date,
    "kind": pl.Utf8,
    "status": pl.Utf8,
    "http_status": pl.Int64,
    "format": pl.Utf8,
    "url": pl.Utf8,
    "bytes": pl.Int64,
    "sha256": pl.Utf8,
    "rows": pl.Int64,
    "attempts": pl.Int64,
    "fetched_at": pl.Utf8,
}
# NSE publishes after close; treat "not published" as final only once the day is this old.
SETTLE_DAYS = 7


def ledger_path(year: int) -> str:
    return f"_ledger/nse/year={year}.parquet"


def today_ist() -> date:
    return datetime.now(IST).date()


def load_ledger(year: int, workdir: Path) -> pl.DataFrame:
    p = hf_store.download(ledger_path(year), workdir / "dl")
    return pl.read_parquet(p) if p else pl.DataFrame(schema=LEDGER_SCHEMA)


def process(days: list[date], stage: Path, delay: float) -> pl.DataFrame:
    """Fetch, store raw + parsed for each (day, kind). Returns ledger rows."""
    rows = []
    with make_client() as client:
        for d in days:
            for kind in KINDS:
                if d < FIRST_DATE[kind]:
                    continue
                f = fetch(client, kind, d)
                n_rows, sha = None, None
                if f.status == "ok":
                    sha = hashlib.sha256(f.content).hexdigest()
                    raw_dir = stage / "raw" / "nse" / kind / str(d.year)
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    (raw_dir / f.url.rsplit("/", 1)[1]).write_bytes(f.content)
                    try:
                        df = parse(kind, f.content, f.fmt, d)
                        out_dir = stage / TABLE[kind] / f"year={d.year}"
                        out_dir.mkdir(parents=True, exist_ok=True)
                        df.write_parquet(out_dir / f"{d.isoformat()}.parquet", compression="zstd")
                        n_rows = df.height
                    except Exception as exc:  # raw is kept; mark for re-parse
                        f.status = "parse_error"
                        print(f"parse_error {kind} {d}: {exc}", file=sys.stderr)
                rows.append(
                    {
                        "date": d,
                        "kind": kind,
                        "status": f.status,
                        "http_status": f.http_status,
                        "format": f.fmt or None,
                        "url": f.url or None,
                        "bytes": len(f.content) or None,
                        "sha256": sha,
                        "rows": n_rows,
                        "attempts": f.attempts,
                        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    }
                )
                time.sleep(delay)
    return pl.DataFrame(rows, schema=LEDGER_SCHEMA)


def merge(old: pl.DataFrame, new: pl.DataFrame) -> pl.DataFrame:
    """New results replace old ones for the same (date, kind), except never downgrade an ok."""
    if new.is_empty():
        return old
    combined = pl.concat([old, new])
    rank = pl.when(pl.col("status") == "ok").then(0).otherwise(1)
    return (
        combined.with_columns(rank.alias("_r"), pl.int_range(pl.len()).alias("_i"))
        .sort(["date", "kind", "_r", "_i"], descending=[False, False, False, True])
        .unique(["date", "kind"], keep="first", maintain_order=True)
        .drop("_r", "_i")
        .sort(["date", "kind"])
    )


def days_needing_work(ledger: pl.DataFrame, candidates: list[date], today: date) -> list[date]:
    done = {
        (r["date"], r["kind"])
        for r in ledger.iter_rows(named=True)
        if r["status"] == "ok" or (r["status"] == "not_published" and (today - r["date"]).days >= SETTLE_DAYS)
    }
    return [d for d in candidates if any((d, k) not in done for k in KINDS if d >= FIRST_DATE[k])]


def run_year(year: int, days: list[date], delay: float, label: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        stage = work / "stage"
        stage.mkdir()
        ledger = load_ledger(year, work)
        todo = days_needing_work(ledger, days, today_ist())
        print(f"{label} {year}: {len(todo)} of {len(days)} days need work")
        if not todo:
            return
        result = process(todo, stage, delay)
        merged = merge(ledger, result)
        (stage / "_ledger" / "nse").mkdir(parents=True, exist_ok=True)
        merged.write_parquet(stage / ledger_path(year))
        counts = result.group_by("kind", "status").len().sort("kind", "status")
        print(counts)
        hf_store.upload_folder(stage, f"{label}: NSE {year} ({len(todo)} days)")


def cmd_backfill(year: int, delay: float) -> None:
    start, end = date(year, 1, 1), min(date(year, 12, 31), today_ist())
    days = [start + timedelta(n) for n in range((end - start).days + 1)]
    run_year(year, days, delay, "backfill")


def cmd_daily(lookback: int, delay: float) -> None:
    today = today_ist()
    window = [today - timedelta(n) for n in range(lookback, -1, -1)]
    for year in sorted({d.year for d in window}):
        start = date(year, 1, 1)
        year_days = [start + timedelta(n) for n in range((min(date(year, 12, 31), today) - start).days + 1)]
        run_year(year, year_days, delay, "daily")


def audit() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as tmp:
        frames = []
        for year in range(FIRST_DATE["cm"].year, today_ist().year + 1):
            p = hf_store.download(ledger_path(year), Path(tmp))
            if p is None:
                frames.append(pl.DataFrame({"missing_ledger_year": [year]}))
                continue
            frames.append(pl.read_parquet(p))
    ledgers = [f for f in frames if "kind" in f.columns]
    missing_years = [f["missing_ledger_year"][0] for f in frames if "missing_ledger_year" in f.columns]
    led = pl.concat(ledgers) if ledgers else pl.DataFrame(schema=LEDGER_SCHEMA)
    wide = led.pivot(on="kind", index="date", values="status", aggregate_function="first")
    for k in KINDS:
        if k not in wide.columns:
            wide = wide.with_columns(pl.lit(None, pl.Utf8).alias(k))
    errors = led.filter(pl.col("status").is_in(["error", "parse_error"]))
    fo_gap = wide.filter(
        (pl.col("cm") == "ok") & (pl.col("fo") != "ok") & (pl.col("date") >= date(2000, 6, 12))
    )
    cm_gap = wide.filter((pl.col("fo") == "ok") & (pl.col("cm") != "ok"))
    first_mto = led.filter((pl.col("kind") == "mto") & (pl.col("status") == "ok"))["date"].min()
    mto_gap = (
        wide.filter((pl.col("cm") == "ok") & (pl.col("mto") != "ok") & (pl.col("date") >= first_mto))
        if first_mto is not None
        else wide.head(0)
    )
    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "missing_ledger_years": missing_years,
        "trading_days": int(wide.filter(pl.col("cm") == "ok").height),
        "status_counts": {
            f"{r['kind']}:{r['status']}": r["len"]
            for r in led.group_by("kind", "status").len().iter_rows(named=True)
        },
        "errors": [f"{r['kind']} {r['date']}" for r in errors.iter_rows(named=True)],
        "fo_missing_on_cm_days": [str(d) for d in fo_gap["date"].to_list()],
        "cm_missing_on_fo_days": [str(d) for d in cm_gap["date"].to_list()],
        "mto_missing_on_cm_days": [str(d) for d in mto_gap["date"].to_list()],
        "dataset_gb": round(hf_store.dataset_size_gb(), 3),
        "first_ok": {
            k: str(led.filter((pl.col("kind") == k) & (pl.col("status") == "ok"))["date"].min())
            for k in KINDS
        },
    }
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--year", type=int, required=True)
    b.add_argument("--delay", type=float, default=0.35)
    d = sub.add_parser("daily")
    d.add_argument("--lookback", type=int, default=10)
    d.add_argument("--delay", type=float, default=0.35)
    sub.add_parser("audit")
    a = ap.parse_args(argv)
    if a.cmd == "backfill":
        cmd_backfill(a.year, a.delay)
    elif a.cmd == "daily":
        cmd_daily(a.lookback, a.delay)
    else:
        report = audit()
        print(json.dumps(report, indent=2, default=str))
        size = float(report["dataset_gb"])  # type: ignore[arg-type]
        if size >= hf_store.WARN_GB:
            print(f"STORAGE WARNING: {size:.1f} GB of {hf_store.FREE_PRIVATE_GB:.0f} GB free private quota")
            return 1
        gaps = (
            report["missing_ledger_years"]
            or report["errors"]
            or report["fo_missing_on_cm_days"]
            or report["cm_missing_on_fo_days"]
            or report["mto_missing_on_cm_days"]
        )
        return 1 if gaps else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
