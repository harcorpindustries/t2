"""Historical news from GDELT 2.1 GKG (one file per 15 minutes since 2015-02-18).

Keeps Indian financial publishers, plus global wires when the article mentions India. Stores per article:
time, publisher, URL, title (or a headline derived from the URL slug before titles existed), GDELT tone,
themes, organizations, persons and NSE symbols tagged from the title and organizations.

  backfill --month YYYY-MM   fetch every 15-minute file of a month (resumes; only non-ok files refetched)

Output: news_gdelt/year=YYYY/YYYY-MM.parquet and ledger _ledger/gdelt/YYYY-MM.parquet (one row per file).
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import tempfile
import zipfile
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
import polars as pl

from t2.data import hf_store

BASE = "https://data.gdeltproject.org/gdeltv2"
FIRST = datetime(2015, 2, 18, 23, 0, tzinfo=UTC)
FINANCE_DOMAINS = (
    "economictimes.indiatimes.com",
    "livemint.com",
    "business-standard.com",
    "thehindubusinessline.com",
    "moneycontrol.com",
    "financialexpress.com",
    "ndtvprofit.com",
    "bloombergquint.com",
    "businesstoday.in",
    "cnbctv18.com",
    "zeebiz.com",
)
WIRE_DOMAINS = ("reuters.com", "bloomberg.com")
WORKERS = 8

ARTICLE_SCHEMA = {
    "gkg_id": pl.Utf8,
    "published_at": pl.Datetime("us", "UTC"),
    "domain": pl.Utf8,
    "url": pl.Utf8,
    "title": pl.Utf8,
    "title_source": pl.Utf8,  # page | url_slug
    "tone": pl.Float64,
    "positive": pl.Float64,
    "negative": pl.Float64,
    "polarity": pl.Float64,
    "word_count": pl.Int64,
    "themes": pl.List(pl.Utf8),
    "organizations": pl.List(pl.Utf8),
    "persons": pl.List(pl.Utf8),
}
LEDGER_SCHEMA = {
    "file_ts": pl.Utf8,
    "status": pl.Utf8,
    "http_status": pl.Int64,
    "rows_total": pl.Int64,
    "rows_kept": pl.Int64,
}


def domain_kind(domain: str) -> str | None:
    d = domain.lower()
    if any(d == x or d.endswith("." + x) for x in FINANCE_DOMAINS):
        return "finance"
    if any(d == x or d.endswith("." + x) for x in WIRE_DOMAINS):
        return "wire"
    return None


_SLUG_ID = re.compile(r"(-?\d{5,}|\.cms|\.html?|\.ece|\.php)$")


def slug_title(url: str) -> str | None:
    """Headline from the URL slug: the longest hyphenated path segment."""
    parts = [unquote(p) for p in urlsplit(url).path.split("/") if "-" in p]
    if not parts:
        return None
    seg = _SLUG_ID.sub("", max(parts, key=len))
    seg = _SLUG_ID.sub("", seg)
    words = [w for w in seg.split("-") if w]
    while words and any(c.isdigit() for c in words[-1]):
        words.pop()  # trailing article ids like 116061500123_1
    return " ".join(words).capitalize() if len(words) >= 3 else None


def _floats(s: str, n: int) -> list[float | None]:
    vals = s.split(",")
    out: list[float | None] = []
    for i in range(n):
        try:
            out.append(float(vals[i]))
        except (IndexError, ValueError):
            out.append(None)
    return out


def _names(s: str) -> list[str]:
    return sorted({p.split(",")[0].strip() for p in s.split(";") if p.strip()})


def _india_economy(x: list[str]) -> bool:
    """Global wires: keep only stories that mention India and carry an economic theme."""
    about_india = "#IN#" in x[9] or "#IN#" in x[10]
    economic = any(t.startswith(("ECON_", "EPU_")) for t in x[7].split(";"))
    return about_india and economic


_TITLE = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.S)


def parse_rows(lines: str | Iterable[str]) -> tuple[list[dict[str, object]], int]:
    if isinstance(lines, str):
        lines = lines.splitlines()
    kept: list[dict[str, object]] = []
    total = 0
    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        total += 1
        head = line.split("\t", 4)
        if len(head) < 5:
            continue
        kind = domain_kind(head[3])
        if kind is None:
            continue
        x = line.split("\t")
        if len(x) < 27:
            continue
        if kind == "wire" and not _india_economy(x):
            continue
        m = _TITLE.search(x[26])
        title = m.group(1).strip() if m else None
        tone, pos, neg, pol, _, _, wc = _floats(x[15], 7)
        kept.append(
            {
                "gkg_id": x[0],
                "published_at": datetime.strptime(x[1], "%Y%m%d%H%M%S").replace(tzinfo=UTC),
                "domain": x[3],
                "url": x[4],
                "title": title or slug_title(x[4]),
                "title_source": "page" if title else "url_slug",
                "tone": tone,
                "positive": pos,
                "negative": neg,
                "polarity": pol,
                "word_count": int(wc) if wc is not None else None,
                "themes": _names(x[8] or x[7]),
                "organizations": _names(x[13]),
                "persons": _names(x[11]),
            }
        )
    return kept, total


def fetch_file(client: httpx.Client, ts: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    url = f"{BASE}/{ts}.gkg.csv.zip"
    status, code, rows, total = "error", -1, [], 0
    for _ in range(3):
        try:
            r = client.get(url)
            code = r.status_code
            if r.status_code == 404:
                status = "not_published"
                break
            if r.status_code == 200:
                # stream the member line by line: 2015-16 files unzip to 40 MB+, some far larger
                with zipfile.ZipFile(io.BytesIO(r.content)) as z, z.open(z.namelist()[0]) as fh:
                    rows, total = parse_rows(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"))
                status = "ok"
                break
        except (httpx.HTTPError, zipfile.BadZipFile) as exc:
            print(f"{ts}: {exc}", file=sys.stderr)
    ledger = {"file_ts": ts, "status": status, "http_status": code, "rows_total": total, "rows_kept": len(rows)}
    return ledger, rows


def month_files(month: str, now: datetime | None = None) -> list[str]:
    start = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
    end = (start + timedelta(days=32)).replace(day=1)
    stop = min(end, (now or datetime.now(UTC)) - timedelta(minutes=30))
    t, out = max(start, FIRST), []
    while t < stop:
        out.append(t.strftime("%Y%m%d%H%M%S"))
        t += timedelta(minutes=15)
    return out


def tag_symbols(df: pl.DataFrame) -> pl.DataFrame:
    from t2.news import tickers

    try:
        m = tickers._matcher()
    except httpx.HTTPError:
        return df.with_columns(pl.lit(None, pl.List(pl.Utf8)).alias("tickers"))
    texts = [
        f"{t or ''}\n{'; '.join(o or [])}"
        for t, o in zip(df["title"].to_list(), df["organizations"].to_list(), strict=True)
    ]
    return df.with_columns(pl.Series("tickers", [tickers.tag(t, m) for t in texts], dtype=pl.List(pl.Utf8)))


CHUNK_FILES = 576  # 6 days of 15-minute files: progress is saved to HF after each chunk


def cmd_backfill(month: str) -> None:
    year = month[:4]
    data_rel, ledger_rel = f"news_gdelt/year={year}/{month}.parquet", f"_ledger/gdelt/{month}.parquet"
    with tempfile.TemporaryDirectory() as tmp:
        dl = Path(tmp) / "dl"
        old_ledger_p, old_data_p = hf_store.download(ledger_rel, dl), hf_store.download(data_rel, dl)
        ledger = pl.read_parquet(old_ledger_p) if old_ledger_p else pl.DataFrame(schema=LEDGER_SCHEMA)
        data = (
            pl.read_parquet(old_data_p)
            if old_data_p
            else pl.DataFrame(schema={**ARTICLE_SCHEMA, "tickers": pl.List(pl.Utf8)})
        )
        done = set(ledger.filter(pl.col("status").is_in(["ok", "not_published"]))["file_ts"].to_list())
        ledger = ledger.filter(pl.col("file_ts").is_in(done))
        todo = [ts for ts in month_files(month) if ts not in done]
        print(f"gdelt {month}: {len(todo)} files to fetch ({len(done)} already done)", flush=True)
        for i in range(0, len(todo), CHUNK_FILES):
            chunk = todo[i : i + CHUNK_FILES]
            ledgers, articles = [], []
            with httpx.Client(timeout=120, follow_redirects=True) as client, ThreadPoolExecutor(WORKERS) as pool:
                for led, rows in pool.map(lambda ts: fetch_file(client, ts), chunk):
                    ledgers.append(led)
                    articles.extend(rows)
            new_ledger = pl.DataFrame(ledgers, schema=LEDGER_SCHEMA)
            new_data = tag_symbols(pl.DataFrame(articles, schema=ARTICLE_SCHEMA))
            ledger = pl.concat([ledger, new_ledger]).unique("file_ts", keep="last").sort("file_ts")
            data = pl.concat([data, new_data], how="diagonal_relaxed").unique("gkg_id").sort("published_at")
            stage = Path(tmp) / f"stage{i}"
            (stage / Path(data_rel).parent).mkdir(parents=True)
            (stage / Path(ledger_rel).parent).mkdir(parents=True)
            data.write_parquet(stage / data_rel, compression="zstd")
            ledger.write_parquet(stage / ledger_rel)
            counts = dict(new_ledger.group_by("status").len().iter_rows())
            print(
                f"{month} {chunk[0]}..{chunk[-1]}: {counts}, +{new_data.height} articles, {data.height} total",
                flush=True,
            )
            hf_store.upload_folder(stage, f"gdelt {month}: {chunk[0]}..{chunk[-1]}, {new_data.height} articles")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--month", required=True)
    a = ap.parse_args(argv)
    cmd_backfill(a.month)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
