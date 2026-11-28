"""Start the time-critical GitHub jobs from the server, on the server's own clock.

GitHub's own schedule is best effort: on 26-27 Nov 2026 the evening data job and the morning signals job started
8-9 hours late, and the 27 Nov paper open traded on the 25 Nov picks. The server's timers fire on time, so they
start the jobs instead (GitHub's schedule stays as a backup):

  evening  19:45 IST weekdays  start nse-daily (the signals workflow follows it automatically when it succeeds)
  morning  08:20 IST weekdays  if the paper book's signals for the last session are missing, start nse-daily again
                               (and so the signals) and say so on the phone; there is time before the 09:20 open

Needs GITHUB_ACTIONS_TOKEN in /opt/t2/.env: a fine-grained token for this repository only, with
"Actions: read and write" (Settings -> API keys in the dashboard). Without it nothing is started.

    python -m t2.jobs evening | morning | check
"""

from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

REPO = os.environ.get("T2_REPO", "harcorpindustries/t2")
API = "https://api.github.com"
IST = ZoneInfo("Asia/Kolkata")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "t2-server"}  # fmt: skip


def token() -> str | None:
    return os.environ.get("GITHUB_ACTIONS_TOKEN") or None


def dispatch(workflow: str, tok: str, ref: str = "main") -> tuple[bool, str]:
    try:
        r = httpx.post(
            f"{API}/repos/{REPO}/actions/workflows/{workflow}/dispatches",
            headers=_headers(tok),
            json={"ref": ref},
            timeout=15,
        )
    except httpx.HTTPError as exc:
        return False, type(exc).__name__
    return r.status_code == 204, f"HTTP {r.status_code}"


def check(tok: str) -> tuple[bool, str]:
    """Can the token see this repository's workflows? (Starting one is not tested: that would run it.)"""
    try:
        r = httpx.get(f"{API}/repos/{REPO}/actions/workflows", headers=_headers(tok), timeout=15)
    except httpx.HTTPError as exc:
        return False, f"no answer from GitHub ({type(exc).__name__})"
    if r.status_code != 200:
        return False, f"GitHub refused it (HTTP {r.status_code}): check the repository and Actions permission"
    names = {w["path"].rsplit("/", 1)[-1] for w in r.json().get("workflows", [])}
    missing = {"nse-daily.yml", "signals.yml"} - names
    return (not missing), "sees the data and signals workflows" if not missing else f"cannot see {sorted(missing)}"


def last_session(today: date) -> date:
    """The weekday before `today` (exchange holidays are not known here: after one, the warning is expected)."""
    d = today - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def signals_behind(latest: date | None, today: date) -> bool:
    return latest is None or latest < last_session(today)


def latest_signal_date(folder: str) -> date | None:
    from t2.trader import paper_live

    dates = paper_live.signal_dates(folder)
    return dates[-1] if dates else None


def evening() -> int:
    from t2 import alerts

    tok = token()
    if not tok:
        print("GITHUB_ACTIONS_TOKEN is not set: nothing started")
        return 0
    ok, msg = dispatch("nse-daily.yml", tok)
    print(f"nse-daily: {msg}")
    if not ok:
        alerts.send(f"T2: could not start the evening data job ({msg}). Signals may be late tomorrow.")
    return 0


def morning() -> int:
    from t2 import alerts
    from t2.trader.paper_live import BookConfig

    today = datetime.now(IST).date()
    folder = BookConfig.load().signals
    latest = latest_signal_date(folder)
    if not signals_behind(latest, today):
        print(f"signals up to date ({latest})")
        return 0
    tok = token()
    if not tok:
        alerts.send(f"T2: no signals for {last_session(today)} yet (latest {latest}); set the GitHub token in "
                    "Settings so the server can start the jobs.")  # fmt: skip
        return 0
    ok, msg = dispatch("nse-daily.yml", tok)
    alerts.send(
        f"T2: signals for {last_session(today)} were missing (latest {latest}); started the data and signals jobs "
        f"at {datetime.now(IST):%H:%M} ({msg}). They take a few minutes, before the 09:20 open."
        if ok
        else f"T2: signals for {last_session(today)} are missing and the jobs could not be started ({msg})."
    )
    print(f"latest signals {latest}; nse-daily: {msg}")
    return 0


def main(argv: list[str] | None = None) -> int:
    from t2.brokers.breeze_check import load_env

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["evening", "morning", "check"])
    a = ap.parse_args(argv)
    load_env()
    if a.cmd == "evening":
        return evening()
    if a.cmd == "morning":
        return morning()
    tok = token()
    print(check(tok)[1] if tok else "GITHUB_ACTIONS_TOKEN is not set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
