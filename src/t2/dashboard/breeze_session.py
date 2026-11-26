"""Daily Breeze login from the dashboard: build ICICI's login link, check a returned session, save it.

Flow: dashboard button -> ICICI login page (our API key) -> ICICI redirects the browser to
https://t2.harcorp.biz/breeze/callback?apisession=N -> that page (signed-in users only) posts N here ->
we confirm it with Breeze, then store it as BREEZE_SESSION_TOKEN in /opt/t2/.env for every job on the server.
"""

from __future__ import annotations

import os
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ENV_FILE = Path(os.environ.get("T2_ENV_FILE", "/opt/t2/.env"))
IST = ZoneInfo("Asia/Kolkata")
LOGIN = "https://api.icicidirect.com/apiuser/login?api_key="


def read_env(path: Path | None = None) -> dict[str, str]:
    path = path or ENV_FILE
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def write_env_value(name: str, value: str, path: Path | None = None) -> None:
    """Replace one KEY=value line atomically, keeping the file private."""
    path = path or ENV_FILE
    lines = [ln for ln in (path.read_text().splitlines() if path.exists() else []) if not ln.startswith(f"{name}=")]
    lines.append(f"{name}={value}")
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.chmod(0o600)
    tmp.replace(path)


def login_url(path: Path | None = None) -> str:
    key = read_env(path).get("BREEZE_API_KEY", "")
    if not key:
        raise RuntimeError("BREEZE_API_KEY is not set on the server")
    return LOGIN + urllib.parse.quote_plus(key)


def clean(session: str) -> str:
    return "".join(ch for ch in session if ch.isalnum())[:64]


def check_with_breeze(session: str, path: Path | None = None) -> tuple[bool, str]:
    """Open a Breeze session with this number (read-only). Returns (ok, message)."""
    env = read_env(path)
    try:
        from breeze_connect import BreezeConnect

        b = BreezeConnect(api_key=env["BREEZE_API_KEY"])
        b.generate_session(api_secret=env["BREEZE_API_SECRET"], session_token=session)
        return True, "session ok"
    except Exception as exc:  # the library raises plain Exceptions for rejected sessions
        return False, f"Breeze rejected the session ({type(exc).__name__}); log in again"


def status(path: Path | None = None) -> dict:
    """When the current session was saved, and whether that was today (sessions end at midnight IST)."""
    path = path or ENV_FILE
    env = read_env(path)
    saved = env.get("BREEZE_SESSION_SAVED_AT")
    today = datetime.now(IST).date().isoformat()
    return {
        "has_session": bool(env.get("BREEZE_SESSION_TOKEN")),
        "saved_at": saved,
        "valid_today": bool(saved) and saved[:10] == today,
    }


def save(session: str, path: Path | None = None) -> None:
    write_env_value("BREEZE_SESSION_TOKEN", session, path)
    write_env_value("BREEZE_SESSION_SAVED_AT", datetime.now(UTC).astimezone(IST).isoformat(timespec="seconds"), path)
