from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class FundingSnapshot:
    exchange_id: str
    compact_symbol: str
    ccxt_symbol: str
    funding_rate: float
    funding_source: str
    next_funding_time: datetime | None
    mark_price: float | None
    volume_24h_usdt: float | None
    timestamp: datetime
    level: str | None
    direction: str


@dataclass(frozen=True)
class VolumeSnapshot:
    exchange_id: str
    compact_symbol: str
    ccxt_symbol: str
    timeframe: str
    current_volume: float | None
    previous_average_volume: float | None
    volume_ratio: float | None
    volume_level: str
    candle_timestamp: datetime | None
    timestamp: datetime
    raw_volume_ratio: float | None = None
    adjusted_volume_ratio: float | None = None
    candle_progress: float | None = None
    one_hour_quote_volume: float | None = None
    recent_volumes: tuple[float, ...] = ()


@dataclass(frozen=True)
class ExchangeSignal:
    funding: FundingSnapshot
    volume: VolumeSnapshot | None


@dataclass(frozen=True)
class Alert:
    compact_symbol: str
    exchange_id: str
    level: str
    direction: str
    funding_rate: float
    funding_source: str
    volume_ratio: float | None
    volume_level: str
    divergence_type: str
    signal_tags: tuple[str, ...]
    message: str
    fingerprint: str
    timestamp: datetime
