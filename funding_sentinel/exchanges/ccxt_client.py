from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from funding_sentinel.config import funding_direction, funding_level, volume_level
from funding_sentinel.models import FundingSnapshot, VolumeSnapshot, utc_now
from funding_sentinel.utils.time import from_ms

logger = logging.getLogger(__name__)


class CcxtExchangeClient:
    """Public REST client.

    The class name is kept so the rest of the app does not change. Direct REST is
    used because ccxt market loading can be slow or fail when an exchange tries
    to preload unrelated spot/option markets.
    """

    def __init__(self, exchange_id: str, funding_levels: dict[str, float]) -> None:
        self.exchange_id = exchange_id
        self.funding_levels = funding_levels

    async def close(self) -> None:
        return None

    async def fetch_funding_snapshot(self, compact_symbol: str) -> FundingSnapshot:
        raw = await asyncio.to_thread(_fetch_funding, self.exchange_id, compact_symbol)
        return self._funding_snapshot_from_raw(compact_symbol, raw)

    async def fetch_market_funding_snapshots(self) -> list[FundingSnapshot]:
        raws = await asyncio.to_thread(_fetch_market_funding, self.exchange_id)
        return [self._funding_snapshot_from_raw(raw["compact_symbol"], raw) for raw in raws]

    async def fetch_market_symbols(self) -> set[str]:
        return await asyncio.to_thread(_fetch_market_symbols, self.exchange_id)

    def _funding_snapshot_from_raw(self, compact_symbol: str, raw: dict[str, Any]) -> FundingSnapshot:
        rate = raw["funding_rate"]
        return FundingSnapshot(
            exchange_id=self.exchange_id,
            compact_symbol=compact_symbol,
            ccxt_symbol=raw["venue_symbol"],
            funding_rate=rate,
            funding_source=raw["funding_source"],
            next_funding_time=from_ms(raw.get("next_funding_time")),
            mark_price=raw.get("mark_price"),
            volume_24h_usdt=raw.get("volume_24h_usdt"),
            timestamp=from_ms(raw.get("timestamp")) or utc_now(),
            level=funding_level(rate, self.funding_levels),
            direction=funding_direction(rate),
        )

    async def fetch_volume_snapshot(
        self,
        compact_symbol: str,
        timeframe: str,
        previous_bars: int,
    ) -> VolumeSnapshot:
        rows = await asyncio.to_thread(_fetch_ohlcv, self.exchange_id, compact_symbol, timeframe, previous_bars + 1)
        return self._volume_snapshot_from_rows(compact_symbol, timeframe, previous_bars, rows)

    async def fetch_volume_trend_snapshot(
        self,
        compact_symbol: str,
        timeframe: str,
        previous_bars: int,
        trend_bars: int,
    ) -> VolumeSnapshot:
        limit = max(previous_bars + 1, trend_bars, 4)
        rows = await asyncio.to_thread(_fetch_ohlcv, self.exchange_id, compact_symbol, timeframe, limit)
        return self._volume_snapshot_from_rows(compact_symbol, timeframe, previous_bars, rows, trend_bars=trend_bars)

    def _volume_snapshot_from_rows(
        self,
        compact_symbol: str,
        timeframe: str,
        previous_bars: int,
        rows: list[dict[str, float | int]],
        trend_bars: int = 0,
    ) -> VolumeSnapshot:
        timestamp = utc_now()
        if len(rows) < previous_bars + 1:
            return VolumeSnapshot(
                exchange_id=self.exchange_id,
                compact_symbol=compact_symbol,
                ccxt_symbol=_venue_symbol(self.exchange_id, compact_symbol),
                timeframe=timeframe,
                current_volume=None,
                previous_average_volume=None,
                volume_ratio=None,
                volume_level="insufficient_data",
                candle_timestamp=None,
                timestamp=timestamp,
            )

        rows = sorted(rows, key=lambda row: row["timestamp"])
        current = rows[-1]
        previous = rows[-(previous_bars + 1) : -1]
        current_volume = current["volume"]
        progress = _candle_progress(current["timestamp"], timeframe, timestamp)
        adjusted_current_volume = _progress_adjusted_volume(current_volume, progress)
        previous_volumes = [row["volume"] for row in previous if row["volume"] is not None]
        previous_average = sum(previous_volumes) / len(previous_volumes) if previous_volumes else None
        raw_ratio = current_volume / previous_average if current_volume is not None and previous_average else None
        adjusted_ratio = (
            adjusted_current_volume / previous_average
            if adjusted_current_volume is not None and previous_average
            else None
        )
        ratio = _confirmation_volume_ratio(raw_ratio, adjusted_ratio, progress)
        one_hour_quote_volume = _one_hour_quote_volume(rows)
        recent_volumes = tuple(
            row["volume"]
            for row in rows[-trend_bars:]
            if trend_bars > 0 and row.get("volume") is not None
        )

        return VolumeSnapshot(
            exchange_id=self.exchange_id,
            compact_symbol=compact_symbol,
            ccxt_symbol=_venue_symbol(self.exchange_id, compact_symbol),
            timeframe=timeframe,
            current_volume=current_volume,
            previous_average_volume=previous_average,
            volume_ratio=ratio,
            volume_level=volume_level(ratio),
            candle_timestamp=from_ms(current["timestamp"]),
            timestamp=timestamp,
            raw_volume_ratio=raw_ratio,
            adjusted_volume_ratio=adjusted_ratio,
            candle_progress=progress,
            one_hour_quote_volume=one_hour_quote_volume,
            recent_volumes=recent_volumes,
        )


