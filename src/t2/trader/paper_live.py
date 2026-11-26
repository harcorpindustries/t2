"""Live paper trading of the champion book on the server: real signals, real prices, simulated fills. No orders.

    python -m t2.trader.paper_live open    # 09:20 IST: rebalance to today's signals at live prices
    python -m t2.trader.paper_live close   # 15:35 IST: mark to market, record the day, export to HF

The book is stock futures, K longs and K shorts held with the hold buffer (holding.rebalance, the same rule as the
backtest). Prices are the cash stock's live price (the same proxy the backtest uses); size is whole futures lots
nearest to `notional_per_position`. Fills: the live price plus slippage, charged at stock-futures rates. Every order
passes the risk manager first; a KILL file in the data directory stops all new positions.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from t2 import alerts
from t2.backtest.holding import rebalance
from t2.brokers.base import Contract, Kind, Order, Product, Side
from t2.data import hf_store
from t2.trader.costs import charges
from t2.trader.risk import Book, Limits, RiskManager

IST = ZoneInfo("Asia/Kolkata")
DATA = Path(os.environ.get("T2_PAPER_DIR", "/opt/t2/data"))
CONFIG = Path(__file__).resolve().parents[3] / "config" / "paper" / "book.json"

Quotes = Callable[[list[str]], dict[str, tuple[float, datetime]]]  # symbol -> (last price, last trade time IST)


@dataclass(frozen=True)
class BookConfig:
    capital: float
    k: int
    exit_k: int
    notional_per_position: float
    slippage_bps: float
    roll_days: int
    risk: Limits
    vehicle: str = "fut"  # "fut": stock futures (lots, margin, rolls) | "delivery": cash shares, fully paid
    long_only: bool = False
    signals: str = "signals"  # dataset folder of the champion this book follows

    @property
    def kind_product(self) -> tuple[Kind, Product]:
        return (Kind.FUT, Product.CARRY) if self.vehicle == "fut" else (Kind.EQ, Product.DELIVERY)

    @classmethod
    def load(cls, path: Path = CONFIG) -> BookConfig:
        raw = json.loads(path.read_text())
        risk_path = Path(tempfile.mkstemp(suffix=".json")[1])
        risk_path.write_text(json.dumps(raw.pop("risk")))
        try:
            return cls(risk=Limits.load(risk_path), **raw)
        finally:
            risk_path.unlink()


SCHEMA = """
create table if not exists positions (symbol text primary key, qty integer, avg_price real, lot_size integer,
  expiry text, opened text);
create table if not exists trades (ts text, day text, symbol text, side text, qty integer, price real,
  charges real, reason text, signal_date text, exported integer default 0);
create table if not exists days (day text primary key, signal_date text, cash real, open_pnl real,
  equity real, gross real, n_long integer, n_short integer, trades integer, charges real, blocked integer,
  exported integer default 0);
create table if not exists events (ts text, kind text, detail text);
create table if not exists account (k text primary key, v real);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or DATA / "paper.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def cash(con: sqlite3.Connection, cfg: BookConfig) -> float:
    row = con.execute("select v from account where k='cash'").fetchone()
    if row is None:
        con.execute("insert into account values ('cash', ?)", (cfg.capital,))
        return cfg.capital
    return float(row[0])


def set_cash(con: sqlite3.Connection, v: float) -> None:
    con.execute("insert or replace into account values ('cash', ?)", (v,))


def positions(con: sqlite3.Connection) -> dict[str, dict]:
    cols = ["symbol", "qty", "avg_price", "lot_size", "expiry", "opened"]
    return {r[0]: dict(zip(cols, r, strict=True)) for r in con.execute("select * from positions where qty != 0")}


def latest_signals(today: date, folder: str = "signals") -> pl.DataFrame:
    """Most recent signals file for a session before today."""
    files = [
        f.path
        for f in hf_store.api().list_repo_tree(hf_store.DATASET_REPO, repo_type="dataset", path_in_repo=folder)
        if f.path.endswith(".parquet")
    ]
    dated = sorted((date.fromisoformat(f.split("date=")[1][:10]), f) for f in files)
    dated = [x for x in dated if x[0] < today]
    if not dated:
        raise SystemExit("no signals yet")
    with tempfile.TemporaryDirectory() as tmp:
        p = hf_store.download(dated[-1][1], Path(tmp))
        assert p is not None
        return pl.read_parquet(p)


