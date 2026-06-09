# Signal Specification

## Funding

Funding levels use absolute values:

- L1: `0.03%`
- L2: `0.05%`
- L3: `0.08%`
- L4: `0.12%`

Direction is stored separately as `positive`, `negative`, or `neutral`.

The collector prefers predicted funding fields when ccxt exposes them. If no
predicted value is available, it falls back to current funding and marks the
snapshot source as `current`.

## Market Discovery

Default mode is full-market discovery:

1. Pull funding snapshots from Binance USD-M, OKX USDT swaps, Bybit linear, and
   Bitget USDT futures.
2. Select symbols whose absolute funding rate reaches the configured minimum
   alert level.
3. Filter out low-liquidity markets with `MIN_24H_VOLUME_USDT`.
4. Filter out tokenized stock symbols when `EXCLUDE_TOKENIZED_STOCKS=true`.
5. Keep the most severe `MAX_CANDIDATE_SYMBOLS` candidates.
6. Fetch per-symbol funding and 15m volume snapshots across all configured
   venues when the candidate exists there.

This avoids pulling K lines for the entire market every cycle.

By default `NEGATIVE_FUNDING_ONLY=false`, so the live alert stream includes both
positive and negative funding extremes. Set it to `true` only when you want to
focus exclusively on negative funding.

## Volume

The default volume window is `15m`.

Volume ratio:

```text
current candle volume / average volume of previous 8 candles
```

Levels:

- `>= 3.0x`: highly_expanded
- `>= 2.0x`: expanded
- `>= 1.3x`: mildly_expanded
- `0.7x - 1.3x`: normal
- `0.4x - 0.7x`: mildly_contracted
- `< 0.4x`: clearly_contracted

Volume is compared only within the same exchange and symbol. Absolute volume is
not compared across exchanges.

## Pattern Types

- `single_exchange_extreme`: one exchange is L3+ while all other exchanges are
  below L1.
- `multi_exchange_sync`: at least two exchanges are L1+ in the same direction.
- `direction_conflict`: exchanges disagree on positive vs negative funding.
- `isolated_signal`: an L1+ signal that does not match the stronger categories.

## Alert Cooldown

The cooldown key is:

```text
symbol + exchange + direction
```

Default cooldown is 45 minutes. L4 cooldown is 45 minutes. A higher funding level
than the last sent level bypasses cooldown immediately.

## Periodic Report

When `REPORT_ENABLED=true`, the service checks after each scan whether a report
is due. Defaults:

- `REPORT_INTERVAL_HOURS=12`
- `REPORT_WINDOW_HOURS=12`
- `REPORT_TOP_N=10`

The report reads recent alert records from SQLite, deduplicates by symbol, and
ranks by:

1. Funding level
2. Volume confirmation
3. Multi-exchange sync
4. Absolute funding rate
5. Volume ratio

If there are no L3+ alerts in the window, the service records the report check
but does not send an empty Telegram message.
