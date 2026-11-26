# pyright: reportMissingImports=false, reportAttributeAccessIssue=false
"""Neural challenger: a selective state-space (Mamba-style) encoder per stock + attention across stocks.

Same recipe and same tests as the LightGBM champion (5-day rank target, all liquid stocks, base + F&O + news
inputs, 6 training years, 10-session embargo, every year scored on data the model never saw), so the two compare
like for like. Runs on GitHub Actions CPUs (workflow: neural); torch is installed there, not on the server.

Inputs per stock and day: the champion's 46 features plus, since step 2, what its headlines say: each headline's
384-number vector (t2.news.embed) averaged per session and compressed to `news_dims` numbers, with the compression
fitted only on years before the test year. LightGBM never sees the headline text.

Architecture (about 1M parameters at the defaults):
  each stock's last `lookback` days (46 + news inputs + a present flag) -> linear -> `layers` x [RMSNorm -> Mamba block,
  RMSNorm -> SwiGLU] -> last state -> RMSNorm -> attention across all stocks that day -> SwiGLU -> score
Training: each step samples trading days, scores a random subset of that day's stocks and maximises the
correlation of score and the day's target rank (directly the rank-IC the champion is judged on). The best
checkpoint on a held-out validation window (before the embargo) is kept.

Long runs are split over up to three chained jobs (GitHub stops a job at 6 hours): --budget-min stops training and
saves a checkpoint, --resume continues it, --final finishes with the best weights whatever happens.
The comparison also scores rank-averaged blends of the two models.

    python -m t2.models.neural fold --year 2024 --out reports/neural/2024
    python -m t2.models.neural compare --folds reports/neural --out reports/compare
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import torch
import torch.nn.functional as F
from torch import nn

from t2.models import seqdata
from t2.models.baseline import Config, evaluate, features, load_panels, walk_forward

RECIPE = Config(target="y5", train_years=6, universe="all", train_universe="all", extras=("fno", "news"), top_k=10)


@dataclass
class NNConfig:
    d_model: int = 128
    layers: int = 3
    d_state: int = 8
    expand: int = 2
    heads: int = 4
    lookback: int = 60
    dropout: float = 0.1
    steps: int = 10000
    news_dims: int = 32  # headline vectors compressed to this many inputs (0 = off)
    batch_stocks: int = 384
    days_per_step: int = 2
    lr: float = 1e-3
    weight_decay: float = 0.01
    warmup: int = 200
    valid_days: int = 120
    eval_every: int = 250
    seed: int = 0


# ----- model -----
class RMSNorm(nn.Module):
    def __init__(self, d: int, eps: float = 1e-6):
        super().__init__()
        self.w = nn.Parameter(torch.ones(d))
        self.eps = eps

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps) * self.w


class SwiGLU(nn.Module):
    def __init__(self, d: int, hidden: int, dropout: float):
        super().__init__()
        self.w1, self.w3 = nn.Linear(d, hidden, bias=False), nn.Linear(d, hidden, bias=False)
        self.w2 = nn.Linear(hidden, d, bias=False)
        self.drop = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.drop(self.w2(F.silu(self.w1(x)) * self.w3(x)))


class Mamba(nn.Module):
    """Selective state-space block (Mamba-1 style) in plain PyTorch: input-dependent step size, B and C,
    diagonal A, causal depthwise convolution and a SiLU gate. The scan is a short loop over the lookback."""

    def __init__(self, d: int, d_state: int, expand: int, conv: int = 4):
        super().__init__()
        di = expand * d
        self.di, self.ds, self.dt_rank = di, d_state, math.ceil(d / 16)
        self.in_proj = nn.Linear(d, 2 * di, bias=False)
        self.conv = nn.Conv1d(di, di, conv, groups=di, padding=conv - 1)
        self.x_proj = nn.Linear(di, self.dt_rank + 2 * d_state, bias=False)
        self.dt_proj = nn.Linear(self.dt_rank, di)
        dt = torch.exp(torch.rand(di) * (math.log(0.1) - math.log(0.001)) + math.log(0.001))
        with torch.no_grad():
            self.dt_proj.bias.copy_(dt + torch.log(-torch.expm1(-dt)))  # softplus^-1: steps start in [0.001, 0.1]
        self.A_log = nn.Parameter(torch.log(torch.arange(1, d_state + 1, dtype=torch.float32)).repeat(di, 1))
        self.D = nn.Parameter(torch.ones(di))
        self.out_proj = nn.Linear(di, d, bias=False)

    def forward(self, u: torch.Tensor) -> torch.Tensor:  # (B, L, d)
        b, length, _ = u.shape
        x, z = self.in_proj(u).chunk(2, dim=-1)
        x = F.silu(self.conv(x.transpose(1, 2))[..., :length].transpose(1, 2))
        dt, bm, cm = self.x_proj(x).split([self.dt_rank, self.ds, self.ds], dim=-1)
        dt = F.softplus(self.dt_proj(dt))  # (B, L, di)
        a = -torch.exp(self.A_log)  # (di, ds)
        h = u.new_zeros(b, self.di, self.ds)
        ys = []
        for t in range(length):
            da = torch.exp(dt[:, t, :, None] * a)
            h = da * h + (dt[:, t, :, None] * bm[:, t, None, :]) * x[:, t, :, None]
            ys.append((h * cm[:, t, None, :]).sum(-1))
        y = torch.stack(ys, dim=1) + x * self.D
        return self.out_proj(y * F.silu(z))


class T2Net(nn.Module):
    def __init__(self, n_in: int, c: NNConfig):
        super().__init__()
        d = c.d_model
        self.inp = nn.Linear(n_in, d)
        self.blocks = nn.ModuleList()
        for _ in range(c.layers):
            self.blocks.append(
                nn.ModuleList(
                    [RMSNorm(d), Mamba(d, c.d_state, c.expand), RMSNorm(d), SwiGLU(d, int(d * 8 / 3), c.dropout)]
                )
            )
        self.norm = RMSNorm(d)
        self.mix_norm = RMSNorm(d)
        self.mix = nn.MultiheadAttention(d, c.heads, dropout=c.dropout, batch_first=True)
        self.ff_norm = RMSNorm(d)
        self.ff = SwiGLU(d, int(d * 8 / 3), c.dropout)
        self.head = nn.Linear(d, 1)
        self.drop = nn.Dropout(c.dropout)

    def encode(self, x: torch.Tensor) -> torch.Tensor:
        """(N, L, n_in) -> (N, d): each stock's own history."""
        h = self.inp(x)
        for n1, mamba, n2, ff in self.blocks:  # type: ignore[misc]
            h = h + self.drop(mamba(n1(h)))
            h = h + ff(n2(h))
        return self.norm(h[:, -1])

    def score(self, h: torch.Tensor) -> torch.Tensor:
        """(N, d) for one day's stocks -> (N,) scores, each stock attending to all the others."""
        q = self.mix_norm(h).unsqueeze(0)
        h = h + self.mix(q, q, q, need_weights=False)[0].squeeze(0)
        h = h + self.ff(self.ff_norm(h))
        return self.head(h).squeeze(-1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.score(self.encode(x))


def n_params(m: nn.Module) -> int:
    return sum(p.numel() for p in m.parameters())


def corr_loss(score: torch.Tensor, label: torch.Tensor) -> torch.Tensor:
    s, y = score - score.mean(), label - label.mean()
    return -(s * y).sum() / (s.norm() * y.norm() + 1e-8)


# ----- training -----
@torch.no_grad()
def predict_day(
    model: T2Net, cube: seqdata.Cube, day: int, lookback: int, chunk: int = 1024
) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    idx = np.nonzero(cube.present[day])[0]
    if not len(idx):
        return idx, np.zeros(0, dtype=np.float32)
    hs = [
        model.encode(torch.from_numpy(seqdata.windows(cube, day, lookback, idx[i : i + chunk])))
        for i in range(0, len(idx), chunk)
    ]
    return idx, model.score(torch.cat(hs)).numpy()


def valid_ic(model: T2Net, cube: seqdata.Cube, days: np.ndarray, lookback: int) -> float:
    ics = []
    for d in days:
        idx, s = predict_day(model, cube, int(d), lookback)
        ic = seqdata.rank_ic(s, cube.label[d, idx])
        if math.isfinite(ic):
            ics.append(ic)
    return float(np.mean(ics)) if ics else float("nan")


def train_fold(
    cube: seqdata.Cube,
    days: dict[str, np.ndarray],
    c: NNConfig,
    resume: dict | None = None,
    budget_s: float | None = None,
) -> tuple[T2Net, dict, dict | None]:
    """Train, keeping the checkpoint with the best validation IC.

    GitHub jobs stop at 6 hours, so long runs are split: with `budget_s`, training stops when the time is up and
    the third value is a checkpoint (`resume` continues it exactly where it stopped). It is None when finished.
    The returned model always carries the best weights seen so far."""
    torch.manual_seed(c.seed)
    rng = np.random.default_rng(c.seed)
    model = T2Net(cube.x.shape[2], c)
    opt = torch.optim.AdamW(model.parameters(), lr=c.lr, weight_decay=c.weight_decay)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / c.warmup) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / c.steps)))
    )
    labelled = np.isfinite(cube.label) & cube.present
    train_days = np.array([d for d in days["train"] if labelled[d].sum() >= 50])
    valid_days = days["valid"][::3]
    best_ic, best_state, history, first, spent = -math.inf, None, [], 1, 0.0
    if resume:
        model.load_state_dict(resume["model"])
        opt.load_state_dict(resume["opt"])
        sched.load_state_dict(resume["sched"])
        torch.set_rng_state(resume["torch_rng"])
        rng.bit_generator.state = resume["meta"]["rng"]
        best_state = resume["best_state"] or None
        best_ic, history = resume["meta"]["best_ic"], resume["meta"]["history"]
        first, spent = resume["meta"]["step"] + 1, resume["meta"]["secs"]
    t0 = time.time()
    step, ckpt = first - 1, None
    for step in range(first, c.steps + 1):
        model.train()
        opt.zero_grad()
        total = 0.0
        for _ in range(c.days_per_step):
            d = int(rng.choice(train_days))
            ok = np.nonzero(labelled[d])[0]
            if len(ok) > c.batch_stocks:
                ok = rng.choice(ok, c.batch_stocks, replace=False)
            xb = torch.from_numpy(seqdata.windows(cube, d, c.lookback, ok))
            loss = corr_loss(model(xb), torch.from_numpy(cube.label[d, ok])) / c.days_per_step
            loss.backward()
            total += float(loss)
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        sched.step()
        if step % c.eval_every == 0 or step == c.steps:
            ic = valid_ic(model, cube, valid_days, c.lookback) if len(valid_days) else -total
            history.append(
                {"step": step, "train_corr": -total, "valid_ic": ic, "secs": round(spent + time.time() - t0)}
            )
            print(json.dumps(history[-1]), flush=True)
            if ic > best_ic:
                best_ic, best_state = ic, {k: v.detach().clone() for k, v in model.state_dict().items()}
        if budget_s is not None and time.time() - t0 > budget_s and step < c.steps:
            ckpt = {
                "model": {k: v.detach().clone() for k, v in model.state_dict().items()},
                "opt": opt.state_dict(),
                "sched": sched.state_dict(),
                "torch_rng": torch.get_rng_state(),
                "best_state": best_state or {},
                "meta": {"step": step, "best_ic": best_ic, "history": history, "rng": rng.bit_generator.state,
                         "secs": round(spent + time.time() - t0)},
            }  # fmt: skip
            print(f"time budget reached at step {step}/{c.steps}", flush=True)
            break
    if best_state is not None:
        model.load_state_dict(best_state)
    return (
        model,
        {
            "best_valid_ic": best_ic,
            "history": history,
            "steps_done": step,
            "train_days": len(train_days),
            "params": n_params(model),
        },
        ckpt,
    )


