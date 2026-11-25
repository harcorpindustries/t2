"""Tag text with NSE symbols using the official equity list (symbol + company name).

Company names match case-insensitively; bare symbols only when written in capitals (so "IDEA" the
symbol matches but "idea" the word does not).
"""

from __future__ import annotations

import io
import re
from functools import lru_cache

import httpx
import polars as pl

from t2.data.nse_archive import USER_AGENT

EQUITY_LIST_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
_SUFFIX = re.compile(r"\b(limited|ltd\.?|private|pvt\.?|corporation|corp\.?|company|co\.?|the)\b", re.I)
_AMBIGUOUS = {"IT", "ALL", "ONE", "BEST", "GOLD", "OIL", "SUN", "LIFE", "INDIA", "BANK", "POWER", "NEW"}


def _short_name(name: str) -> str:
    return re.sub(r"\s+", " ", _SUFFIX.sub(" ", name)).strip(" .,&-")


def _alternation(keys: list[str]) -> str:
    return "|".join(re.escape(k) for k in sorted(keys, key=len, reverse=True))


def build(rows: list[tuple[str, str]]) -> tuple[re.Pattern[str], dict[str, str], re.Pattern[str], set[str]]:
    names: dict[str, str] = {}
    symbols: set[str] = set()
    for sym, name in rows:
        short = _short_name(name)
        if len(short) >= 5:
            names[short.lower()] = sym
        if len(sym) >= 3 and sym not in _AMBIGUOUS:
            symbols.add(sym)
    edge_l, edge_r = r"(?<![\w&])", r"(?![\w&])"
    name_re = re.compile(edge_l + "(" + _alternation(list(names)) + ")" + edge_r, re.I)
    sym_re = re.compile(edge_l + "(" + _alternation(list(symbols)) + ")" + edge_r)
    return name_re, names, sym_re, symbols


@lru_cache(maxsize=1)
def _matcher() -> tuple[re.Pattern[str], dict[str, str], re.Pattern[str], set[str]]:
    raw = httpx.get(EQUITY_LIST_URL, headers={"User-Agent": USER_AGENT}, timeout=30).content
    df = pl.read_csv(io.BytesIO(raw), infer_schema=False)
    df = df.rename({c: c.strip() for c in df.columns})
    return build([(s, n) for s, n in df.select("SYMBOL", "NAME OF COMPANY").iter_rows()])


def tag(
    text: str | None, matcher: tuple[re.Pattern[str], dict[str, str], re.Pattern[str], set[str]] | None = None
) -> list[str]:
    if not text:
        return []
    name_re, names, sym_re, _ = matcher or _matcher()
    found = {names[m.group(1).lower()] for m in name_re.finditer(text)}
    for line in text.splitlines():
        letters = [c for c in line if c.isalpha()]
        if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6:
            continue  # ALL-CAPS line (exchange titles): capitals carry no signal, rely on names
        found |= {m.group(1) for m in sym_re.finditer(line)}
    return sorted(found)
