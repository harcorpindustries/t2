"""API keys and secrets managed from the dashboard instead of the terminal.

Rules (a stolen session cookie must not be enough to take over the accounts):
  - only the keys listed here, never arbitrary names (the tunnel token, the session key and today's Breeze
    session stay with their own tools)
  - values are write-only: the API reports set / not set, when it changed and the last 4 characters, never the value
  - every change needs the dashboard password again, is rate limited with the login, written to the event log
    and announced on the phone
  - stored in /opt/t2/.env (mode 600) like before; jobs read it on their next run, the dashboard at once
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from t2.dashboard import breeze_session as bs

SECRETS: dict[str, dict] = {
    "BREEZE_API_KEY": {"group": "Breeze (ICICI Direct)", "label": "API key", "secret": True,
                       "help": "From the ICICI Breeze API page (App Key)."},
    "BREEZE_API_SECRET": {"group": "Breeze (ICICI Direct)", "label": "API secret", "secret": True,
                          "help": "From the ICICI Breeze API page (Secret Key)."},
    "TELEGRAM_BOT_TOKEN": {"group": "Telegram alerts", "label": "Bot token", "secret": True,
                           "help": "From @BotFather (/newbot)."},
    "TELEGRAM_CHAT_ID": {"group": "Telegram alerts", "label": "Chat ID", "secret": False,
                         "help": "Your chat with the bot. Send the bot a message, then use 'Find my chat'."},
    "HF_TOKEN": {"group": "Hugging Face", "label": "Access token", "secret": True,
                 "help": "huggingface.co → Settings → Access Tokens (write access to the t2 repos)."},
    "GITHUB_ACTIONS_TOKEN": {"group": "GitHub", "label": "Actions token", "secret": True,
                             "help": "Lets the server start the data and signals jobs on time. github.com → Settings → "
                                     "Developer settings → Fine-grained tokens: only the t2 repository, "
                                     "permission Actions: read and write, nothing else."},
}  # fmt: skip

VALUE = re.compile(r"[\x21-\x7e]{1,512}")  # printable ASCII, no spaces
UNSAFE = set("\"'\\`")  # characters the service manager's env-file parser would interpret


def meta_file() -> Path:
    return Path(os.environ.get("T2_PAPER_DIR", "/opt/t2/data")) / "secrets_meta.json"


def _meta() -> dict[str, str]:
    try:
        return json.loads(meta_file().read_text())
    except (OSError, ValueError):
        return {}


def listing(env_path: Path | None = None) -> list[dict]:
    env = bs.read_env(env_path)
    meta = _meta()
    out = []
    for key, spec in SECRETS.items():
        v = env.get(key, "")
        hint = None
        if v:
            hint = f"…{v[-4:]}" if spec["secret"] and len(v) >= 12 else (v if not spec["secret"] else None)
        out.append({"key": key, **spec, "set": bool(v), "hint": hint, "updated_at": meta.get(key)})
    return out


def validate(key: str, value: str) -> str | None:
    """Error message, or None when the value can be stored."""
    if key not in SECRETS:
        return "unknown setting"
    if value == "":
        return None  # clearing is allowed
    if not VALUE.fullmatch(value) or UNSAFE & set(value):
        return "use the value exactly as given: no spaces, quotes or backslashes"
    if key == "TELEGRAM_CHAT_ID" and not re.fullmatch(r"-?\d{1,20}", value):
        return "a chat ID is a number"
    if key == "TELEGRAM_BOT_TOKEN" and not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", value):
        return "a bot token looks like 123456789:ABC…"
    if key == "HF_TOKEN" and not value.startswith("hf_"):
        return "a Hugging Face token starts with hf_"
    if key == "GITHUB_ACTIONS_TOKEN" and not value.startswith(("github_pat_", "ghp_")):
        return "a GitHub token starts with github_pat_ (fine-grained, preferred) or ghp_"
    return None


def store(key: str, value: str, env_path: Path | None = None) -> None:
    bs.write_env_value(key, value, env_path)
    if value:
        os.environ[key] = value
    else:
        os.environ.pop(key, None)
    meta = _meta()
    meta[key] = datetime.now(UTC).isoformat(timespec="seconds")
    f = meta_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(meta, indent=2))


def test(key: str) -> tuple[bool, str]:
    """Check that a stored setting works, without revealing it."""
    env = bs.read_env()
    if key.startswith("TELEGRAM_"):
        from t2 import alerts

        os.environ.update({k: env[k] for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if env.get(k)})
        return (True, "test message sent") if alerts.send("T2: test alert from Settings.") else (
            False, "not sent: check the bot token and chat ID")  # fmt: skip
    if key == "HF_TOKEN":
        try:
            from huggingface_hub import HfApi

            who = HfApi(token=env.get("HF_TOKEN")).whoami()
            return True, f"signed in as {who.get('name', '?')}"
        except Exception as exc:
            return False, f"rejected ({type(exc).__name__})"
    if key == "GITHUB_ACTIONS_TOKEN":
        from t2 import jobs

        tok = env.get(key)
        return jobs.check(tok) if tok else (False, "not set")
    if key.startswith("BREEZE_"):
        session = env.get("BREEZE_SESSION_TOKEN", "")
        if not bs.status().get("valid_today"):
            return False, "log in to Breeze today first; the key and secret are checked with today's session"
        ok, msg = bs.check_with_breeze(session)
        return ok, "key, secret and today's session work" if ok else msg
    return False, "no test for this setting"
