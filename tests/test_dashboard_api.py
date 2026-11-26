import sqlite3
from datetime import date

import polars as pl
import pytest
from fastapi.testclient import TestClient

from t2.dashboard import api, auth
from t2.trader import paper_live

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
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    con = sqlite3.connect(tmp_path / "paper.db")
    con.executescript(paper_live.SCHEMA)
    con.executescript(
        """insert into days (day, signal_date, equity, gross, charges, trades, blocked) values
          ('2026-11-27', '2026-11-26', 50500, 32000, 60, 2, 0), ('2026-11-30', '2026-11-27', 50200, 32000, 0, 0, 0);
        insert into positions values ('TCS', 5, 3200, 1, null, '2026-11-27');
        insert into trades (ts, day, symbol, side, qty, price, charges, reason, signal_date) values
          ('2026-11-27T09:20:00', '2026-11-27', 'TCS', 'buy', 5, 3200, 20, 'enter', '2026-11-26'),
          ('2026-11-27T09:20:01', '2026-11-27', 'INFY', 'buy', 10, 1500, 20, 'enter', '2026-11-26'),
          ('2026-11-30T09:20:00', '2026-11-30', 'INFY', 'sell', 10, 1560, 20, 'exit', '2026-11-27');
        insert into account values ('cash', 18000);"""
    )
    con.commit()
    px = pl.DataFrame(
        {
            "date": [date(2026, 11, 26), date(2026, 11, 27), date(2026, 11, 30)] * 2,
            "symbol": ["TCS"] * 3 + ["INFY"] * 3,
            "open": [3190.0, 3200, 3240, 1490, 1500, 1550],
            "high": [3210.0, 3260, 3270, 1510, 1560, 1570],
            "low": [3180.0, 3190, 3230, 1480, 1495, 1540],
            "close": [3200.0, 3250, 3260, 1500, 1550, 1560],
            "prev_close": [3180.0, 3200, 3250, 1490, 1500, 1550],
            "volume": [1e6] * 6,
            "turnover": [1e9] * 6,
        }
    )
    hist = pl.DataFrame(
        {
            "date": [date(2026, 11, 26)] * 2 + [date(2026, 11, 27)] * 2,
            "symbol": ["TCS", "INFY", "INFY", "TCS"],
            "rank": [1, 2, 1, 2],
            "score": [0.5, 0.1, 0.4, 0.2],
            "close": [3200.0, 1500, 1550, 3250],
        }
    )
    monkeypatch.setattr(api, "prices", lambda: px)
    monkeypatch.setattr(api, "signal_history", lambda: hist)
    monkeypatch.setattr(api, "sectors", lambda: {"TCS": "Information Technology"})
    monkeypatch.setattr(
        api,
        "book_cfg",
        lambda: {"capital": 50000, "k": 3, "exit_k": 200, "vehicle": "delivery", "risk": {"max_open_positions": 4}},
    )
    news = sqlite3.connect(tmp_path / "news.db")
    news.executescript(
        """create table items (id text, source text, category text, url text, title text, summary text,
        published_at text, first_seen_at text, tickers text, text text, text_status text);
        insert into items values ('a1', 'mint', 'news', 'https://x.com/tcs', 'TCS results', '', '2026-11-27',
          '2026-11-27', 'TCS,INFY', 'Full article text', 'ok');
        insert into items values ('a2', 'et', 'news', 'https://x.com/mkt', 'Markets today', '', '2026-11-27',
          '2026-11-27', '', null, 'error');
        insert into items values ('f1', 'nse_online_announcements', 'exchange',
          'https://nsearchives.nseindia.com/corporate/xbrl/X.xml', 'Dalmia Bharat Limited', 'informed the Exchange',
          '2026-11-27', '2026-11-27', 'DALMIABHA', null, 'skipped');
        insert into items values ('f2', 'nse_board_meetings', 'exchange',
          'https://nsearchives.nseindia.com/corporate/B.pdf', 'Dollex', '', '2026-11-26', '2026-11-26', '', null,
          'skipped');"""
    )
    news.commit()
    c = TestClient(api.app, base_url="https://testserver")
    assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
    return c


def test_book(client):
    b = client.get("/api/book").json()
    assert b["equity"] == 50200 and b["day_pnl"] == -300 and b["total_pnl"] == 200
    assert b["kill"] == {"on": False, "flatten": False}
    tcs = b["positions"][0]
    assert tcs["symbol"] == "TCS" and tcs["last"] == 3260 and tcs["pnl"] == 300 and tcs["rank"] == 2
    assert tcs["sector"] == "Information Technology"
    (trip,) = b["round_trips"]
    assert trip["symbol"] == "INFY" and trip["pnl"] == 600 - 40  # after both legs' charges
    assert b["trade_stats"]["win_rate"] == 1.0
    assert b["stats"]["total_return"] == 50200 / 50000 - 1
    assert set(b["trades"][0]["breakdown"]) >= {"stt", "brokerage", "gst", "stamp", "total"}


