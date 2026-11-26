"""Dashboard backend on the live server: read-only views of the paper book, signals, model, pipelines and news,
plus the kill switch. Serves the static dashboard build from /opt/t2/dashboard.

Listens on 127.0.0.1 only. Public access goes through a Cloudflare Tunnel (t2.harcorp.biz); every page and API
call needs a password login (auth.py) or, for scripts, the DASHBOARD_TOKEN header.

    uvicorn t2.dashboard.api:app --host 127.0.0.1 --port 8080
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from t2.dashboard import auth

DATA = Path(os.environ.get("T2_PAPER_DIR", "/opt/t2/data"))
NEWS_DB = Path(os.environ.get("T2_NEWS_DB", "/opt/t2/data/news.db"))
STATIC = Path(os.environ.get("T2_DASHBOARD_DIR", "/opt/t2/dashboard"))

app = FastAPI(title="t2 dashboard", docs_url=None, redoc_url=None, openapi_url=None)
PUBLIC = {"/login", "/login.html", "/api/login", "/favicon.ico"}
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
@app.get("/api/book")
def book() -> dict:
    days = rows(paper_db(), "select * from days order by day")
    acct = rows(paper_db(), "select v from account where k='cash'")
    marked = [d for d in days if d.get("equity") is not None]
    first_equity = marked[0]["equity"] if marked else None
    last = marked[-1] if marked else None
    prev = marked[-2] if len(marked) > 1 else None
    return {
        "days": days,
        "cash": acct[0]["v"] if acct else None,
        "equity": last["equity"] if last else None,
        "day_pnl": (last["equity"] - prev["equity"]) if last and prev else None,
        "total_pnl": (last["equity"] - first_equity) if last and first_equity is not None else None,
        "gross": last["gross"] if last else None,
        "positions": rows(paper_db(), "select * from positions where qty != 0 order by qty desc"),
        "trades": rows(paper_db(), "select * from trades order by ts desc limit 200"),
        "events": rows(paper_db(), "select * from events order by ts desc limit 100"),
        "kill": kill_state(),
    }


# ----- kill switch -----
def kill_state() -> dict:
    f = DATA / "KILL"
    if not f.exists():
        return {"on": False}
    return {"on": True, "since": datetime.fromtimestamp(f.stat().st_mtime, UTC).isoformat(), "reason": f.read_text()}


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
    return kill_state()


# ----- signals and model (from Hugging Face, cached) -----
def _signals() -> dict:
    import polars as pl

    from t2.data import hf_store

    folder = "signals"
    try:  # follow the champion the paper book trades
        from t2.trader.paper_live import CONFIG

        folder = json.loads(CONFIG.read_text()).get("signals", folder)
    except (OSError, ValueError):
        pass
    files = sorted(
        f.path
        for f in hf_store.api().list_repo_tree(hf_store.DATASET_REPO, repo_type="dataset", path_in_repo=folder)
        if f.path.endswith(".parquet")
    )
    if not files:
        return {"date": None, "rows": []}
    p = hf_store.download(files[-1], DATA / "cache")
    df = pl.read_parquet(p) if p else pl.DataFrame()
    return {"date": str(df["date"][0]) if df.height else None, "rows": df.drop("date").to_dicts()}


@app.get("/api/signals")
def signals() -> dict:
    return cached("signals", 600, _signals)


def _model() -> dict:
    from huggingface_hub import hf_hub_download

    # the repo name only: importing the model code would pull in the ML libraries the server does not need
    repo = os.environ.get("HF_MODEL_REPO", "harcorp/t2-models")
    prefix = "champion"
    try:
        from t2.trader.paper_live import CONFIG

        if json.loads(CONFIG.read_text()).get("signals") == "signals-cash":
            prefix = "champion-cash"
    except (OSError, ValueError):
        pass
    p = hf_hub_download(repo, f"{prefix}/meta.json", token=os.environ.get("HF_TOKEN"))
    return json.loads(Path(p).read_text())


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
    }


# ----- news -----
@app.get("/api/news")
def news(q: str = "", symbol: str = "", limit: int = 50) -> dict:
    where, args = ["1=1"], []
    if q:
        where.append("(title like ? or summary like ?)")
        args += [f"%{q}%", f"%{q}%"]
    if symbol:
        where.append("(',' || tickers || ',') like ?")
        args.append(f"%,{symbol.upper()},%")
    sql = (
        "select source, category, url, title, summary, published_at, first_seen_at, tickers from items where "
        + " and ".join(where)
        + " order by coalesce(published_at, first_seen_at) desc limit ?"
    )
    return {"items": rows(NEWS_DB, sql, (*args, min(max(limit, 1), 200)))}


# ----- static dashboard -----
if (STATIC / "_next").exists():
    app.mount("/_next", StaticFiles(directory=STATIC / "_next"), name="next")


@app.get("/{path:path}", include_in_schema=False)
def page(path: str) -> FileResponse:
    for candidate in (STATIC / path, STATIC / f"{path}.html", STATIC / path / "index.html", STATIC / "index.html"):
        if candidate.is_file() and STATIC in candidate.resolve().parents:
            return FileResponse(candidate)
    raise HTTPException(status_code=404, detail="dashboard not built yet")
