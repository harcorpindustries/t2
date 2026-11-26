"""Indian trading charges per fill: brokerage, STT, exchange fee, SEBI fee, stamp duty, GST, DP charge.

Statutory rates change with budgets and exchange circulars, so they are a dated table. A fill uses the
newest schedule whose start date is on or before its trade date (older trades use the oldest one).
Brokerage depends on the account's plan and is a separate setting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from t2.brokers.base import Kind, Product, Side


@dataclass(frozen=True)
class Statutory:
    start: date
    stt: dict[str, tuple[float, float]]  # segment -> (buy rate, sell rate)
    exchange: dict[str, float]  # NSE transaction charge, both sides
    stamp_buy: dict[str, float]
    sebi: float = 10 / 1e7  # Rs 10 per crore
    gst: float = 0.18


SCHEDULES: tuple[Statutory, ...] = (
    Statutory(
        start=date(2024, 10, 1),
        stt={"delivery": (0.001, 0.001), "intraday": (0, 0.00025), "fut": (0, 0.0002), "opt": (0, 0.001)},
        exchange={"delivery": 0.0000297, "intraday": 0.0000297, "fut": 0.0000173, "opt": 0.0003503},
        stamp_buy={"delivery": 0.00015, "intraday": 0.00003, "fut": 0.00002, "opt": 0.00003},
    ),
    # Union Budget 2026-27: F&O STT raised (futures 0.05%, options 0.15% of premium on sell).
    Statutory(
        start=date(2026, 4, 1),
        stt={"delivery": (0.001, 0.001), "intraday": (0, 0.00025), "fut": (0, 0.0005), "opt": (0, 0.0015)},
        exchange={"delivery": 0.0000297, "intraday": 0.0000297, "fut": 0.0000173, "opt": 0.0003503},
        stamp_buy={"delivery": 0.00015, "intraday": 0.00003, "fut": 0.00002, "opt": 0.00003},
    ),
)


@dataclass(frozen=True)
class BrokeragePlan:
    """Brokerage per executed order: pct of turnover, clipped to [minimum, maximum]."""

    pct: float = 0.0
    minimum: float = 20.0
    maximum: float = 20.0
    dp_per_sell: float = 20.0  # depository charge per delivery sell (per scrip per day, charged per sell fill here)


DEFAULT_PLAN = BrokeragePlan()


def segment(kind: Kind, product: Product) -> str:
    if kind == Kind.FUT:
        return "fut"
    if kind == Kind.OPT:
        return "opt"
    return "intraday" if product == Product.INTRADAY else "delivery"


def schedule_for(d: date) -> Statutory:
    current = SCHEDULES[0]
    for s in SCHEDULES:
        if s.start <= d:
            current = s
    return current


@dataclass(frozen=True)
class Charges:
    brokerage: float
    stt: float
    exchange: float
    sebi: float
    stamp: float
    gst: float
    dp: float

    @property
    def total(self) -> float:
        return self.brokerage + self.stt + self.exchange + self.sebi + self.stamp + self.gst + self.dp


def charges(
    kind: Kind, product: Product, side: Side, qty: int, price: float, d: date, plan: BrokeragePlan = DEFAULT_PLAN
) -> Charges:
    """Charges for one fill. For options, price is the premium, so turnover is premium x qty."""
    seg = segment(kind, product)
    s = schedule_for(d)
    turnover = abs(qty) * price
    brokerage = min(max(turnover * plan.pct, plan.minimum), plan.maximum)
    buy_rate, sell_rate = s.stt[seg]
    stt = turnover * (buy_rate if side == Side.BUY else sell_rate)
    exchange = turnover * s.exchange[seg]
    sebi = turnover * s.sebi
    stamp = turnover * s.stamp_buy[seg] if side == Side.BUY else 0.0
    dp = plan.dp_per_sell if (seg == "delivery" and side == Side.SELL) else 0.0
    gst = (brokerage + exchange + sebi + dp) * s.gst
    return Charges(brokerage, stt, exchange, sebi, stamp, gst, dp)
