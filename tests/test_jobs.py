from datetime import date

import httpx

from t2 import alerts, jobs
from t2.dashboard import secrets


def test_last_session_skips_weekends():
    assert jobs.last_session(date(2026, 11, 30)) == date(2026, 11, 27)  # Monday -> Friday
    assert jobs.last_session(date(2026, 11, 27)) == date(2026, 11, 26)
    assert jobs.last_session(date(2026, 11, 29)) == date(2026, 11, 27)  # Sunday -> Friday


def test_signals_behind():
    mon = date(2026, 11, 30)
    assert not jobs.signals_behind(date(2026, 11, 27), mon)
    assert jobs.signals_behind(date(2026, 11, 26), mon)
    assert jobs.signals_behind(None, mon)


def test_dispatch_posts_to_the_workflow(monkeypatch):
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, auth=headers["Authorization"], body=json)
        return httpx.Response(204)

    monkeypatch.setattr(httpx, "post", fake_post)
    ok, msg = jobs.dispatch("nse-daily.yml", "github_pat_x")
    assert ok and msg == "HTTP 204"
    assert seen["url"].endswith("/repos/harcorpindustries/t2/actions/workflows/nse-daily.yml/dispatches")
    assert seen["auth"] == "Bearer github_pat_x" and seen["body"] == {"ref": "main"}


def test_morning_starts_jobs_only_when_behind(monkeypatch):
    sent, started = [], []
    monkeypatch.setattr(alerts, "send", lambda t: sent.append(t) or True)
    monkeypatch.setattr(jobs, "dispatch", lambda wf, tok: started.append(wf) or (True, "HTTP 204"))
    monkeypatch.setenv("GITHUB_ACTIONS_TOKEN", "github_pat_x")
    monkeypatch.setattr(jobs, "latest_signal_date", lambda folder: date(2000, 1, 3))
    jobs.morning()
    assert started == ["nse-daily.yml"] and "missing" in sent[0]
    sent.clear(), started.clear()
    monkeypatch.setattr(jobs, "latest_signal_date", lambda folder: date(2999, 1, 1))
    jobs.morning()
    assert not started and not sent


def test_token_format_is_checked():
    assert secrets.validate("GITHUB_ACTIONS_TOKEN", "github_pat_abc123") is None
    assert secrets.validate("GITHUB_ACTIONS_TOKEN", "hf_abc") is not None


def test_open_alert_carries_the_warning():
    msg = alerts.open_summary({"filled": 2, "blocked": 1, "charges": 84.7, "signal_date": "2026-11-25",
                               "warning": "traded on picks from 2026-11-25"})  # fmt: skip
    assert "WARNING: traded on picks from 2026-11-25" in msg
    assert "WARNING" not in alerts.open_summary({"filled": 1, "signal_date": "2026-11-26"})
