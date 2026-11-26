from datetime import UTC, date, datetime

import numpy as np
import polars as pl

from t2.features import extra
from t2.news import embed


def test_bytes_round_trip():
    rng = np.random.default_rng(0)
    e = rng.normal(size=(3, embed.DIM)).astype(np.float32)
    arts = pl.DataFrame({"gkg_id": ["a", "b", "c"], "published_at": [datetime(2024, 1, 2, tzinfo=UTC)] * 3,
                         "title": ["x" * 20] * 3, "tickers": [["TCS"], ["INFY"], ["TCS", "INFY"]]})  # fmt: skip
    back = embed.from_frame(embed.to_frame(arts, e))
    assert back.shape == (3, embed.DIM) and np.allclose(back, e, atol=1e-2)
    assert embed.from_frame(embed.to_frame(arts.head(0), e[:0])).shape == (0, embed.DIM)


def test_articles_filters_and_dedupes(tmp_path):
    d = tmp_path / "news_gdelt" / "year=2024"
    d.mkdir(parents=True)
    t = datetime(2024, 3, 1, 5, tzinfo=UTC)
    pl.DataFrame({
        "gkg_id": ["1", "2", "3", "4"],
        "published_at": [t, t, t, t],
        "title": ["Infosys wins large deal", "Infosys wins large deal", "short", "No tickers on this one"],
        "tickers": [["INFY"], ["INFY"], ["INFY"], []],
    }).write_parquet(d / "2024-03.parquet")  # fmt: skip
    a = embed.articles(tmp_path, 2024)
    assert a["gkg_id"].to_list() == ["1"]
    assert embed.articles(tmp_path, 2023).height == 0


def test_vectors_averaged_per_session_and_stock():
    s1, s2 = date(2024, 1, 2), date(2024, 1, 3)
    arts = pl.DataFrame({
        "published_at": [datetime(2024, 1, 2, 4, tzinfo=UTC),   # before 15:30 IST: session 1
                         datetime(2024, 1, 2, 6, tzinfo=UTC),   # session 1
                         datetime(2024, 1, 2, 11, tzinfo=UTC),  # after the close: session 2
                         datetime(2024, 1, 5, 11, tzinfo=UTC)], # after the last session: dropped
        "tickers": [["TCS"], ["TCS", "INFY"], ["TCS"], ["TCS"]],
    })  # fmt: skip
    e = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 1]], dtype=np.float32)
    keys, m = extra.news_emb_by_session(arts, e, [s1, s2])
    rows = {(r["date"], r["symbol"]): (r["n"], m[i]) for i, r in enumerate(keys.iter_rows(named=True))}
    assert set(rows) == {(s1, "TCS"), (s1, "INFY"), (s2, "TCS")}
    n, v = rows[(s1, "TCS")]
    assert n == 2 and np.allclose(v, np.array([1, 1, 0]) / np.sqrt(2))
    assert np.allclose(rows[(s1, "INFY")][1], [0, 1, 0]) and np.allclose(rows[(s2, "TCS")][1], [0, 0, 1])
