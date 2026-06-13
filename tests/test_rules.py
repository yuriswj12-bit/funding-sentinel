from datetime import UTC, datetime
import unittest

from funding_sentinel.analysis import build_15m_volume_spike_alerts, build_alerts, build_stealth_volume_alerts
from funding_sentinel.config import (
    Settings,
    funding_direction,
    funding_level,
    is_tokenized_stock_symbol,
    volume_level,
)
from funding_sentinel.exchanges.ccxt_client import _confirmation_volume_ratio
from funding_sentinel.main import _passes_24h_volume_filter
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

    def test_tokenized_stock_symbol_filter(self) -> None:
        self.assertTrue(is_tokenized_stock_symbol("AAPLUSDT"))
        self.assertTrue(is_tokenized_stock_symbol("TSLAUSDT"))
        self.assertTrue(is_tokenized_stock_symbol("CRWDUSDT"))
        self.assertTrue(is_tokenized_stock_symbol("AAOIUSDT"))
        self.assertTrue(is_tokenized_stock_symbol("ARMUSDT"))
        self.assertTrue(is_tokenized_stock_symbol("QCOMUSDT"))
        self.assertTrue(is_tokenized_stock_symbol("DELLUSDT"))
        self.assertTrue(is_tokenized_stock_symbol("MRVLUSDT"))
        self.assertTrue(is_tokenized_stock_symbol("SNDKUSDT"))
        self.assertFalse(is_tokenized_stock_symbol("SENTUSDT"))

    def test_24h_volume_filter(self) -> None:
        settings = Settings(min_24h_volume_usdt=5_000_000)
        self.assertTrue(_passes_24h_volume_filter(_funding("SENTUSDT", -0.01, 6_000_000), settings))
        self.assertFalse(_passes_24h_volume_filter(_funding("SENTUSDT", -0.01, 4_000_000), settings))
        self.assertFalse(_passes_24h_volume_filter(_funding("SENTUSDT", -0.01, None), settings))

    def test_settings_default_to_include_positive_and_negative_funding(self) -> None:
        settings = Settings()
        self.assertFalse(settings.negative_funding_only)
        self.assertFalse(settings.prefer_negative_funding)
        self.assertEqual(settings.max_candidate_symbols, 70)
        self.assertEqual(settings.min_alert_level, "L1")
        self.assertEqual(settings.volume_timeframe, "3m")

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
        self.assertIn("ZECUSDT", alerts[0].message)
        self.assertAlmostEqual(alerts[0].volume_ratio or 0, 2.5)

    def test_alert_detects_multi_exchange_sync(self) -> None:
        signals = [
            _signal("binanceusdm", "BTCUSDT", -0.0008, 0.5),
            _signal("okx", "BTCUSDT", -0.0009, 0.6),
        ]
        alerts = build_alerts(signals, min_level_rank=1)
        self.assertEqual(len(alerts), 1)
        self.assertEqual({alert.divergence_type for alert in alerts}, {"multi_exchange_sync"})
        self.assertEqual(alerts[0].fingerprint, "BTCUSDT:negative:multi_exchange_sync")
        self.assertEqual(alerts[0].volume_level, "clearly_contracted")

    def test_l1_l2_need_volume_confirmation(self) -> None:
        weak_volume = [_signal("binanceusdm", "SENTUSDT", 0.0003, 1.0)]
        self.assertEqual(build_alerts(weak_volume, min_level_rank=1), [])

        confirmed_volume = [_signal("binanceusdm", "SENTUSDT", 0.0003, 2.1)]
        alerts = build_alerts(confirmed_volume, min_level_rank=1)
        self.assertEqual(len(alerts), 1)
        self.assertIn("volume_confirmed", alerts[0].signal_tags)

    def test_early_candle_volume_confirmation_is_conservative(self) -> None:
        self.assertEqual(_confirmation_volume_ratio(0.8, 2.4, 0.33), 0.8)
        self.assertEqual(_confirmation_volume_ratio(1.2, 3.6, 0.33), 3.6)
        self.assertEqual(_confirmation_volume_ratio(0.8, 1.6, 0.5), 1.6)

    def test_15m_volume_spike_alert_needs_funding_and_raw_volume(self) -> None:
        no_spike = [_signal("binanceusdm", "SENTUSDT", 0.0003, 3.9, raw_ratio=3.9)]
        self.assertEqual(build_15m_volume_spike_alerts(no_spike, min_level_rank=1, spike_threshold=4.0), [])

        no_funding = [_signal("binanceusdm", "SENTUSDT", 0.0001, 5.0, raw_ratio=5.0)]
        self.assertEqual(build_15m_volume_spike_alerts(no_funding, min_level_rank=1, spike_threshold=4.0), [])

        spike = [_signal("binanceusdm", "SENTUSDT", 0.0003, 5.0, raw_ratio=5.0)]
        alerts = build_15m_volume_spike_alerts(spike, min_level_rank=1, spike_threshold=4.0)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].divergence_type, "15m_volume_spike")
        self.assertEqual(alerts[0].fingerprint, "SENTUSDT:positive:15m_volume_spike")
        self.assertTrue(alerts[0].message.startswith("❗"))

    def test_stealth_volume_alert_needs_stable_funding_liquidity_and_trend(self) -> None:
        valid = [
            _signal(
                "binanceusdm",
                "SENTUSDT",
                0.0001,
                2.6,
                raw_ratio=2.6,
                one_hour_volume=6_000_000,
                recent_volumes=(100.0, 120.0, 150.0),
            )
        ]
        alerts = build_stealth_volume_alerts(valid, 0.0003, 2.5, 5_000_000, 3)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].divergence_type, "stealth_volume_accumulation")
        self.assertEqual(alerts[0].fingerprint, "SENTUSDT:neutral:stealth_volume_accumulation")

        unstable_funding = [
            _signal("binanceusdm", "SENTUSDT", 0.0003, 2.6, raw_ratio=2.6, one_hour_volume=6_000_000, recent_volumes=(1, 2, 3))
        ]
        self.assertEqual(build_stealth_volume_alerts(unstable_funding, 0.0003, 2.5, 5_000_000, 3), [])

        weak_liquidity = [
            _signal("binanceusdm", "SENTUSDT", 0.0001, 2.6, raw_ratio=2.6, one_hour_volume=4_000_000, recent_volumes=(1, 2, 3))
        ]
        self.assertEqual(build_stealth_volume_alerts(weak_liquidity, 0.0003, 2.5, 5_000_000, 3), [])

        not_increasing = [
            _signal("binanceusdm", "SENTUSDT", 0.0001, 2.6, raw_ratio=2.6, one_hour_volume=6_000_000, recent_volumes=(3, 2, 4))
        ]
        self.assertEqual(build_stealth_volume_alerts(not_increasing, 0.0003, 2.5, 5_000_000, 3), [])


