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
    model, info = neural.train_fold(cube, days, c)
    ics = []
    for d in days["test"][:20]:
        idx, s = neural.predict_day(model, cube, int(d), c.lookback)
        ics.append(seqdata.rank_ic(s, cube.label[d, idx]))
    assert np.nanmean(ics) > 0.5 and info["best_valid_ic"] > 0.5
