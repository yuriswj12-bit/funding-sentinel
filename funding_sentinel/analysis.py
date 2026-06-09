from __future__ import annotations

from collections import defaultdict
from datetime import UTC
from zoneinfo import ZoneInfo

from funding_sentinel.config import level_rank
from funding_sentinel.models import Alert, ExchangeSignal, utc_now

CN_TZ = ZoneInfo("Asia/Shanghai")


def build_alerts(signals: list[ExchangeSignal], min_level_rank: int) -> list[Alert]:
    by_symbol: dict[str, list[ExchangeSignal]] = defaultdict(list)
    for signal in signals:
        by_symbol[signal.funding.compact_symbol].append(signal)

    alerts: list[Alert] = []
    for symbol, symbol_signals in by_symbol.items():
        alert = _build_symbol_alert(symbol, symbol_signals, min_level_rank)
        if alert:
            alerts.append(alert)
    return alerts


def _build_symbol_alert(
    symbol: str,
    signals: list[ExchangeSignal],
    min_level_rank: int,
) -> Alert | None:
    ranked = [signal for signal in signals if level_rank(signal.funding.level) >= min_level_rank]
    if not ranked:
        return None

    directions = {signal.funding.direction for signal in ranked if signal.funding.direction != "neutral"}
    extreme_by_direction: dict[str, int] = defaultdict(int)
    for signal in ranked:
        extreme_by_direction[signal.funding.direction] += 1

    primary = max(
        ranked,
        key=lambda signal: (
            level_rank(signal.funding.level),
            abs(signal.funding.funding_rate),
            signal.volume.volume_ratio if signal.volume and signal.volume.volume_ratio else 0,
        ),
    )
    divergence_type = _symbol_divergence_type(primary, signals, extreme_by_direction, directions)
    tags = _symbol_tags(ranked, divergence_type)
    direction = _dominant_direction(ranked)
    volume_ratio = _max_volume_ratio(ranked)
    volume_name = _aggregate_volume_state(ranked)
    message = format_alert_message(primary, divergence_type, tags, signals, ranked)
    fingerprint = f"{symbol}:{direction}:{divergence_type}"

    return Alert(
        compact_symbol=symbol,
        exchange_id="multi",
        level=primary.funding.level or "L0",
        direction=direction,
        funding_rate=primary.funding.funding_rate,
        funding_source=primary.funding.funding_source,
        volume_ratio=volume_ratio,
        volume_level=volume_name,
        divergence_type=divergence_type,
        signal_tags=tags,
        message=message,
        fingerprint=fingerprint,
        timestamp=utc_now(),
    )


def _symbol_divergence_type(
    primary: ExchangeSignal,
    all_signals: list[ExchangeSignal],
    extreme_by_direction: dict[str, int],
    directions: set[str],
) -> str:
    if len(directions) > 1:
        return "direction_conflict"

    same_direction_extremes = extreme_by_direction.get(primary.funding.direction, 0)
    if same_direction_extremes >= 2:
        return "multi_exchange_sync"

    other_levels = [
        level_rank(item.funding.level)
        for item in all_signals
        if item.funding.exchange_id != primary.funding.exchange_id
    ]
    if level_rank(primary.funding.level) >= 3 and all(rank < 1 for rank in other_levels):
        return "single_exchange_extreme"

    return "isolated_signal"


def _symbol_tags(ranked: list[ExchangeSignal], divergence_type: str) -> tuple[str, ...]:
    tags = [divergence_type]
    max_ratio = _max_volume_ratio(ranked)
    if max_ratio is not None:
        if max_ratio >= 2.0:
            tags.append("volume_confirmed")
        elif all(
            signal.volume and signal.volume.volume_ratio is not None and signal.volume.volume_ratio < 0.7
            for signal in ranked
        ):
            tags.append("volume_not_confirmed")
    if any(level_rank(signal.funding.level) >= 4 for signal in ranked):
        tags.append("critical_funding")
    return tuple(tags)