def save_ckpt(ckpt: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    torch.save({k: v for k, v in ckpt.items() if k != "meta"}, out / "ckpt.pt")
    (out / "ckpt.json").write_text(json.dumps(ckpt["meta"]))


def load_ckpt(folder: Path) -> dict | None:
    if not (folder / "ckpt.pt").exists():
        return None
    ck = torch.load(folder / "ckpt.pt", weights_only=True)
    ck["meta"] = json.loads((folder / "ckpt.json").read_text())
    return ck


def load_news_vectors(root: Path, sessions: list, offline: bool) -> tuple[pl.DataFrame, np.ndarray]:
    from t2.features import extra
    from t2.news import embed

    if not offline:
        embed.fetch(root, table="news_emb")
    files = sorted((root / "news_emb").glob("*.parquet"))
    if not files:
        raise SystemExit("news_emb is not on the dataset yet: run the news-embed workflow first")
    df = pl.concat([pl.read_parquet(f) for f in files])
    keys, vecs = extra.news_emb_by_session(df, embed.from_frame(df), sessions)
    print(f"news vectors: {df.height:,} headlines -> {keys.height:,} stock-days", flush=True)
    return keys, vecs


# ----- CLI: one walk-forward year -----
def cmd_fold(a: argparse.Namespace) -> None:
    out = Path(a.out)
    prev = Path(a.resume) if a.resume else None
    if prev and (prev / "fold.json").exists():  # an earlier job already finished this year
        shutil.copytree(prev, out, dirs_exist_ok=True)
        print(f"{a.year} already finished in an earlier job", flush=True)
        return
    torch.set_num_threads(os.cpu_count() or 4)
    c = NNConfig(steps=a.steps, d_model=a.d_model, layers=a.layers, lookback=a.lookback, news_dims=a.news_dims,
                 seed=a.seed)  # fmt: skip
    t0 = time.time()
    panel, _ = load_panels(RECIPE, Path(a.data), a.offline)
    feats = features(RECIPE)
    if c.news_dims:
        sessions = panel.select(pl.col("date").unique().sort())["date"].to_list()
        keys, vecs = load_news_vectors(Path(a.data), sessions, a.offline)
        cols, names = seqdata.news_columns(keys, vecs, date(a.year, 1, 1), c.news_dims)
        panel = panel.join(cols, on=["date", "symbol"], how="left")
        feats = feats + names
    train_start = date(a.year - RECIPE.train_years, 1, 1)
    cube = seqdata.build(
        panel, feats, RECIPE.target, train_start - timedelta(days=c.lookback * 2), date(a.year, 12, 31)
    )
    days = seqdata.split_days(cube, a.year, train_start, RECIPE.embargo_days, c.valid_days)
    if not len(days["test"]):
        raise SystemExit(f"no data for {a.year}")
    seqdata.scale(cube, days["train"])
    print(f"cube {cube.x.shape} built in {time.time() - t0:.0f}s; train {len(days['train'])} days, "
          f"valid {len(days['valid'])}, test {len(days['test'])}", flush=True)  # fmt: skip
    resume = load_ckpt(prev) if prev else None
    budget = a.budget_min * 60 - (time.time() - t0) if a.budget_min else None
    model, info, ckpt = train_fold(cube, days, c, resume, budget)
    if ckpt is not None and not a.final:
        save_ckpt(ckpt, out)
        print(f"checkpoint saved at step {ckpt['meta']['step']}; the next job continues", flush=True)
        return
    rows = []
    for d in days["test"]:
        idx, s = predict_day(model, cube, int(d), c.lookback)
        rows += [(cube.dates[d], cube.symbols[i], float(v)) for i, v in zip(idx, s, strict=True)]
    preds = pl.DataFrame(rows, schema={"date": pl.Date, "symbol": pl.Utf8, "score": pl.Float64}, orient="row")
    scored = preds.join(panel.select("date", "symbol", "close", RECIPE.target), on=["date", "symbol"]).filter(
        pl.col(RECIPE.target).is_not_null()
    )
    m = {"year": a.year, "secs": round(time.time() - t0)} | evaluate(scored, RECIPE)
    out.mkdir(parents=True, exist_ok=True)
    for f in ("ckpt.pt", "ckpt.json"):
        (out / f).unlink(missing_ok=True)
    preds.write_parquet(out / "preds.parquet")
    (out / "fold.json").write_text(
        json.dumps({"metrics": m, "train": info, "config": asdict(c)}, indent=2, default=str)
    )
    torch.save(model.state_dict(), out / "model.pt")
    print(json.dumps({k: round(v, 4) if isinstance(v, float) else v for k, v in m.items()}), flush=True)


# ----- CLI: compare against the LightGBM champion -----
CASH_BOOK = {"k": 3, "exit_k": 200, "notional": 16_000.0, "long_only": True, "vehicle": "delivery"}


def book_stats(preds: pl.DataFrame, panel: pl.DataFrame) -> dict:
    from t2.backtest.holding import HoldConfig, run_book, stats, yearly
    from t2.features import eod

    df = preds.select("date", "symbol", "score").join(
        panel.select("date", "symbol", "close", "y1", *eod.NEXT), on=["date", "symbol"]
    )
    daily = run_book(df, HoldConfig(**CASH_BOOK))
    return {"overall": stats(daily), "yearly": yearly(daily)}


BLENDS = (0.5, 0.25)  # share of the neural score; 50/50 is the pre-declared candidate, 25% is for information


def daily_rank(p: pl.DataFrame) -> pl.DataFrame:
    """Each day's scores as percentile ranks (0..1], so two models on different scales can be averaged."""
    return p.select("date", "symbol", (pl.col("score").rank() / pl.col("score").count()).over("date").alias("r"))


def blend(nn_preds: pl.DataFrame, lgb_preds: pl.DataFrame, w: float) -> pl.DataFrame:
    """Rank-average of the two models on the stocks both scored."""
    j = daily_rank(nn_preds).join(daily_rank(lgb_preds), on=["date", "symbol"], suffix="_g")
    return j.select("date", "symbol", (w * pl.col("r") + (1 - w) * pl.col("r_g")).alias("score"))


def score_agreement(nn_preds: pl.DataFrame, lgb_preds: pl.DataFrame) -> float:
    """Mean daily rank correlation between the two models: low means their mistakes differ (good for a blend)."""
    j = daily_rank(nn_preds).join(daily_rank(lgb_preds), on=["date", "symbol"], suffix="_g")
    c = j.group_by("date").agg(pl.corr("r", "r_g").alias("c"))["c"].drop_nans().mean()
    return float(c) if isinstance(c, float) else float("nan")


def model_name(cfg: dict) -> str:
    news = cfg.get("news_dims", 0)
    return "Neural (Mamba + cross-stock attention" + (f" + headline vectors {news}d)" if news else ")")


def cmd_compare(a: argparse.Namespace) -> None:
    folds = sorted(Path(a.folds).glob("*/fold.json"))
    nn_folds = [json.loads(f.read_text()) for f in folds]
    nn_preds = pl.concat([pl.read_parquet(f.parent / "preds.parquet") for f in folds]).select("date", "symbol", "score")
    years = sorted(f["metrics"]["year"] for f in nn_folds)
    panel, train_panel = load_panels(RECIPE, Path(a.data), a.offline)
    lgb_folds, lgb_preds = walk_forward(panel, years, RECIPE, train_panel)
    lgb_preds = lgb_preds.select("date", "symbol", "score")

    def overall(p: pl.DataFrame) -> dict:
        s = p.join(panel.select("date", "symbol", "close", RECIPE.target), on=["date", "symbol"], how="inner")
        return evaluate(s.filter(pl.col(RECIPE.target).is_not_null()), RECIPE)

    def yearly_ic(p: pl.DataFrame) -> dict[int, float]:
        s = p.join(panel.select("date", "symbol", RECIPE.target), on=["date", "symbol"]).filter(
            pl.col(RECIPE.target).is_not_null()
        )
        daily = s.group_by("date").agg(pl.corr("score", RECIPE.target, method="spearman").alias("ic"))
        by = daily.group_by(pl.col("date").dt.year().alias("y")).agg(pl.col("ic").mean()).sort("y")
        return dict(zip(by["y"].to_list(), by["ic"].to_list(), strict=True))

    cfg = nn_folds[0]["config"]
    res: dict = {
        "years": years,
        "name": model_name(cfg),
        "neural": {
            "overall": overall(nn_preds),
            "book": book_stats(nn_preds, panel),
            "folds": [f["metrics"] for f in nn_folds],
            "params": nn_folds[0]["train"]["params"],
            "steps_done": [f["train"].get("steps_done") for f in nn_folds],
            "config": cfg,
        },
        "lightgbm": {"overall": overall(lgb_preds), "book": book_stats(lgb_preds, panel), "folds": lgb_folds},
        "agreement": score_agreement(nn_preds, lgb_preds),
        "blends": {},
    }
    ic_years = {"neural": yearly_ic(nn_preds), "lightgbm": yearly_ic(lgb_preds)}
    for w in BLENDS:
        b = blend(nn_preds, lgb_preds, w)
        res["blends"][f"{w:g}"] = {"weight": w, "overall": overall(b), "book": book_stats(b, panel)}
        ic_years[f"blend {w:g}"] = yearly_ic(b)

    def beats(r: dict) -> bool:
        g = res["lightgbm"]
        return r["overall"]["ic_mean"] > g["overall"]["ic_mean"] and (
            r["book"]["overall"]["annual_return"] > g["book"]["overall"]["annual_return"]
        )

    primary = res["blends"][f"{BLENDS[0]:g}"]
    res["verdict"] = (
        "neural beats the champion" if beats(res["neural"])
        else f"blend {BLENDS[0]:.0%} beats the champion" if beats(primary)
        else "champion stays"
    )  # fmt: skip
    res["run"] = os.environ.get("GITHUB_RUN_ID", "local")
    res["finished"] = date.today().isoformat()

    n = res["neural"]
    lines = [
        f"## {res['name']} vs LightGBM champion ({years[0]}-{years[-1]}, {n['params']:,} parameters)",
        "",
        f"**Verdict: {res['verdict']}** (needs higher rank IC and higher cash-book return; the 50/50 blend is the "
        "pre-declared blend candidate)",
        "",
        f"Daily rank agreement between the two models: {res['agreement']:.2f} (1 = identical picks)",
        "",
        "| | rank IC | IC > 0 days | top-10 up days | cash book annual | Sharpe | max drawdown |",
        "|---|---|---|---|---|---|---|",
    ]
    rows = [("Neural", n), ("LightGBM champion", res["lightgbm"])] + [
        (f"Blend {w:.0%} neural", res["blends"][f"{w:g}"]) for w in BLENDS
    ]
    for name, r in rows:
        o, b = r["overall"], r["book"]["overall"]
        lines.append(
            f"| {name} | {o['ic_mean']:.4f} | {o['ic_hit']:.0%} | {o['long_hit']:.0%} | {b['annual_return']:+.1%} | "
            f"{b['sharpe']:.2f} | {b['max_drawdown']:.1%} |"
        )
    cols = list(ic_years)
    lines += ["", "| year | " + " | ".join(f"{c} IC" for c in cols) + " |", "|---" * (len(cols) + 1) + "|"]
    for y in years:
        lines.append(f"| {y} | " + " | ".join(f"{ic_years[c].get(y, float('nan')):.4f}" for c in cols) + " |")
    md = "\n".join(lines) + "\n"
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(res, indent=2, default=str))
    (out / "summary.md").write_text(md)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as fh:
            fh.write(md)
    print(md)
    if a.publish:
        from huggingface_hub import HfApi

        repo = os.environ.get("HF_MODEL_REPO", "harcorp/t2-models")
        HfApi(token=os.environ.get("HF_TOKEN")).upload_file(
            path_or_fileobj=str(out / "summary.json"),
            path_in_repo=f"experiments/neural/{res['finished']}-{res['run']}.json",
            repo_id=repo,
            commit_message=f"neural challenger: {res['verdict']}",
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fold")
    f.add_argument("--year", type=int, required=True)
    f.add_argument("--steps", type=int, default=NNConfig.steps)
    f.add_argument("--d-model", type=int, default=NNConfig.d_model)
    f.add_argument("--layers", type=int, default=NNConfig.layers)
    f.add_argument("--lookback", type=int, default=NNConfig.lookback)
    f.add_argument("--news-dims", type=int, default=NNConfig.news_dims)
    f.add_argument("--seed", type=int, default=0)
    f.add_argument("--resume", help="folder with an earlier job's checkpoint (or finished fold) for this year")
    f.add_argument("--budget-min", type=float, help="stop training after this many minutes of the job")
    f.add_argument("--final", action="store_true", help="last job: finish with the best weights even if cut short")
    c = sub.add_parser("compare")
    c.add_argument("--folds", required=True)
    c.add_argument("--publish", action="store_true")
    for p in (f, c):
        p.add_argument("--data", default="data/hf")
        p.add_argument("--offline", action="store_true")
        p.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    (cmd_fold if a.cmd == "fold" else cmd_compare)(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
