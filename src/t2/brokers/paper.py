"""PaperBroker: simulated broker that fills limit orders against bars as conservatively as the real market would.

Fill rules (per bar, in time order):
- An order only becomes eligible on bars that start after it was placed: no fills inside the bar it was decided on.
- Buy limit: if the bar opens at or below the limit, it fills at the open (a gap in our favour). Otherwise it fills at
  the limit only if the low trades strictly through it by at least one tick (touching is not enough: queue position).
  Sell is the mirror image.
- Each bar fills at most `participation` x bar volume, so large orders fill over several bars (partial fills).
- Breeze-like rules: limit price on the tick grid, F&O quantity in whole lots, at most `max_orders_per_sec`.
- Cash: delivery buys are paid in full. Intraday and F&O block `margin[segment]` x notional (bought options: in full).
"""

from __future__ import annotations

import itertools
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from t2.brokers.base import Contract, Fill, Kind, Order, Position, Product, Side, Status
from t2.trader.costs import DEFAULT_PLAN, BrokeragePlan, charges, segment

DEFAULT_MARGIN = {"intraday": 0.2, "delivery": 1.0, "fut": 0.15, "opt_short": 0.15, "opt_long": 1.0}


@dataclass(frozen=True)
class Bar:
    ts: datetime  # bar start
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class PaperBroker:
    starting_cash: float
    plan: BrokeragePlan = DEFAULT_PLAN
    participation: float = 0.1
    max_orders_per_sec: int = 10
    margin: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_MARGIN))
    _cash: float = field(init=False)
    _orders: dict[str, Order] = field(init=False, default_factory=dict)
    _positions: dict[tuple[str, Product], Position] = field(init=False, default_factory=dict)
    _fills: list[Fill] = field(init=False, default_factory=list)
    _recent: deque[datetime] = field(init=False, default_factory=deque)
    _ids: itertools.count[int] = field(init=False, default_factory=itertools.count)
    _last: dict[str, float] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self._cash = self.starting_cash

    # ----- Broker protocol -----
    def place(self, order: Order) -> Order:
        order.id = f"P{next(self._ids):08d}"
        self._orders[order.id] = order
        reason = self._validate(order)
        if reason:
            order.status, order.reason = Status.REJECTED, reason
        else:
            self._recent.append(order.created)
        return order

    def cancel(self, order_id: str) -> Order:
        o = self._orders[order_id]
        if o.active:
            o.status = Status.CANCELLED
        return o

    def orders(self) -> list[Order]:
        return list(self._orders.values())

    def positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.qty != 0 or p.realized != 0]

    def cash(self) -> float:
        return self._cash

    # ----- simulation -----
    @property
    def fills(self) -> list[Fill]:
        return list(self._fills)

    def on_bar(self, contract_key: str, bar: Bar) -> list[Fill]:
        self._last[contract_key] = bar.close
        left = int(bar.volume * self.participation)
        out: list[Fill] = []
        for o in self._orders.values():
            if left <= 0:
                break
            if not o.active or o.contract.key != contract_key or o.created >= bar.ts:
                continue
            price = _fill_price(o, bar)
            if price is None:
                continue
            qty = min(o.remaining, left)
            if o.contract.kind != Kind.EQ:
                qty -= qty % o.contract.lot_size
            if qty <= 0:
                continue
            out.append(self._fill(o, qty, price, bar.ts))
            left -= qty
        return out

    def mark(self, contract_key: str, price: float) -> None:
        self._last[contract_key] = price

    def equity(self) -> float:
        """Free cash plus the mark-to-market value of open positions (including margin blocked for them)."""
        value = 0.0
        for p in self._positions.values():
            if p.qty == 0:
                continue
            px = self._last.get(p.contract.key, p.avg_price)
            if p.product == Product.DELIVERY or (p.contract.kind == Kind.OPT and p.qty > 0):
                value += p.qty * px  # owned asset
            else:  # leveraged: blocked margin comes back, plus the open P&L
                blocked = abs(p.qty) * p.avg_price * self._margin_rate(p.contract, p.product, _opening_side(p.qty))
                value += blocked + p.qty * (px - p.avg_price)
        return self._cash + value

    def square_off(self, ts: datetime, products: tuple[Product, ...] = (Product.INTRADAY,)) -> list[Fill]:
        """Close positions at the last price (broker auto square-off). Cancels their open orders first."""
        for o in self._orders.values():
            if o.active and o.product in products:
                o.status = Status.CANCELLED
        out = []
        for p in list(self._positions.values()):
            if p.qty == 0 or p.product not in products:
                continue
            side = Side.SELL if p.qty > 0 else Side.BUY
            px = self._last.get(p.contract.key, p.avg_price)
            o = Order(p.contract, side, abs(p.qty), px, p.product, ts, tag="square_off")
            o.id = f"P{next(self._ids):08d}"
            self._orders[o.id] = o
            out.append(self._fill(o, abs(p.qty), px, ts))
        return out

    # ----- internals -----
    def _validate(self, o: Order) -> str:
        c = o.contract
        if o.qty <= 0:
            return "qty must be positive"
        if c.kind != Kind.EQ and o.qty % c.lot_size:
            return f"qty must be a multiple of lot size {c.lot_size}"
        if c.kind == Kind.EQ and o.product == Product.CARRY:
            return "carry product is for F&O only"
        if c.kind != Kind.EQ and o.product == Product.DELIVERY:
            return "delivery product is for cash equity only"
        if o.limit <= 0 or abs(round(o.limit / c.tick) * c.tick - o.limit) > 1e-6:
            return f"limit must be positive and on the {c.tick} tick grid"
        while self._recent and o.created - self._recent[0] >= timedelta(seconds=1):
            self._recent.popleft()
        if len(self._recent) >= self.max_orders_per_sec:
            return "order rate limit"
        need = self._cash_needed(o, o.qty, o.limit)
        if need > self._cash + 1e-9:
            return f"insufficient funds: need {need:.2f}, have {self._cash:.2f}"
        return ""

    def _margin_rate(self, c: Contract, product: Product, side: Side) -> float:
        if c.kind == Kind.OPT:
            return self.margin["opt_long"] if side == Side.BUY else self.margin["opt_short"]
        return self.margin[segment(c.kind, product)]

    def _cash_needed(self, o: Order, qty: int, price: float) -> float:
        """Extra cash this order takes if it only opens or adds to a position (closing frees cash instead)."""
        p = self._positions.get((o.contract.key, o.product))
        held = p.qty if p else 0
        signed = qty if o.side == Side.BUY else -qty
        opening = max(0, abs(held + signed) - abs(held)) if held * signed >= 0 else max(0, abs(signed) - abs(held))
        if o.contract.kind == Kind.EQ and o.product == Product.DELIVERY and o.side == Side.SELL:
            return 0.0 if held >= qty else float("inf")  # no short selling in delivery
        return opening * price * self._margin_rate(o.contract, o.product, o.side)

    def _fill(self, o: Order, qty: int, price: float, ts: datetime) -> Fill:
        c = o.contract
        ch = charges(c.kind, o.product, o.side, qty, price, ts.date(), self.plan).total
        key = (c.key, o.product)
        p = self._positions.setdefault(key, Position(c, o.product))
        signed = qty if o.side == Side.BUY else -qty
        rate = self._margin_rate(c, o.product, o.side)
        owned = o.product == Product.DELIVERY or (c.kind == Kind.OPT and (p.qty > 0 or (p.qty == 0 and signed > 0)))

        if p.qty == 0 or (p.qty > 0) == (signed > 0):  # open or add
            if owned:
                self._cash -= qty * price
            else:
                self._cash -= qty * price * rate
            p.avg_price = (p.avg_price * abs(p.qty) + price * qty) / (abs(p.qty) + qty)
            p.qty += signed
        else:  # reduce, close, or flip
            closing = min(qty, abs(p.qty))
            direction = 1 if p.qty > 0 else -1
            pnl = closing * (price - p.avg_price) * direction
            p.realized += pnl
            if owned:
                self._cash += closing * price
            else:
                self._cash += closing * p.avg_price * self._margin_rate(c, o.product, _opening_side(p.qty)) + pnl
            p.qty += direction * -closing
            rest = qty - closing
            if rest:
                p.avg_price = price
                p.qty = signed // qty * rest
                self._cash -= rest * price * (1.0 if (c.kind == Kind.OPT and signed > 0) else rate)
            elif p.qty == 0:
                p.avg_price = 0.0
        self._cash -= ch
        p.realized -= ch

        o.avg_price = (o.avg_price * o.filled + price * qty) / (o.filled + qty)
        o.filled += qty
        o.status = Status.FILLED if o.remaining == 0 else Status.PARTIAL
        f = Fill(o.id, c, o.side, o.product, qty, price, ts, ch)
        p.fills.append(f)
        self._fills.append(f)
        return f


def _opening_side(qty: int) -> Side:
    return Side.BUY if qty > 0 else Side.SELL


def _fill_price(o: Order, bar: Bar) -> float | None:
    tick = o.contract.tick
    if o.side == Side.BUY:
        if bar.open <= o.limit:
            return bar.open
        return o.limit if bar.low <= o.limit - tick else None
    if bar.open >= o.limit:
        return bar.open
    return o.limit if bar.high >= o.limit + tick else None
