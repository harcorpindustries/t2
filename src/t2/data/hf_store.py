"""Thin helpers around the Hugging Face dataset repo."""

from __future__ import annotations

import os
import time
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.errors import EntryNotFoundError

DATASET_REPO = os.environ.get("HF_DATASET_REPO", "harcorp/t2-market-data")


def api() -> HfApi:
    return HfApi(token=os.environ.get("HF_TOKEN"))


def download(path_in_repo: str, dest_dir: Path) -> Path | None:
    """Download one file from the dataset, or None if it does not exist yet."""
    try:
        return Path(
            hf_hub_download(
                DATASET_REPO,
                path_in_repo,
                repo_type="dataset",
                local_dir=dest_dir,
                token=os.environ.get("HF_TOKEN"),
            )
        )
    except EntryNotFoundError:
        return None


def upload_folder(folder: Path, message: str, retries: int = 5) -> None:
    """Commit everything under `folder` (laid out like the repo) in one commit, with retries."""
    for i in range(retries):
        try:
            api().upload_folder(
                repo_id=DATASET_REPO, repo_type="dataset", folder_path=folder, commit_message=message
            )
            return
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(10 * (i + 1))


FREE_PRIVATE_GB = 100.0
WARN_GB = 70.0


def dataset_size_gb() -> float:
    info = api().dataset_info(DATASET_REPO, files_metadata=True)
    return sum((s.size or 0) for s in (info.siblings or [])) / 1e9