def plan(held: dict[str, dict], sig: pl.DataFrame, cfg: BookConfig, today: date) -> list[dict]:
    """Orders (as intents) that move the held book to today's target. Pure: no I/O."""
    tradable = (sig.filter(pl.col("lot_size").is_not_null()) if cfg.vehicle == "fut" else sig).sort("rank")
    ranked = tradable["symbol"].to_list()
    info = {r["symbol"]: r for r in tradable.iter_rows(named=True)}
    longs = {s for s, p in held.items() if p["qty"] > 0}
    shorts = {s for s, p in held.items() if p["qty"] < 0}
    keep_l, keep_s, new_l, new_s = rebalance(longs, shorts, ranked, cfg.k, cfg.exit_k)
    if cfg.long_only:
        keep_s, new_s = set(), []
    out: list[dict] = []
    for s in sorted((longs - keep_l) | (shorts - keep_s)):
        out.append({"symbol": s, "qty": -held[s]["qty"], "reason": "exit"})
    for s in sorted(keep_l | keep_s):  # roll contracts close to expiry: close and reopen in the next month
        p = held[s]
        if (
            cfg.vehicle == "fut"
            and p["expiry"]
            and (date.fromisoformat(p["expiry"]) - today).days <= cfg.roll_days
            and s in info
        ):
            out.append({"symbol": s, "qty": -p["qty"], "reason": "roll_close"})
            out.append({"symbol": s, "qty": p["qty"], "reason": "roll_open", "expiry": str(info[s]["fut_expiry"])})
    for side, names in ((1, new_l), (-1, new_s)):
        for s in names:
            r = info[s]
            if cfg.vehicle == "delivery":
                shares = int(cfg.notional_per_position // r["close"])
                if shares > 0:
                    out.append({"symbol": s, "qty": side * shares, "reason": "enter", "lot_size": 1, "expiry": None})
                continue
            lot = int(r["lot_size"])
            lots = max(1, round(cfg.notional_per_position / (lot * r["close"])))
            out.append(
                {
                    "symbol": s,
                    "qty": side * lots * lot,
                    "reason": "enter",
                    "lot_size": lot,
                    "expiry": str(r["fut_expiry"]),
                }
            )
    return out


def fut(symbol: str) -> Contract:
    return Contract(symbol, Kind.FUT, tick=0.01)


def contract(symbol: str, cfg: BookConfig) -> Contract:
    return fut(symbol) if cfg.vehicle == "fut" else Contract(symbol, Kind.EQ, tick=0.01)


def make_book(held: dict[str, dict], live: dict[str, tuple[float, datetime]], cfg: BookConfig) -> Book:
    """What the risk manager sees: positions and last prices keyed by the traded contract."""
    product = cfg.kind_product[1].value
    last = {contract(s, cfg).key: v[0] for s, v in live.items()}
    pos = {}
    for s, p in held.items():
        key = contract(s, cfg).key
        pos[(key, product)] = (int(p["qty"]), float(last.get(key) or p["avg_price"]))
    return Book(pos, 0.0, last)


def run_open(con: sqlite3.Connection, cfg: BookConfig, quotes: Quotes, now: datetime) -> dict:
    today = now.date()
    if con.execute("select 1 from days where day=?", (str(today),)).fetchone():
        return {"skipped": "already traded today"}
    sig = latest_signals(today, cfg.signals)
    signal_date = str(sig["date"][0])
    if (today - sig["date"][0]).days > 4:
        return {"skipped": f"signals are stale ({signal_date}); not trading on old picks"}
    held = positions(con)
    flatten = (DATA / "FLATTEN").exists()
    if flatten:  # requested from the dashboard: sell everything held, open nothing new
        intents = [{"symbol": s, "qty": -p["qty"], "reason": "flatten"} for s, p in sorted(held.items())]
    else:
        intents = plan(held, sig, cfg, today)
    need = sorted({i["symbol"] for i in intents} | set(held))
    px = quotes(need)
    live = {s: v for s, v in px.items() if v[1].date() == today}
    if need and not live:
        return {"skipped": "market closed (no trades today in any quote)"}
    risk = RiskManager(cfg.risk)
    if (DATA / "KILL").exists():
        risk.engage_kill("KILL file present", now)
    c = cash(con, cfg)
    book = make_book(held, live, cfg)
    done = blocked = 0
    total_ch = 0.0
    for n, it in enumerate(intents):
        s = it["symbol"]
        if s not in live:
            con.execute("insert into events values (?,?,?)", (now.isoformat(), "no_price", s))
            blocked += 1
            continue
        last = live[s][0]
        side = Side.BUY if it["qty"] > 0 else Side.SELL
        slip = cfg.slippage_bps / 1e4
        price = round(last * (1 + slip if side == Side.BUY else 1 - slip), 2)
        kind, product = cfg.kind_product
        order = Order(contract(s, cfg), side, abs(it["qty"]), price, product, now + timedelta(milliseconds=250 * n))
        decision = risk.check(order, book)
        if not decision.ok:
            con.execute("insert into events values (?,?,?)", (now.isoformat(), "blocked", f"{s}: {decision.reason}"))
            blocked += 1
            continue
        ch = charges(kind, product, side, abs(it["qty"]), price, today).total
        if cfg.vehicle == "delivery" and side == Side.BUY and abs(it["qty"]) * price + ch > c:
            con.execute("insert into events values (?,?,?)", (now.isoformat(), "blocked", f"{s}: insufficient cash"))
            blocked += 1
            continue
        c = apply_fill(con, s, it, price, c - ch, today, cfg.vehicle)
        con.execute(
            "insert into trades (ts, day, symbol, side, qty, price, charges, reason, signal_date)"
            " values (?,?,?,?,?,?,?,?,?)",
            (now.isoformat(), str(today), s, side.value, abs(it["qty"]), price, ch, it["reason"], signal_date),
        )
        held = positions(con)
        book = make_book(held, live, cfg)
        done += 1
        total_ch += ch
    set_cash(con, c)
    con.execute(
        "insert into days (day, signal_date, trades, charges, blocked) values (?,?,?,?,?)",
        (str(today), signal_date, done, total_ch, blocked),
    )
    con.commit()
    if flatten:
        (DATA / "FLATTEN").unlink(missing_ok=True)
        con.execute("insert into events values (?,?,?)", (now.isoformat(), "flatten_done", f"{done} exits"))
        con.commit()
    return {
        "signal_date": signal_date,
        "intents": len(intents),
        "filled": done,
        "blocked": blocked,
        "charges": total_ch,
    }


def apply_fill(
    con: sqlite3.Connection, s: str, it: dict, price: float, c: float, today: date, vehicle: str = "fut"
) -> float:
    """Update the position and return cash.

    Futures: nothing is paid up front; realised P&L settles in cash. Delivery: buys pay in full, sells receive.
    """
    if vehicle == "delivery":
        c -= it["qty"] * price  # buy: qty > 0 pays; sell: qty < 0 receives
    row = con.execute("select qty, avg_price, lot_size, expiry from positions where symbol=?", (s,)).fetchone()
    qty, avg, lot, expiry = row if row else (0, 0.0, it.get("lot_size", 0), it.get("expiry"))
    dq = it["qty"]
    if qty == 0 or (qty > 0) == (dq > 0):  # open / add
        avg = (avg * abs(qty) + price * abs(dq)) / (abs(qty) + abs(dq))
        qty += dq
        expiry = it.get("expiry", expiry)
    else:  # reduce / close
        closing = min(abs(dq), abs(qty))
        if vehicle == "fut":
            c += closing * (price - avg) * (1 if qty > 0 else -1)
        qty += dq
        if qty == 0:
            avg = 0.0
    con.execute(
        "insert or replace into positions values (?,?,?,?,?,?)",
        (s, qty, avg, lot or it.get("lot_size", 0), expiry, str(today)),
    )
    return c


def run_close(con: sqlite3.Connection, cfg: BookConfig, quotes: Quotes, now: datetime) -> dict:
    today = now.date()
    row = con.execute("select 1 from days where day=?", (str(today),)).fetchone()
    if not row:
        return {"skipped": "no open run today"}
    held = positions(con)
    px = quotes(sorted(held))
    c = cash(con, cfg)
    open_pnl = sum(p["qty"] * (px.get(s, (p["avg_price"],))[0] - p["avg_price"]) for s, p in held.items())
    gross = sum(abs(p["qty"]) * px.get(s, (p["avg_price"],))[0] for s, p in held.items())
    # futures: equity = cash + open P&L. delivery: cash already paid for the shares, so add their market value
    equity = c + (gross if cfg.vehicle == "delivery" else open_pnl)
    con.execute(
        "update days set cash=?, open_pnl=?, equity=?, gross=?, n_long=?, n_short=? where day=?",
        (
            c,
            open_pnl,
            equity,
            gross,
            sum(1 for p in held.values() if p["qty"] > 0),
            sum(1 for p in held.values() if p["qty"] < 0),
            str(today),
        ),
    )
    con.commit()
    export(con)
    return {"equity": equity, "open_pnl": open_pnl, "gross": gross, "positions": len(held)}


def export(con: sqlite3.Connection) -> None:
    """Append new trades and the day table to the HF dataset (paper/ ...)."""
    trades = pl.read_database("select rowid as id, * from trades where exported=0", con)
    days = pl.read_database("select * from days order by day", con)
    pos = pl.read_database("select * from positions where qty != 0", con)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "paper"
        (root / "trades").mkdir(parents=True)
        if trades.height:
            trades.drop("exported").write_parquet(root / "trades" / f"{stamp}.parquet")
        days.write_parquet(root / "days.parquet")
        pos.write_parquet(root / "positions.parquet")
        hf_store.upload_folder(Path(tmp), f"paper book {stamp}: {trades.height} trades")
    if trades.height:
        con.executemany("update trades set exported=1 where rowid=?", [(i,) for i in trades["id"].to_list()])
    con.commit()


def breeze_quotes() -> Quotes:
    """Live cash quotes from Breeze (REST, one call per symbol)."""
    from breeze_connect import BreezeConnect

    from t2.brokers.breeze_check import load_env
    from t2.brokers.breeze_master import fno_universe, load_master

    load_env()
    breeze = BreezeConnect(api_key=os.environ["BREEZE_API_KEY"])
    breeze.generate_session(
        api_secret=os.environ["BREEZE_API_SECRET"], session_token=os.environ["BREEZE_SESSION_TOKEN"]
    )
    code = {i.nse_symbol: i.breeze_code for i in fno_universe(load_master()) if i.kind == "stock"}

    def get(symbols: list[str]) -> dict[str, tuple[float, datetime]]:
        out = {}
        for s in symbols:
            if s not in code:
                continue
            r = breeze.get_quotes(stock_code=code[s], exchange_code="NSE", product_type="cash")
            rows = r.get("Success") if isinstance(r, dict) else None
            if not rows:
                continue
            q = rows[0]
            try:
                ltt = datetime.strptime(q["ltt"], "%d-%b-%Y %H:%M:%S")
                out[s] = (float(q["ltp"]), ltt)
            except (KeyError, ValueError, TypeError):
                continue
        return out

    return get


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["open", "close", "export"])
    a = ap.parse_args(argv)
    from t2.brokers.breeze_check import load_env

    load_env()
    cfg = BookConfig.load()
    con = connect()
    now = datetime.now(IST).replace(tzinfo=None)
    if a.cmd == "export":
        export(con)
        return 0
    if a.cmd == "open" and now.time() < time(9, 15):
        print("before the open")
        return 0
    prev = con.execute(
        "select equity from days where equity is not null and day < ? order by day desc limit 1", (str(now.date()),)
    ).fetchone()
    try:
        result = (run_open if a.cmd == "open" else run_close)(con, cfg, breeze_quotes(), now)
    except Exception as exc:
        alerts.send(f"T2 paper {a.cmd} failed: {type(exc).__name__}: {exc}"[:500])
        raise
    print(json.dumps(result, default=str))
    if a.cmd == "close":
        alerts.send(alerts.close_summary(result, prev[0] if prev else cfg.capital))
    elif "skipped" not in result or now.time() >= time(10, 15):  # earlier skips are retried at 09:40 / 10:15
        alerts.send(alerts.open_summary(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
