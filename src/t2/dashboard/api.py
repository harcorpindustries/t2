"""Dashboard backend on the live server: read-only views of the paper book, signals, model, pipelines and news,
plus the kill switch. Serves the static dashboard build from /opt/t2/dashboard.

Listens on 127.0.0.1 only. Public access goes through a Cloudflare Tunnel (t2.harcorp.biz); every page and API
call needs a password login (auth.py) or, for scripts, the DASHBOARD_TOKEN header.

    uvicorn t2.dashboard.api:app --host 127.0.0.1 --port 8080
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import time
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from t2 import alerts
from t2.dashboard import auth
from t2.dashboard import breeze_session as bs
from t2.dashboard import insights as ins

DATA = Path(os.environ.get("T2_PAPER_DIR", "/opt/t2/data"))
NEWS_DB = Path(os.environ.get("T2_NEWS_DB", "/opt/t2/data/news.db"))
STATIC = Path(os.environ.get("T2_DASHBOARD_DIR", "/opt/t2/dashboard"))

app = FastAPI(title="t2 dashboard", docs_url=None, redoc_url=None, openapi_url=None)
# /breeze/callback is where ICICI sends the browser after login; the page itself saves nothing (the save is an
# authenticated API call made from it), so it can load before the dashboard session is checked.
PUBLIC = {
    "/login",
    "/login.html",
    "/api/login",
    "/breeze/callback",
    "/breeze/callback.html",
    # icons and the mascot (shown on the sign-in page; no data)
    "/favicon.ico",
    "/icon.png",
    "/apple-icon.png",
    "/mascot.png",
}
PUBLIC_PREFIX = "/_next/"  # the UI's static assets (no data in them)


def _token_ok(request: Request) -> bool:
    expected = os.environ.get("DASHBOARD_TOKEN", "")
    got = request.headers.get("x-dashboard-token", "")
    return bool(expected) and secrets.compare_digest(got, expected)


@app.middleware("http")
async def require_login(request: Request, call_next: Any) -> Response:
    path = request.url.path
    if path in PUBLIC or path.startswith(PUBLIC_PREFIX):
        return await call_next(request)
    if not auth.configured():
        return JSONResponse({"detail": "dashboard password not set"}, status_code=503)
    if auth.valid_session(request.cookies.get(auth.COOKIE)) or _token_ok(request):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response
    if path.startswith("/api/"):
        return JSONResponse({"detail": "login required"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


class LoginRequest(BaseModel):
    password: str


def _client(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")


@app.post("/api/login")
def login(req: LoginRequest, request: Request) -> Response:
    if not auth.configured():
        return JSONResponse({"detail": "dashboard password not set"}, status_code=503)
    client = _client(request)
    if not auth.allowed_attempt(client):
        return JSONResponse({"detail": "too many attempts, wait 15 minutes"}, status_code=429)
    if not auth.check_password(req.password, os.environ["DASHBOARD_PASSWORD_HASH"]):
        auth.record_failure(client)
        return JSONResponse({"detail": "wrong password"}, status_code=401)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        auth.COOKIE,
        auth.make_session(),
        max_age=auth.SESSION_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return resp


@app.post("/api/logout")
def logout() -> Response:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


_cache: dict[str, tuple[float, Any]] = {}


def cached(key: str, ttl: float, fn: Any) -> Any:
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = fn()
    _cache[key] = (time.time(), value)
    return value


def rows(db: Path, sql: str, args: tuple = ()) -> list[dict]:
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args)]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def paper_db() -> Path:
    return DATA / "paper.db"


# ----- book -----
def _safe(fn: Any, default: Any) -> Any:
    """Optional enrichment from downloaded data: the core page must load even when the download fails."""
    try:
        return fn()
    except Exception:
        return default


@app.get("/api/book")
def book() -> dict:
    cfg = book_cfg()
    capital = float(cfg.get("capital") or 0)
    vehicle = cfg.get("vehicle", "fut")
    days = rows(paper_db(), "select * from days order by day")
    acct = rows(paper_db(), "select v from account where k='cash'")
    marked = [d for d in days if d.get("equity") is not None]
    first_equity = capital or (marked[0]["equity"] if marked else None)
    last = marked[-1] if marked else None
    prev = marked[-2] if len(marked) > 1 else None
    trades = rows(paper_db(), "select * from trades order by ts desc")
    positions = rows(paper_db(), "select * from positions where qty != 0 order by qty desc")
    closes = _safe(last_closes, {})
    ranks: dict[str, int] = {}
    hist = _safe(signal_history, None)
    if hist is not None and not hist.is_empty():
        latest = hist.filter(hist["date"] == hist["date"].max())
        ranks = dict(zip(latest["symbol"].to_list(), latest["rank"].to_list(), strict=True))
    sec = _safe(sectors, {})
    today = ins.now_ist().date()
    for p in positions:
        px = closes.get(p["symbol"])
        p["last"] = px
        p["value"] = abs(p["qty"]) * (px or p["avg_price"])
        p["pnl"] = p["qty"] * (px - p["avg_price"]) if px else None
        p["pnl_pct"] = (px / p["avg_price"] - 1) * (1 if p["qty"] > 0 else -1) if px and p["avg_price"] else None
        first_buy = min((t["day"] for t in trades if t["symbol"] == p["symbol"]), default=p.get("opened"))
        p["since"] = first_buy
        p["days_held"] = (today - datetime.fromisoformat(first_buy).date()).days if first_buy else None
        p["rank"] = ranks.get(p["symbol"])
        p["exit_k"] = cfg.get("exit_k")
        p["sector"] = sec.get(p["symbol"]) or None
    for t in trades:
        t["breakdown"] = _safe(lambda t=t: ins.charge_breakdown(t, vehicle), None)
    trips = ins.round_trips(trades)
    eq = [capital] + [float(d["equity"]) for d in marked] if capital else [float(d["equity"]) for d in marked]
    dd = ins.drawdown(eq)
    return {
        "days": days,
        "cash": acct[0]["v"] if acct else None,
        "capital": capital or None,
        "vehicle": vehicle,
        "equity": last["equity"] if last else None,
        "day_pnl": (last["equity"] - (prev["equity"] if prev else capital)) if last and (prev or capital) else None,
        "total_pnl": (last["equity"] - first_equity) if last and first_equity is not None else None,
        "gross": last["gross"] if last else None,
        "positions": positions,
        "trades": trades[:500],
        "round_trips": trips[::-1],
        "stats": ins.perf(days, capital) if capital else None,
        "trade_stats": ins.trade_stats(trips),
        "drawdown": [{"day": d["day"], "dd": x} for d, x in zip(marked, dd[1:] if capital else dd, strict=False)],
        "events": rows(paper_db(), "select * from events order by ts desc limit 200"),
        "kill": kill_state(),
    }


@app.get("/api/benchmark")
def benchmark() -> dict:
    """Paper equity vs Nifty 50 and the equal-weight market, rebased to 100."""
    capital = float(book_cfg().get("capital") or 0)
    days = rows(paper_db(), "select * from days order by day")
    if not capital:
        return {"points": []}
    key = f"bench:{len(days)}:{days[-1].get('equity') if days else ''}"
    return {"points": cached(key, 3600, lambda: _safe(lambda: ins.benchmark(days, prices(), cache_dir(), capital), []))}


# ----- one stock -----
@app.get("/api/stock/{symbol}")
def stock(symbol: str) -> dict:
    import polars as pl

    sym = symbol.upper()
    if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", sym):
        raise HTTPException(status_code=400, detail="bad symbol")
    px = _safe(prices, None)
    candles: list[dict] = []
    if px is not None and not px.is_empty():
        bars = px.filter(pl.col("symbol") == sym).sort("date").tail(250)
        candles = [
            {"date": str(r["date"]), "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
             "volume": r["volume"]}
            for r in bars.iter_rows(named=True)
        ]  # fmt: skip
    scores: list[dict] = []
    hist = _safe(signal_history, None)
    if hist is not None and not hist.is_empty():
        n = hist.group_by("date").len()
        mine = hist.filter(pl.col("symbol") == sym).join(n, on="date").sort("date")
        scores = [
            {"date": str(r["date"]), "rank": r["rank"], "score": r["score"], "of": r["len"]}
            for r in mine.iter_rows(named=True)
        ]
    pos = rows(paper_db(), "select * from positions where symbol=? and qty != 0", (sym,))
    trades = rows(paper_db(), "select * from trades where symbol=? order by ts", (sym,))
    news = rows(
        NEWS_DB,
        "select id, source, category, url, title, published_at, first_seen_at, tickers from items"
        " where (',' || tickers || ',') like ? order by coalesce(published_at, first_seen_at) desc limit 30",
        (f"%,{sym},%",),
    )
    return {
        "symbol": sym,
        "sector": _safe(sectors, {}).get(sym) or None,
        "candles": candles,
        "scores": scores,
        "position": pos[0] if pos else None,
        "trades": trades,
        "news": [it | news_links(it) | {"tone": ins.headline_tone(it["title"])} for it in news],
    }


@app.get("/api/symbols")
def symbols() -> dict:
    """Every symbol the dashboard knows (for search): ranked stocks first."""
    hist = _safe(signal_history, None)
    out: list[str] = []
    if hist is not None and not hist.is_empty():
        latest = hist.filter(hist["date"] == hist["date"].max()).sort("rank")
        out = latest["symbol"].to_list()
    return {"symbols": out}


# ----- risk -----
@app.get("/api/risk")
def risk() -> dict:
    cfg = book_cfg()
    lim = cfg.get("risk", {})
    today = str(ins.now_ist().date())
    positions = rows(paper_db(), "select * from positions where qty != 0")
    closes = _safe(last_closes, {})
    values = {p["symbol"]: abs(p["qty"]) * (closes.get(p["symbol"]) or p["avg_price"]) for p in positions}
    days = [d for d in rows(paper_db(), "select * from days order by day") if d.get("equity") is not None]
    capital = float(cfg.get("capital") or 0)
    day_pnl = None
    if days:
        prev = days[-2]["equity"] if len(days) > 1 else capital
        day_pnl = days[-1]["equity"] - prev if days[-1]["day"] == today else 0.0
    orders_today = rows(paper_db(), "select count(*) n from trades where day=?", (today,))
    return {
        "limits": lim,
        "usage": {
            "exposure": sum(values.values()),
            "largest_position": max(values.values(), default=0.0),
            "open_positions": len(positions),
            "orders_today": orders_today[0]["n"] if orders_today else 0,
            "day_loss": -day_pnl if day_pnl and day_pnl < 0 else 0.0,
        },
        "blocked": rows(
            paper_db(),
            "select * from events where kind in ('blocked', 'no_price', 'kill_on', 'kill_off', 'flatten_on',"
            " 'flatten_off', 'flatten_done') order by ts desc limit 100",
        ),
        "kill": kill_state(),
    }


@app.get("/api/ping")
def ping() -> dict:
    """Small status for the top bar on every page: kill switch, Breeze session, server time."""
    return {"kill": kill_state(), "breeze": bs.status(), "server_time": datetime.now(UTC).isoformat()}


# ----- daily Breeze login -----
@app.get("/api/breeze/status")
def breeze_status() -> dict:
    return bs.status()


@app.get("/api/breeze/login-url")
def breeze_login_url() -> dict:
    try:
        return {"url": bs.login_url()}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class SessionRequest(BaseModel):
    apisession: str


@app.post("/api/breeze/session")
def breeze_session(req: SessionRequest) -> dict:
    """Signed-in users only (require_login): confirm the session with Breeze, then save it for every server job."""
    session = bs.clean(req.apisession)
    if len(session) < 4:
        raise HTTPException(status_code=400, detail="no session number")
    ok, msg = bs.check_with_breeze(session)
    if not ok:
        raise HTTPException(status_code=422, detail=msg)
    bs.save(session)
    _record_event("breeze_login", "session saved from the dashboard")
    return bs.status() | {"ok": True}


@app.post("/breeze/callback", include_in_schema=False)
async def breeze_callback_post(request: Request) -> Response:
    """If ICICI posts the session as a form, turn it into the GET the callback page reads. Saves nothing."""
    form = await request.form()
    session = bs.clean(str(form.get("apisession") or form.get("API_Session") or ""))
    return RedirectResponse(f"/breeze/callback?apisession={session}", status_code=303)


def _record_event(kind: str, detail: str) -> None:
    con = sqlite3.connect(paper_db())
    con.execute("create table if not exists events (ts text, kind text, detail text)")
    con.execute("insert into events values (?,?,?)", (datetime.now(UTC).isoformat(), kind, detail))
    con.commit()
    con.close()


# ----- kill switch -----
def kill_state() -> dict:
    f = DATA / "KILL"
    flatten = (DATA / "FLATTEN").exists()
    if not f.exists():
        return {"on": False, "flatten": flatten}
    since = datetime.fromtimestamp(f.stat().st_mtime, UTC).isoformat()
    return {"on": True, "since": since, "reason": f.read_text(), "flatten": flatten}


class KillRequest(BaseModel):
    on: bool
    reason: str = ""


@app.post("/api/kill")
def set_kill(req: KillRequest) -> dict:
    """Signed-in users (or the DASHBOARD_TOKEN header) only: enforced by require_login."""
    f = DATA / "KILL"
    if req.on:
        f.write_text(req.reason or "kill switch from dashboard")
    elif f.exists():
        f.unlink()
    con = sqlite3.connect(paper_db())
    con.execute("create table if not exists events (ts text, kind text, detail text)")
    con.execute(
        "insert into events values (?,?,?)",
        (datetime.now(UTC).isoformat(), "kill_on" if req.on else "kill_off", req.reason or "dashboard"),
    )
    con.commit()
    con.close()
    alerts.send(
        f"T2 kill switch {'ON' if req.on else 'off'} from the dashboard" + (f": {req.reason}" if req.reason else "")
    )
    return kill_state()


class FlattenRequest(BaseModel):
    on: bool


@app.post("/api/flatten")
def set_flatten(req: FlattenRequest) -> dict:
    """Paper book only: at the next open run, sell every position and open nothing new (then this clears)."""
    f = DATA / "FLATTEN"
    if req.on:
        f.write_text(datetime.now(UTC).isoformat())
    elif f.exists():
        f.unlink()
    _record_event("flatten_on" if req.on else "flatten_off", "dashboard")
    if req.on:
        alerts.send("T2: flatten requested. The paper book sells everything at the next open run.")
    return {"flatten": f.exists()}


# ----- shared data (Hugging Face + NSE files, cached) -----
def book_cfg() -> dict:
    """The paper book's settings (config/paper/book.json in the repo)."""
    try:
        from t2.trader.paper_live import CONFIG

        return json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def cache_dir() -> Path:
    d = DATA / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def prices() -> Any:
    return cached("prices", 3600, lambda: ins.prices(cache_dir()))


