from __future__ import annotations

import asyncio
import argparse
import logging
import signal
from contextlib import suppress
from dataclasses import replace

from funding_sentinel.analysis import build_alerts
from funding_sentinel.config import Settings, is_tokenized_stock_symbol, level_rank, load_settings
from funding_sentinel.exchanges.ccxt_client import CcxtExchangeClient, close_all
from funding_sentinel.models import Alert, ExchangeSignal, FundingSnapshot, utc_now
from funding_sentinel.notifier import TelegramNotifier
from funding_sentinel.report import maybe_build_periodic_report
from funding_sentinel.storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main(settings: Settings | None = None) -> None:
    settings = settings or load_settings()
    storage = Storage(settings.sqlite_path)
    notifier = TelegramNotifier(settings.tg_bot_token, settings.tg_chat_id, settings.tg_parse_mode)
    clients = [CcxtExchangeClient(exchange_id, settings.funding_levels) for exchange_id in settings.exchange_ids]
    stop_event = asyncio.Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            asyncio.get_running_loop().add_signal_handler(sig, stop_event.set)

    try:
        while not stop_event.is_set():
            await run_once(settings, clients, storage, notifier)
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=settings.check_interval_seconds)
    finally:
        await close_all(clients)
        storage.close()


async def main_once(settings: Settings | None = None) -> None:
    settings = settings or load_settings()
    storage = Storage(settings.sqlite_path)
    notifier = TelegramNotifier(settings.tg_bot_token, settings.tg_chat_id, settings.tg_parse_mode)
    clients = [CcxtExchangeClient(exchange_id, settings.funding_levels) for exchange_id in settings.exchange_ids]
    try:
        await run_once(settings, clients, storage, notifier)
    finally:
        await close_all(clients)
        storage.close()


