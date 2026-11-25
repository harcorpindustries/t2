---
license: other
license_name: harcorp-license
pretty_name: T2 Market Data
tags:
  - finance
  - nse
  - india
  - time-series
configs:
  - config_name: eq_daily
    data_files: eq_daily/**/*.parquet
  - config_name: fo_daily
    data_files: fo_daily/**/*.parquet
  - config_name: eq_delivery
    data_files: eq_delivery/**/*.parquet
  - config_name: intraday_1m
    data_files: intraday_1m/**/*.parquet
  - config_name: ticks
    data_files: ticks/**/*.parquet
  - config_name: option_chain
    data_files: option_chain/**/*.parquet
  - config_name: corp_actions
    data_files: corp_actions/**/*.parquet
  - config_name: news
    data_files: news/**/*.parquet
  - config_name: features
    data_files: features/**/*.parquet
  - config_name: predictions_trades
    data_files: predictions_trades/**/*.parquet
---

# T2 Market Data

Private dataset behind T2. Everything the system collects lands here as zstd-compressed Parquet,
partitioned by date (`<config>/date=YYYY-MM-DD/part-*.parquet`). History is append-only.

| Config | Source | Granularity |
|---|---|---|
| `eq_daily` | NSE equity bhavcopy | Daily OHLCV, delivery % |
| `fo_daily` | NSE F&O bhavcopy | Daily futures/options OHLC + OI |
| `eq_delivery` | NSE security-wise delivery (MTO) | Traded vs deliverable quantity, delivery % |
| `intraday_1m` | Broker backfill + live recorder | 1-minute bars |
| `ticks` | Live recorder | Ticks + depth for a focused watchlist |
| `option_chain` | Broker snapshots | Periodic chain snapshots |
| `corp_actions` | NSE | Splits, bonuses, dividends, adjustment factors |
| `news` | News crawler | Articles with tickers, event type, sentiment, embedding |
| `features` | Feature pipeline | Versioned model-ready tables |
| `predictions_trades` | Trader | Predictions, orders, fills, P&L (sandbox and live) |

Completeness: every calendar day is checked for every source. `_ledger/nse/year=YYYY.parquet` records
status (ok / not_published / error / parse_error), HTTP status, source URL, byte size, SHA-256 and row count
per day and source. Original files are kept unchanged under `raw/`, so every table can be rebuilt.
A daily audit flags errors and inconsistent days (e.g. equity present but F&O missing). Every trained model records the dataset
commit it used.

Not for redistribution: contains exchange data and news text under third-party terms.
