from datetime import UTC, datetime
import unittest

from funding_sentinel.analysis import build_alerts
from funding_sentinel.config import funding_direction, funding_level, volume_level
from funding_sentinel.models import ExchangeSignal, FundingSnapshot, VolumeSnapshot


class RuleTests(unittest.TestCase):
    def test_funding_level_and_direction(self) -> None:
        self.assertIsNone(funding_level(0.00029))
        self.assertEqual(funding_level(0.0003), "L1")
        self.assertEqual(funding_level(-0.0008), "L3")
        self.assertEqual(funding_level(0.0012), "L4")
        self.assertEqual(funding_direction(-0.1), "negative")
        self.assertEqual(funding_direction(0.1), "positive")

    def test_volume_level(self) -> None:
        self.assertEqual(volume_level(3.0), "highly_expanded")
        self.assertEqual(volume_level(2.0), "expanded")
        self.assertEqual(volume_level(1.3), "mildly_expanded")
        self.assertEqual(volume_level(1.0), "normal")
        self.assertEqual(volume_level(0.5), "mildly_contracted")
        self.assertEqual(volume_level(0.39), "clearly_contracted")

    def test_alert_detects_single_exchange_extreme(self) -> None:
        signals = [
            _signal("binanceusdm", "ZECUSDT", 0.0010, 2.5),
            _signal("okx", "ZECUSDT", 0.0001, 1.0),
            _signal("bybit", "ZECUSDT", 0.0001, 1.0),
        ]
        alerts = build_alerts(signals, min_level_rank=1)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].exchange_id, "multi")
        self.assertEqual(alerts[0].divergence_type, "single_exchange_extreme")
        self.assertIn("volume_confirmed", alerts[0].signal_tags)
        self.assertIn("多平台快照", alerts[0].message)
        self.assertIn("量能：最大量比 2.50x，已形成放量确认", alerts[0].message)

    def test_alert_detects_multi_exchange_sync(self) -> None:
        signals = [
            _signal("binanceusdm", "BTCUSDT", -0.0005, 0.5),
            _signal("okx", "BTCUSDT", -0.0004, 0.6),
        ]
        alerts = build_alerts(signals, min_level_rank=1)
        self.assertEqual(len(alerts), 1)
        self.assertEqual({alert.divergence_type for alert in alerts}, {"multi_exchange_sync"})
        self.assertEqual(alerts[0].fingerprint, "BTCUSDT:negative:multi_exchange_sync")
        self.assertIn("量能：最大量比 0.60x，整体明显缩量，未形成放量确认", alerts[0].message)


def _signal(exchange_id: str, symbol: str, rate: float, ratio: float) -> ExchangeSignal:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    funding = FundingSnapshot(
        exchange_id=exchange_id,
        compact_symbol=symbol,
        ccxt_symbol="BTC/USDT:USDT",
        funding_rate=rate,
        funding_source="current",
        next_funding_time=None,
        mark_price=None,
        timestamp=now,
        level=funding_level(rate),
        direction=funding_direction(rate),
    )
    volume = VolumeSnapshot(
        exchange_id=exchange_id,
        compact_symbol=symbol,
        ccxt_symbol="BTC/USDT:USDT",
        timeframe="15m",
        current_volume=ratio,
        previous_average_volume=1.0,
        volume_ratio=ratio,
        volume_level=volume_level(ratio),
        candle_timestamp=now,
        timestamp=now,
    )
    return ExchangeSignal(funding=funding, volume=volume)


if __name__ == "__main__":
    unittest.main()
