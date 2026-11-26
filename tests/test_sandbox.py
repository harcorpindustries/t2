from datetime import date, datetime, timedelta

import pytest

from t2.brokers.base import Contract, Kind, Order, Product, Side, Status
from t2.brokers.paper import Bar, PaperBroker
from t2.trader.costs import BrokeragePlan, charges

T0 = datetime(2026, 11, 2, 9, 15)
EQ = Contract("RELIANCE")
FUT = Contract("NIFTY", Kind.FUT, expiry=date(2026, 11, 24), lot_size=75, tick=0.1)
OPT = Contract("NIFTY", Kind.OPT, expiry=date(2026, 11, 24), strike=24000, right="CE", lot_size=75)
FREE = BrokeragePlan(minimum=0, maximum=0, dp_per_sell=0)


def bar(minute: int, o: float, h: float, low: float, c: float, v: int = 1_000_000) -> Bar:
    return Bar(T0 + timedelta(minutes=minute), o, h, low, c, v)


def order(contract=EQ, side=Side.BUY, qty=10, limit=100.0, product=Product.INTRADAY, at=0) -> Order:
    return Order(contract, side, qty, limit, product, T0 + timedelta(minutes=at, seconds=1))


def test_charges_delivery_buy_and_sell():
    buy = charges(Kind.EQ, Product.DELIVERY, Side.BUY, 100, 1000.0, date(2026, 11, 2))
    assert buy.stt == pytest.approx(100.0)  # 0.1% of 1 lakh
    assert buy.stamp == pytest.approx(15.0)
    assert buy.dp == 0
    sell = charges(Kind.EQ, Product.DELIVERY, Side.SELL, 100, 1000.0, date(2026, 11, 2))
    assert sell.stamp == 0 and sell.dp == 20.0
    assert sell.gst == pytest.approx((20 + 2.97 + 0.1 + 20) * 0.18)


def test_charges_fno_stt_follows_budget_date():
    before = charges(Kind.FUT, Product.CARRY, Side.SELL, 75, 24000.0, date(2026, 3, 31))
    after = charges(Kind.FUT, Product.CARRY, Side.SELL, 75, 24000.0, date(2026, 4, 1))
    assert before.stt == pytest.approx(75 * 24000 * 0.0002)
    assert after.stt == pytest.approx(75 * 24000 * 0.0005)
    assert charges(Kind.OPT, Product.CARRY, Side.BUY, 75, 100.0, date(2026, 4, 1)).stt == 0


def test_no_fill_in_the_bar_the_order_was_placed():
    b = PaperBroker(1_000_000, plan=FREE)
    o = b.place(order(limit=100.0, at=0))
    assert b.on_bar(EQ.key, bar(0, 99, 99, 98, 99)) == []  # same bar: not eligible
    assert len(b.on_bar(EQ.key, bar(1, 99, 99, 98, 99))) == 1
    assert o.status == Status.FILLED and o.avg_price == 99  # opened below the limit: fills at the open


def test_touching_the_limit_is_not_a_fill():
    b = PaperBroker(1_000_000, plan=FREE)
    o = b.place(order(limit=100.0))
    b.on_bar(EQ.key, bar(1, 101, 102, 100.0, 101))
    assert o.status == Status.OPEN
    b.on_bar(EQ.key, bar(2, 101, 102, 99.95, 101))
    assert o.status == Status.FILLED and o.avg_price == 100.0


def test_partial_fills_follow_volume():
    b = PaperBroker(1_000_000, plan=FREE, participation=0.1)
    o = b.place(order(qty=150, limit=100.0))
    b.on_bar(EQ.key, bar(1, 100, 100, 99, 100, v=1000))
    assert o.status == Status.PARTIAL and o.filled == 100
    b.on_bar(EQ.key, bar(2, 100, 100, 99, 100, v=1000))
    assert o.status == Status.FILLED


