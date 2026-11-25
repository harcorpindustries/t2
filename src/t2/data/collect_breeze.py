"""Backfill intraday candles from Breeze within the daily call budget, newest data first.

Passes run in order; within a pass, time windows go newest to oldest across all instruments
(breadth-first), so recent history is complete for every symbol before older years start.

Breeze returns at most 1000 rows per call and keeps the LAST 1000 when a range is too long,
so windows are sized to stay under that, and any full response is split and refetched.

State (server): SQLite at T2_BREEZE_DB. Staged candles: parquet files exported hourly to HF as
  intraday_<interval>/year=YYYY/<SYMBOL>.parquet   and the window ledger as _ledger/breeze/windows.parquet

Commands:
  run --max-calls N    fetch windows until N calls, the daily budget, or the allowed hours run out
  export               merge staged candles into the HF dataset
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from t2.data import hf_store

IST = ZoneInfo("Asia/Kolkata")
DB_PATH = Path(os.environ.get("T2_BREEZE_DB", "/opt/t2/data/breeze.db"))
STAGE = Path(os.environ.get("T2_BREEZE_STAGE", "/opt/t2/data/breeze_stage"))
DAILY_BUDGET = int(os.environ.get("T2_BREEZE_BACKFILL_BUDGET", "4000"))  # of 5000/day; rest kept for trading
CALLS_PER_MIN = 80  # API allows 100/min
MAX_ROWS = 1000
MAX_ATTEMPTS = 3  # a window that errors this many times is marked failed and left for the audit
EMPTY_STREAK_TO_STOP = 5  # consecutive empty windows (on trading days) = before listing / data start


@dataclass(frozen=True)
class Pass:
    interval: str
    days_per_window: int
    start: date
    end: date | None  # None = up to yesterday


def passes(today: date) -> list[Pass]:
    two_years_ago = date(today.year - 2, today.month, 1)
    return [
        Pass("1minute", 2, two_years_ago, None),
        Pass("5minute", 12, date(2012, 1, 1), None),
        Pass("1minute", 2, date(2012, 1, 1), two_years_ago - timedelta(days=1)),
    ]


SCHEMA = """
CREATE TABLE IF NOT EXISTS windows (
  interval TEXT, code TEXT, symbol TEXT, start TEXT, end TEXT,
  status TEXT, rows INTEGER, calls INTEGER, fetched_at TEXT, exported_at TEXT,
  PRIMARY KEY (interval, code, start, end)
);
CREATE TABLE IF NOT EXISTS calls (day TEXT PRIMARY KEY, n INTEGER NOT NULL);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=60)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def windows(trading_days: list[date], p: Pass, today: date) -> list[tuple[date, date]]:
    """Newest-first windows of `days_per_window` trading days within the pass range."""
    end = p.end or (today - timedelta(days=1))
    days = [d for d in trading_days if p.start <= d <= end]
    days.sort(reverse=True)
    out = []
    for i in range(0, len(days), p.days_per_window):
        chunk = days[i : i + p.days_per_window]
        out.append((chunk[-1], chunk[0]))
    return out


Fetch = Callable[[str, str, date, date], list[dict[str, object]]]


def fetch_window(fetch: Fetch, interval: str, code: str, start: date, end: date) -> tuple[list[dict[str, object]], int]:
    """Fetch [start, end]; if Breeze returns a full page, split the range and refetch both halves."""
    rows = fetch(interval, code, start, end)
    calls = 1
    if len(rows) < MAX_ROWS or start == end:
        return rows, calls
    mid = start + (end - start) / 2
    left, c1 = fetch_window(fetch, interval, code, start, mid)
    right, c2 = fetch_window(fetch, interval, code, mid + timedelta(days=1), end)
    return left + right, calls + c1 + c2


def today_ist() -> date:
    return datetime.now(IST).date()


def calls_today(con: sqlite3.Connection) -> int:
    row = con.execute("SELECT n FROM calls WHERE day=?", (today_ist().isoformat(),)).fetchone()
    return int(row["n"]) if row else 0


def add_calls(con: sqlite3.Connection, n: int) -> None:
    con.execute(
        "INSERT INTO calls(day, n) VALUES(?, ?) ON CONFLICT(day) DO UPDATE SET n = n + excluded.n",
        (today_ist().isoformat(), n),
    )


def allowed_now(now: datetime | None = None) -> bool:
    """Only outside market hours (keep the API free for trading) and before the session expires."""
    t = (now or datetime.now(IST)).time()
    return (t.hour, t.minute) >= (16, 0) and (t.hour, t.minute) < (23, 45)


