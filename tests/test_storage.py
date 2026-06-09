from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from funding_sentinel.models import Alert
from funding_sentinel.storage import Storage


class StorageTests(unittest.TestCase):
    def test_alert_cooldown_and_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "sentinel.sqlite3")
            first = _alert("L2", datetime(2026, 1, 1, tzinfo=UTC))
            self.assertTrue(storage.should_send_alert(first, cooldown_seconds=900, l4_cooldown_seconds=300))
            storage.mark_alert_sent(first, delivered=True)

            repeated = _alert("L2", datetime(2026, 1, 1, 0, 5, tzinfo=UTC))
            self.assertFalse(storage.should_send_alert(repeated, cooldown_seconds=900, l4_cooldown_seconds=300))

            upgraded = _alert("L3", datetime(2026, 1, 1, 0, 6, tzinfo=UTC))
            self.assertTrue(storage.should_send_alert(upgraded, cooldown_seconds=900, l4_cooldown_seconds=300))
            storage.close()

    def test_l4_shorter_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "sentinel.sqlite3")
            first = _alert("L4", datetime(2026, 1, 1, tzinfo=UTC))
            storage.mark_alert_sent(first, delivered=True)

            repeated = _alert("L4", datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=301))
            self.assertTrue(storage.should_send_alert(repeated, cooldown_seconds=900, l4_cooldown_seconds=300))
            storage.close()


def _alert(level: str, timestamp: datetime) -> Alert:
    return Alert(
        compact_symbol="BTCUSDT",
        exchange_id="binanceusdm",
        level=level,
        direction="positive",
        funding_rate=0.001,
        funding_source="current",
        volume_ratio=2.0,
        volume_level="expanded",
        divergence_type="single_exchange_extreme",
        signal_tags=("single_exchange_extreme",),
        message="test",
        fingerprint="BTCUSDT:binanceusdm:positive",
        timestamp=timestamp,
    )


if __name__ == "__main__":
    unittest.main()
