from datetime import date, timedelta

import numpy as np
import polars as pl

from t2.backtest.holding import HoldConfig, run_book, stats


def frame(oracle: float, n_days: int = 60, n_sym: int = 60, seed: int = 1) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_days):
        d = date(2025, 1, 1) + timedelta(days=i)
        for s in range(n_sym):
            gap, oc = rng.normal(0, 0.005), rng.normal(0, 0.01)
            noise = rng.normal(0, 1)
            score = oracle * (gap + oc) * 100 + noise
            rows.append((d, f"S{s:02d}", 100.0, score, oc, gap, gap + oc))
    return pl.DataFrame(rows, schema=["date", "symbol", "close", "score", "y1", "next_gap", "next_lr"], orient="row")


def test_informative_scores_beat_noise_after_costs():
    good = stats(run_book(frame(oracle=5.0), HoldConfig(k=5, exit_k=5)))
    noise = stats(run_book(frame(oracle=0.0), HoldConfig(k=5, exit_k=5)))
    assert good["net_bps"] > 0 > noise["net_bps"]


def test_buffer_cuts_trading():
    f = frame(oracle=0.0)
    tight = stats(run_book(f, HoldConfig(k=5, exit_k=5)))
    loose = stats(run_book(f, HoldConfig(k=5, exit_k=30)))
    assert loose["trades_per_day"] < tight["trades_per_day"] and loose["cost_bps"] < tight["cost_bps"]


def test_book_never_holds_more_than_k_per_side():
    daily = run_book(frame(oracle=1.0), HoldConfig(k=4, exit_k=20))
    assert (
        daily["trades"].to_list() and max(daily["trades"].to_list()) <= 4 * 4
    )  # at most full turnover: 4 exits + 4 entries per side