def trading_calendar(workdir: Path) -> list[date]:
    days: list[date] = []
    for year in range(2010, today_ist().year + 1):
        p = hf_store.download(f"_ledger/nse/year={year}.parquet", workdir)
        if p is None:
            continue
        led = pl.read_parquet(p)
        days += led.filter((pl.col("kind") == "cm") & (pl.col("status") == "ok"))["date"].to_list()
    return sorted(set(days))


def plan(
    con: sqlite3.Connection, instruments: list[tuple[str, str]], trading_days: list[date], today: date
) -> Iterator[tuple[Pass, str, str, date, date]]:
    """Yield pending (pass, code, symbol, start, end) in priority order."""
    done = {
        (r["interval"], r["code"], r["start"], r["end"])
        for r in con.execute("SELECT interval, code, start, end FROM windows WHERE status IN ('ok','empty','failed')")
    }
    stopped = {
        (r["interval"], r["code"])
        for r in con.execute(
            "SELECT interval, code FROM windows WHERE status='data_start'"  # marker row: no older data
        )
    }
    for p in passes(today):
        for start, end in windows(trading_days, p, today):
            for code, symbol in instruments:
                if (p.interval, code) in stopped:
                    continue
                if (p.interval, code, start.isoformat(), end.isoformat()) in done:
                    continue
                yield p, code, symbol, start, end


def empty_streak(con: sqlite3.Connection, interval: str, code: str) -> int:
    rows = con.execute(
        "SELECT status FROM windows WHERE interval=? AND code=? AND status IN ('ok','empty')"
        " ORDER BY start ASC LIMIT ?",
        (interval, code, EMPTY_STREAK_TO_STOP),
    ).fetchall()
    n = 0
    for r in rows:
        if r["status"] != "empty":
            break
        n += 1
    return n


def to_frame(rows: list[dict[str, object]], symbol: str, code: str) -> pl.DataFrame:
    df = pl.DataFrame(
        {
            "datetime": [str(r["datetime"]) for r in rows],
            "open": [float(r["open"]) for r in rows],  # type: ignore[arg-type]
            "high": [float(r["high"]) for r in rows],  # type: ignore[arg-type]
            "low": [float(r["low"]) for r in rows],  # type: ignore[arg-type]
            "close": [float(r["close"]) for r in rows],  # type: ignore[arg-type]
            "volume": [int(float(r.get("volume") or 0)) for r in rows],  # type: ignore[arg-type]
        }
    )
    return df.with_columns(
        pl.col("datetime").str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S").dt.replace_time_zone("Asia/Kolkata"),
        pl.lit(symbol).alias("symbol"),
        pl.lit(code).alias("breeze_code"),
    ).select("datetime", "symbol", "breeze_code", "open", "high", "low", "close", "volume")


def breeze_fetcher() -> Fetch:
    from breeze_connect import BreezeConnect

    from t2.brokers.breeze_check import load_env

    load_env()
    b = BreezeConnect(api_key=os.environ["BREEZE_API_KEY"])
    b.generate_session(api_secret=os.environ["BREEZE_API_SECRET"], session_token=os.environ["BREEZE_SESSION_TOKEN"])
    last = [0.0]

    def fetch(interval: str, code: str, start: date, end: date) -> list[dict[str, object]]:
        wait = 60 / CALLS_PER_MIN - (time.monotonic() - last[0])
        if wait > 0:
            time.sleep(wait)
        last[0] = time.monotonic()
        r = b.get_historical_data_v2(
            interval=interval,
            from_date=f"{start.isoformat()}T09:00:00.000Z",
            to_date=f"{end.isoformat()}T16:00:00.000Z",
            stock_code=code,
            exchange_code="NSE",
            product_type="cash",
        )
        if not isinstance(r, dict) or r.get("Status") not in (200, None) or r.get("Error"):
            raise RuntimeError(f"breeze error: {r.get('Error') if isinstance(r, dict) else r}")
        return list(r.get("Success") or [])

    return fetch


