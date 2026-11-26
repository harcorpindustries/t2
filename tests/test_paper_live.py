from datetime import date, datetime

import polars as pl
import pytest

from t2.trader import paper_live as pl_live
from t2.trader.paper_live import BookConfig, connect, plan, positions, run_close, run_open
from t2.trader.risk import Limits

TODAY = date(2026, 12, 1)
NOW = datetime(2026, 12, 1, 9, 20)


def cfg() -> BookConfig:
    lim = Limits(
        capital=12_000_000.0,
        max_order_value=2e6,
        max_position_value=2e6,
        max_open_positions=30,
        max_daily_loss=1e6,
        max_price_deviation=0.05,
        allow_kinds=("fut",),
        allow_products=("carry",),
    )
    return BookConfig(
        capital=3_000_000,
        k=2,
        exit_k=3,
        notional_per_position=500_000,
        slippage_bps=5,
        roll_days=2,
        risk=lim,
    )


def signals(order: list[str], d: date = date(2026, 11, 30)) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "date": [d] * len(order),
            "symbol": order,
            "rank": list(range(1, len(order) + 1)),
            "close": [1000.0] * len(order),
            "lot_size": [250] * len(order),
            "fut_expiry": [date(2026, 12, 29)] * len(order),
        }
    )


def quotes(prices: dict[str, float], when: datetime = NOW):
    return lambda syms: {s: (prices.get(s, 1000.0), when) for s in syms}


def test_plan_enters_top_and_bottom_in_whole_lots():
    intents = plan({}, signals(list("ABCDEFGH")), cfg(), TODAY)
    got = {(i["symbol"], i["qty"]) for i in intents}
    assert got == {("A", 500), ("B", 500), ("H", -500), ("G", -500)}  # 2 lots of 250 at Rs 1000 = Rs 5 lakh


def test_plan_rolls_near_expiry():
    held = {"A": {"qty": 500, "avg_price": 990.0, "lot_size": 250, "expiry": "2026-12-02", "opened": "x"}}
    intents = plan(held, signals(list("ABCDEFGH")), cfg(), TODAY)
    reasons = [i["reason"] for i in intents if i["symbol"] == "A"]
    assert reasons == ["roll_close", "roll_open"]


def test_open_and_close_day(tmp_path, monkeypatch):
    monkeypatch.setattr(pl_live, "DATA", tmp_path)
    monkeypatch.setattr(pl_live, "latest_signals", lambda today, folder="signals": signals(list("ABCDEFGH")))
    monkeypatch.setattr(pl_live, "export", lambda con: None)
    con = connect(tmp_path / "paper.db")
    c = cfg()
    r = run_open(con, c, quotes({}), NOW)
    assert r["filled"] == 4 and r["blocked"] == 0
    assert run_open(con, c, quotes({}), NOW)["skipped"].startswith("already")
    held = positions(con)
    assert held["A"]["qty"] == 500 and held["H"]["qty"] == -500
    out = run_close(
        con, c, quotes({"A": 1010.0, "B": 1000.0, "G": 1000.0, "H": 990.0}), NOW.replace(hour=15, minute=35)
    )
    # long A +10/share, short H +10/share on 500 each, minus slippage paid on entry
    assert out["open_pnl"] == pytest.approx(500 * (1010 - 1000.5) + 500 * (1000 - 990) - 500 * 0.5 * 3, abs=1)


def test_kill_file_blocks_new_positions(tmp_path, monkeypatch):
    monkeypatch.setattr(pl_live, "DATA", tmp_path)
    monkeypatch.setattr(pl_live, "latest_signals", lambda today, folder="signals": signals(list("ABCDEFGH")))
    (tmp_path / "KILL").touch()
    r = run_open(connect(tmp_path / "paper.db"), cfg(), quotes({}), NOW)
    assert r["filled"] == 0 and r["blocked"] == 4


def test_holiday_and_stale_signals_skip(tmp_path, monkeypatch):
    monkeypatch.setattr(pl_live, "DATA", tmp_path)
    monkeypatch.setattr(pl_live, "latest_signals", lambda today, folder="signals": signals(list("ABCDEFGH")))
    con = connect(tmp_path / "paper.db")
    assert "market closed" in run_open(con, cfg(), quotes({}, when=datetime(2026, 11, 30, 15, 29)), NOW)["skipped"]
    monkeypatch.setattr(
        pl_live, "latest_signals", lambda today, folder="signals": signals(list("ABCDEFGH"), d=date(2026, 11, 20))
    )
    assert "stale" in run_open(con, cfg(), quotes({}), NOW)["skipped"]


def test_config_file_loads():
    c = BookConfig.load()  # the Rs 50,000 paper account: long-only cash book following the cash champion
    assert c.capital == 50_000 and c.vehicle == "delivery" and c.long_only and c.signals == "signals-cash"
    assert c.risk.allow_kinds == ("eq",) and c.risk.allow_products == ("delivery",)
    assert c.k * c.notional_per_position <= c.capital


def delivery_cfg() -> BookConfig:
    lim = Limits(
        capital=60_000.0,
        max_order_value=15_000,
        max_position_value=15_000,
        max_open_positions=6,
        max_daily_loss=5_000,
        max_price_deviation=0.05,
        allow_kinds=("eq",),
        allow_products=("delivery",),
    )
    return BookConfig(
        capital=50_000,
        k=3,
        exit_k=4,
        notional_per_position=10_000,
        slippage_bps=5,
        roll_days=0,
        risk=lim,
        vehicle="delivery",
        long_only=True,
    )


def test_delivery_book_pays_cash_and_marks_shares(tmp_path, monkeypatch):
    monkeypatch.setattr(pl_live, "DATA", tmp_path)
    monkeypatch.setattr(
        pl_live,
        "latest_signals",
        lambda today, folder="signals": signals(list("ABCDEFGH")).with_columns(
            pl.lit(None, dtype=pl.Int64).alias("lot_size")
        ),
    )  # cash book: no futures lot needed
    monkeypatch.setattr(pl_live, "export", lambda con: None)
    con = connect(tmp_path / "paper.db")
    c = delivery_cfg()
    r = run_open(con, c, quotes({}), NOW)
    held = positions(con)
    assert (
        r["filled"] == 3 and set(held) == {"A", "B", "C"} and all(p["qty"] == 10 for p in held.values())
    )  # 10k / 1000
    cash_left = pl_live.cash(con, c)
    assert cash_left == pytest.approx(50_000 - 3 * 10 * 1000.5 - r["charges"])
    out = run_close(con, c, quotes({"A": 1100.0, "B": 1000.0, "C": 900.0}), NOW.replace(hour=15, minute=35))
    assert out["equity"] == pytest.approx(cash_left + 10 * (1100 + 1000 + 900))


def test_delivery_book_never_spends_more_than_cash(tmp_path, monkeypatch):
    monkeypatch.setattr(pl_live, "DATA", tmp_path)
    monkeypatch.setattr(pl_live, "latest_signals", lambda today, folder="signals": signals(list("ABCDEFGH")))
    c = delivery_cfg()
    c = BookConfig(**{**c.__dict__, "capital": 15_000})
    r = run_open(connect(tmp_path / "paper.db"), c, quotes({}), NOW)
    assert r["filled"] == 1 and r["blocked"] == 2
