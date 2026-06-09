from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from funding_sentinel.models import Alert
from funding_sentinel.report import REPORT_NAME, maybe_build_periodic_report
from funding_sentinel.storage import Storage


class ReportTests(unittest.TestCase):
    def test_periodic_report_ranks_and_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "sentinel.sqlite3")
            now = datetime(2026, 1, 1, 12, tzinfo=UTC)
            storage.mark_alert_sent(_alert("SENTUSDT", "L4", -0.006, 1.0, ("multi_exchange_sync",)), True)
            storage.mark_alert_sent(_alert("COSUSDT", "L3", -0.001, 5.0, ("single_exchange_extreme", "volume_confirmed")), True)
            storage.mark_alert_sent(_alert("SENTUSDT", "L3", -0.001, 1.0, ("single_exchange_extreme",)), True)

            report = maybe_build_periodic_report(
                storage,
                now=now,
                interval_hours=12,
                window_hours=12,
                top_n=10,
                min_level_rank=3,
                negative_funding_only=False,
            )
            self.assertIsNotNone(report)
            assert report is not None
            self.assertIn("SENTUSDT", report)
            self.assertIn("COSUSDT", report)
            self.assertEqual(report.count("SENTUSDT"), 1)
            storage.close()

    def test_dry_run_report_does_not_mark_sent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "sentinel.sqlite3")
            now = datetime(2026, 1, 1, 12, tzinfo=UTC)
            storage.mark_alert_sent(_alert("SENTUSDT", "L4", -0.006, 1.0, ("multi_exchange_sync",)), True)
            report = maybe_build_periodic_report(
                storage,
                now=now,
                interval_hours=12,
                window_hours=12,
                top_n=10,
                min_level_rank=3,
                negative_funding_only=False,
                mark_sent=False,
            )
            self.assertIsNotNone(report)
            self.assertTrue(storage.should_send_report(REPORT_NAME, 12 * 60 * 60, now + timedelta(minutes=1)))
            storage.close()


def _alert(
    symbol: str,
    level: str,
    funding_rate: float,
    volume_ratio: float,
    tags: tuple[str, ...],
) -> Alert:
    return Alert(
        compact_symbol=symbol,
        exchange_id="multi",
        level=level,
        direction="negative" if funding_rate < 0 else "positive",
        funding_rate=funding_rate,
        funding_source="current",
        volume_ratio=volume_ratio,
        volume_level="volume_confirmed" if volume_ratio >= 2 else "normal",
        divergence_type=tags[0],
        signal_tags=tags,
        message="test",
        fingerprint=f"{symbol}:negative:{tags[0]}",
        timestamp=datetime(2026, 1, 1, 11, tzinfo=UTC),
    )


if __name__ == "__main__":
    unittest.main()
