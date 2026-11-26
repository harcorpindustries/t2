import sqlite3

import pytest
from fastapi.testclient import TestClient

from t2.dashboard import api, auth

PASSWORD = "correct horse battery"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA", tmp_path)
    monkeypatch.setattr(api, "NEWS_DB", tmp_path / "news.db")
    monkeypatch.setattr(api, "STATIC", tmp_path / "static")
    monkeypatch.setenv("DASHBOARD_TOKEN", "t0k")
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", auth.hash_password(PASSWORD))
    monkeypatch.setenv("DASHBOARD_SESSION_KEY", "k" * 40)
    auth._failures.clear()
    con = sqlite3.connect(tmp_path / "paper.db")
    con.executescript(
        """create table days (day text, equity real, gross real);
        insert into days values ('2026-11-27', 3000000, 1e7), ('2026-11-30', 3010000, 1e7);
        create table positions (symbol text, qty integer); insert into positions values ('TCS', 225);
        create table trades (ts text); create table events (ts text, kind text, detail text);
        create table account (k text, v real); insert into account values ('cash', 2990000);"""
    )
    con.commit()
    news = sqlite3.connect(tmp_path / "news.db")
    news.executescript(
        """create table items (source text, category text, url text, title text, summary text,
        published_at text, first_seen_at text, tickers text);
        insert into items values ('nse', 'filing', 'u1', 'TCS results', '', '2026-11-27', '2026-11-27', 'TCS,INFY');
        insert into items values ('et', 'press', 'u2', 'Markets today', '', '2026-11-27', '2026-11-27', '');"""
    )
    news.commit()
    c = TestClient(api.app, base_url="https://testserver")
    assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
    return c


def test_book(client):
    b = client.get("/api/book").json()
    assert b["equity"] == 3010000 and b["day_pnl"] == 10000 and b["total_pnl"] == 10000
    assert b["positions"][0]["symbol"] == "TCS" and b["kill"] == {"on": False}


def test_kill_switch_needs_login_or_token(client, tmp_path):
    anon = TestClient(api.app, base_url="https://testserver")
    assert anon.post("/api/kill", json={"on": True}).status_code == 401
    r = anon.post("/api/kill", json={"on": True, "reason": "test"}, headers={"x-dashboard-token": "t0k"})
    assert r.json()["on"] and (tmp_path / "KILL").exists()
    client.post("/api/kill", json={"on": False})
    assert not (tmp_path / "KILL").exists()
    kinds = [e["kind"] for e in client.get("/api/book").json()["events"]]
    assert set(kinds) == {"kill_on", "kill_off"}


def test_news_search(client):
    assert [i["url"] for i in client.get("/api/news", params={"symbol": "infy"}).json()["items"]] == ["u1"]
    assert [i["url"] for i in client.get("/api/news", params={"q": "markets"}).json()["items"]] == ["u2"]


def test_everything_needs_login(client):
    anon = TestClient(api.app, base_url="https://testserver", follow_redirects=False)
    assert anon.get("/api/book").status_code == 401
    assert anon.get("/api/news").status_code == 401
    r = anon.get("/book")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert anon.post("/api/login", json={"password": "nope"}).status_code == 401
    client.post("/api/logout")
    assert client.get("/api/book").status_code == 401


def test_login_rate_limit(client):
    anon = TestClient(api.app, base_url="https://testserver")
    codes = [anon.post("/api/login", json={"password": "bad"}).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    assert anon.post("/api/login", json={"password": PASSWORD}).status_code == 429  # locked for the window


def test_no_password_configured_means_closed(client, monkeypatch):
    monkeypatch.delenv("DASHBOARD_PASSWORD_HASH")
    assert client.get("/api/book").status_code == 503


def test_session_tokens():
    import os

    os.environ["DASHBOARD_SESSION_KEY"] = "s" * 40
    t = auth.make_session(now=1000.0)
    assert auth.valid_session(t, now=1001.0)
    assert not auth.valid_session(t, now=1000.0 + auth.SESSION_SECONDS + 1)
    assert not auth.valid_session(t[:-1] + ("0" if t[-1] != "0" else "1"), now=1001.0)
    assert auth.check_password("pw", auth.hash_password("pw")) and not auth.check_password(
        "px", auth.hash_password("pw")
    )


def test_static_fallback_and_no_path_escape(client, tmp_path):
    assert client.get("/").status_code == 404  # not built yet
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "index.html").write_text("<html>ok</html>")
    assert client.get("/").text == "<html>ok</html>"
    assert client.get("/../paper.db").text == "<html>ok</html>"


def test_breeze_login_flow(client, tmp_path, monkeypatch):
    from t2.dashboard import breeze_session as bs

    env = tmp_path / ".env"
    env.write_text("BREEZE_API_KEY=k+y/1\nBREEZE_API_SECRET=s\nOTHER=1\n")
    monkeypatch.setattr(bs, "ENV_FILE", env)
    assert client.get("/api/breeze/login-url").json()["url"].endswith("api_key=k%2By%2F1")
    assert client.get("/api/breeze/status").json()["valid_today"] is False

    monkeypatch.setattr(bs, "check_with_breeze", lambda s, path=None: (False, "rejected"))
    assert client.post("/api/breeze/session", json={"apisession": "1234"}).status_code == 422
    assert "BREEZE_SESSION_TOKEN" not in env.read_text()  # a rejected session is never saved

    monkeypatch.setattr(bs, "check_with_breeze", lambda s, path=None: (True, "ok"))
    r = client.post("/api/breeze/session", json={"apisession": "12345678"})
    assert r.status_code == 200 and r.json()["valid_today"] is True
    text = env.read_text()
    assert "BREEZE_SESSION_TOKEN=12345678" in text and "OTHER=1" in text and "BREEZE_API_KEY=k+y/1" in text
    assert (env.stat().st_mode & 0o777) == 0o600


def test_breeze_session_needs_dashboard_login(client):
    anon = TestClient(api.app, base_url="https://testserver", follow_redirects=False)
    assert anon.post("/api/breeze/session", json={"apisession": "12345678"}).status_code == 401
    assert anon.get("/api/breeze/login-url").status_code == 401
    # the callback form post is public but only redirects to the page, saving nothing
    r = anon.post("/breeze/callback", data={"apisession": "1234<script>"})
    assert r.status_code == 303 and r.headers["location"] == "/breeze/callback?apisession=1234script"
