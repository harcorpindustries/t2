from datetime import date

import polars as pl

from t2.data.compact import compact_year
from t2.features.eod import table


def test_compact_year_merges_days_and_is_read_first(tmp_path):
    d = tmp_path / "eq_daily" / "year=2026"
    d.mkdir(parents=True)
    pl.DataFrame({"date": [date(2026, 1, 2)], "symbol": ["B"], "close": [2.0]}).write_parquet(d / "2026-01-02.parquet")
    pl.DataFrame({"date": [date(2026, 1, 1)] * 2, "symbol": ["B", "A"], "close": [1.0, 3.0]}).write_parquet(
        d / "2026-01-01.parquet"
    )
    df = compact_year(tmp_path, "eq_daily", 2026)
    assert df is not None and df["symbol"].to_list() == ["A", "B", "B"]
    assert compact_year(tmp_path, "eq_daily", 2025) is None

    assert table(tmp_path, "eq_daily").collect().height == 3  # per-day files when nothing is compacted
    out = tmp_path / "compact" / "eq_daily"
    out.mkdir(parents=True)
    df.head(1).write_parquet(out / "2026.parquet")
    assert table(tmp_path, "eq_daily").collect().height == 1  # compacted copy wins when present
