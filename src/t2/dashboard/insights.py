"""Numbers behind the dashboard pages.

Pure functions (performance, round trips, charges, signal quality) take plain rows and are unit tested.
Loaders read the Hugging Face dataset and NSE's public index files into a disk cache under the data folder;
the API wraps them in a time cache so the server downloads each file at most once an hour.
"""

from __future__ import annotations

import csv
import io
import itertools
import math
import re
import time
from collections import defaultdict, deque
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

from t2.brokers.base import Kind, Product, Side
from t2.trader.costs import charges

TRADING_DAYS = 252


# ----- performance -----
def drawdown(equity: list[float]) -> list[float]:
    """Fall from the running peak, as a fraction (0 at a new high, -0.1 = 10% below the peak)."""
    out, peak = [], -math.inf
    for e in equity:
        peak = max(peak, e)
        out.append(e / peak - 1 if peak > 0 else 0.0)
    return out


def perf(days: list[dict], capital: float) -> dict:
    """Headline statistics of the paper book, measured from the starting capital."""
    marked = [d for d in days if d.get("equity") is not None]
    eq = [capital] + [float(d["equity"]) for d in marked]
    rets = [b / a - 1 for a, b in itertools.pairwise(eq) if a]
    mean = sum(rets) / len(rets) if rets else 0.0
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) if len(rets) > 1 else 0.0
    traded = sum(float(d.get("gross") or 0) for d in marked)
    charges_paid = sum(float(d.get("charges") or 0) for d in days)
    return {
        "capital": capital,
        "equity": eq[-1],
        "total_return": eq[-1] / capital - 1 if capital else None,
        "days": len(marked),
        "sharpe": mean / sd * math.sqrt(TRADING_DAYS) if sd > 0 else None,
        "volatility": sd * math.sqrt(TRADING_DAYS) if sd > 0 else None,
        "max_drawdown": min(drawdown(eq)),
        "best_day": max(rets) if rets else None,
        "worst_day": min(rets) if rets else None,
        "up_days": sum(r > 0 for r in rets),
        "down_days": sum(r < 0 for r in rets),
        "charges": charges_paid,
        "cost_drag": charges_paid / capital if capital else None,
        "avg_exposure": traded / len(marked) / capital if marked and capital else None,
    }


def round_trips(trades: list[dict]) -> list[dict]:
    """Closed positions, matched first-in first-out per symbol. P&L is after the charges of both legs."""
    lots: dict[str, deque[list]] = defaultdict(deque)  # symbol -> [signed qty, price, charges per share, day]
    out = []
    for t in sorted(trades, key=lambda t: (t["ts"], t.get("symbol", ""))):
        q = int(t["qty"]) * (1 if t["side"] == Side.BUY.value else -1)
        per = float(t.get("charges") or 0) / abs(q) if q else 0.0
        book = lots[t["symbol"]]
        while q and book and (book[0][0] > 0) != (q > 0):
            open_q, price, open_per, opened = book[0]
            n = min(abs(q), abs(open_q))
            sign = 1 if open_q > 0 else -1
            pnl = n * (float(t["price"]) - price) * sign - n * (open_per + per)
            out.append(
                {
                    "symbol": t["symbol"],
                    "side": "long" if sign > 0 else "short",
                    "opened": opened,
                    "closed": t["day"],
                    "qty": n,
                    "entry": price,
                    "exit": float(t["price"]),
                    "pnl": pnl,
                    "ret": pnl / (n * price) if price else 0.0,
                    "days": (date.fromisoformat(t["day"]) - date.fromisoformat(opened)).days,
                }
            )
            book[0][0] -= n * sign
            q += n * sign
            if book[0][0] == 0:
                book.popleft()
        if q:
            book.append([q, float(t["price"]), per, t["day"]])
    return out


def trade_stats(trips: list[dict]) -> dict:
    wins = [t["pnl"] for t in trips if t["pnl"] > 0]
    losses = [t["pnl"] for t in trips if t["pnl"] <= 0]
    return {
        "closed": len(trips),
        "win_rate": len(wins) / len(trips) if trips else None,
        "avg_win": sum(wins) / len(wins) if wins else None,
        "avg_loss": sum(losses) / len(losses) if losses else None,
        "profit_factor": sum(wins) / -sum(losses) if losses and sum(losses) < 0 else None,
        "realized": sum(t["pnl"] for t in trips),
        "avg_days": sum(t["days"] for t in trips) / len(trips) if trips else None,
    }


def kind_product(vehicle: str) -> tuple[Kind, Product]:
    return (Kind.FUT, Product.CARRY) if vehicle == "fut" else (Kind.EQ, Product.DELIVERY)


