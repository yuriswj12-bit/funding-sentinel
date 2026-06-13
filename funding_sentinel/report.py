from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from sqlite3 import Row
from zoneinfo import ZoneInfo

from funding_sentinel.config import is_excluded_market_symbol, level_rank
from funding_sentinel.storage import Storage

CN_TZ = ZoneInfo("Asia/Shanghai")
REPORT_NAME = "funding_sentinel_periodic"


@dataclass(frozen=True)
class ReportCandidate:
    compact_symbol: str
    level: str
    direction: str
    funding_rate: float
    volume_ratio: float | None
    volume_level: str
    divergence_type: str
    signal_tags: tuple[str, ...]
    timestamp: datetime

    @property
    def score(self) -> tuple[int, int, int, float, float]:
        return (
            level_rank(self.level),
            1 if "volume_confirmed" in self.signal_tags else 0,
            1 if self.divergence_type == "multi_exchange_sync" else 0,
            abs(self.funding_rate),
            self.volume_ratio or 0.0,
        )


def maybe_build_periodic_report(
    storage: Storage,
    *,
    now: datetime,
    interval_hours: int,
    window_hours: int,
    top_n: int,
    min_level_rank: int,
    negative_funding_only: bool = True,
    exclude_tokenized_stocks: bool = True,
    exclude_major_spot_symbols: bool = True,
    exclude_stablecoins: bool = True,
    mark_sent: bool = True,
) -> str | None:
    interval_seconds = interval_hours * 60 * 60
    if not storage.should_send_report(REPORT_NAME, interval_seconds, now):
        return None

    since = now - timedelta(hours=window_hours)
    rows = storage.fetch_recent_alerts(since, min_level_rank)
    if mark_sent:
        storage.mark_report_sent(REPORT_NAME, now)
    if not rows:
        return None

    candidates = [
        candidate
        for candidate in (_row_to_candidate(row) for row in rows)
        if _passes_report_filters(
            candidate,
            negative_funding_only,
            exclude_tokenized_stocks,
            exclude_major_spot_symbols,
            exclude_stablecoins,
        )
    ]
    if not candidates:
        return None
    candidates = _dedupe_candidates(candidates)
    candidates = sorted(candidates, key=lambda item: item.score, reverse=True)[:top_n]
    return format_periodic_report(candidates, now=now, window_hours=window_hours)


def _passes_report_filters(
    candidate: ReportCandidate,
    negative_funding_only: bool,
    exclude_tokenized_stocks: bool,
    exclude_major_spot_symbols: bool,
    exclude_stablecoins: bool,
) -> bool:
    if negative_funding_only and candidate.funding_rate >= 0:
        return False
    if is_excluded_market_symbol(
        candidate.compact_symbol,
        exclude_tokenized_stocks=exclude_tokenized_stocks,
        exclude_major_spot_symbols=exclude_major_spot_symbols,
        exclude_stablecoins=exclude_stablecoins,
    ):
        return False
    return True


def format_periodic_report(
    candidates: list[ReportCandidate],
    *,
    now: datetime,
    window_hours: int,
) -> str:
    local_time = now.astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M:%S CST")
    lines = [
        "【资金费率哨兵周期报告】",
        "",
        f"统计窗口：过去 {window_hours} 小时",
        f"强信号数量：{len(candidates)}",
        f"生成时间：{local_time}",
        "",
        "📌 Top Signals",
    ]
    for index, item in enumerate(candidates, start=1):
        direction = "负费率" if item.direction == "negative" else "正费率"
        volume_ratio = "n/a" if item.volume_ratio is None else f"{item.volume_ratio:.2f}x"
        tags = _zh_tags(item.signal_tags)
        lines.append(
            f"{index}. {item.compact_symbol} | {item.level} {direction} | "
            f"{item.funding_rate * 100:+.4f}% | 量比 {volume_ratio} | "
            f"{_zh_divergence_type(item.divergence_type)} | {tags}"
        )
    lines.extend(
        [
            "",
            "观察建议：优先复盘 L4、多平台同步、且量能已确认的标的；量能未确认的极端费率更适合作为观察名单。",
        ]
    )
    return "\n".join(lines)


def _dedupe_candidates(candidates) -> list[ReportCandidate]:
    by_symbol: dict[str, ReportCandidate] = {}
    for candidate in candidates:
        current = by_symbol.get(candidate.compact_symbol)
        if current is None or candidate.score > current.score:
            by_symbol[candidate.compact_symbol] = candidate
    return list(by_symbol.values())


def _row_to_candidate(row: Row) -> ReportCandidate:
    return ReportCandidate(
        compact_symbol=row["compact_symbol"],
        level=row["level"],
        direction=row["direction"],
        funding_rate=float(row["funding_rate"]),
        volume_ratio=row["volume_ratio"],
        volume_level=row["volume_level"],
        divergence_type=row["divergence_type"],
        signal_tags=tuple(tag for tag in str(row["signal_tags"]).split(",") if tag),
        timestamp=_parse_dt(row["timestamp"]),
    )


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _zh_divergence_type(value: str) -> str:
    return {
        "single_exchange_extreme": "单平台极端",
        "multi_exchange_sync": "多平台同步",
        "direction_conflict": "方向冲突",
        "isolated_signal": "孤立信号",
    }.get(value, value)


def _zh_tags(tags: tuple[str, ...]) -> str:
    mapping = {
        "volume_confirmed": "放量确认",
        "volume_not_confirmed": "量能未确认",
        "critical_funding": "极端费率",
        "multi_exchange_sync": "多平台同步",
        "single_exchange_extreme": "单平台极端",
        "direction_conflict": "方向冲突",
        "isolated_signal": "孤立信号",
    }
    return ", ".join(mapping.get(tag, tag) for tag in tags)
