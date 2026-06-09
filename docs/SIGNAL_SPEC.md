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

1. Pull batch funding snapshots from Binance USD-M, Bybit linear, and Bitget
   USDT futures.
2. Select symbols whose absolute funding rate reaches the configured minimum
   alert level.
3. Keep the most severe `MAX_CANDIDATE_SYMBOLS` candidates.
4. Fetch per-symbol funding and 15m volume snapshots across all configured
   venues, including OKX when the candidate exists there.

This avoids pulling K lines for the entire market every cycle.

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

Default cooldown is 15 minutes. L4 cooldown is 5 minutes. A higher funding level
than the last sent level bypasses cooldown immediately.
