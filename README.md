# T2

An AI system that learns from NSE market data and market news, predicts price moves, and trades
(intraday, delivery, stocks and F&O) through a broker-agnostic interface. ICICI Direct Breeze is the
first broker.

> **Not financial advice.** This is research software. Trading involves substantial risk of loss.

## Layout

| Path | Purpose |
|---|---|
| `src/t2/data` | Market data collectors (NSE bhavcopy, Breeze backfill, live recorder) |
| `src/t2/news` | News crawler and search index |
| `src/t2/features` | Feature pipelines |
| `src/t2/models` | Model architectures |
| `src/t2/training` | Training, walk-forward evaluation, champion/challenger |
| `src/t2/backtest` | Event-driven backtester |
| `src/t2/brokers` | `Broker` interface, paper broker, Breeze broker |
| `src/t2/trader` | Decision layer and risk manager |
| `dashboard/` | Next.js dashboard |
| `infra/` | Server bootstrap and infrastructure |
| `tools/` | Repo tooling |

## Development

```bash
uv sync
uv run pytest
uvx pre-commit install --hook-type pre-commit --hook-type commit-msg
```

## License

HARCORP LICENSE: public for review only. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
Outside contributions are not accepted.
