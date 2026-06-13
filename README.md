# Crypto Funding & Volume Sentinel

Multi-exchange funding-rate and volume anomaly monitor for Binance USD-M,
OKX, Bitget, and Bybit perpetual swaps. It uses public REST endpoints and does
not require exchange API keys.

## What It Does

- Discovers abnormal funding-rate symbols across the whole USDT perpetual market.
- Uses Binance, OKX, Bybit, and Bitget public funding endpoints for market discovery.
- Filters low-liquidity contracts with `MIN_24H_VOLUME_USDT`.
- Excludes common tokenized stock symbols by default.
- Excludes major spot-volume symbols and stablecoins by default.
- Computes L1-L4 funding severity in both positive and negative directions.
- Compares the current 3m candle volume against the previous 8 candles.
- Detects single-exchange extremes, multi-exchange sync, direction conflicts,
  and volume-confirmed signals.
- Writes funding, volume, and alert records to SQLite.
- Sends Telegram alerts with cooldown and level-upgrade handling.
- Sends a periodic summary report for the strongest recent signals.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

Edit `.env`, then run:

```powershell
python -m funding_sentinel.main
```

Run one scan and exit:

```powershell
python -m funding_sentinel.main --once
```

Telegram is optional. If `TG_BOT_TOKEN` or `TG_CHAT_ID` is empty, alerts are
logged and stored but not pushed.

## Notes

- `MARKET_SCAN=true` is the default. In this mode, `MONITORED_SYMBOLS` is ignored
  and the system scans the broader USDT perpetual market for funding anomalies.
- Set `MARKET_SCAN=false` to monitor only `MONITORED_SYMBOLS`.
- Default market filters:
  - `MIN_ALERT_LEVEL=L1`
  - `MIN_24H_VOLUME_USDT=5000000`
  - `MAX_CANDIDATE_SYMBOLS=70`
  - `NEGATIVE_FUNDING_ONLY=false`
  - `PREFER_NEGATIVE_FUNDING=false`
  - `EXCLUDE_TOKENIZED_STOCKS=true`
  - `EXCLUDE_MAJOR_SPOT_SYMBOLS=true`
  - `EXCLUDE_STABLECOINS=true`
  - `VOLUME_TIMEFRAME=3m`
- Periodic report defaults:
  - `REPORT_ENABLED=true`
  - `REPORT_INTERVAL_HOURS=12`
  - `REPORT_WINDOW_HOURS=12`
  - `REPORT_TOP_N=10`
- Alert cooldown defaults:
  - `ALERT_COOLDOWN_SECONDS=2700`
  - `L4_COOLDOWN_SECONDS=2700`
- L1/L2 alerts are only sent when volume is confirmed. L3/L4 can alert before
  volume confirmation, then send a follow-up when 3m volume confirms.
- A separate 15m spike alert is sent when funding is at L1-L4 and the raw
  current 15m volume is at least 4x the previous 8 candles' average volume.
  It uses its own 45-minute cooldown and starts with `❗`.
- A stealth-volume alert is sent when funding is stable below L1, raw 15m
  volume ratio is at least 2.5x, the latest 1h quote volume is at least
  5M USDT, and the latest 3 candles' volume is increasing.
- Volume comparisons are per exchange only. Absolute volume is not compared
  across exchanges because units can differ by venue.
- Funding source is marked as `predicted` when a next funding value is available,
  otherwise `current`.
- Signal rules are documented in `docs/SIGNAL_SPEC.md`.
