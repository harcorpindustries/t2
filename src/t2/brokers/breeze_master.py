"""ICICI security master: maps Breeze stock codes to NSE symbols and streaming tokens."""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass

import httpx

MASTER_URL = "https://directlink.icicidirect.com/NewSecurityMaster/SecurityMaster.zip"


@dataclass(frozen=True)
class Instrument:
    breeze_code: str  # e.g. RELIND
    nse_symbol: str  # e.g. RELIANCE ("NIFTY 50" for indices)
    kind: str  # index | stock
    token: str = ""  # cash-segment streaming token, e.g. 2885


def _rows(z: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    text = z.read(name).decode("latin-1")
    return list(csv.DictReader(io.StringIO(text), skipinitialspace=True))


def load_master(content: bytes | None = None) -> zipfile.ZipFile:
    if content is None:
        content = httpx.get(MASTER_URL, timeout=120, follow_redirects=True).content
    return zipfile.ZipFile(io.BytesIO(content))


def fno_universe(z: zipfile.ZipFile) -> list[Instrument]:
    """Every index and stock with NSE futures, keyed by its cash-segment Breeze code."""
    cash = {r["ShortName"]: r for r in _rows(z, "NSEScripMaster.txt") if r.get("Series") == "EQ"}
    seen: dict[str, Instrument] = {}
    for r in _rows(z, "FONSEScripMaster.txt"):
        kind = {"FUTIDX": "index", "FUTSTK": "stock"}.get(r["InstrumentName"])
        code = r["ShortName"]
        if kind is None or code in seen:
            continue
        token = cash[code]["Token"] if code in cash else ""
        symbol = cash[code]["ExchangeCode"] if code in cash else r["ExchangeCode"]
        seen[code] = Instrument(code, symbol, kind, token)
    return sorted(seen.values(), key=lambda i: (i.kind != "index", i.nse_symbol))
