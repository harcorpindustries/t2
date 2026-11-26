from datetime import date, timedelta

import numpy as np
import polars as pl

from t2.models import seqdata


def synthetic(n_sym: int = 40, n_days: int = 300, seed: int = 0) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    days = [
        date(2018, 1, 1) + timedelta(days=i)
        for i in range(n_days * 2)
        if (date(2018, 1, 1) + timedelta(days=i)).weekday() < 5
    ]
    days = days[:n_days]
    rows = []
    for s in range(n_sym):
        for d in days:
            if s == 0 and d.day < 8:
                continue  # stock 0 drops out of the universe some days
            f0, f1 = rng.normal(), rng.normal() * 100
            rows.append({"date": d, "symbol": f"S{s:02d}", "f0": f0, "f1": f1, "y5": f0 * 0.5 + rng.normal() * 0.1})
    return pl.DataFrame(rows)


def test_cube_layout_and_labels():
    p = synthetic()
    cube = seqdata.build(p, ["f0", "f1"], "y5", date(2018, 1, 1), date(2019, 12, 31))
    assert cube.x.shape == (40, 300, 3)
    s0 = cube.symbols.index("S00")
    off = [i for i, d in enumerate(cube.dates) if d.day < 8]
    assert not cube.present[off, s0].any() and cube.x[s0, off, -1].sum() == 0
    d = 50
    lab = cube.label[d][cube.present[d]]
    assert abs(float(np.nanmean(lab))) < 0.05 and np.nanmax(lab) <= 0.5 and np.nanmin(lab) >= -0.5


def test_scale_uses_fit_days_only_and_clips():
    p = synthetic().with_columns(
        pl.when(pl.col("date") >= date(2019, 1, 1)).then(pl.col("f1") * 1000).otherwise(pl.col("f1")).alias("f1")
    )
    cube = seqdata.build(p, ["f0", "f1"], "y5", date(2018, 1, 1), date(2019, 12, 31))
    fit = np.array([i for i, d in enumerate(cube.dates) if d.year == 2018])
    _, sc = seqdata.scale(cube, fit)
    assert 50 < sc[1] < 200  # fitted on 2018 (scale ~100), not on the inflated 2019 values
    assert cube.x.dtype == np.float16 and float(np.abs(cube.x[..., :2]).max()) <= seqdata.CLIP
    s0 = cube.symbols.index("S00")
    off = [i for i, d in enumerate(cube.dates) if d.day < 8]
    assert float(np.abs(cube.x[s0, off, :]).max()) == 0  # missing rows stay exactly 0


def test_windows_pad_before_the_cube():
    cube = seqdata.build(synthetic(), ["f0", "f1"], "y5", date(2018, 1, 1), date(2019, 12, 31))
    w = seqdata.windows(cube, 3, 10, np.array([1, 2]))
    assert w.shape == (2, 10, 3) and float(np.abs(w[:, :6]).sum()) == 0
    assert np.array_equal(w[:, 6:], cube.x[[1, 2], 0:4].astype(np.float32))


def test_split_days_keep_gaps():
    p = synthetic(n_days=600)
    cube = seqdata.build(p, ["f0", "f1"], "y5", date(2018, 1, 1), date(2020, 12, 31))
    test_year = cube.dates[-1].year
    days = seqdata.split_days(cube, test_year, date(2018, 1, 1), embargo=10, valid_days=40)
    assert days["train"].max() + 10 < days["valid"].min()
    assert days["valid"].max() + 10 < days["test"].min()
    assert all(cube.dates[i].year == test_year for i in days["test"])


def test_rank_ic():
    x = np.arange(50, dtype=float)
    assert abs(seqdata.rank_ic(x, x) - 1) < 1e-9 and abs(seqdata.rank_ic(x, -x) + 1) < 1e-9
    assert np.isnan(seqdata.rank_ic(x[:5], x[:5]))


def test_pca_fit_only_on_rows_before_the_cutoff():
    rng = np.random.default_rng(0)
    n = 400
    dates = [date(2020, 1, 1) + timedelta(days=i) for i in range(n)]
    vecs = rng.normal(size=(n, 16)).astype(np.float32)
    vecs[:, 0] *= 5  # dominant direction in every year
    late = np.array([d >= date(2020, 9, 1) for d in dates])
    vecs[late, 1] += 50  # something that only happens after the cutoff must not shape the compression
    keys = pl.DataFrame({"date": dates, "symbol": ["A"] * n})
    cols, names = seqdata.news_columns(keys, vecs, date(2020, 9, 1), 2)
    assert names == ["news_e0", "news_e1"] and cols.height == n
    _, comp = seqdata.pca_fit(vecs[~late], 2)
    assert abs(comp[0, 0]) > 0.9 and abs(comp[0, 1]) < 0.2
    z = vecs @ comp.T
    assert np.allclose(np.corrcoef(cols["news_e0"].to_numpy(), z[:, 0])[0, 1], 1.0, atol=1e-4)


def test_pca_needs_enough_training_rows():
    keys = pl.DataFrame({"date": [date(2021, 1, 1)] * 5, "symbol": ["A"] * 5})
    try:
        seqdata.news_columns(keys, np.zeros((5, 8), dtype=np.float32), date(2021, 1, 1), 4)
    except ValueError:
        return
    raise AssertionError("expected a ValueError")
