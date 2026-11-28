"""Runs where torch is installed (the neural workflow); skipped in the default CI."""

from datetime import date

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from t2.models import neural, seqdata  # noqa: E402
from tests.test_seqdata import synthetic  # noqa: E402


def test_shapes_and_size():
    m = neural.T2Net(47, neural.NNConfig())
    out = m(torch.randn(30, 40, 47))
    assert out.shape == (30,)
    assert 500_000 < neural.n_params(m) < 3_000_000


def test_mamba_is_causal():
    torch.manual_seed(0)
    blk = neural.Mamba(16, 4, 2)
    x = torch.randn(3, 12, 16)
    y1 = blk(x)
    x2 = x.clone()
    x2[:, 8:] += 5.0
    y2 = blk(x2)
    assert torch.allclose(y1[:, :8], y2[:, :8], atol=1e-5) and not torch.allclose(y1[:, 8:], y2[:, 8:])


def test_learns_a_planted_signal():
    p = synthetic(n_sym=60, n_days=400)
    cube = seqdata.build(p, ["f0", "f1"], "y5", date(2018, 1, 1), date(2019, 12, 31))
    year = cube.dates[-1].year
    days = seqdata.split_days(cube, year, date(2018, 1, 1), embargo=10, valid_days=30)
    seqdata.scale(cube, days["train"])
    c = neural.NNConfig(d_model=32, layers=1, lookback=8, steps=150, eval_every=50, warmup=20, batch_stocks=60)
    model, info, ckpt = neural.train_fold(cube, days, c)
    assert ckpt is None and info["steps_done"] == 150
    ics = []
    for d in days["test"][:20]:
        idx, s = neural.predict_day(model, cube, int(d), c.lookback)
        ics.append(seqdata.rank_ic(s, cube.label[d, idx]))
    assert np.nanmean(ics) > 0.5 and info["best_valid_ic"] > 0.5


def test_resume_continues_exactly():
    p = synthetic(n_sym=60, n_days=400)  # spans two years; training uses days with 50+ stocks
    cube = seqdata.build(p, ["f0", "f1"], "y5", date(2018, 1, 1), date(2019, 12, 31))
    days = seqdata.split_days(cube, cube.dates[-1].year, date(2018, 1, 1), embargo=10, valid_days=20)
    seqdata.scale(cube, days["train"])
    c = neural.NNConfig(d_model=16, layers=1, lookback=6, steps=12, eval_every=4, warmup=3, batch_stocks=60)
    whole, _, _ = neural.train_fold(cube, days, c)
    _, _, ckpt = neural.train_fold(cube, days, c, budget_s=0.0)
    assert ckpt is not None and ckpt["meta"]["step"] == 1
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        neural.save_ckpt(ckpt, Path(tmp))
        back = neural.load_ckpt(Path(tmp))
    split, info, rest = neural.train_fold(cube, days, c, resume=back)
    assert rest is None and info["steps_done"] == 12 and len(info["history"]) == 3
    for k, v in whole.state_dict().items():
        assert torch.allclose(v, split.state_dict()[k], atol=1e-5), k


def test_blend_ranks_and_agreement():
    import polars as pl

    d = [date(2024, 1, 1)] * 4
    a = pl.DataFrame({"date": d, "symbol": list("ABCD"), "score": [1.0, 2.0, 3.0, 4.0]})
    b = pl.DataFrame({"date": d, "symbol": list("ABCD"), "score": [400.0, 300.0, 200.0, 100.0]})
    m = neural.blend(a, b, 0.5).sort("symbol")
    assert np.allclose(m["score"].to_numpy(), 0.625)  # opposite rankings cancel out
    assert neural.blend(a, b, 1.0).sort("symbol")["score"].to_list() == [0.25, 0.5, 0.75, 1.0]
    assert neural.score_agreement(a, b) == pytest.approx(-1.0)
    assert neural.score_agreement(a, a) == pytest.approx(1.0)


def test_seed_average_ranks_then_means():
    import polars as pl

    d = [date(2024, 1, 1)] * 3
    a = pl.DataFrame({"date": d, "symbol": list("ABC"), "score": [1.0, 2.0, 3.0]})
    b = pl.DataFrame({"date": d, "symbol": list("ABC"), "score": [30.0, 10.0, 20.0]})
    m = neural.seed_average([(0, a), (1, b)]).sort("symbol")
    assert np.allclose(m["score"].to_numpy(), [(1 / 3 + 1) / 2, (2 / 3 + 1 / 3) / 2, (1 + 2 / 3) / 2])
    assert neural.seed_average([(0, a)])["score"].to_list() == [1.0, 2.0, 3.0]
