# Crypto Funding & Volume Sentinel

Multi-exchange funding-rate and volume anomaly monitor for Binance USD-M,
OKX, Bitget, and Bybit perpetual swaps. It uses public REST endpoints and does
not require exchange API keys.

## What It Does

- Discovers abnormal funding-rate symbols across the whole USDT perpetual market.
- Uses Binance, Bybit, and Bitget batch funding endpoints for market discovery,
  then uses OKX as a confirmation venue for candidate symbols.
- Computes L1-L4 funding severity in both positive and negative directions.
- Compares the current 15m candle volume against the previous 8 candles.
- Detects single-exchange extremes, multi-exchange sync, direction conflicts,
  and volume-confirmed signals.
- Writes funding, volume, and alert records to SQLite.
- Sends Telegram alerts with cooldown and level-upgrade handling.

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
- Volume comparisons are per exchange only. Absolute volume is not compared
  across exchanges because units can differ by venue.
- Funding source is marked as `predicted` when a next funding value is available,
  otherwise `current`.
- Signal rules are documented in `docs/SIGNAL_SPEC.md`.
