from datetime import date, datetime, time
from pathlib import Path

import pytest

from t2.brokers.base import Contract, Kind, Order, Product, Side
from t2.trader.risk import Book, Limits, RiskManager

EQ = Contract("TCS")
OPT = Contract("NIFTY", Kind.OPT, expiry=date(2026, 12, 29), strike=24000, right="CE", lot_size=75)
AT = datetime(2026, 11, 26, 10, 0)


def order(c=EQ, side=Side.BUY, qty=10, limit=100.0, product=Product.INTRADAY, at=AT) -> Order:
    return Order(c, side, qty, limit, product, at)


def book(positions=None, pnl=0.0, last=None) -> Book:
    return Book(positions or {}, pnl, last or {EQ.key: 100.0, OPT.key: 100.0})


def rm(**kw) -> RiskManager:
    return RiskManager(Limits(**kw))


def test_ok_order_passes():
    assert rm().check(order(), book()).ok


@pytest.mark.parametrize(
    ("o", "why"),
    [
        (order(limit=104.0), "from last"),
        (order(qty=2000), "order value"),
        (order(at=datetime(2026, 11, 26, 9, 0)), "entry window"),
        (order(at=datetime(2026, 11, 26, 15, 12)), "entry window"),
        (order(c=OPT, side=Side.SELL, qty=75, product=Product.CARRY), "short options"),
    ],
)
def test_blocks(o, why):
    d = rm().check(o, book())
    assert not d.ok and why in d.reason


def test_unknown_price_blocks():
    assert "no last price" in rm().check(order(c=Contract("XYZ")), book()).reason


def test_daily_loss_trips_kill_but_allows_reducing():
    r = rm(max_daily_loss=1000)
    held = {(EQ.key, "intraday"): (50, 100.0)}
    assert "kill switch" in r.check(order(), book(held, pnl=-1500)).reason
    assert r.kill
    assert r.check(order(side=Side.SELL, qty=50), book(held, pnl=-1500)).ok  # closing is always allowed
    assert not r.check(order(side=Side.SELL, qty=60), book(held, pnl=-1500)).ok  # flipping short is new exposure
    r.release_kill(AT, by="owner")
    assert r.check(order(), book(held, pnl=0)).ok


def test_reducing_allowed_after_cutoff():
    held = {(EQ.key, "intraday"): (50, 100.0)}
    late = datetime(2026, 11, 26, 15, 20)
    assert rm().check(order(side=Side.SELL, qty=50, at=late), book(held)).ok


def test_rate_limits():
    r = rm(max_orders_per_sec=2, max_orders_per_day=3)
    assert [r.check(order(), book()).ok for _ in range(3)] == [True, True, False]
    later = AT.replace(second=5)
    assert r.check(order(at=later), book()).ok
    assert "per day" in r.check(order(at=later.replace(second=10)), book()).reason


def test_position_and_exposure_caps():
    r = rm(max_position_value=5000, max_open_positions=1, capital=20_000)
    held = {(EQ.key, "intraday"): (45, 100.0)}
    assert "position value" in r.check(order(qty=10), book(held)).reason
    other = Contract("INFY")
    last = {EQ.key: 100.0, other.key: 100.0}
    assert "open positions" in r.check(order(c=other), book(held, last=last)).reason


def test_live_config_is_locked_down_until_owner_sets_it():
    lim = Limits.load(Path("config/live/risk_limits.json"))
    assert lim.capital == 0 and lim.max_daily_loss == 0
    r = RiskManager(lim)
    assert not r.check(order(), book()).ok  # zero capital: nothing can open


def test_unknown_keys_rejected(tmp_path):
    p = tmp_path / "l.json"
    p.write_text('{"capitol": 5}')
    with pytest.raises(ValueError, match="unknown"):
        Limits.load(p)


def test_session_time_parsing(tmp_path):
    p = tmp_path / "l.json"
    p.write_text('{"entry_cutoff": "14:30"}')
    assert Limits.load(p).entry_cutoff == time(14, 30)
