import sqlite3

import pytest
from fastapi.testclient import TestClient

from t2.dashboard import api


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA", tmp_path)
    monkeypatch.setattr(api, "NEWS_DB", tmp_path / "news.db")
    monkeypatch.setattr(api, "STATIC", tmp_path / "static")
    monkeypatch.setenv("DASHBOARD_TOKEN", "t0k")
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
    return TestClient(api.app)


def test_book(client):
    b = client.get("/api/book").json()
    assert b["equity"] == 3010000 and b["day_pnl"] == 10000 and b["total_pnl"] == 10000
    assert b["positions"][0]["symbol"] == "TCS" and b["kill"] == {"on": False}


def test_kill_switch_needs_token(client, tmp_path):
    assert client.post("/api/kill", json={"on": True}).status_code == 403
    r = client.post("/api/kill", json={"on": True, "reason": "test"}, headers={"x-dashboard-token": "t0k"})
    assert r.json()["on"] and (tmp_path / "KILL").exists()
    client.post("/api/kill", json={"on": False}, headers={"x-dashboard-token": "t0k"})
    assert not (tmp_path / "KILL").exists()
    kinds = [e["kind"] for e in client.get("/api/book").json()["events"]]
    assert set(kinds) == {"kill_on", "kill_off"}


def test_news_search(client):
    assert [i["url"] for i in client.get("/api/news", params={"symbol": "infy"}).json()["items"]] == ["u1"]
    assert [i["url"] for i in client.get("/api/news", params={"q": "markets"}).json()["items"]] == ["u2"]


def test_static_fallback_and_no_path_escape(client, tmp_path):
    assert client.get("/").status_code == 404  # not built yet
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "index.html").write_text("<html>ok</html>")
    assert client.get("/").text == "<html>ok</html>"
    assert client.get("/../paper.db").text == "<html>ok</html>"
