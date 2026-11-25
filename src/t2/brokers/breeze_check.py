"""Read-only Breeze connectivity check. Never places, modifies or cancels orders.

Run on the live server (static IP), after the daily login:
  uv run --with breeze-connect python -m t2.brokers.breeze_check
Reads BREEZE_API_KEY, BREEZE_API_SECRET, BREEZE_SESSION_TOKEN from the environment or /opt/t2/.env.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ENV_FILE = Path("/opt/t2/.env")


def load_env(path: Path = ENV_FILE) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def summarize(resp: Any) -> str:
    if not isinstance(resp, dict):
        return f"unexpected response type {type(resp).__name__}"
    status, error, success = resp.get("Status"), resp.get("Error"), resp.get("Success")
    if error:
        return f"status={status} error={error}"
    if isinstance(success, list):
        return f"status={status} rows={len(success)}"
    if isinstance(success, dict):
        return f"status={status} keys={sorted(success)[:8]}"
    return f"status={status}"


def main() -> int:
    load_env()
    from breeze_connect import BreezeConnect  # imported lazily: optional dependency

    breeze = BreezeConnect(api_key=os.environ["BREEZE_API_KEY"])
    breeze.generate_session(
        api_secret=os.environ["BREEZE_API_SECRET"], session_token=os.environ["BREEZE_SESSION_TOKEN"]
    )
    print("session: ok")

    now = datetime.now()
    checks = {
        "funds": lambda: breeze.get_funds(),
        "quote RELIANCE (NSE cash)": lambda: breeze.get_quotes(
            stock_code="RELIND", exchange_code="NSE", product_type="cash"
        ),
        "historical v2 RELIANCE 1minute (last 3 days)": lambda: breeze.get_historical_data_v2(
            interval="1minute",
            from_date=(now - timedelta(days=3)).strftime("%Y-%m-%dT09:15:00.000Z"),
            to_date=now.strftime("%Y-%m-%dT15:30:00.000Z"),
            stock_code="RELIND",
            exchange_code="NSE",
            product_type="cash",
        ),
    }
    failed = 0
    for name, call in checks.items():
        try:
            result = summarize(call())
        except Exception as exc:  # report every check, don't stop at the first failure
            result, failed = f"EXCEPTION {type(exc).__name__}: {exc}", failed + 1
        print(f"{name}: {result}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
