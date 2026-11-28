"""Phone alerts through a Telegram bot: Breeze login reminder, paper fills, end-of-day summary, errors, kill switch.

Off until both settings exist in /opt/t2/.env (set them with infra/set_server_secret.sh, never in chat):
  TELEGRAM_BOT_TOKEN  from @BotFather
  TELEGRAM_CHAT_ID    your chat with the bot; after messaging the bot once, `python -m t2.alerts chat-id` prints it

    python -m t2.alerts remind    # weekday mornings: nudge if today's Breeze login is missing
    python -m t2.alerts test      # send a test message
    python -m t2.alerts chat-id   # list chats that have messaged the bot
"""

from __future__ import annotations

import argparse
import os

import httpx

DASHBOARD = os.environ.get("T2_DASHBOARD_URL", "https://t2.harcorp.biz")


def configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def send(text: str) -> bool:
    """Send one message. Never raises: an alert failing must not stop trading or a dashboard action."""
    if not configured():
        return False
    token, chat = os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True},
            timeout=10,
        )
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def rupees(v: float | None) -> str:
    if v is None:
        return "-"
    sign = "-" if v < 0 else ""
    return f"{sign}Rs {abs(v):,.0f}"


def open_summary(result: dict) -> str:
    if "skipped" in result:
        return f"T2 paper open: skipped ({result['skipped']})"
    msg = (
        f"T2 paper open: {result.get('filled', 0)} filled, {result.get('blocked', 0)} blocked, "
        f"charges {rupees(result.get('charges'))} (signals from {result.get('signal_date')})"
    )
    return msg + (f"\nWARNING: {result['warning']}" if result.get("warning") else "")


def close_summary(result: dict, prev_equity: float | None) -> str:
    if "skipped" in result:
        return f"T2 paper close: skipped ({result['skipped']})"
    eq = result.get("equity")
    day = f", day {rupees(eq - prev_equity)}" if eq is not None and prev_equity is not None else ""
    return f"T2 paper close: equity {rupees(eq)}{day}, {result.get('positions', 0)} positions"


def remind() -> int:
    from t2.dashboard import breeze_session as bs

    if not bs.status()["valid_today"]:
        send(f"T2: Breeze login needed before 09:20 IST. Open {DASHBOARD} and tap 'Log in to Breeze'.")
    return 0


def chat_ids() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set")
        return 1
    r = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10).json()
    seen = {}
    for u in r.get("result", []):
        chat = (u.get("message") or {}).get("chat") or {}
        if chat.get("id") is not None:
            seen[chat["id"]] = chat.get("username") or chat.get("title") or ""
    for cid, name in seen.items():
        print(cid, name)
    if not seen:
        print("no chats yet: send any message to the bot, then run this again")
    return 0


def main(argv: list[str] | None = None) -> int:
    from t2.brokers.breeze_check import load_env

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["remind", "test", "chat-id"])
    a = ap.parse_args(argv)
    load_env()
    if a.cmd == "remind":
        return remind()
    if a.cmd == "chat-id":
        return chat_ids()
    print("sent" if send("T2: test alert. Alerts are working.") else "not sent (check the two TELEGRAM_ settings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
