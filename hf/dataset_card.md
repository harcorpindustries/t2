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
  - config_name: intraday_5m
    data_files: intraday_5m/**/*.parquet
  - config_name: ticks
    data_files: ticks/**/*.parquet
  - config_name: option_chain
    data_files: option_chain/**/*.parquet
  - config_name: corp_actions
    data_files: corp_actions/**/*.parquet
  - config_name: news
    data_files: news/**/*.parquet
  - config_name: news_feed_polls
    data_files: _ledger/news/feed_polls/*.parquet
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
| `intraday_1m` | Breeze history, then live recorder | 1-minute OHLCV, all F&O stocks + indices, newest years first (`year=YYYY/<SYMBOL>.parquet`, IST timestamps) |
| `intraday_5m` | Breeze history | 5-minute OHLCV back to 2012, same universe |
| `ticks` | Live recorder | Ticks + depth for a focused watchlist |
| `option_chain` | Broker snapshots | Periodic chain snapshots |
| `corp_actions` | NSE | Splits, bonuses, dividends, adjustment factors |
| `news` | News crawler | Exchange filings (NSE RSS), regulator releases (RBI, SEBI), financial press (ET, Mint, Business Standard, BusinessLine) and aggregator headlines; full text where the site allows it, tagged NSE symbols. Event type, sentiment and embeddings are added by later pipelines |
| `features` | Feature pipeline | Versioned model-ready tables |
| `predictions_trades` | Trader | Predictions, orders, fills, P&L (sandbox and live) |

Completeness: every calendar day is checked for every source. `_ledger/nse/year=YYYY.parquet` records
status (ok / not_published / error / parse_error), HTTP status, source URL, byte size, SHA-256 and row count
per day and source. Original files are kept unchanged under `raw/`, so every table can be rebuilt.
News feeds are polled every 5 minutes; every poll (status, items seen, new items, errors) is logged in
`_ledger/news/feed_polls/`, so outages are visible. Breeze backfill windows (instrument, interval, date range, status, rows, calls) are in
`_ledger/breeze/windows.parquet`. A daily audit flags errors and inconsistent days (e.g. equity present but F&O missing). Every trained model records the dataset
commit it used.

Not for redistribution: contains exchange data and news text under third-party terms.
