"""Risk manager: hard-coded rules every order passes through before any broker sees it. Never learned, never bypassed.

Checks, in order (the first failure blocks the order):
 1. kill switch: when on, only orders that reduce an existing position pass
 2. allowed instruments/products (e.g. no naked option selling until enabled)
 3. trading window: no new exposure before the open, after the entry cut-off, or on non-session days
 4. fat-finger: limit price within `max_price_deviation` of the last traded price
 5. order rate: orders per second (below the SEBI retail algo threshold) and per day
 6. size: per-order notional, per-symbol position notional, open position count, total gross exposure
 7. daily loss: once the day's P&L (realized + open) hits `max_daily_loss`, the kill switch turns on by itself

Defaults are for the paper sandbox. Live limits load from config/live/ and change only via an owner-approved PR.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, time, timedelta
from pathlib import Path

from t2.brokers.base import Kind, Order, Product, Side


@dataclass(frozen=True)
class Limits:
    capital: float = 1_000_000.0  # total money the system may put at risk (gross exposure cap)
    max_order_value: float = 100_000.0
    max_position_value: float = 200_000.0
    max_open_positions: int = 20
    max_daily_loss: float = 20_000.0
    max_orders_per_sec: int = 5
    max_orders_per_day: int = 500
    max_price_deviation: float = 0.03
    allow_kinds: tuple[str, ...] = ("eq", "fut", "opt")
    allow_products: tuple[str, ...] = ("intraday", "delivery", "carry")
    allow_short_options: bool = False
    session_open: time = time(9, 15)
    entry_cutoff: time = time(15, 10)  # no new exposure after this
    square_off: time = time(15, 15)  # intraday positions closed from here

    @classmethod
    def load(cls, path: Path) -> Limits:
        raw = json.loads(path.read_text())
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"unknown risk limit keys: {sorted(unknown)}")
        for k in ("session_open", "entry_cutoff", "square_off"):
            if k in raw:
                raw[k] = time.fromisoformat(raw[k])
        for k in ("allow_kinds", "allow_products"):
            if k in raw:
                raw[k] = tuple(raw[k])
        return cls(**raw)


@dataclass(frozen=True)
class Decision:
    ok: bool
    reason: str = ""


@dataclass(frozen=True)
class Book:
    """What the risk manager needs to know about the account right now (from the broker)."""

    positions: dict[tuple[str, str], tuple[int, float]]  # (contract key, product) -> (signed qty, last price)
    day_pnl: float  # realized + open P&L since the session started, after charges
    last_price: dict[str, float]


@dataclass
class RiskManager:
    limits: Limits = field(default_factory=Limits)
    kill: bool = False
    kill_reason: str = ""
    _sent: deque[datetime] = field(default_factory=deque)
    _day: date | None = None
    _day_count: int = 0
    events: list[dict] = field(default_factory=list)

    def engage_kill(self, reason: str, ts: datetime) -> None:
        if not self.kill:
            self.kill, self.kill_reason = True, reason
            self.events.append({"ts": ts.isoformat(), "event": "kill_on", "reason": reason})

    def release_kill(self, ts: datetime, by: str) -> None:
        """Only a person turns the kill switch off (dashboard button / CLI), never the system."""
        if self.kill:
            self.events.append({"ts": ts.isoformat(), "event": "kill_off", "by": by})
        self.kill, self.kill_reason = False, ""

    def check(self, o: Order, book: Book, session_day: bool = True) -> Decision:
        d = self._check(o, book, session_day)
        if d.ok:
            self._record(o.created)
        else:
            self.events.append(
                {"ts": o.created.isoformat(), "event": "blocked", "order": o.contract.key, "why": d.reason}
            )
        return d

    # ----- internals -----
    def _check(self, o: Order, book: Book, session_day: bool) -> Decision:
        lim = self.limits
        if book.day_pnl <= -lim.max_daily_loss:
            self.engage_kill(f"daily loss {book.day_pnl:,.0f} hit limit {lim.max_daily_loss:,.0f}", o.created)

        held, _ = book.positions.get((o.contract.key, o.product.value), (0, 0.0))
        signed = o.qty if o.side == Side.BUY else -o.qty
        reducing = held != 0 and held * signed < 0 and abs(signed) <= abs(held)

        if self.kill and not reducing:
            return Decision(False, f"kill switch on: {self.kill_reason}")
        if o.contract.kind.value not in lim.allow_kinds:
            return Decision(False, f"{o.contract.kind.value} not allowed")
        if o.product.value not in lim.allow_products:
            return Decision(False, f"{o.product.value} not allowed")
        if o.contract.kind == Kind.OPT and not reducing and held + signed < 0 and not lim.allow_short_options:
            return Decision(False, "short options not allowed")

        now = o.created.time()
        if not reducing:
            if not session_day:
                return Decision(False, "not a trading session")
            if now < lim.session_open or now >= lim.entry_cutoff:
                return Decision(False, f"outside entry window {lim.session_open}-{lim.entry_cutoff}")
            if o.product == Product.INTRADAY and now >= lim.square_off:
                return Decision(False, "intraday square-off time")

        last = book.last_price.get(o.contract.key)
        if last is None:
            return Decision(False, "no last price: cannot sanity-check the limit")
        if abs(o.limit / last - 1) > lim.max_price_deviation:
            return Decision(False, f"limit {o.limit} is more than {lim.max_price_deviation:.0%} from last {last}")

        self._roll(o.created)
        if len(self._sent) >= lim.max_orders_per_sec:
            return Decision(False, "orders per second limit")
        if self._day_count >= lim.max_orders_per_day:
            return Decision(False, "orders per day limit")

        if reducing:
            return Decision(True)
        value = o.qty * o.limit  # F&O qty is in units (lots x lot size); option value is the premium
        if value > lim.max_order_value:
            return Decision(False, f"order value {value:,.0f} over {lim.max_order_value:,.0f}")
        new_pos = abs(held + signed) * o.limit
        if new_pos > lim.max_position_value:
            return Decision(False, f"position value {new_pos:,.0f} over {lim.max_position_value:,.0f}")
        open_count = sum(1 for q, _ in book.positions.values() if q != 0)
        if held == 0 and open_count >= lim.max_open_positions:
            return Decision(False, f"{open_count} open positions (max {lim.max_open_positions})")
        gross = sum(abs(q) * px for q, px in book.positions.values()) + value
        if gross > lim.capital:
            return Decision(False, f"gross exposure {gross:,.0f} over capital {lim.capital:,.0f}")
        return Decision(True)

    def _roll(self, ts: datetime) -> None:
        while self._sent and ts - self._sent[0] >= timedelta(seconds=1):
            self._sent.popleft()
        if self._day != ts.date():
            self._day, self._day_count = ts.date(), 0

    def _record(self, ts: datetime) -> None:
        self._roll(ts)
        self._sent.append(ts)
        self._day_count += 1

    def snapshot(self) -> dict:
        return {"kill": self.kill, "kill_reason": self.kill_reason, "limits": asdict(self.limits)}
