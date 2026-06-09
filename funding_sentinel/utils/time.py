from __future__ import annotations

from datetime import UTC, datetime


def from_ms(value: int | float | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value) / 1000, tz=UTC)

