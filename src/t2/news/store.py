"""Local SQLite buffer for crawled news. Every item is stored once (keyed by URL hash)."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("T2_NEWS_DB", "/opt/t2/data/news.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  category TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT,
  summary TEXT,
  published_at TEXT,
  first_seen_at TEXT NOT NULL,
  text TEXT,
  text_status TEXT NOT NULL DEFAULT 'pending',
  tickers TEXT,
  exported_at TEXT
);
CREATE INDEX IF NOT EXISTS items_text_status ON items(text_status);
CREATE INDEX IF NOT EXISTS items_exported ON items(exported_at);
CREATE TABLE IF NOT EXISTS feed_polls (
  source TEXT NOT NULL,
  polled_at TEXT NOT NULL,
  http_status INTEGER,
  items_seen INTEGER,
  items_new INTEGER,
  error TEXT,
  exported_at TEXT
);
"""


def item_id(url: str) -> str:
    return hashlib.sha256(url.strip().encode()).hexdigest()[:32]


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con