def test_signals_with_rank_change(client, monkeypatch):
    from t2.data import hf_store

    monkeypatch.setattr(hf_store, "download", lambda path, dest: None)
    api._cache.clear()
    s = client.get("/api/signals").json()
    assert s["date"] == "2026-11-27" and s["prev_date"] == "2026-11-26"
    assert {r["symbol"]: r["prev_rank"] for r in s["rows"]} == {"INFY": 2, "TCS": 1}
    assert client.get("/api/signals", params={"date": "2026-11-26"}).json()["rows"][0]["prev_rank"] is None


def test_stock_risk_and_flatten(client, tmp_path):
    st = client.get("/api/stock/tcs").json()
    assert st["symbol"] == "TCS" and len(st["candles"]) == 3 and st["position"]["qty"] == 5
    assert [x["rank"] for x in st["scores"]] == [1, 2] and st["news"][0]["id"] == "a1"
    assert client.get("/api/stock/..%2Fx").status_code in (400, 404)
    r = client.get("/api/risk").json()
    assert r["usage"]["open_positions"] == 1 and r["usage"]["exposure"] == 5 * 3260
    assert client.post("/api/flatten", json={"on": True}).json() == {"flatten": True}
    assert (tmp_path / "FLATTEN").exists() and client.get("/api/book").json()["kill"]["flatten"]
    client.post("/api/flatten", json={"on": False})
    assert not (tmp_path / "FLATTEN").exists()


def test_logs_reject_other_units(client):
    assert client.get("/api/logs/sshd").status_code == 400
    assert client.get("/api/logs/t2-paper-open").status_code == 200


def test_revoke_sessions_signs_out_other_browsers(client, tmp_path, monkeypatch):
    from t2.dashboard import breeze_session as bs

    monkeypatch.setattr(bs, "ENV_FILE", tmp_path / ".env")
    other = TestClient(api.app, base_url="https://testserver")
    assert other.post("/api/login", json={"password": PASSWORD}).status_code == 200
    assert client.post("/api/sessions/revoke").status_code == 200
    assert other.get("/api/book").status_code == 401
    assert client.get("/api/book").status_code == 200
    assert "DASHBOARD_SESSION_KEY=" in (tmp_path / ".env").read_text()


def test_news_for_holdings_and_tone(client):
    items = client.get("/api/news", params={"symbols": "INFY,XYZ", "group": "all"}).json()["items"]
    assert [i["id"] for i in items] == ["a1"]
    assert client.get("/api/news-tone").status_code == 200


def test_kill_switch_needs_login_or_token(client, tmp_path):
    anon = TestClient(api.app, base_url="https://testserver")
    assert anon.post("/api/kill", json={"on": True}).status_code == 401
    r = anon.post("/api/kill", json={"on": True, "reason": "test"}, headers={"x-dashboard-token": "t0k"})
    assert r.json()["on"] and (tmp_path / "KILL").exists()
    client.post("/api/kill", json={"on": False})
    assert not (tmp_path / "KILL").exists()
    kinds = [e["kind"] for e in client.get("/api/book").json()["events"]]
    assert set(kinds) == {"kill_on", "kill_off"}
    assert client.get("/api/risk").json()["blocked"][0]["kind"] == "kill_off"


def test_news_search(client):
    assert [i["id"] for i in client.get("/api/news", params={"symbol": "infy"}).json()["items"]] == ["a1"]
    assert [i["id"] for i in client.get("/api/news", params={"q": "markets"}).json()["items"]] == ["a2"]


def test_news_groups_and_human_links(client):
    arts = client.get("/api/news").json()["items"]  # default group: readable articles only
    assert {i["id"] for i in arts} == {"a1", "a2"}
    assert arts[0]["link"].startswith("https://x.com/") and arts[0]["raw_url"] is None
    filings = {i["id"]: i for i in client.get("/api/news", params={"group": "filings"}).json()["items"]}
    xbrl = filings["f1"]
    assert xbrl["link"].endswith("corporate-filings-announcements?symbol=DALMIABHA")
    assert xbrl["raw_type"] == "xml" and xbrl["raw_url"].endswith("X.xml")
    assert filings["f2"]["link"].endswith("B.pdf")  # PDFs are readable: link straight to them
    assert len(client.get("/api/news", params={"group": "all"}).json()["items"]) == 4


def test_news_item_text(client):
    assert client.get("/api/news/a1").json()["text"] == "Full article text"
    assert client.get("/api/news/nope").status_code == 404


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
