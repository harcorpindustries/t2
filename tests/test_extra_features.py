import math
from datetime import UTC, date, datetime

import polars as pl
import pytest

from t2.features import extra


def write(root, rel, df):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def test_news_assigned_to_the_session_it_was_published_before(tmp_path):
    arts = pl.DataFrame(
        {
            "published_at": [
                datetime(2026, 1, 5, 9, 0, tzinfo=UTC),  # before Monday's 15:30 IST close -> Monday
                datetime(2026, 1, 5, 11, 0, tzinfo=UTC),  # after Monday's close -> Tuesday
                datetime(2026, 1, 3, 12, 0, tzinfo=UTC),  # Saturday -> Monday
            ],
            "tone": [1.0, -3.0, 2.0],
            "tickers": [["TCS"], ["TCS"], ["TCS", "INFY"]],
        }
    )
    write(tmp_path, "news_gdelt/year=2026/2026-01.parquet", arts)
    nb = extra.news_by_session(tmp_path, [date(2026, 1, 5), date(2026, 1, 6)]).sort("date", "symbol")
    got = {(r["date"], r["symbol"]): (r["n"], r["tone_sum"]) for r in nb.iter_rows(named=True)}
    assert got[(date(2026, 1, 5), "TCS")] == (2, 3.0)
    assert got[(date(2026, 1, 6), "TCS")] == (1, -3.0)
    assert got[(date(2026, 1, 5), "INFY")] == (1, 2.0)


def test_fno_features(tmp_path):
    rows = []
    for i, d in enumerate([date(2026, 1, 5), date(2026, 1, 6)]):
        rows += [
            (d, "FUTSTK", "TCS", date(2026, 1, 27), None, None, 101.0, 1000 * (i + 1), 5e8),
            (d, "FUTSTK", "TCS", date(2026, 2, 24), None, None, 102.0, 1000, 1e8),
            (d, "OPTSTK", "TCS", date(2026, 1, 27), 100.0, "CE", 2.0, 400, 1e6),
            (d, "OPTSTK", "TCS", date(2026, 1, 27), 100.0, "PE", 2.0, 200, 1e6),
        ]
    cols = ["date", "instrument", "symbol", "expiry", "strike", "option_type", "close", "oi", "turnover"]
    write(tmp_path, "fo_daily/year=2026/x.parquet", pl.DataFrame(rows, schema=cols, orient="row"))
    panel = pl.DataFrame(
        {"date": [date(2026, 1, 5), date(2026, 1, 6)], "symbol": ["TCS"] * 2, "close": [100.0] * 2, "lturn": [20.0] * 2}
    )
    out = extra.add_fno(panel, tmp_path).sort("date")
    assert out["fut_oi_chg1"][1] == pytest.approx(math.log(3000 / 2000))  # all expiries summed
    assert out["pcr"][0] == pytest.approx(math.log(200 / 400))
    assert out["basis_ann"][0] == pytest.approx(math.log(1.01) * 365 / 22)  # near month, 22 days left
