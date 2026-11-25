"""NSE end-of-day archives: URL rules, download and parsing into normalized tables.

Kinds:
  cm  - equity bhavcopy (legacy format 1994-11 .. 2024-07, UDiFF format 2024+)
  fo  - F&O bhavcopy (legacy 2000-06 .. 2024-07, UDiFF 2024+)
  mto - security-wise delivery position
"""

from __future__ import annotations

import io
import time
import zipfile
from dataclasses import dataclass
from datetime import date

import httpx
import polars as pl

BASE = "https://nsearchives.nseindia.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
KINDS = ("cm", "fo", "mto")
FIRST_DATE = {"cm": date(1994, 11, 1), "fo": date(2000, 6, 1), "mto": date(1995, 1, 1)}


def candidate_urls(kind: str, d: date) -> list[tuple[str, str]]:
    """(format, url) pairs to try in order. UDiFF first, legacy as fallback."""
    ymd, dmy = d.strftime("%Y%m%d"), d.strftime("%d%m%Y")
    mon, legacy_day = d.strftime("%b").upper(), d.strftime("%d%b%Y").upper()
    if kind == "cm":
        return [
            ("udiff", f"{BASE}/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip"),
            ("legacy", f"{BASE}/content/historical/EQUITIES/{d.year}/{mon}/cm{legacy_day}bhav.csv.zip"),
        ]
    if kind == "fo":
        return [
            ("udiff", f"{BASE}/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"),
            ("legacy", f"{BASE}/content/historical/DERIVATIVES/{d.year}/{mon}/fo{legacy_day}bhav.csv.zip"),
        ]
    if kind == "mto":
        return [("mto", f"{BASE}/archives/equities/mto/MTO_{dmy}.DAT")]
    raise ValueError(f"unknown kind {kind}")


@dataclass
class Fetched:
    status: str  # ok | not_published | source_empty | error
    http_status: int
    fmt: str = ""
    url: str = ""
    content: bytes = b""
    attempts: int = 0


def fetch(client: httpx.Client, kind: str, d: date, retries: int = 4) -> Fetched:
    """Try each candidate URL. 404 on all of them means NSE published nothing for that day."""
    attempts, last_status = 0, 0
    empty: tuple[str, str] | None = None
    for fmt, url in candidate_urls(kind, d):
        for i in range(retries):
            attempts += 1
            try:
                r = client.get(url)
            except httpx.HTTPError:
                last_status = -1
                time.sleep(2**i)
                continue
            last_status = r.status_code
            if r.status_code == 200 and r.content and not r.content.lstrip().startswith(b"<"):
                return Fetched("ok", 200, fmt, url, r.content, attempts)
            if r.status_code == 404:
                break  # definitive for this URL; try the next format
            if r.status_code == 200 and not r.content and i >= 1:
                empty = (fmt, url)  # NSE serves a 0-byte file: a hole in the source archive
                break
            time.sleep(2**i)  # 403/429/5xx or HTML error page: back off and retry
        else:
            return Fetched("error", last_status, fmt, url, attempts=attempts)
    if empty:
        return Fetched("source_empty", 200, empty[0], empty[1], attempts=attempts)
    return Fetched("not_published", 404, attempts=attempts)


def make_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)


# ---------------------------------------------------------------- parsing


def _read_csv(raw: bytes) -> pl.DataFrame:
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            raw = z.read(z.namelist()[0])
    df = pl.read_csv(io.BytesIO(raw), infer_schema=False, truncate_ragged_lines=True)
    df = df.rename({c: c.strip() for c in df.columns})
    keep = [c for c in df.columns if c and not c.startswith("_duplicated")]
    return df.select(keep).with_columns(pl.all().str.strip_chars())


def _col(df: pl.DataFrame, name: str, dtype: type[pl.DataType] | pl.DataType = pl.Utf8) -> pl.Expr:
    if name in df.columns:
        e = pl.col(name).replace("", None)
        return e.cast(dtype, strict=False) if dtype != pl.Utf8 else e
    return pl.lit(None, dtype=dtype)


_FO_TYPE = {"IDF": "FUTIDX", "STF": "FUTSTK", "IDO": "OPTIDX", "STO": "OPTSTK"}


def parse_cm(raw: bytes, fmt: str, d: date) -> pl.DataFrame:
    df = _read_csv(raw)
    f = pl.Float64
    if fmt == "udiff":
        cols = [
            _col(df, "TckrSymb").alias("symbol"),
            _col(df, "SctySrs").alias("series"),
            _col(df, "ISIN").alias("isin"),
            _col(df, "FinInstrmTp").alias("instrument_type"),
            _col(df, "OpnPric", f).alias("open"),
            _col(df, "HghPric", f).alias("high"),
            _col(df, "LwPric", f).alias("low"),
            _col(df, "ClsPric", f).alias("close"),
            _col(df, "LastPric", f).alias("last"),
            _col(df, "PrvsClsgPric", f).alias("prev_close"),
            _col(df, "TtlTradgVol", f).cast(pl.Int64).alias("volume"),
            _col(df, "TtlTrfVal", f).alias("turnover"),
            _col(df, "TtlNbOfTxsExctd", f).cast(pl.Int64).alias("trades"),
        ]
    else:
        cols = [
            _col(df, "SYMBOL").alias("symbol"),
            _col(df, "SERIES").alias("series"),
            _col(df, "ISIN").alias("isin"),
            pl.lit("STK").alias("instrument_type"),
            _col(df, "OPEN", f).alias("open"),
            _col(df, "HIGH", f).alias("high"),
            _col(df, "LOW", f).alias("low"),
            _col(df, "CLOSE", f).alias("close"),
            _col(df, "LAST", f).alias("last"),
            _col(df, "PREVCLOSE", f).alias("prev_close"),
            _col(df, "TOTTRDQTY", f).cast(pl.Int64).alias("volume"),
            _col(df, "TOTTRDVAL", f).alias("turnover"),
            _col(df, "TOTALTRADES", f).cast(pl.Int64).alias("trades"),
        ]
    out = df.select(cols).filter(pl.col("symbol").is_not_null())
    return out.with_columns(pl.lit(d).alias("date"), pl.lit(fmt).alias("source_format")).select(
        "date", *[c for c in out.columns], "source_format"
    )


