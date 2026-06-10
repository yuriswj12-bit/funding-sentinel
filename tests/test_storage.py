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

    def test_l4_uses_45_minute_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "sentinel.sqlite3")
            first = _alert("L4", datetime(2026, 1, 1, tzinfo=UTC))
            storage.mark_alert_sent(first, delivered=True)

            repeated = _alert("L4", datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=44))
            self.assertFalse(storage.should_send_alert(repeated, cooldown_seconds=2700, l4_cooldown_seconds=2700))

            cooled_down = _alert("L4", datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=45, seconds=1))
            self.assertTrue(storage.should_send_alert(cooled_down, cooldown_seconds=2700, l4_cooldown_seconds=2700))
            storage.close()

    def test_volume_confirmation_upgrade_bypasses_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "sentinel.sqlite3")
            first = _alert("L4", datetime(2026, 1, 1, tzinfo=UTC), volume_confirmed=False)
            storage.mark_alert_sent(first, delivered=True)

            upgraded = _alert(
                "L4",
                datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=10),
                volume_confirmed=True,
            )
            self.assertTrue(storage.should_send_alert(upgraded, cooldown_seconds=2700, l4_cooldown_seconds=2700))

            storage.mark_alert_sent(upgraded, delivered=True)
            repeated = _alert(
                "L4",
                datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=20),
                volume_confirmed=True,
            )
            self.assertFalse(storage.should_send_alert(repeated, cooldown_seconds=2700, l4_cooldown_seconds=2700))
            storage.close()

def _alert(level: str, timestamp: datetime, volume_confirmed: bool = False) -> Alert:
    tags = ["single_exchange_extreme"]
    if volume_confirmed:
        tags.append("volume_confirmed")
    return Alert(
        compact_symbol="BTCUSDT",
        exchange_id="binanceusdm",
        level=level,
        direction="positive",
        funding_rate=0.001,
        funding_source="current",
        volume_ratio=2.0 if volume_confirmed else 1.0,
        volume_level="volume_confirmed" if volume_confirmed else "normal",
        divergence_type="single_exchange_extreme",
        signal_tags=tuple(tags),
        message="test",
        fingerprint="BTCUSDT:binanceusdm:positive",
        timestamp=timestamp,
    )


if __name__ == "__main__":
    unittest.main()