async def close_all(clients: list[CcxtExchangeClient]) -> None:
    await asyncio.gather(*(client.close() for client in clients), return_exceptions=True)


def _fetch_funding(exchange_id: str, compact_symbol: str) -> dict[str, Any]:
    if exchange_id == "binanceusdm":
        data = _get_json("https://fapi.binance.com/fapi/v1/premiumIndex", {"symbol": compact_symbol})
        return {
            "venue_symbol": compact_symbol,
            "funding_rate": _float(data["lastFundingRate"]),
            "funding_source": "current",
            "next_funding_time": _int(data.get("nextFundingTime")),
            "mark_price": _float(data.get("markPrice")),
            "volume_24h_usdt": None,
            "timestamp": _int(data.get("time")),
        }

    if exchange_id == "okx":
        venue_symbol = _venue_symbol(exchange_id, compact_symbol)
        data = _get_json("https://www.okx.com/api/v5/public/funding-rate", {"instId": venue_symbol})
        item = data["data"][0]
        next_rate = _float(item.get("nextFundingRate"))
        current_rate = _float(item["fundingRate"])
        return {
            "venue_symbol": venue_symbol,
            "funding_rate": next_rate if next_rate is not None else current_rate,
            "funding_source": "predicted" if next_rate is not None else "current",
            "next_funding_time": _int(item.get("nextFundingTime") or item.get("fundingTime")),
            "mark_price": None,
            "volume_24h_usdt": None,
            "timestamp": _int(item.get("ts")),
        }

    if exchange_id == "bitget":
        data = _get_json(
            "https://api.bitget.com/api/v2/mix/market/current-fund-rate",
            {"symbol": compact_symbol, "productType": "USDT-FUTURES"},
        )
        item = data["data"][0]
        return {
            "venue_symbol": compact_symbol,
            "funding_rate": _float(item["fundingRate"]),
            "funding_source": "current",
            "next_funding_time": _int(item.get("nextUpdate")),
            "mark_price": None,
            "volume_24h_usdt": None,
            "timestamp": _int(data.get("requestTime")),
        }

    if exchange_id == "bybit":
        data = _get_json(
            "https://api.bybit.com/v5/market/tickers",
            {"category": "linear", "symbol": compact_symbol},
        )
        item = data["result"]["list"][0]
        return {
            "venue_symbol": compact_symbol,
            "funding_rate": _float(item["fundingRate"]),
            "funding_source": "current",
            "next_funding_time": _int(item.get("nextFundingTime")),
            "mark_price": _float(item.get("markPrice")),
            "volume_24h_usdt": _float(item.get("turnover24h")),
            "timestamp": _int(data.get("time")),
        }

    raise ValueError(f"Unsupported exchange: {exchange_id}")