def signal_history() -> Any:
    folder = book_cfg().get("signals", "signals")
    return cached(f"sighist:{folder}", 600, lambda: ins.signal_history(cache_dir(), folder))


def sectors() -> dict[str, str]:
    return cached("sectors", 6 * 3600, lambda: ins.sectors(cache_dir()))


def last_closes() -> dict[str, float]:
    import polars as pl

    px = prices()
    if px.is_empty():
        return {}
    last = px.sort("date").group_by("symbol").agg(pl.col("close").last(), pl.col("date").last())
    return dict(zip(last["symbol"].to_list(), last["close"].to_list(), strict=True))


# ----- signals -----
def _signals(day: str | None) -> dict:
    import polars as pl

    h = signal_history()
    if h.is_empty():
        return {"date": None, "dates": [], "rows": []}
    dates = sorted({str(d) for d in h["date"].unique().to_list()})
    pick = day if day in dates else dates[-1]
    i = dates.index(pick)
    cur = h.filter(pl.col("date").cast(pl.Utf8) == pick)
    # the full row (lot size, futures expiry) lives in the day's file; history keeps the ranking columns
    folder = book_cfg().get("signals", "signals")
    from t2.data import hf_store

    full_path = hf_store.download(f"{folder}/date={pick}.parquet", cache_dir())
    full = pl.read_parquet(full_path) if full_path else cur
    rows = full.drop("date").sort("rank")
    if i > 0:
        prev = h.filter(pl.col("date").cast(pl.Utf8) == dates[i - 1]).select(
            "symbol", pl.col("rank").alias("prev_rank")
        )
        rows = rows.join(prev, on="symbol", how="left")
    else:
        rows = rows.with_columns(pl.lit(None, dtype=pl.Int64).alias("prev_rank"))
    sec = sectors()
    out = rows.to_dicts()
    for r in out:
        r["sector"] = sec.get(r["symbol"]) or None
    return {"date": pick, "dates": dates, "prev_date": dates[i - 1] if i > 0 else None, "rows": out}


