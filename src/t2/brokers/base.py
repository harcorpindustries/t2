"""Broker-neutral order model. Every broker (paper, Breeze, future others) speaks these types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class Kind(StrEnum):
    EQ = "eq"
    FUT = "fut"
    OPT = "opt"


class Product(StrEnum):
    INTRADAY = "intraday"  # squared off the same day, leveraged
    DELIVERY = "delivery"  # cash equity held overnight, fully paid
    CARRY = "carry"  # F&O positions held overnight (NRML)


class Status(StrEnum):
    OPEN = "open"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Contract:
    symbol: str
    kind: Kind = Kind.EQ
    expiry: date | None = None
    strike: float | None = None
    right: str | None = None  # "CE" / "PE" for options
    lot_size: int = 1
    tick: float = 0.05

    @property
    def key(self) -> str:
        if self.kind == Kind.EQ:
            return self.symbol
        parts = [self.symbol, self.kind.value, self.expiry.isoformat() if self.expiry else ""]
        if self.kind == Kind.OPT:
            parts += [f"{self.strike:g}", self.right or ""]
        return ":".join(parts)


@dataclass
class Order:
    contract: Contract
    side: Side
    qty: int
    limit: float  # Breeze and SEBI rules for algos: limit orders only
    product: Product
    created: datetime
    tag: str = ""
    id: str = ""
    status: Status = Status.OPEN
    filled: int = 0
    avg_price: float = 0.0
    reason: str = ""

    @property
    def remaining(self) -> int:
        return self.qty - self.filled

    @property
    def active(self) -> bool:
        return self.status in (Status.OPEN, Status.PARTIAL)


@dataclass(frozen=True)
class Fill:
    order_id: str
    contract: Contract
    side: Side
    product: Product
    qty: int
    price: float
    ts: datetime
    charges: float


@dataclass
class Position:
    contract: Contract
    product: Product
    qty: int = 0  # signed: + long, - short
    avg_price: float = 0.0
    realized: float = 0.0
    fills: list[Fill] = field(default_factory=list)


class Broker(Protocol):
    def place(self, order: Order) -> Order: ...
    def cancel(self, order_id: str) -> Order: ...
    def orders(self) -> list[Order]: ...
    def positions(self) -> list[Position]: ...
    def cash(self) -> float: ...
