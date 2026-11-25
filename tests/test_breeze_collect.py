import sqlite3
from datetime import date, datetime
from pathlib import Path

from t2.data.collect_breeze import (
    MAX_ROWS,
    Pass,
    allowed_now,
    connect,
    fetch_window,
    plan,
    windows,
)

IST_DAYS = [date(2026, 11, d) for d in (17, 18, 19, 20, 23, 24, 25)]


def test_windows_are_newest_first_and_cover_every_trading_day() -> None:
    w = windows(IST_DAYS, Pass("1minute", 2, date(2026, 11, 1), None), today=date(2026, 11, 26))
    assert w[0] == (date(2026, 11, 24), date(2026, 11, 25))
    covered = {d for s, e in w for d in IST_DAYS if s <= d <= e}
    assert covered == set(IST_DAYS)


def test_full_page_is_split_until_every_part_fits() -> None:
    calls: list[tuple[date, date]] = []

    def fake(interval: str, code: str, s: date, e: date) -> list[dict[str, object]]:
        calls.append((s, e))
        n = ((e - s).days + 1) * 400  # 400 rows per day
        return [{"i": i} for i in range(min(n, MAX_ROWS))]

    rows, n = fetch_window(fake, "1minute", "X", date(2026, 11, 1), date(2026, 11, 4))
    assert len(rows) == 4 * 400 and n == len(calls) == 3


def test_backfill_hours() -> None:
    assert allowed_now(datetime(2026, 11, 26, 18, 0))
    assert not allowed_now(datetime(2026, 11, 26, 11, 0))  # market hours
    assert not allowed_now(datetime(2026, 11, 26, 23, 50))  # session about to expire


def test_plan_is_breadth_first_and_skips_done(tmp_path: Path) -> None:
    con: sqlite3.Connection = connect(tmp_path / "b.db")
    con.execute("INSERT INTO windows VALUES ('1minute','A','A','2026-11-24','2026-11-25','ok',700,1,'t',NULL)")
    todo = list(plan(con, [("A", "A"), ("B", "B")], IST_DAYS, date(2026, 11, 26)))
    first = [(p.interval, code, s) for p, code, _, s, _ in todo[:3]]
    assert first == [
        ("1minute", "B", date(2026, 11, 24)),
        ("1minute", "A", date(2026, 11, 20)),
        ("1minute", "B", date(2026, 11, 20)),
    ]