@app.get("/api/signals")
def signals(date: str = "") -> dict:
    day = date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else ""
    return cached(f"signals:{day}", 600, lambda: _signals(day or None))


@app.get("/api/signals/quality")
def signal_quality() -> dict:
    """How past picks did: rank IC and top-k return over the 5 sessions after each signal date."""
    k = int(book_cfg().get("k", 3))
    q = cached("quality", 3600, lambda: ins.signal_quality(signal_history(), prices(), k))
    done = [x for x in q if x["complete"]]
    mean = lambda key: sum(x[key] for x in done) / len(done) if done else None  # noqa: E731
    return {
        "k": k,
        "days": q,
        "summary": {
            "dates": len(done),
            "mean_ic": mean("ic"),
            "top_ret": mean("top_ret"),
            "market_ret": mean("market_ret"),
            "beat_rate": sum(x["top_ret"] > x["market_ret"] for x in done) / len(done) if done else None,
        },
    }


# ----- model -----
def importance(model_text: str) -> list[dict]:
    """LightGBM writes split counts per feature at the end of model.txt; no ML library needed to read them."""
    if "feature_importances:" not in model_text:
        return []
    block = model_text.split("feature_importances:", 1)[1].strip().split("\n\n", 1)[0]
    out = []
    for line in block.splitlines():
        name, _, v = line.partition("=")
        if v.strip().isdigit():
            out.append({"feature": name.strip(), "splits": int(v)})
    return sorted(out, key=lambda x: -x["splits"])


