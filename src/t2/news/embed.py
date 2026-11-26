# pyright: reportMissingImports=false
"""Headline embeddings: every stock-tagged news title turned into a 384-number meaning vector.

The LightGBM champion only sees how much news a stock had and its average GDELT tone. These vectors carry what
the headline says (results, orders, downgrades, fraud, ...), for the neural model to learn from.

Model: BAAI/bge-small-en-v1.5 (33M parameters, MIT licence), unit-length vectors. Runs on GitHub Actions; the
sentence-transformers package is installed there only, like torch.

Output: news_emb/year=YYYY.parquet on the dataset repo, one row per article:
  gkg_id, published_at, tickers, emb (384 float16 values as bytes)

    python -m t2.news.embed --year 2024 --data data/hf --out reports/news_emb --publish
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import numpy as np
import polars as pl

from t2.data.hf_store import DATASET_REPO

MODEL = "BAAI/bge-small-en-v1.5"
DIM = 384
MIN_TITLE = 12


def articles(root: Path, year: int) -> pl.DataFrame:
    """Stock-tagged articles of a year with a usable title, one row per distinct (title, time)."""
    files = sorted((root / "news_gdelt" / f"year={year}").glob("*.parquet"))
    if not files:
        return pl.DataFrame(
            schema={"gkg_id": pl.Utf8, "published_at": pl.Datetime("us", "UTC"), "title": pl.Utf8,
                    "tickers": pl.List(pl.Utf8)}
        )  # fmt: skip
    return (
        pl.scan_parquet(files)
        .select(pl.col("gkg_id").cast(pl.Utf8), "published_at", "title", "tickers")
        .filter(pl.col("tickers").list.len() > 0, pl.col("title").str.len_chars() >= MIN_TITLE)
        .with_columns(pl.col("title").str.strip_chars())
        .unique(["title", "published_at"], keep="first", maintain_order=True)
        .sort("published_at")
        .collect()
    )


def to_frame(arts: pl.DataFrame, emb: np.ndarray) -> pl.DataFrame:
    e16 = np.ascontiguousarray(emb, dtype=np.float16)
    return arts.select("gkg_id", "published_at", "tickers").with_columns(
        pl.Series("emb", [r.tobytes() for r in e16], dtype=pl.Binary)
    )


def from_frame(df: pl.DataFrame) -> np.ndarray:
    """(N, DIM) float32 from the stored bytes."""
    if not df.height:
        return np.zeros((0, DIM), dtype=np.float32)
    return np.frombuffer(b"".join(df["emb"].to_list()), dtype=np.float16).reshape(-1, DIM).astype(np.float32)


def encode(titles: list[str], batch: int = 256) -> np.ndarray:
    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(os.cpu_count() or 4)
    model = SentenceTransformer(MODEL, device="cpu")
    model.max_seq_length = 64  # headlines are short
    return model.encode(titles, batch_size=batch, normalize_embeddings=True, show_progress_bar=False)


def fetch(dest: Path, year: int | None = None, table: str = "news_gdelt") -> Path:
    from huggingface_hub import snapshot_download

    pattern = f"{table}/year={year}/*" if year is not None and table == "news_gdelt" else f"{table}/*"
    snapshot_download(
        DATASET_REPO,
        repo_type="dataset",
        local_dir=dest,
        allow_patterns=[pattern],
        token=os.environ.get("HF_TOKEN"),
        max_workers=8,
    )
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--data", default="data/hf")
    ap.add_argument("--out", required=True)
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args(argv)
    root = fetch(Path(a.data), a.year)
    arts = articles(root, a.year)
    t0 = time.time()
    emb = encode(arts["title"].to_list()) if arts.height else np.zeros((0, DIM), dtype=np.float32)
    print(f"{a.year}: {arts.height:,} headlines embedded in {time.time() - t0:.0f}s", flush=True)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"year={a.year}.parquet"
    to_frame(arts, emb).write_parquet(path, compression="zstd")
    print(f"{path}: {path.stat().st_size / 1e6:.1f} MB", flush=True)
    if a.publish:
        from huggingface_hub import HfApi

        for attempt in range(4):  # parallel years can race on the repo's head commit
            try:
                HfApi(token=os.environ.get("HF_TOKEN")).upload_file(
                    path_or_fileobj=str(path),
                    path_in_repo=f"news_emb/year={a.year}.parquet",
                    repo_id=DATASET_REPO,
                    repo_type="dataset",
                    commit_message=f"news_emb: {a.year} ({arts.height} headlines)",
                )
                break
            except Exception as exc:
                if attempt == 3:
                    raise
                print(f"upload failed ({type(exc).__name__}), retrying", flush=True)
                time.sleep(20 * (attempt + 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