def _dominant_direction(ranked: list[ExchangeSignal]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for signal in ranked:
        counts[signal.funding.direction] += 1
    return max(counts, key=counts.get)


def _max_volume_ratio(ranked: list[ExchangeSignal]) -> float | None:
    ratios = [
        signal.volume.volume_ratio
        for signal in ranked
        if signal.volume and signal.volume.volume_ratio is not None
    ]
    return max(ratios) if ratios else None


def _signed_max_funding_rate(ranked: list[ExchangeSignal]) -> float:
    return max((signal.funding.funding_rate for signal in ranked), key=abs)


def _aggregate_volume_state(ranked: list[ExchangeSignal]) -> str:
    ratios = [
        signal.volume.volume_ratio
        for signal in ranked
        if signal.volume and signal.volume.volume_ratio is not None
    ]
    if not ratios:
        return "unknown"
    if max(ratios) >= 2.0:
        return "volume_confirmed"
    if max(ratios) >= 1.3:
        return "mildly_expanded"
    if all(ratio < 0.7 for ratio in ratios):
        return "clearly_contracted"
    if any(ratio < 0.7 for ratio in ratios):
        return "partly_contracted"
    return "normal"


def _volume_summary(ranked: list[ExchangeSignal]) -> str:
    max_ratio = _max_volume_ratio(ranked)
    if max_ratio is None:
        return "量能：数据不足，未形成放量确认"

    state = _aggregate_volume_state(ranked)
    state_text = {
        "volume_confirmed": "已形成放量确认",
        "mildly_expanded": "轻度放量，未形成强放量确认",
        "clearly_contracted": "整体明显缩量，未形成放量确认",
        "partly_contracted": "部分缩量，未形成放量确认",
        "normal": "整体正常，未形成放量确认",
        "unknown": "数据不足，未形成放量确认",
    }[state]
    return f"量能：最大量比 {max_ratio:.2f}x，{state_text}"


def _trigger_title(level: str, tags: tuple[str, ...]) -> str:
    rank = level_rank(level)
    if rank >= 4:
        return f"{level} 极端风险信号"
    if "volume_confirmed" in tags and rank >= 3:
        return f"{level} 高概率交易机会"
    if rank >= 3:
        return f"{level} 高优先级观察"
    if rank >= 2:
        return f"{level} 中高优先级观察"
    return f"{level} 低优先级观察"


def format_alert_message(
    primary: ExchangeSignal,
    divergence_type: str,
    tags: tuple[str, ...],
    all_signals: list[ExchangeSignal],
    ranked: list[ExchangeSignal],
) -> str:
    funding = primary.funding
    max_level = funding.level or "L0"
    signed_max_rate = _signed_max_funding_rate(ranked) * 100
    hot_exchanges = ", ".join(_exchange_name(signal.funding.exchange_id) for signal in ranked)
    event_time = utc_now().astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M:%S CST")
    exchange_lines = []

    for item in sorted(all_signals, key=lambda value: value.funding.exchange_id):
        rate_pct = item.funding.funding_rate * 100
        level = item.funding.level or "L0"
        vol_ratio = "n/a" if not item.volume or item.volume.volume_ratio is None else f"{item.volume.volume_ratio:.2f}x"
        direction = _zh_direction(item.funding.direction)
        volume_state = _zh_volume_level(item.volume.volume_level) if item.volume else "未知"
        exchange_lines.append(
            f"- {_exchange_name(item.funding.exchange_id)}: {rate_pct:+.4f}% {level} "
            f"{direction}, 量比 {vol_ratio} {volume_state}"
        )

    return "\n".join(
        [
            "【资金费率哨兵告警】",
            "",
            f"🪖 触发级别：{_trigger_title(max_level, tags)}",
            "",
            f"币种：{funding.compact_symbol}",
            f"触发类型：{_zh_divergence_type(divergence_type)}",
            f"触发平台：{hot_exchanges}",
            f"最大资金费率：{signed_max_rate:+.4f}%",
            _volume_summary(ranked),
            "",
            "📊 多平台快照",
            *exchange_lines,
            "",
            f"🕒 时间：{event_time}",
            f"💡 信号说明：{_signal_explanation(divergence_type, _dominant_direction(ranked), tags)}",
            "",
            f"⚠️ 观察建议：{_observation_advice(tags)}",
        ]
    )


def _signal_explanation(divergence_type: str, direction: str, tags: tuple[str, ...]) -> str:
    direction_text = "负费率" if direction == "negative" else "正费率"
    if divergence_type == "multi_exchange_sync":
        base = f"多平台{direction_text}同步进入极端区间，说明同方向持仓成本显著上升，市场仓位可能正在拥挤。"
    elif divergence_type == "single_exchange_extreme":
        base = f"单个平台{direction_text}明显偏离其他平台，可能存在局部仓位拥挤或平台特异性资金行为。"
    elif divergence_type == "direction_conflict":
        base = "平台之间资金费率方向冲突，说明不同交易所仓位结构分歧较大。"
    else:
        base = f"{direction_text}达到监控阈值，但暂未形成更强的跨平台共振。"

    if "volume_confirmed" in tags:
        return base + " 当前已有放量确认，信号优先级提高。"
    return base + " 当前量能未确认，暂不视为完整趋势信号。"


def _observation_advice(tags: tuple[str, ...]) -> str:
    if "volume_confirmed" in tags:
        return "重点观察价格是否顺着费率方向放量突破/跌破关键位，入场仍需结合结构和止损。"
    return "等待价格与成交量确认；若放量跌破/突破关键位，偏趋势延续；若价格拒绝延续并快速反向，警惕拥挤仓位被挤压。"


def _exchange_name(value: str) -> str:
    return {
        "binanceusdm": "Binance",
        "okx": "OKX",
        "bitget": "Bitget",
        "bybit": "Bybit",
        "multi": "多平台",
    }.get(value, value)


def _zh_direction(value: str) -> str:
    return {
        "positive": "正费率",
        "negative": "负费率",
        "neutral": "中性",
    }.get(value, value)


def _zh_volume_level(value: str) -> str:
    return {
        "highly_expanded": "高度异常放量",
        "expanded": "异常放量",
        "mildly_expanded": "轻度放量",
        "normal": "正常",
        "mildly_contracted": "轻度缩量",
        "clearly_contracted": "明显缩量",
        "insufficient_data": "数据不足",
        "unknown": "未知",
    }.get(value, value)


def _zh_divergence_type(value: str) -> str:
    return {
        "single_exchange_extreme": "单平台极端",
        "multi_exchange_sync": "多平台同步",
        "direction_conflict": "平台方向冲突",
        "isolated_signal": "孤立信号",
    }.get(value, value)
