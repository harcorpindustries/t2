from datetime import date, timedelta

import polars as pl
import pytest

from t2.backtest.daily import Strategy, plan_orders, replay, tick_round
from t2.brokers.base import Side

D0 = date(2026, 1, 5)


def bars_and_preds(oracle: bool):
    days = [D0 + timedelta(days=i) for i in range(10)]
    bars, preds = [], []
    for i, d in enumerate(days):
        for s in range(10):
            up = (s + i) % 2 == 0  # tomorrow's direction for symbol s alternates
            o = 100.0
            c = 102.0 if up else 98.0
            bars.append((d, f"S{s}", o, max(o, c) + 0.5, min(o, c) - 0.5, c, 1_000_000))
    bars_df = pl.DataFrame(bars, schema=["date", "symbol", "open", "high", "low", "close", "volume"], orient="row")
    for i, d in enumerate(days[:-1]):
        for s in range(10):
            next_up = (s + i + 1) % 2 == 0
            preds.append((d, f"S{s}", (1.0 if next_up else -1.0) * (1 if oracle else -1)))
    return pl.DataFrame(preds, schema=["date", "symbol", "score"], orient="row"), bars_df


def test_oracle_makes_money_and_inverse_loses():
    s = Strategy(top_k=3, position_rs=10_000, entry_band=0.03)
    p, b = bars_and_preds(oracle=True)
    daily, summary = replay(p, b, s)
    assert daily.height == 9 and summary["hit_rate"] == 1.0 and summary["fill_rate"] == 1.0
    assert summary["final_equity"] > s.capital
    p2, _ = bars_and_preds(oracle=False)
    _, bad = replay(p2, b, s)
    assert bad["final_equity"] < s.capital


def test_gap_past_band_does_not_fill():
    s = Strategy(top_k=1, position_rs=10_000, entry_band=0.01, short=False)
    p, b = bars_and_preds(oracle=True)
    b = b.with_columns(pl.col("open") * 1.05, pl.col("low") * 1.05)  # every stock gaps up 5%
    _, summary = replay(p, b, s)
    assert summary["fill_rate"] == 0 and summary["final_equity"] == pytest.approx(s.capital)


def test_tick_rounding_never_crosses_the_intended_price():
    assert tick_round(101.07, Side.BUY) == 101.05
    assert tick_round(98.93, Side.SELL) == 98.95
    assert tick_round(100.0, Side.BUY) == 100.0


def test_plan_orders_sizes_and_sides():
    scores = pl.DataFrame({"symbol": ["A", "B", "C", "D"], "score": [0.9, 0.1, -0.2, 0.5]})
    orders = plan_orders(scores, {"A": 100, "B": 50, "C": 200, "D": 10}, D0, Strategy(top_k=1, position_rs=10_000))
    assert [(o.contract.symbol, o.side) for o in orders] == [("A", Side.BUY), ("C", Side.SELL)]
    assert orders[0].qty == 99 and orders[0].limit == 101.0
