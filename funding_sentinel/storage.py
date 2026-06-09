from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from funding_sentinel.config import level_rank
from funding_sentinel.models import Alert, FundingSnapshot, VolumeSnapshot


class Storage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def insert_funding(self, snapshot: FundingSnapshot) -> None:
        self.conn.execute(
            """
            INSERT INTO funding_snapshots (
                timestamp, exchange_id, compact_symbol, ccxt_symbol, funding_rate,
                funding_source, next_funding_time, mark_price, volume_24h_usdt, level, direction
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _dt(snapshot.timestamp),
                snapshot.exchange_id,
                snapshot.compact_symbol,
                snapshot.ccxt_symbol,
                snapshot.funding_rate,
                snapshot.funding_source,
                _dt(snapshot.next_funding_time),
                snapshot.mark_price,
                snapshot.volume_24h_usdt,
                snapshot.level,
                snapshot.direction,
            ),
        )
        self.conn.commit()

    def insert_volume(self, snapshot: VolumeSnapshot) -> None:
        self.conn.execute(
            """
            INSERT INTO volume_snapshots (
                timestamp, exchange_id, compact_symbol, ccxt_symbol, timeframe,
                current_volume, previous_average_volume, volume_ratio,
                volume_level, candle_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _dt(snapshot.timestamp),
                snapshot.exchange_id,
                snapshot.compact_symbol,
                snapshot.ccxt_symbol,
                snapshot.timeframe,
                snapshot.current_volume,
                snapshot.previous_average_volume,
                snapshot.volume_ratio,
                snapshot.volume_level,
                _dt(snapshot.candle_timestamp),
            ),
        )
        self.conn.commit()

    def should_send_alert(
        self,
        alert: Alert,
        cooldown_seconds: int,
        l4_cooldown_seconds: int,
    ) -> bool:
        row = self.conn.execute(
            "SELECT last_sent_at, last_level FROM alert_state WHERE fingerprint = ?",
            (alert.fingerprint,),
        ).fetchone()
        if row is None:
            return True

        last_sent_at = _parse_dt(row["last_sent_at"])
        last_level = row["last_level"]
        if level_rank(alert.level) > level_rank(last_level):
            return True

        cooldown = l4_cooldown_seconds if alert.level == "L4" else cooldown_seconds
        elapsed = (alert.timestamp - last_sent_at).total_seconds()
        return elapsed >= cooldown

    def mark_alert_sent(self, alert: Alert, delivered: bool, error: str | None = None) -> None:
        self.conn.execute(
            """
            INSERT INTO alerts (
                timestamp, compact_symbol, exchange_id, level, direction,
                funding_rate, funding_source, volume_ratio, volume_level,
                divergence_type, signal_tags, fingerprint, message, delivered, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _dt(alert.timestamp),
                alert.compact_symbol,
                alert.exchange_id,
                alert.level,
                alert.direction,
                alert.funding_rate,
                alert.funding_source,
                alert.volume_ratio,
                alert.volume_level,
                alert.divergence_type,
                ",".join(alert.signal_tags),
                alert.fingerprint,
                alert.message,
                1 if delivered else 0,
                error,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO alert_state (fingerprint, last_sent_at, last_level)
            VALUES (?, ?, ?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                last_sent_at = excluded.last_sent_at,
                last_level = excluded.last_level
            """,
            (alert.fingerprint, _dt(alert.timestamp), alert.level),
        )
        self.conn.commit()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS funding_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                exchange_id TEXT NOT NULL,
                compact_symbol TEXT NOT NULL,
                ccxt_symbol TEXT NOT NULL,
                funding_rate REAL NOT NULL,
                funding_source TEXT NOT NULL,
                next_funding_time TEXT,
                mark_price REAL,
                volume_24h_usdt REAL,
                level TEXT,
                direction TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS volume_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                exchange_id TEXT NOT NULL,
                compact_symbol TEXT NOT NULL,
                ccxt_symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                current_volume REAL,
                previous_average_volume REAL,
                volume_ratio REAL,
                volume_level TEXT NOT NULL,
                candle_timestamp TEXT
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                compact_symbol TEXT NOT NULL,
                exchange_id TEXT NOT NULL,
                level TEXT NOT NULL,
                direction TEXT NOT NULL,
                funding_rate REAL NOT NULL,
                funding_source TEXT NOT NULL,
                volume_ratio REAL,
                volume_level TEXT NOT NULL,
                divergence_type TEXT NOT NULL,
                signal_tags TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                message TEXT NOT NULL,
                delivered INTEGER NOT NULL,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS alert_state (
                fingerprint TEXT PRIMARY KEY,
                last_sent_at TEXT NOT NULL,
                last_level TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_funding_symbol_time
                ON funding_snapshots (compact_symbol, timestamp);
            CREATE INDEX IF NOT EXISTS idx_alerts_symbol_time
                ON alerts (compact_symbol, timestamp);
            """
        )
        columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(funding_snapshots)").fetchall()
        }
        if "volume_24h_usdt" not in columns:
            self.conn.execute("ALTER TABLE funding_snapshots ADD COLUMN volume_24h_usdt REAL")
        self.conn.commit()


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat()


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