async def run_once(
    settings: Settings,
    clients: list[CcxtExchangeClient],
    storage: Storage,
    notifier: TelegramNotifier,
) -> None:
    if settings.market_scan:
        symbols, funding_cache, supported_symbols = await _discover_market_candidates(settings, clients)
        logger.info("Starting market scan for %s candidate symbols", len(symbols))
    else:
        symbols = settings.monitored_symbols
        funding_cache = {}
        supported_symbols = {client.exchange_id: set(symbols) for client in clients}
        logger.info("Starting configured scan for %s", ", ".join(symbols))

    if not symbols:
        logger.info("No candidate symbols found")
        return

    tasks = [
        _collect_signal(client, compact_symbol, settings, funding_cache)
        for compact_symbol in symbols
        for client in clients
        if compact_symbol in supported_symbols.get(client.exchange_id, set())
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    signals: list[ExchangeSignal] = []

    for result in results:
        if isinstance(result, Exception):
            logger.warning("Collection failed: %r", result)
            continue
        signals.append(result)
        storage.insert_funding(result.funding)
        if result.volume:
            storage.insert_volume(result.volume)

    alerts = build_alerts(signals, settings.min_alert_rank)
    logger.info("Scan produced %s signals and %s candidate alerts", len(signals), len(alerts))

    for alert in alerts:
        is_volume_upgrade = storage.is_volume_confirmation_upgrade(alert)
        if not storage.should_send_alert(alert, settings.alert_cooldown_seconds, settings.l4_cooldown_seconds):
            continue
        if is_volume_upgrade:
            alert = _with_volume_upgrade_notice(alert, settings.volume_timeframe)
        if settings.dry_run:
            logger.info("Dry-run alert:\n%s", alert.message)
            continue
        delivered, error = notifier.send(alert.message)
        storage.mark_alert_sent(alert, delivered=delivered, error=error)
        if error:
            logger.info("Alert recorded with delivery status: %s", error)

    if settings.report_enabled:
        report = maybe_build_periodic_report(
            storage,
            now=utc_now(),
            interval_hours=settings.report_interval_hours,
            window_hours=settings.report_window_hours,
            top_n=settings.report_top_n,
            min_level_rank=settings.min_alert_rank,
            negative_funding_only=settings.negative_funding_only,
            exclude_tokenized_stocks=settings.exclude_tokenized_stocks,
            mark_sent=not settings.dry_run,
        )
        if report:
            if settings.dry_run:
                logger.info("Dry-run report:\n%s", report)
            else:
                delivered, error = notifier.send(report)
                if error:
                    logger.info("Report delivery status: %s", error)


async def _collect_signal(
    client: CcxtExchangeClient,
    compact_symbol: str,
    settings: Settings,
    funding_cache: dict[tuple[str, str], FundingSnapshot] | None = None,
) -> ExchangeSignal:
    cached_funding = (funding_cache or {}).get((client.exchange_id, compact_symbol))
    if cached_funding:
        funding = cached_funding
        volume = await client.fetch_volume_snapshot(compact_symbol, settings.volume_timeframe, settings.volume_prev_bars)
    else:
        funding, volume = await asyncio.gather(
            client.fetch_funding_snapshot(compact_symbol),
            client.fetch_volume_snapshot(compact_symbol, settings.volume_timeframe, settings.volume_prev_bars),
        )
    return ExchangeSignal(funding=funding, volume=volume)


async def _discover_market_candidates(
    settings: Settings,
    clients: list[CcxtExchangeClient],
) -> tuple[list[str], dict[tuple[str, str], FundingSnapshot], dict[str, set[str]]]:
    funding_results = await asyncio.gather(
        *(client.fetch_market_funding_snapshots() for client in clients),
        return_exceptions=True,
    )
    symbol_results = await asyncio.gather(
        *(client.fetch_market_symbols() for client in clients),
        return_exceptions=True,
    )
    funding_cache: dict[tuple[str, str], FundingSnapshot] = {}
    supported_symbols: dict[str, set[str]] = {}
    severity_by_symbol: dict[str, tuple[int, int, float, float]] = {}

    for client, result in zip(clients, symbol_results, strict=True):
        if isinstance(result, Exception):
            logger.warning("Market symbol discovery failed for %s: %r", client.exchange_id, result)
            supported_symbols[client.exchange_id] = set()
        else:
            supported_symbols[client.exchange_id] = result

    for client, result in zip(clients, funding_results, strict=True):
        if isinstance(result, Exception):
            logger.warning("Market funding discovery failed for %s: %r", client.exchange_id, result)
            continue
        logger.info("Discovered %s funding snapshots from %s", len(result), client.exchange_id)
        for snapshot in result:
            funding_cache[(client.exchange_id, snapshot.compact_symbol)] = snapshot
            if settings.exclude_tokenized_stocks and is_tokenized_stock_symbol(snapshot.compact_symbol):
                continue
            if settings.negative_funding_only and snapshot.funding_rate >= 0:
                continue
            if not _passes_24h_volume_filter(snapshot, settings):
                continue
            rank = level_rank(snapshot.level)
            if rank < settings.min_alert_rank:
                continue
            negative_priority = 1 if settings.prefer_negative_funding and snapshot.funding_rate < 0 else 0
            score = (
                rank,
                negative_priority,
                abs(snapshot.funding_rate),
                snapshot.volume_24h_usdt or 0.0,
            )
            if score > severity_by_symbol.get(snapshot.compact_symbol, (0, 0, 0.0, 0.0)):
                severity_by_symbol[snapshot.compact_symbol] = score

    sorted_symbols = sorted(
        severity_by_symbol,
        key=lambda symbol: severity_by_symbol[symbol],
        reverse=True,
    )
    if settings.max_candidate_symbols > 0:
        sorted_symbols = sorted_symbols[: settings.max_candidate_symbols]
    logger.info(
        "Market discovery selected %s symbols from %s threshold hits",
        len(sorted_symbols),
        len(severity_by_symbol),
    )
    if sorted_symbols:
        logger.info("Market candidates: %s", ", ".join(sorted_symbols))
    return sorted_symbols, funding_cache, supported_symbols


def _passes_24h_volume_filter(snapshot: FundingSnapshot, settings: Settings) -> bool:
    if settings.min_24h_volume_usdt <= 0:
        return True
    if snapshot.volume_24h_usdt is None:
        return False
    return snapshot.volume_24h_usdt >= settings.min_24h_volume_usdt


def _with_volume_upgrade_notice(alert: Alert, timeframe: str) -> Alert:
    tags = tuple(dict.fromkeys((*alert.signal_tags, "volume_confirmation_upgrade")))
    message = "\n".join(
        [
            f"🚨【重点关注：{timeframe} 放量确认升级】",
            "上一条信号量能未确认，现在已出现放量确认，请重新检查价格结构和突破/跌破位置。",
            "",
            alert.message,
        ]
    )
    return replace(alert, signal_tags=tags, message=message)


def run() -> None:
    parser = argparse.ArgumentParser(description="Crypto funding and volume anomaly monitor.")
    parser.add_argument("--once", action="store_true", help="Run one scan and exit.")
    args = parser.parse_args()
    if args.once:
        asyncio.run(main_once())
    else:
        asyncio.run(main())


if __name__ == "__main__":
    run()