def _fetch_market_funding(exchange_id: str) -> list[dict[str, Any]]:
    if exchange_id == "binanceusdm":
        data = _get_json("https://fapi.binance.com/fapi/v1/premiumIndex", {})
        tickers = {
            item["symbol"]: item
            for item in _get_json("https://fapi.binance.com/fapi/v1/ticker/24hr", {})
            if str(item.get("symbol", "")).endswith("USDT")
        }
        return [
            {
                "compact_symbol": item["symbol"],
                "venue_symbol": item["symbol"],
                "funding_rate": _float(item["lastFundingRate"]),
                "funding_source": "current",
                "next_funding_time": _int(item.get("nextFundingTime")),
                "mark_price": _float(item.get("markPrice")),
                "volume_24h_usdt": _float((tickers.get(item["symbol"]) or {}).get("quoteVolume")),
                "timestamp": _int(item.get("time")),
            }
            for item in data
            if str(item.get("symbol", "")).endswith("USDT") and _float(item.get("lastFundingRate")) is not None
        ]

    if exchange_id == "bybit":
        data = _get_json("https://api.bybit.com/v5/market/tickers", {"category": "linear"})
        return [
            {
                "compact_symbol": item["symbol"],
                "venue_symbol": item["symbol"],
                "funding_rate": _float(item["fundingRate"]),
                "funding_source": "current",
                "next_funding_time": _int(item.get("nextFundingTime")),
                "mark_price": _float(item.get("markPrice")),
                "volume_24h_usdt": _float(item.get("turnover24h")),
                "timestamp": _int(data.get("time")),
            }
            for item in data["result"]["list"]
            if str(item.get("symbol", "")).endswith("USDT") and _float(item.get("fundingRate")) is not None
        ]

    if exchange_id == "bitget":
        tickers_data = _get_json(
            "https://api.bitget.com/api/v2/mix/market/tickers",
            {"productType": "USDT-FUTURES"},
        )
        tickers = {
            item["symbol"]: item
            for item in tickers_data.get("data", [])
            if str(item.get("symbol", "")).endswith("USDT")
        }
        data = _get_json(
            "https://api.bitget.com/api/v2/mix/market/current-fund-rate",
            {"productType": "USDT-FUTURES"},
        )
        return [
            {
                "compact_symbol": item["symbol"],
                "venue_symbol": item["symbol"],
                "funding_rate": _float(item["fundingRate"]),
                "funding_source": "current",
                "next_funding_time": _int(item.get("nextUpdate")),
                "mark_price": None,
                "volume_24h_usdt": _first_float(
                    (tickers.get(item["symbol"]) or {}),
                    "usdtVolume",
                    "quoteVolume",
                    "baseVolume",
                ),
                "timestamp": _int(data.get("requestTime")),
            }
            for item in data["data"]
            if str(item.get("symbol", "")).endswith("USDT") and _float(item.get("fundingRate")) is not None
        ]

    if exchange_id == "okx":
        instruments = _get_json("https://www.okx.com/api/v5/public/instruments", {"instType": "SWAP"})
        tickers_data = _get_json("https://www.okx.com/api/v5/market/tickers", {"instType": "SWAP"})
        tickers = {
            item["instId"]: item
            for item in tickers_data.get("data", [])
            if str(item.get("instId", "")).endswith("-USDT-SWAP")
        }
        symbols = [
            item["instId"].replace("-USDT-SWAP", "USDT")
            for item in instruments.get("data", [])
            if item.get("state") == "live" and str(item.get("instId", "")).endswith("-USDT-SWAP")
        ]
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_map = {executor.submit(_fetch_funding, exchange_id, symbol): symbol for symbol in symbols}
            for future in as_completed(future_map):
                symbol = future_map[future]
                try:
                    item = future.result()
                except Exception as exc:
                    logger.debug("OKX market funding failed for %s: %r", symbol, exc)
                    continue
                item["compact_symbol"] = symbol
                ticker = tickers.get(item["venue_symbol"]) or {}
                item["volume_24h_usdt"] = _okx_quote_volume(ticker)
                results.append(item)
        return results

    return []


def _fetch_market_symbols(exchange_id: str) -> set[str]:
    if exchange_id in {"binanceusdm", "bybit", "bitget"}:
        return {item["compact_symbol"] for item in _fetch_market_funding(exchange_id)}

    if exchange_id == "okx":
        data = _get_json("https://www.okx.com/api/v5/public/instruments", {"instType": "SWAP"})
        symbols: set[str] = set()
        for item in data["data"]:
            inst_id = str(item.get("instId", ""))
            if item.get("state") != "live":
                continue
            if not inst_id.endswith("-USDT-SWAP"):
                continue
            symbols.add(inst_id.replace("-USDT-SWAP", "USDT"))
        return symbols

    return set()


