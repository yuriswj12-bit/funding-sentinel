from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


FUNDING_LEVELS: dict[str, float] = {
    "L1": 0.0003,
    "L2": 0.0005,
    "L3": 0.0008,
    "L4": 0.0012,
}

VOLUME_LEVELS: list[tuple[str, float | None, float | None]] = [
    ("highly_expanded", 3.0, None),
    ("expanded", 2.0, 3.0),
    ("mildly_expanded", 1.3, 2.0),
    ("normal", 0.7, 1.3),
    ("mildly_contracted", 0.4, 0.7),
    ("clearly_contracted", None, 0.4),
]

EXCHANGE_IDS = ("binanceusdm", "okx", "bitget", "bybit")
TOKENIZED_STOCK_BASES = {
    "AAPL",
    "AMZN",
    "AMD",
    "BABA",
    "COIN",
    "CRCL",
    "CRWD",
    "GOOGL",
    "META",
    "MSFT",
    "MSTR",
    "NFLX",
    "NOKIA",
    "NVDA",
    "QQQ",
    "SAMSUNG",
    "SKHYNIX",
    "SPY",
    "TSLA",
    "IWM",
    "AAOI",
}


@dataclass(frozen=True)
class Settings:
    monitored_symbols: list[str] = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT", "ZECUSDT"])
    exchange_ids: tuple[str, ...] = EXCHANGE_IDS
    market_scan: bool = True
    max_candidate_symbols: int = 70
    min_24h_volume_usdt: float = 5_000_000
    prefer_negative_funding: bool = False
    negative_funding_only: bool = False
    exclude_tokenized_stocks: bool = True
    funding_levels: dict[str, float] = field(default_factory=lambda: dict(FUNDING_LEVELS))
    volume_timeframe: str = "3m"
    volume_prev_bars: int = 8
    check_interval_seconds: int = 45
    alert_cooldown_seconds: int = 45 * 60
    l4_cooldown_seconds: int = 45 * 60
    min_alert_level: str = "L1"
    sqlite_path: Path = Path("data/sentinel.sqlite3")
    tg_bot_token: str = ""
    tg_chat_id: str = ""
    tg_parse_mode: str = "Markdown"
    dry_run: bool = False
    report_enabled: bool = True
    report_interval_hours: int = 12
    report_window_hours: int = 12
    report_top_n: int = 10

    @property
    def min_alert_rank(self) -> int:
        return level_rank(self.min_alert_level)


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        monitored_symbols=_csv("MONITORED_SYMBOLS", ["BTCUSDT", "ETHUSDT", "ZECUSDT"]),
        market_scan=_bool("MARKET_SCAN", True),
        max_candidate_symbols=_int("MAX_CANDIDATE_SYMBOLS", 70),
        min_24h_volume_usdt=_float_env("MIN_24H_VOLUME_USDT", 5_000_000),
        prefer_negative_funding=_bool("PREFER_NEGATIVE_FUNDING", False),
        negative_funding_only=_bool("NEGATIVE_FUNDING_ONLY", False),
        exclude_tokenized_stocks=_bool("EXCLUDE_TOKENIZED_STOCKS", True),
        check_interval_seconds=_int("CHECK_INTERVAL_SECONDS", 45),
        alert_cooldown_seconds=_int("ALERT_COOLDOWN_SECONDS", 45 * 60),
        l4_cooldown_seconds=_int("L4_COOLDOWN_SECONDS", 45 * 60),
        sqlite_path=Path(os.getenv("SQLITE_PATH", "data/sentinel.sqlite3")),
        min_alert_level=os.getenv("MIN_ALERT_LEVEL", "L1"),
        volume_timeframe=os.getenv("VOLUME_TIMEFRAME", "3m"),
        tg_bot_token=os.getenv("TG_BOT_TOKEN", ""),
        tg_chat_id=os.getenv("TG_CHAT_ID", ""),
        dry_run=_bool("DRY_RUN", False),
        report_enabled=_bool("REPORT_ENABLED", True),
        report_interval_hours=_int("REPORT_INTERVAL_HOURS", 12),
        report_window_hours=_int("REPORT_WINDOW_HOURS", 12),
        report_top_n=_int("REPORT_TOP_N", 10),
    )


def compact_to_swap_symbol(symbol: str) -> str:
    normalized = symbol.upper().replace("-", "").replace("/", "").replace(":", "")
    if not normalized.endswith("USDT"):
        raise ValueError(f"Only USDT swap symbols are supported by default: {symbol}")
    base = normalized[:-4]
    return f"{base}/USDT:USDT"


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def level_rank(level: str | None) -> int:
    if not level:
        return 0
    return {"L1": 1, "L2": 2, "L3": 3, "L4": 4}.get(level, 0)


def funding_level(value: float, levels: dict[str, float] | None = None) -> str | None:
    thresholds = levels or FUNDING_LEVELS
    abs_value = abs(value)
    result: str | None = None
    for level, threshold in thresholds.items():
        if abs_value >= threshold:
            result = level
    return result


def funding_direction(value: float) -> str:
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"


def volume_level(ratio: float | None) -> str:
    if ratio is None:
        return "unknown"
    for name, lower, upper in VOLUME_LEVELS:
        if lower is not None and ratio < lower:
            continue
        if upper is not None and ratio >= upper:
            continue
        return name
    return "unknown"


def is_tokenized_stock_symbol(symbol: str) -> bool:
    normalized = symbol.upper()
    if not normalized.endswith("USDT"):
        return False
    base = normalized[:-4]
    return base in TOKENIZED_STOCK_BASES


def _csv(key: str, default: list[str]) -> list[str]:
    raw = os.getenv(key)
    if not raw:
        return default
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def _int(key: str, default: int) -> int:
    raw = os.getenv(key)
    return int(raw) if raw else default


def _float_env(key: str, default: float) -> float:
    raw = os.getenv(key)
    return float(raw) if raw else default


def _bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}
