"""Sequence data for the neural models: the feature panel as a dense (stock x day x feature) cube.

No deep-learning library here, so this part is unit tested in CI on its own.

- rows exist only while a stock is in the universe; missing days stay 0 and a `present` channel marks real rows
- features are scaled with robust statistics (median, IQR) fitted on the fold's training days only, then clipped
- labels are each day's cross-sectional rank of the target, centred on 0 (the same label as the LightGBM baseline)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

CLIP = 5.0


@dataclass
class Cube:
    dates: list[date]
    symbols: list[str]
    x: np.ndarray  # (S, D, F + 1) float16, last channel = present
    label: np.ndarray  # (D, S) float32, NaN where there is no target
    present: np.ndarray  # (D, S) bool: the stock is in the universe that day (can be scored)
    features: list[str]

    def day_index(self, d: date) -> int:
        return self.dates.index(d)


def build(panel: pl.DataFrame, features: list[str], target: str, start: date, end: date) -> Cube:
    """Dense cube of the panel between `start` and `end` (inclusive). Unscaled until `scale` is called."""
    p = panel.filter(pl.col("date").is_between(start, end))
    dates = sorted(p["date"].unique().to_list())
    symbols = sorted(p["symbol"].unique().to_list())
    di = {d: i for i, d in enumerate(dates)}
    si = {s: i for i, s in enumerate(symbols)}
    rows = np.array([di[d] for d in p["date"].to_list()], dtype=np.int64)
    cols = np.array([si[s] for s in p["symbol"].to_list()], dtype=np.int64)
    feats = p.select(features).to_numpy().astype(np.float32)
    x = np.zeros((len(symbols), len(dates), len(features) + 1), dtype=np.float32)
    x[cols, rows, :-1] = feats
    x[cols, rows, -1] = 1.0
    present = np.zeros((len(dates), len(symbols)), dtype=bool)
    present[rows, cols] = True
    lab = np.full((len(dates), len(symbols)), np.nan, dtype=np.float32)
    ranked = p.with_columns(
        pl.when(pl.col(target).is_not_null())
        .then((pl.col(target).rank() / pl.col(target).count()).over("date") - 0.5)
        .alias("_label")
    )["_label"].to_numpy()
    lab[rows, cols] = ranked.astype(np.float32)
    return Cube(dates, symbols, x, lab, present, list(features))


def scale(cube: Cube, fit_days: np.ndarray, max_rows: int = 300_000, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Robust-scale the features in place with statistics from `fit_days` only (no peeking at test data).

    Missing values become 0 (the median) after scaling. Returns (median, scale) per feature."""
    f = cube.x.shape[2] - 1
    mask = cube.present[fit_days]  # (Dfit, S)
    d_idx, s_idx = np.nonzero(mask)
    if len(d_idx) > max_rows:
        pick = np.random.default_rng(seed).choice(len(d_idx), max_rows, replace=False)
        d_idx, s_idx = d_idx[pick], s_idx[pick]
    sample = cube.x[s_idx, fit_days[d_idx], :f].astype(np.float32)
    med = np.nanmedian(sample, axis=0)
    q75, q25 = np.nanpercentile(sample, [75, 25], axis=0)
    sc = (q75 - q25) / 1.349
    sc = np.where(np.isfinite(sc) & (sc > 1e-8), sc, np.nanstd(sample, axis=0))
    sc = np.where(np.isfinite(sc) & (sc > 1e-8), sc, 1.0)
    med = np.where(np.isfinite(med), med, 0.0)
    real = cube.x[:, :, -1:] > 0
    z = (cube.x[:, :, :f] - med) / sc
    z = np.clip(np.nan_to_num(z, nan=0.0, posinf=CLIP, neginf=-CLIP), -CLIP, CLIP)
    cube.x[:, :, :f] = np.where(real, z, 0.0)
    cube.x = cube.x.astype(np.float16)
    return med.astype(np.float32), sc.astype(np.float32)


def windows(cube: Cube, day: int, lookback: int, symbols: np.ndarray) -> np.ndarray:
    """(n, lookback, F + 1) history ending at `day` for the given stock indices; days before the cube are 0."""
    lo = day - lookback + 1
    if lo >= 0:
        return cube.x[symbols, lo : day + 1].astype(np.float32)
    out = np.zeros((len(symbols), lookback, cube.x.shape[2]), dtype=np.float32)
    out[:, -lo:] = cube.x[symbols, : day + 1]
    return out


def split_days(cube: Cube, test_year: int, train_start: date, embargo: int, valid_days: int) -> dict[str, np.ndarray]:
    """Day indices: train | gap | validation | embargo | test. Gaps keep 5-day targets from overlapping."""
    idx = np.arange(len(cube.dates))
    years = np.array([d.year for d in cube.dates])
    test = idx[years == test_year]
    if not len(test):
        return {"train": idx[:0], "valid": idx[:0], "test": test}
    after_start = np.array([d >= train_start for d in cube.dates])
    before = idx[(idx < test[0] - embargo) & after_start]
    valid = before[-valid_days:] if len(before) > valid_days * 3 else before[:0]
    train = before[: -(valid_days + embargo)] if len(valid) else before
    return {"train": train, "valid": valid, "test": test}


def rank_ic(score: np.ndarray, label: np.ndarray) -> float:
    """Spearman correlation of one day's scores with its labels (labels are already ranks)."""
    ok = np.isfinite(score) & np.isfinite(label)
    if ok.sum() < 10:
        return float("nan")
    a = np.argsort(np.argsort(score[ok])).astype(np.float64)
    b = np.argsort(np.argsort(label[ok])).astype(np.float64)
    return float(np.corrcoef(a, b)[0, 1])


def pca_fit(x: np.ndarray, k: int, max_rows: int = 200_000, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """(mean, components (k, dim)) of the rows of x; components are sign-fixed so refits agree."""
    if len(x) > max_rows:
        x = x[np.random.default_rng(seed).choice(len(x), max_rows, replace=False)]
    mean = x.mean(axis=0)
    _, _, vt = np.linalg.svd(x - mean, full_matrices=False)
    comp = vt[:k]
    comp *= np.where(comp[np.arange(len(comp)), np.abs(comp).argmax(axis=1)] < 0, -1.0, 1.0)[:, None]
    return mean.astype(np.float32), comp.astype(np.float32)


def news_columns(keys: pl.DataFrame, vecs: np.ndarray, fit_before: date, k: int) -> tuple[pl.DataFrame, list[str]]:
    """Headline vectors per (date, symbol) compressed to k numbers, with the compression fitted only on rows
    dated before `fit_before` (the fold's training period: no peeking at the test years)."""
    names = [f"news_e{i}" for i in range(k)]
    fit = (keys["date"] < fit_before).to_numpy()
    if fit.sum() < k * 10:
        raise ValueError(f"only {int(fit.sum())} news rows before {fit_before}: too few to fit {k} components")
    mean, comp = pca_fit(vecs[fit], k)
    z = (vecs - mean) @ comp.T
    cols = keys.select("date", "symbol").with_columns(
        [pl.Series(n, z[:, i].astype(np.float32)) for i, n in enumerate(names)]
    )
    return cols, names