def _fetch_ohlcv(exchange_id: str, compact_symbol: str, timeframe: str, limit: int) -> list[dict[str, float | int]]:
    if exchange_id == "binanceusdm":
        data = _get_json(
            "https://fapi.binance.com/fapi/v1/klines",
            {"symbol": compact_symbol, "interval": _binance_interval(timeframe), "limit": limit},
        )
        return [{"timestamp": _int(row[0]), "volume": _float(row[5]), "quote_volume": _float(row[7])} for row in data]

    if exchange_id == "okx":
        venue_symbol = _venue_symbol(exchange_id, compact_symbol)
        data = _get_json(
            "https://www.okx.com/api/v5/market/candles",
            {"instId": venue_symbol, "bar": timeframe, "limit": limit},
        )
        return [{"timestamp": _int(row[0]), "volume": _float(row[5]), "quote_volume": _float(row[7])} for row in data["data"]]

    if exchange_id == "bitget":
        data = _get_json(
            "https://api.bitget.com/api/v2/mix/market/candles",
            {
                "symbol": compact_symbol,
                "productType": "USDT-FUTURES",
                "granularity": timeframe,
                "limit": limit,
            },
        )
        return [{"timestamp": _int(row[0]), "volume": _float(row[5]), "quote_volume": _float(row[6])} for row in data["data"]]

    if exchange_id == "bybit":
        data = _get_json(
            "https://api.bybit.com/v5/market/kline",
            {"category": "linear", "symbol": compact_symbol, "interval": _bybit_interval(timeframe), "limit": limit},
        )
        return [{"timestamp": _int(row[0]), "volume": _float(row[5]), "quote_volume": _float(row[6])} for row in data["result"]["list"]]

    raise ValueError(f"Unsupported exchange: {exchange_id}")


def _get_json(url: str, params: dict[str, Any]) -> Any:
    query = urlencode(params)
    full_url = f"{url}?{query}" if query else url
    request = Request(full_url, headers={"User-Agent": "funding-sentinel/0.1"})
    with urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _venue_symbol(exchange_id: str, compact_symbol: str) -> str:
    if exchange_id == "okx":
        if not compact_symbol.endswith("USDT"):
            raise ValueError(f"Only USDT swaps are supported: {compact_symbol}")
        return f"{compact_symbol[:-4]}-USDT-SWAP"
    return compact_symbol


def _binance_interval(timeframe: str) -> str:
    return timeframe


def _bybit_interval(timeframe: str) -> str:
    if timeframe.endswith("m"):
        return timeframe[:-1]
    if timeframe.endswith("h"):
        return str(int(timeframe[:-1]) * 60)
    return timeframe


def _progress_adjusted_volume(current_volume: float | None, progress: float | None) -> float | None:
    if current_volume is None or progress is None:
        return current_volume
    return current_volume / max(progress, 0.1)


def _candle_progress(candle_timestamp: int | None, timeframe: str, now) -> float | None:
    if candle_timestamp is None:
        return None
    duration_ms = _timeframe_ms(timeframe)
    if not duration_ms:
        return None
    now_ms = int(now.timestamp() * 1000)
    elapsed_ms = now_ms - candle_timestamp
    if elapsed_ms <= 0:
        return 0.0
    if elapsed_ms >= duration_ms:
        return 1.0
    return elapsed_ms / duration_ms


def _confirmation_volume_ratio(
    raw_ratio: float | None,
    adjusted_ratio: float | None,
    progress: float | None,
) -> float | None:
    if raw_ratio is None:
        return None
    if adjusted_ratio is None or progress is None:
        return raw_ratio
    if progress >= 0.5 or raw_ratio >= 1.2:
        return adjusted_ratio
    return raw_ratio


def _one_hour_quote_volume(rows: list[dict[str, float | int]]) -> float | None:
    recent = rows[-4:]
    values = [
        row.get("quote_volume") if row.get("quote_volume") is not None else row.get("volume")
        for row in recent
    ]
    if len(values) < 4 or any(value is None for value in values):
        return None
    return float(sum(values))


def _timeframe_ms(timeframe: str) -> int | None:
    if timeframe.endswith("m"):
        return int(timeframe[:-1]) * 60 * 1000
    if timeframe.endswith("h"):
        return int(timeframe[:-1]) * 60 * 60 * 1000
    return None


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _first_float(source: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _float(source.get(key))
        if value is not None:
            return value
    return None


def _okx_quote_volume(ticker: dict[str, Any]) -> float | None:
    direct = _first_float(ticker, "volCcyQuote24h", "volUsd24h")
    if direct is not None:
        return direct
    base_volume = _float(ticker.get("volCcy24h"))
    last_price = _float(ticker.get("last"))
    if base_volume is None or last_price is None:
        return None
    return base_volume * last_price


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(float(value))