def _model() -> dict:
    from huggingface_hub import HfApi, hf_hub_download

    # the repo name only: importing the model code would pull in the ML libraries the server does not need
    repo = os.environ.get("HF_MODEL_REPO", "harcorp/t2-models")
    token = os.environ.get("HF_TOKEN")
    cash = book_cfg().get("signals") == "signals-cash"
    prefix, name = ("champion-cash", "cash") if cash else ("champion", "futures")
    meta = json.loads(Path(hf_hub_download(repo, f"{prefix}/meta.json", token=token)).read_text())
    try:
        text = Path(hf_hub_download(repo, f"{prefix}/model.txt", token=token)).read_text()
        meta["importance"] = importance(text)
    except Exception:  # the page still shows the recipe without the chart
        meta["importance"] = []
    history = []
    try:
        tree = HfApi(token=token).list_repo_tree(repo, path_in_repo=f"history/{name}")
        for d in sorted(f.path for f in tree)[-20:]:
            m = json.loads(Path(hf_hub_download(repo, f"{d}/meta.json", token=token)).read_text())
            history.append(
                {k: m.get(k) for k in ("trained_on", "data_last_date", "train_rows", "code_commit", "data_commit")}
            )
    except Exception:
        pass
    meta["history"] = history
    return meta


@app.get("/api/model")
def model() -> dict:
    return cached("model", 1800, _model)