def cmd_run(max_calls: int, ignore_hours: bool = False) -> int:
    if not ignore_hours and not allowed_now():
        print("outside backfill hours (16:00-23:45 IST); nothing to do")
        return 0
    con = connect()
    remaining = min(max_calls, DAILY_BUDGET - calls_today(con))
    if remaining <= 0:
        print(f"daily backfill budget used ({calls_today(con)}/{DAILY_BUDGET})")
        return 0
    try:
        fetch = breeze_fetcher()
    except Exception as exc:
        print(f"no valid Breeze session (log in again): {exc}", file=sys.stderr)
        return 0
    from t2.brokers.breeze_master import fno_universe, load_master

    instruments = [(i.breeze_code, i.nse_symbol) for i in fno_universe(load_master())]
    with tempfile.TemporaryDirectory() as tmp:
        calendar = trading_calendar(Path(tmp))
    STAGE.mkdir(parents=True, exist_ok=True)
    used = fetched = 0
    for p, code, symbol, start, end in plan(con, instruments, calendar, today_ist()):
        if used >= remaining or (not ignore_hours and not allowed_now()):
            break
        if empty_streak(con, p.interval, code) >= EMPTY_STREAK_TO_STOP:
            con.execute(
                "INSERT OR REPLACE INTO windows VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                (p.interval, code, symbol, "0000-00-00", "0000-00-00", "data_start", 0, 0, _now()),
            )
            con.commit()
            continue
        try:
            rows, calls = fetch_window(fetch, p.interval, code, start, end)
            status = "ok" if rows else "empty"
        except Exception as exc:
            rows, calls = [], 1
            prior = con.execute(
                "SELECT rows FROM windows WHERE interval=? AND code=? AND start=? AND end=? AND status='error'",
                (p.interval, code, start.isoformat(), end.isoformat()),
            ).fetchone()
            attempts = (prior["rows"] if prior else 0) + 1  # error rows store the attempt count in `rows`
            status = "failed" if attempts >= MAX_ATTEMPTS else "error"
            print(f"{p.interval} {code} {start}..{end} attempt {attempts}: {exc}", file=sys.stderr)
            con.execute(
                "INSERT OR REPLACE INTO windows VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                (p.interval, code, symbol, start.isoformat(), end.isoformat(), status, attempts, calls, _now()),
            )
            add_calls(con, calls)
            con.commit()
            used += calls
            continue
        used += calls
        add_calls(con, calls)
        if rows:
            df = to_frame(rows, symbol, code).unique("datetime").sort("datetime")
            out = STAGE / p.interval / f"{code}_{start}_{end}.parquet"
            out.parent.mkdir(parents=True, exist_ok=True)
            df.write_parquet(out)
            fetched += df.height
        con.execute(
            "INSERT OR REPLACE INTO windows VALUES (?,?,?,?,?,?,?,?,?,NULL)",
            (p.interval, code, symbol, start.isoformat(), end.isoformat(), status, len(rows), calls, _now()),
        )
        con.commit()
    print(f"run: {used} calls, {fetched} candles staged, {calls_today(con)}/{DAILY_BUDGET} used today")
    return 0


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def cmd_export() -> int:
    con = connect()
    files = sorted(STAGE.glob("*/*.parquet"))
    if not files:
        print("export: nothing staged")
        return 0
    staged = pl.concat([pl.read_parquet(f).with_columns(pl.lit(f.parent.name).alias("interval")) for f in files])
    staged = staged.with_columns(pl.col("datetime").dt.year().alias("year"))
    short = {"1minute": "1m", "5minute": "5m"}
    with tempfile.TemporaryDirectory() as tmp:
        stage, dl = Path(tmp) / "stage", Path(tmp) / "dl"
        for (interval, year, symbol), part in staged.group_by("interval", "year", "symbol"):
            rel = f"intraday_{short[str(interval)]}/year={year}/{str(symbol).replace(' ', '_')}.parquet"
            existing = hf_store.download(rel, dl)
            frames = [part.drop("interval", "year")]
            if existing:
                frames.append(pl.read_parquet(existing))
            merged = pl.concat(frames).unique(["datetime"], keep="first").sort("datetime")
            (stage / rel).parent.mkdir(parents=True, exist_ok=True)
            merged.write_parquet(stage / rel, compression="zstd")
        ledger = pl.read_database("SELECT * FROM windows", con, infer_schema_length=None)
        (stage / "_ledger" / "breeze").mkdir(parents=True, exist_ok=True)
        ledger.drop("exported_at").write_parquet(stage / "_ledger" / "breeze" / "windows.parquet")
        hf_store.upload_folder(stage, f"breeze intraday export: {staged.height} candles from {len(files)} windows")
    for f in files:
        f.unlink()
    print(f"export: {staged.height} candles from {len(files)} windows")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--max-calls", type=int, default=800)
    r.add_argument("--ignore-hours", action="store_true", help="for manual tests only")
    sub.add_parser("export")
    a = ap.parse_args(argv)
    return cmd_run(a.max_calls, a.ignore_hours) if a.cmd == "run" else cmd_export()


if __name__ == "__main__":
    raise SystemExit(main())