def _signal(
    exchange_id: str,
    symbol: str,
    rate: float,
    ratio: float,
    raw_ratio: float | None = None,
    one_hour_volume: float | None = None,
    recent_volumes: tuple[float, ...] = (),
) -> ExchangeSignal:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    funding = _funding(symbol, rate, 10_000_000, exchange_id=exchange_id, now=now)
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
        raw_volume_ratio=raw_ratio,
        adjusted_volume_ratio=ratio,
        candle_progress=1.0,
        one_hour_quote_volume=one_hour_volume,
        recent_volumes=recent_volumes,
    )
    return ExchangeSignal(funding=funding, volume=volume)


def _funding(
    symbol: str,
    rate: float,
    volume_24h_usdt: float | None,
    exchange_id: str = "binanceusdm",
    now: datetime | None = None,
) -> FundingSnapshot:
    now = now or datetime(2026, 1, 1, tzinfo=UTC)
    return FundingSnapshot(
        exchange_id=exchange_id,
        compact_symbol=symbol,
        ccxt_symbol="BTC/USDT:USDT",
        funding_rate=rate,
        funding_source="current",
        next_funding_time=None,
        mark_price=None,
        volume_24h_usdt=volume_24h_usdt,
        timestamp=now,
        level=funding_level(rate),
        direction=funding_direction(rate),
    )


if __name__ == "__main__":
    unittest.main()