def test_rejections():
    b = PaperBroker(10_000, plan=FREE)
    assert b.place(order(limit=100.03)).reason.startswith("limit must")
    assert b.place(order(contract=FUT, qty=10, product=Product.CARRY, limit=24000.0)).reason.startswith("qty must")
    assert b.place(order(product=Product.CARRY)).status == Status.REJECTED
    assert b.place(order(side=Side.SELL, product=Product.DELIVERY)).reason.startswith("insufficient")  # no shorting
    assert b.place(order(qty=1000, limit=100.0, product=Product.DELIVERY)).reason.startswith("insufficient")


def test_order_rate_limit():
    b = PaperBroker(10_000_000, plan=FREE, max_orders_per_sec=10)
    placed = [b.place(Order(EQ, Side.BUY, 1, 100.0, Product.INTRADAY, T0)) for _ in range(11)]
    assert [o.status for o in placed].count(Status.REJECTED) == 1
    assert b.place(Order(EQ, Side.BUY, 1, 100.0, Product.INTRADAY, T0 + timedelta(seconds=1))).status == Status.OPEN


def test_intraday_round_trip_pnl_and_cash():
    b = PaperBroker(100_000, plan=FREE)
    b.place(order(qty=100, limit=100.0))
    b.on_bar(EQ.key, bar(1, 100, 100, 99, 100))
    assert b.cash() == pytest.approx(100_000 - 100 * 100 * 0.2 - _ch(Side.BUY, 100, 100))
    b.place(order(side=Side.SELL, qty=100, limit=105.0, at=2))
    b.on_bar(EQ.key, bar(3, 105, 106, 104, 105))
    expected = 100_000 + 500 - _ch(Side.BUY, 100, 100) - _ch(Side.SELL, 100, 105)
    assert b.cash() == pytest.approx(expected)
    assert b.equity() == pytest.approx(expected)


def test_short_intraday_and_square_off():
    b = PaperBroker(100_000, plan=FREE)
    b.place(order(side=Side.SELL, qty=50, limit=200.0))
    b.on_bar(EQ.key, bar(1, 200, 201, 199, 198))
    assert b.cash() == pytest.approx(100_000 - 50 * 200 * 0.2 - b.fills[0].charges)
    assert b.equity() == pytest.approx(100_000 - b.fills[0].charges + 50 * 2)
    fills = b.square_off(T0 + timedelta(hours=6))
    assert len(fills) == 1 and fills[0].side == Side.BUY and fills[0].price == 198
    pos = b.positions()[0]
    assert pos.qty == 0 and pos.realized == pytest.approx(100 - sum(f.charges for f in b.fills))
    assert b.cash() == pytest.approx(100_000 + pos.realized)


def test_option_buy_paid_in_full_and_sold():
    b = PaperBroker(100_000, plan=FREE)
    b.place(order(contract=OPT, qty=75, limit=100.0, product=Product.CARRY))
    b.on_bar(OPT.key, bar(1, 100, 101, 99, 120))
    assert b.cash() == pytest.approx(100_000 - 7500 - b.fills[0].charges)
    assert b.equity() == pytest.approx(b.cash() + 75 * 120)
    b.place(order(contract=OPT, side=Side.SELL, qty=75, limit=120.0, product=Product.CARRY, at=2))
    b.on_bar(OPT.key, bar(3, 120, 121, 119, 120))
    total_charges = sum(f.charges for f in b.fills)
    assert b.cash() == pytest.approx(100_000 + 75 * 20 - total_charges)


def _ch(side: Side, qty: int, price: float) -> float:
    return charges(Kind.EQ, Product.INTRADAY, side, qty, price, T0.date(), FREE).total


def test_slippage_is_adverse_but_never_past_the_limit():
    b = PaperBroker(1_000_000, plan=FREE, slippage_bps=10)
    o = b.place(order(limit=100.0))
    b.on_bar(EQ.key, bar(1, 99.0, 99, 98, 99))
    assert o.avg_price == pytest.approx(99.0 * 1.001)
    o2 = b.place(order(limit=100.0, at=2))
    b.on_bar(EQ.key, bar(3, 99.95, 100, 99, 99))
    assert o2.avg_price == 100.0  # capped at the limit
