from datetime import date

import polars as pl

from t2.dashboard import insights as ins


def test_drawdown_and_perf():
    assert ins.drawdown([100, 110, 99, 120]) == [0.0, 0.0, 99 / 110 - 1, 0.0]
    days = [{"day": "d1", "equity": 101.0, "charges": 1}, {"day": "d2", "equity": 99.0, "charges": 0}]
    p = ins.perf(days, 100.0)
    assert abs(p["total_return"] + 0.01) < 1e-12 and p["up_days"] == 1 and p["down_days"] == 1
    assert p["max_drawdown"] == 99 / 101 - 1 and p["charges"] == 1


def test_round_trips_fifo_with_partial_exits():
    t = [
        {"ts": "1", "day": "2026-11-02", "symbol": "A", "side": "buy", "qty": 10, "price": 100, "charges": 10},
        {"ts": "2", "day": "2026-11-03", "symbol": "A", "side": "buy", "qty": 10, "price": 110, "charges": 10},
        {"ts": "3", "day": "2026-11-06", "symbol": "A", "side": "sell", "qty": 15, "price": 120, "charges": 15},
    ]
    a, b = ins.round_trips(t)
    assert (a["qty"], a["entry"], a["pnl"], a["days"]) == (10, 100, 200 - 10 - 10, 4)
    assert (b["qty"], b["entry"], b["pnl"]) == (5, 110, 50 - 5 - 5)
    s = ins.trade_stats([a, b])
    assert s["win_rate"] == 1.0 and s["closed"] == 2


def test_short_round_trip():
    t = [
        {"ts": "1", "day": "2026-11-02", "symbol": "A", "side": "sell", "qty": 5, "price": 100, "charges": 0},
        {"ts": "2", "day": "2026-11-03", "symbol": "A", "side": "buy", "qty": 5, "price": 90, "charges": 0},
    ]
    (trip,) = ins.round_trips(t)
    assert trip["side"] == "short" and trip["pnl"] == 50


def test_charge_breakdown_sums():
    b = ins.charge_breakdown({"side": "buy", "qty": 10, "price": 1600, "day": "2026-11-27"}, "delivery")
    parts = sum(v for k, v in b.items() if k != "total")
    assert abs(parts - b["total"]) < 0.05 and b["stt"] > 0


def test_headline_tone():
    assert ins.headline_tone("TCS shares surge after strong results") == 1
    assert ins.headline_tone("Infosys falls on weak guidance") == -1
    assert ins.headline_tone("Board meeting on Friday") == 0


def test_signal_quality_uses_next_open_to_fifth_close():
    days = [date(2026, 11, d) for d in (2, 3, 4, 5, 6, 9, 10)]
    syms = [f"S{i}" for i in range(30)]
    rows = []
    for i, s in enumerate(syms):
        for j, d in enumerate(days):
            px = 100 + i * j  # higher i = stronger stock
            rows.append({"date": d, "symbol": s, "open": px, "close": px, "prev_close": px, "turnover": 1e9})
    px = pl.DataFrame(rows)
    hist = pl.DataFrame(
        {"date": [days[0]] * 30, "symbol": syms, "rank": list(range(30, 0, -1)), "score": [float(i) for i in range(30)]}
    )
    (q,) = ins.signal_quality(hist, px, k=3)
    assert q["complete"] and q["sessions"] == 5 and q["ic"] > 0.99 and q["top_ret"] > q["market_ret"]
    assert q["top_hits"] == 3


def test_market_index_rebases_to_100():
    px = pl.DataFrame(
        {
            "date": [date(2026, 11, 2), date(2026, 11, 3)],
            "symbol": ["A", "A"],
            "close": [100.0, 110.0],
            "prev_close": [100.0, 100.0],
            "turnover": [1e9, 1e9],
        }
    )
    m = ins.market_index(px)
    assert m["level"].to_list()[0] == 100.0 and abs(m["level"].to_list()[1] - 110.0) < 1e-9
