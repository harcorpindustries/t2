"""News crawler: poll feeds, extract article text, tag tickers, export to the HF dataset.

Commands (run on the live server by systemd timers):
  poll     poll every feed once, store new items, extract text for pending articles
  export   upload items and feed-poll stats not yet exported to HF (news/ and _ledger/news/)
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
import time
import urllib.robotparser
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

import feedparser
import httpx
import polars as pl
import trafilatura

from t2.data import hf_store
from t2.data.nse_archive import USER_AGENT
from t2.news import tickers
from t2.news.sources import FEEDS, Feed
from t2.news.store import connect, item_id

TEXT_BATCH = 150  # articles fetched per poll run
DOMAIN_DELAY = 1.0  # seconds between requests to the same site


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _iso(entry: feedparser.FeedParserDict) -> str | None:
    for key in ("published", "updated", "pubDate"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            return parsedate_to_datetime(str(raw)).astimezone(UTC).isoformat(timespec="seconds")
        except (TypeError, ValueError):
            for fmt in ("%d-%b-%Y %H:%M:%S", "%d %b %Y %H:%M:%S"):
                try:  # NSE/SEBI style, Indian time
                    dt = datetime.strptime(str(raw).split(" +")[0], fmt)
                    return dt.replace(tzinfo=_IST).astimezone(UTC).isoformat(timespec="seconds")
                except ValueError:
                    continue
            return str(raw)
    return None


try:
    from zoneinfo import ZoneInfo

    _IST = ZoneInfo("Asia/Kolkata")
except Exception:  # pragma: no cover
    _IST = UTC  # type: ignore[assignment]


def poll_feed(client: httpx.Client, con: sqlite3.Connection, feed: Feed) -> None:
    status, seen, new, error = None, 0, 0, None
    try:
        r = client.get(feed.url)
        status = r.status_code
        r.raise_for_status()
        parsed = feedparser.parse(r.content)
        for e in parsed.entries:
            url = str(e.get("link") or e.get("id") or "").strip()
            if not url:
                continue
            seen += 1
            title, summary = str(e.get("title", "")).strip(), str(e.get("summary", "")).strip()
            cur = con.execute(
                "INSERT OR IGNORE INTO items (id, source, category, url, title, summary, published_at,"
                " first_seen_at, text_status) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    item_id(url),
                    feed.name,
                    feed.category,
                    url,
                    title,
                    summary,
                    _iso(e),
                    now(),
                    "pending" if feed.fetch_text else "skipped",
                ),
            )
            new += cur.rowcount
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:500]
    con.execute(
        "INSERT INTO feed_polls (source, polled_at, http_status, items_seen, items_new, error) VALUES (?,?,?,?,?,?)",
        (feed.name, now(), status, seen, new, error),
    )
    con.commit()


_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def allowed(client: httpx.Client, url: str) -> bool:
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in _robots:
        rp: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
        try:
            r = client.get(base + "/robots.txt")
            if r.status_code == 200:
                rp.parse(r.text.splitlines())  # type: ignore[union-attr]
            else:
                rp = None  # no robots.txt: allowed
        except httpx.HTTPError:
            rp = None
        _robots[base] = rp
    rp = _robots[base]
    return True if rp is None else rp.can_fetch(USER_AGENT, url)


def extract_pending(client: httpx.Client, con: sqlite3.Connection, limit: int = TEXT_BATCH) -> None:
    rows = con.execute(
        "SELECT id, url FROM items WHERE text_status='pending' ORDER BY first_seen_at LIMIT ?", (limit,)
    ).fetchall()
    last_hit: dict[str, float] = {}
    for row in rows:
        host = urlsplit(row["url"]).netloc
        wait = DOMAIN_DELAY - (time.monotonic() - last_hit.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        status, text = "error", None
        try:
            if not allowed(client, row["url"]):
                status = "robots_disallowed"
            else:
                r = client.get(row["url"])
                last_hit[host] = time.monotonic()
                if r.status_code == 200:
                    text = trafilatura.extract(r.text, include_comments=False, include_tables=True)
                    status = "ok" if text else "no_text"
                else:
                    status = f"http_{r.status_code}"
        except Exception as exc:
            print(f"extract {row['url']}: {exc}", file=sys.stderr)
        con.execute("UPDATE items SET text=?, text_status=? WHERE id=?", (text, status, row["id"]))
        con.commit()


def tag_untagged(con: sqlite3.Connection) -> None:
    rows = con.execute(
        "SELECT id, title, summary, text FROM items WHERE tickers IS NULL AND text_status != 'pending'"
    ).fetchall()
    for row in rows:
        found = tickers.tag(" \n".join(x for x in (row["title"], row["summary"], row["text"]) if x))
        con.execute("UPDATE items SET tickers=? WHERE id=?", (",".join(found), row["id"]))
    con.commit()


def cmd_poll() -> None:
    con = connect()
    started = now()
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as client:
        for feed in FEEDS:
            poll_feed(client, con, feed)
        extract_pending(client, con)
    try:
        tag_untagged(con)
    except httpx.HTTPError as exc:  # equity list unavailable: tag on a later run
        print(f"tagging skipped: {exc}", file=sys.stderr)
    failed = con.execute(
        "SELECT source, error FROM feed_polls WHERE polled_at >= ? AND error IS NOT NULL", (started,)
    ).fetchall()
    pending = con.execute("SELECT COUNT(*) FROM items WHERE text_status='pending'").fetchone()[0]
    print(f"poll done: {len(FEEDS)} feeds, {len(failed)} failed, {pending} articles waiting for text")
    for row in failed:
        print(f"  feed error {row['source']}: {row['error']}", file=sys.stderr)


def cmd_export() -> None:
    con = connect()
    stamp = now()
    item_cols = "id, source, category, url, title, summary, published_at, first_seen_at, text, text_status, tickers"
    item_rows = con.execute(
        f"SELECT {item_cols} FROM items WHERE exported_at IS NULL AND text_status != 'pending'"
    ).fetchall()
    items = pl.DataFrame(
        [tuple(r) for r in item_rows],
        schema=dict.fromkeys(item_cols.replace(" ", "").split(","), pl.Utf8),
        orient="row",
    )
    poll_schema = {
        "_rid": pl.Int64,
        "source": pl.Utf8,
        "polled_at": pl.Utf8,
        "http_status": pl.Int64,
        "items_seen": pl.Int64,
        "items_new": pl.Int64,
        "error": pl.Utf8,
    }
    poll_rows = con.execute(
        "SELECT rowid, source, polled_at, http_status, items_seen, items_new, error"
        " FROM feed_polls WHERE exported_at IS NULL"
    ).fetchall()
    polls = pl.DataFrame([tuple(r) for r in poll_rows], schema=poll_schema, orient="row")
    if items.is_empty() and polls.is_empty():
        print("export: nothing new")
        return
    run = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        if not items.is_empty():
            items = items.with_columns(
                pl.col("tickers").str.split(",").list.eval(pl.element().filter(pl.element() != "")),
                pl.col("first_seen_at").str.slice(0, 10).alias("day"),
            )
            for (day,), part in items.group_by("day"):
                out = stage / "news" / f"date={day}"
                out.mkdir(parents=True, exist_ok=True)
                part.drop("day").write_parquet(out / f"{run}.parquet", compression="zstd")
        if not polls.is_empty():
            out = stage / "_ledger" / "news" / "feed_polls"
            out.mkdir(parents=True, exist_ok=True)
            polls.drop("_rid").write_parquet(out / f"{run}.parquet", compression="zstd")
        hf_store.upload_folder(stage, f"news export {run}: {items.height} items, {polls.height} polls")
    with con:
        con.executemany("UPDATE items SET exported_at=? WHERE id=?", [(stamp, i) for i in items["id"].to_list()])
        rids = [(stamp, r) for r in polls["_rid"].to_list()] if not polls.is_empty() else []
        con.executemany("UPDATE feed_polls SET exported_at=? WHERE rowid=?", rids)
    print(f"export: {items.height} items, {polls.height} feed polls")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["poll", "export"])
    a = ap.parse_args(argv)
    cmd_poll() if a.cmd == "poll" else cmd_export()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
