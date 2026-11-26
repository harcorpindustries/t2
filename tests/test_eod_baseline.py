from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from t2.features import eod
from t2.models.baseline import Config, evaluate, walk_forward


def synthetic(n_sym: int = 30, n_days: int = 400, seed: int = 0) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    days = [
        date(2018, 1, 1) + timedelta(days=i)
        for i in range(n_days * 2)
        if (date(2018, 1, 1) + timedelta(days=i)).weekday() < 5
    ][:n_days]
    rows = []
    for s in range(n_sym):
        px = 100.0
        for d in days:
            prev = px
            if s == 0 and d == days[200]:
                prev = prev / 2  # 1:1 bonus: NSE halves prev_close on the ex-date
                px = px / 2
            o = px * np.exp(rng.normal(0, 0.005))
            px = o * np.exp(rng.normal(0.0002, 0.015))
            hi, lo = max(o, px) * 1.01, min(o, px) * 0.99
            rows.append((d, f"S{s:02d}", o, hi, lo, px, prev, 100_000, 1e8, 50.0 + rng.normal(0, 5)))
    return pl.DataFrame(
        rows,
        schema=[
            "date",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "prev_close",
            "volume",
            "turnover",
            "deliverable_pct",
        ],
        orient="row",
    )


def test_bonus_does_not_create_a_fake_crash():
    feats = eod.build(synthetic())
    s0 = feats.filter(pl.col("symbol") == "S00")
    assert float(s0["lr"].abs().max()) < 0.2  # type: ignore[arg-type]


def test_features_do_not_look_ahead():
    raw = synthetic()
    cut = raw["date"].unique().sort()[300]
    changed = raw.with_columns(
        pl.when(pl.col("date") > cut).then(pl.col("close") * 1.5).otherwise(pl.col("close")).alias("close"),
        pl.when(pl.col("date") > cut).then(pl.col("turnover") * 9).otherwise(pl.col("turnover")).alias("turnover"),
    )
    a = eod.build(raw).filter(pl.col("date") <= cut).sort("date", "symbol").select("date", "symbol", *eod.FEATURES)
    b = eod.build(changed).filter(pl.col("date") <= cut).sort("date", "symbol").select("date", "symbol", *eod.FEATURES)
    assert a.equals(b)


def test_targets_start_at_next_open():
    raw = synthetic(n_sym=3)
    f = eod.build(raw).filter(pl.col("symbol") == "S01").sort("date")
    r = raw.filter(pl.col("symbol") == "S01").sort("date")
    i = 250
    d = f["date"][i - eod.MIN_HISTORY]
    j = r["date"].to_list().index(d)
    expected = np.log(r["close"][j + 1] / r["open"][j + 1])
    assert f.filter(pl.col("date") == d)["y1"][0] == pytest.approx(expected)


def test_walk_forward_runs_and_respects_embargo():
    panel = eod.build(synthetic(n_sym=40, n_days=700))
    cfg = Config(train_years=1, rounds=20, top_k=5)
    folds, preds = walk_forward(panel, [2020], cfg)
    assert len(folds) == 1 and preds.height > 0
    assert folds[0]["train_end"] < str(preds["date"].min())


def test_evaluate_perfect_foresight_is_profitable():
    panel = eod.build(synthetic(n_sym=40))
    p = panel.filter(pl.col("y1").is_not_null()).with_columns(pl.col("y1").alias("score"))
    m = evaluate(p, Config(top_k=5))
    assert m["ic_mean"] > 0.99 and m["long_net_bps"] > m["bench_bps"]


def test_trade_universe_subset_trains_on_wider_panel():
    panel = eod.build(synthetic(n_sym=40, n_days=700))
    subset = panel.filter(pl.col("symbol").is_in([f"S{i:02d}" for i in range(15)]))
    folds, preds = walk_forward(subset, [2020], Config(train_years=1, rounds=20, top_k=3), train_panel=panel)
    assert set(preds["symbol"].unique()) <= {f"S{i:02d}" for i in range(15)}
    assert folds[0]["train_rows"] > subset.filter(pl.col("date").dt.year() == 2019).height