def parse_fo(raw: bytes, fmt: str, d: date) -> pl.DataFrame:
    df = _read_csv(raw)
    f = pl.Float64
    if fmt == "udiff":
        cols = [
            _col(df, "FinInstrmTp").replace(_FO_TYPE).alias("instrument"),
            _col(df, "TckrSymb").alias("symbol"),
            _col(df, "XpryDt").str.strptime(pl.Date, "%Y-%m-%d", strict=False).alias("expiry"),
            _col(df, "StrkPric", f).alias("strike"),
            _col(df, "OptnTp").alias("option_type"),
            _col(df, "OpnPric", f).alias("open"),
            _col(df, "HghPric", f).alias("high"),
            _col(df, "LwPric", f).alias("low"),
            _col(df, "ClsPric", f).alias("close"),
            _col(df, "SttlmPric", f).alias("settle"),
            _col(df, "TtlTradgVol", f).cast(pl.Int64).alias("contracts"),
            _col(df, "TtlTrfVal", f).alias("turnover"),
            _col(df, "OpnIntrst", f).cast(pl.Int64).alias("oi"),
            _col(df, "ChngInOpnIntrst", f).cast(pl.Int64).alias("chg_oi"),
            _col(df, "UndrlygPric", f).alias("underlying_price"),
            _col(df, "NewBrdLotQty", f).cast(pl.Int64).alias("lot_size"),
            _col(df, "TtlNbOfTxsExctd", f).cast(pl.Int64).alias("trades"),
        ]
    else:
        cols = [
            _col(df, "INSTRUMENT").alias("instrument"),
            _col(df, "SYMBOL").alias("symbol"),
            _col(df, "EXPIRY_DT")
            .str.to_titlecase()
            .str.strptime(pl.Date, "%d-%b-%Y", strict=False)
            .alias("expiry"),
            _col(df, "STRIKE_PR", f).alias("strike"),
            _col(df, "OPTION_TYP").replace("XX", None).alias("option_type"),
            _col(df, "OPEN", f).alias("open"),
            _col(df, "HIGH", f).alias("high"),
            _col(df, "LOW", f).alias("low"),
            _col(df, "CLOSE", f).alias("close"),
            _col(df, "SETTLE_PR", f).alias("settle"),
            _col(df, "CONTRACTS", f).cast(pl.Int64).alias("contracts"),
            (_col(df, "VAL_INLAKH", f) * 1e5).alias("turnover"),
            _col(df, "OPEN_INT", f).cast(pl.Int64).alias("oi"),
            _col(df, "CHG_IN_OI", f).cast(pl.Int64).alias("chg_oi"),
            pl.lit(None, dtype=f).alias("underlying_price"),
            pl.lit(None, dtype=pl.Int64).alias("lot_size"),
            pl.lit(None, dtype=pl.Int64).alias("trades"),
        ]
    out = df.select(cols).filter(pl.col("symbol").is_not_null())
    # Futures have no strike: legacy files say 0, UDiFF leaves it empty. Normalize to null.
    out = out.with_columns(
        pl.when(pl.col("instrument").str.starts_with("FUT"))
        .then(None)
        .otherwise(pl.col("strike"))
        .alias("strike")
    )
    return out.with_columns(pl.lit(d).alias("date"), pl.lit(fmt).alias("source_format")).select(
        "date", *[c for c in out.columns], "source_format"
    )


def parse_mto(raw: bytes, d: date) -> pl.DataFrame:
    rows: list[tuple[str, str, int | None, int | None, float | None]] = []

    def num(s: str) -> float | None:
        try:
            return float(s)
        except ValueError:
            return None

    for line in raw.decode("latin-1").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 7 and parts[0] == "20":
            tq, dq, dp = num(parts[4]), num(parts[5]), num(parts[6])
            rows.append(
                (
                    parts[2],
                    parts[3],
                    int(tq) if tq is not None else None,
                    int(dq) if dq is not None else None,
                    dp,
                )
            )
    schema = {
        "symbol": pl.Utf8,
        "series": pl.Utf8,
        "traded_qty": pl.Int64,
        "deliverable_qty": pl.Int64,
        "deliverable_pct": pl.Float64,
    }
    df = pl.DataFrame(rows, schema=schema, orient="row")
    return df.with_columns(pl.lit(d).alias("date")).select("date", *schema)


def parse(kind: str, raw: bytes, fmt: str, d: date) -> pl.DataFrame:
    if kind == "cm":
        return parse_cm(raw, fmt, d)
    if kind == "fo":
        return parse_fo(raw, fmt, d)
    return parse_mto(raw, d)