def charge_breakdown(trade: dict, vehicle: str) -> dict:
    """The statutory and broker charges of one simulated fill, item by item."""
    kind, product = kind_product(vehicle)
    c = charges(
        kind, product, Side(trade["side"]), int(trade["qty"]), float(trade["price"]), date.fromisoformat(trade["day"])
    )
    return {k: round(v, 2) for k, v in asdict(c).items()} | {"total": round(c.total, 2)}


def headline_tone(title: str | None) -> int:
    """Rough tone of a headline from a short finance word list: +1, 0 or -1. A hint, not a model."""
    words = set(re.findall(r"[a-z]+", (title or "").lower()))
    pos = len(words & POSITIVE)
    neg = len(words & NEGATIVE)
    return (pos > neg) - (neg > pos)


POSITIVE = {
    "gain", "gains", "surge", "surges", "jump", "jumps", "rally", "rallies", "rise", "rises", "up", "high", "record",
    "profit", "profits", "beat", "beats", "upgrade", "upgrades", "growth", "strong", "wins", "win", "order", "orders",
    "approval", "approves", "dividend", "bonus", "buyback", "expands", "soars", "outperform", "bullish", "boost",
}  # fmt: skip
NEGATIVE = {
    "fall", "falls", "drop", "drops", "slump", "slumps", "plunge", "plunges", "crash", "down", "low", "loss",
    "losses", "miss", "misses", "downgrade", "downgrades", "weak", "decline", "declines", "probe", "penalty",
    "fraud", "default", "resigns", "cuts", "cut", "bearish", "underperform", "sell", "selloff", "warns", "slows",
}  # fmt: skip


# ----- prices (HF compact tables) -----
def prices(cache: Path, today: date | None = None) -> pl.DataFrame:
    """Daily EQ-series bars for this year and last, from the dataset's yearly compact files."""
    from t2.data import hf_store

    today = today or date.today()
    frames = []
    for y in (today.year - 1, today.year):
        p = hf_store.download(f"compact/eq_daily/{y}.parquet", cache)
        if p:
            frames.append(
                pl.read_parquet(p)
                .filter(pl.col("series") == "EQ")
                .select("date", "symbol", "open", "high", "low", "close", "prev_close", "volume", "turnover")
            )
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames).unique(["date", "symbol"]).sort("symbol", "date")


def market_index(px: pl.DataFrame, min_turnover: float = 5e7) -> pl.DataFrame:
    """Equal-weight market of liquid stocks: average daily log return, as an index (first day = 100)."""
    if px.is_empty():
        return pl.DataFrame({"date": [], "level": []})
    lr = (pl.col("close") / pl.col("prev_close")).log()
    daily = (
        px.filter((pl.col("prev_close") > 0) & (pl.col("turnover") >= min_turnover))
        .with_columns(lr.alias("lr"))
        .filter(pl.col("lr").abs() < 0.5)
        .group_by("date")
        .agg(pl.col("lr").mean())
        .sort("date")
    )
    return daily.select("date", (pl.col("lr").cum_sum().exp() * 100).alias("level"))


def forward_returns(px: pl.DataFrame, d: date, horizon: int = 5) -> tuple[pl.DataFrame, int]:
    """Per symbol: next session's open to the close `horizon` sessions later (the model's y5 target).

    Returns the frame and how many of the horizon's sessions exist yet (horizon = complete)."""
    cal = px.select(pl.col("date").unique().sort())["date"].to_list()
    after = [x for x in cal if x > d][:horizon]
    if not after:
        return pl.DataFrame({"symbol": [], "fwd": []}), 0
    first = px.filter(pl.col("date") == after[0]).select("symbol", pl.col("open").alias("o"))
    last = px.filter(pl.col("date") == after[-1]).select("symbol", pl.col("close").alias("c"))
    out = first.join(last, on="symbol").filter(pl.col("o") > 0)
    return out.select("symbol", (pl.col("c") / pl.col("o") - 1).alias("fwd")), len(after)


def signal_quality(history: pl.DataFrame, px: pl.DataFrame, k: int, horizon: int = 5) -> list[dict]:
    """For each past signal date: rank IC (score vs what happened next), the top-k picks' return and the
    average stock's return over the same window."""
    out = []
    if history.is_empty() or px.is_empty():
        return out
    for d in sorted(history["date"].unique().to_list()):
        fwd, n = forward_returns(px, d, horizon)
        if n == 0:
            continue
        day = history.filter(pl.col("date") == d).join(fwd, on="symbol").drop_nulls(["score", "fwd"])
        if day.height < 20:
            continue
        ic = day.select(pl.corr("score", "fwd", method="spearman")).item()
        top = day.sort("rank").head(k)["fwd"].mean()
        out.append(
            {
                "date": str(d),
                "ic": ic,
                "top_ret": top,
                "market_ret": day["fwd"].mean(),
                "top_hits": int((day.sort("rank").head(k)["fwd"] > day["fwd"].median()).sum()),
                "k": k,
                "n": day.height,
                "sessions": n,
                "complete": n >= horizon,
            }
        )
    return out