# ----- pipelines -----
@app.get("/api/status")
def status() -> dict:
    def timers() -> list[dict]:
        try:
            out = subprocess.run(
                ["systemctl", "list-timers", "t2-*", "--all", "--no-pager", "--output=json"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            items = json.loads(out or "[]")
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return []
        res = []
        for t in items:
            unit = t.get("activates", "")
            state = subprocess.run(
                ["systemctl", "show", unit, "--property=Result,ActiveState", "--value"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.split()
            res.append(
                {
                    "unit": unit.removesuffix(".service"),
                    "next_us": t.get("next"),
                    "last_us": t.get("last"),
                    "result": state[0] if state else None,
                    "active": state[1] if len(state) > 1 else None,
                }
            )
        return res

    news = rows(NEWS_DB, "select count(*) n, max(first_seen_at) last from items")
    breeze = rows(DATA / "breeze.db", "select * from calls order by day desc limit 1")
    return {
        "server_time": datetime.now(UTC).isoformat(),
        "timers": cached("timers", 30, timers),
        "news": news[0] if news else None,
        "breeze_calls": breeze[0] if breeze else None,
        "breeze_windows": rows(
            DATA / "breeze.db", "select interval, status, count(*) n, sum(rows) rows from windows group by 1, 2"
        ),
        "kill": kill_state(),
        "server": server_stats(),
        "freshness": cached("freshness", 900, freshness),
        "hf_gb": cached("hf_gb", 6 * 3600, lambda: _safe(_hf_gb, None)),
        "hf_free_gb": 100.0,
        "breeze_budget": 5000,
        "alerts": alerts.configured(),
    }


def _hf_gb() -> float:
    from t2.data import hf_store

    return hf_store.dataset_size_gb()


def server_stats() -> dict:
    mem: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            mem[k] = int(v.split()[0]) * 1024
    except (OSError, ValueError):
        pass
    disk = shutil.disk_usage(DATA if DATA.exists() else Path("/"))
    try:
        load = os.getloadavg()
    except OSError:
        load = (0.0, 0.0, 0.0)
    return {
        "load": load,
        "cpus": os.cpu_count(),
        "mem_total": mem.get("MemTotal"),
        "mem_used": (mem["MemTotal"] - mem["MemAvailable"]) if "MemAvailable" in mem else None,
        "disk_total": disk.total,
        "disk_used": disk.used,
    }


def freshness() -> list[dict]:
    """Latest day each dataset has reached."""
    out = []
    px = _safe(prices, None)
    if px is not None and not px.is_empty():
        last = px["date"].max()
        out.append({"name": "NSE daily prices", "last": str(last), "rows": px.height})
    hist = _safe(signal_history, None)
    if hist is not None and not hist.is_empty():
        out.append({"name": "Model signals", "last": str(hist["date"].max()), "rows": hist.height})
    news_last = rows(NEWS_DB, "select max(first_seen_at) last, count(*) n from items")
    if news_last and news_last[0]["last"]:
        out.append({"name": "News", "last": news_last[0]["last"], "rows": news_last[0]["n"]})
    win = rows(DATA / "breeze.db", "select max(fetched_at) last, sum(rows) n from windows where status='ok'")
    if win and win[0].get("last"):
        out.append({"name": "Breeze intraday", "last": win[0]["last"], "rows": win[0]["n"]})
    paper = rows(paper_db(), "select max(day) last, count(*) n from days")
    if paper and paper[0]["last"]:
        out.append({"name": "Paper book", "last": paper[0]["last"], "rows": paper[0]["n"]})
    return out


@app.get("/api/logs/{unit}")
def logs(unit: str, lines: int = 60) -> dict:
    """Last lines of one t2 job's log (journal)."""
    if not re.fullmatch(r"t2-[a-z0-9-]{1,40}", unit):
        raise HTTPException(status_code=400, detail="bad unit")
    try:
        out = subprocess.run(
            ["journalctl", "-u", f"{unit}.service", "-n", str(min(max(lines, 1), 300)), "--no-pager", "-o",
             "short-iso"],
            capture_output=True, text=True, timeout=10,
        ).stdout  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        out = ""
    return {"unit": unit, "text": out[-30000:]}


# ----- settings -----
@app.get("/api/settings")
def settings() -> dict:
    return {
        "book": book_cfg(),
        "alerts": alerts.configured(),
        "session_days": auth.SESSION_SECONDS // 86400,
    }


@app.post("/api/sessions/revoke")
def revoke_sessions() -> Response:
    """Sign out every browser: a new signing key invalidates all cookies; this browser gets a fresh one."""
    key = secrets.token_urlsafe(48)
    bs.write_env_value("DASHBOARD_SESSION_KEY", key)
    os.environ["DASHBOARD_SESSION_KEY"] = key
    _record_event("sessions_revoked", "all dashboard sessions signed out")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        auth.COOKIE, auth.make_session(), max_age=auth.SESSION_SECONDS, httponly=True, secure=True,
        samesite="strict", path="/",
    )  # fmt: skip
    return resp


@app.post("/api/alerts/test")
def alerts_test() -> dict:
    return {"sent": alerts.send("T2: test alert from the dashboard.")}


# ----- news -----
NSE_FILINGS = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
GROUPS = {
    "articles": ("news", "aggregator"),
    "filings": ("exchange",),
    "regulators": ("regulator",),
}


def file_type(url: str) -> str:
    path = url.split("?", 1)[0].lower()
    for ext in ("xml", "zip", "pdf"):
        if path.endswith("." + ext):
            return ext
    return "page"


def news_links(item: dict) -> dict:
    """The link a person should open, plus the raw file for exchange filings (XBRL/ZIP are data, not pages)."""
    url, kind = item["url"], file_type(item["url"])
    if item["category"] == "exchange" and kind in ("xml", "zip"):
        symbols = [t for t in (item.get("tickers") or "").split(",") if t]
        link = f"{NSE_FILINGS}?symbol={urllib.parse.quote(symbols[0])}" if symbols else NSE_FILINGS
        return {"link": link, "raw_url": url, "raw_type": kind}
    return {"link": url, "raw_url": None, "raw_type": kind if kind != "page" else None}


@app.get("/api/news")
def news(q: str = "", symbol: str = "", symbols: str = "", group: str = "articles", limit: int = 50) -> dict:
    where, args = ["1=1"], []
    many = [x for x in symbols.upper().split(",") if re.fullmatch(r"[A-Z0-9&\-]{1,20}", x)][:50]
    if many:
        where.append("(" + " or ".join(["(',' || tickers || ',') like ?"] * len(many)) + ")")
        args += [f"%,{x},%" for x in many]
    if group in GROUPS:
        cats = GROUPS[group]
        where.append(f"category in ({','.join('?' * len(cats))})")
        args += list(cats)
    if q:
        where.append("(title like ? or summary like ?)")
        args += [f"%{q}%", f"%{q}%"]
    if symbol:
        where.append("(',' || tickers || ',') like ?")
        args.append(f"%,{symbol.upper()},%")
    sql = (
        "select id, source, category, url, title, summary, published_at, first_seen_at, tickers,"
        " text_status = 'ok' as has_text from items where "
        + " and ".join(where)
        + " order by coalesce(published_at, first_seen_at) desc limit ?"
    )
    items = rows(NEWS_DB, sql, (*args, min(max(limit, 1), 200)))
    return {"items": [it | news_links(it) | {"tone": ins.headline_tone(it["title"])} for it in items]}


@app.get("/api/news-tone")
def news_tone(days: int = 30) -> dict:
    """Headlines per day with a rough tone count (word list), for the whole feed and for held stocks."""
    since = (datetime.now(UTC) - timedelta(days=min(max(days, 1), 120))).isoformat()
    items = rows(
        NEWS_DB,
        "select substr(coalesce(published_at, first_seen_at), 1, 10) day, title, tickers from items"
        " where coalesce(published_at, first_seen_at) >= ? and category in ('news', 'aggregator')",
        (since,),
    )
    held = {p["symbol"] for p in rows(paper_db(), "select symbol from positions where qty != 0")}
    by: dict[str, dict] = {}
    for it in items:
        d = by.setdefault(it["day"], {"day": it["day"], "pos": 0, "neg": 0, "neutral": 0, "held": 0})
        t = ins.headline_tone(it["title"])
        d["pos" if t > 0 else "neg" if t < 0 else "neutral"] += 1
        if held & set((it["tickers"] or "").split(",")):
            d["held"] += 1
    return {"days": sorted(by.values(), key=lambda x: x["day"])}


@app.get("/api/news/{item_id}")
def news_item(item_id: str) -> dict:
    found = rows(NEWS_DB, "select id, title, url, source, published_at, text from items where id = ?", (item_id,))
    if not found:
        raise HTTPException(status_code=404, detail="not found")
    it = found[0]
    it["text"] = (it.get("text") or "")[:20000]
    return it


# ----- static dashboard -----
if (STATIC / "_next").exists():
    app.mount("/_next", StaticFiles(directory=STATIC / "_next"), name="next")


@app.get("/{path:path}", include_in_schema=False)
def page(path: str) -> FileResponse:
    for candidate in (STATIC / path, STATIC / f"{path}.html", STATIC / path / "index.html", STATIC / "index.html"):
        if candidate.is_file() and STATIC in candidate.resolve().parents:
            return FileResponse(candidate)
    raise HTTPException(status_code=404, detail="dashboard not built yet")