# ----- signals history -----
def signal_files(folder: str) -> list[tuple[date, str]]:
    from t2.data import hf_store

    files = [
        f.path
        for f in hf_store.api().list_repo_tree(hf_store.DATASET_REPO, repo_type="dataset", path_in_repo=folder)
        if f.path.endswith(".parquet") and "date=" in f.path
    ]
    return sorted((date.fromisoformat(f.split("date=")[1][:10]), f) for f in files)


def signal_history(cache: Path, folder: str, last_n: int = 90) -> pl.DataFrame:
    """The last `last_n` signal files, one frame. Older files are immutable, so a cached copy is reused;
    the newest is re-checked in case the day's run was repeated."""
    from t2.data import hf_store

    files = signal_files(folder)[-last_n:]
    frames = []
    for i, (_, path) in enumerate(files):
        local = cache / path
        p = local if local.exists() and i < len(files) - 1 else hf_store.download(path, cache)
        if p:
            df = pl.read_parquet(p)
            frames.append(df.select("date", "symbol", "rank", "score", "close"))
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames, how="vertical_relaxed")


# ----- NSE public files: Nifty 50 closes and the industry of each stock -----
NSE = "https://nsearchives.nseindia.com/content/indices"


def _get(url: str) -> bytes | None:
    from t2.data.nse_archive import make_client

    try:
        with make_client() as c:
            r = c.get(url)
            return r.content if r.status_code == 200 else None
    except Exception:  # network trouble: the page shows the equal-weight market instead
        return None


def nifty_close(d: date, cache: Path) -> float | None:
    """Nifty 50 close for one session from NSE's daily index file (cached on disk once found)."""
    f = cache / "nifty50" / f"{d}.txt"
    if f.exists():
        return float(f.read_text())
    raw = _get(f"{NSE}/ind_close_all_{d:%d%m%Y}.csv")
    if not raw:
        return None
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8", "ignore"))):
        name = (row.get("Index Name") or "").strip().lower()
        if name == "nifty 50":
            try:
                v = float((row.get("Closing Index Value") or "").replace(",", ""))
            except ValueError:
                return None
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(str(v))
            return v
    return None


def sectors(cache: Path, max_age_days: int = 7) -> dict[str, str]:
    """Symbol -> industry, from NSE's Nifty 500 list (refreshed weekly). Smaller stocks have none."""
    f = cache / "nifty500.csv"
    if not f.exists() or time.time() - f.stat().st_mtime > max_age_days * 86400:
        raw = _get(f"{NSE}/ind_nifty500list.csv")
        if raw:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(raw)
    if not f.exists():
        return {}
    rows = csv.DictReader(io.StringIO(f.read_text("utf-8", "ignore")))
    return {(r.get("Symbol") or "").strip(): (r.get("Industry") or "").strip() for r in rows if r.get("Symbol")}


def benchmark(days: list[dict], px: pl.DataFrame, cache: Path, capital: float) -> list[dict]:
    """Paper equity next to Nifty 50 and the equal-weight market, all rebased to 100 at the start.

    The base is the close of the session the first signals came from (the book starts in cash before that)."""
    marked = [d for d in days if d.get("equity") is not None]
    if not marked:
        return []
    base_day = date.fromisoformat(marked[0].get("signal_date") or marked[0]["day"])
    if base_day.isoformat() == marked[0]["day"]:
        base_day -= timedelta(days=1)
    mkt = market_index(px)
    level = dict(zip(mkt["date"].to_list(), mkt["level"].to_list(), strict=True)) if mkt.height else {}
    m0 = next((level[x] for x in sorted(level, reverse=True) if x <= base_day), None)
    n0 = nifty_close(base_day, cache)
    out = [{"day": str(base_day), "t2": 100.0, "nifty": 100.0 if n0 else None, "market": 100.0 if m0 else None}]
    for d in marked:
        day = date.fromisoformat(d["day"])
        n = nifty_close(day, cache) if n0 else None
        m = level.get(day)
        out.append(
            {
                "day": d["day"],
                "t2": float(d["equity"]) / capital * 100,
                "nifty": n / n0 * 100 if n and n0 else None,
                "market": m / m0 * 100 if m and m0 else None,
            }
        )
    return out


def now_ist() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
