from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from threading import Lock
from time import monotonic

import httpx
import pandas as pd

from app.core.settings import Settings, get_settings
from app.models.schemas import PricePoint, StockSnapshot

logger = logging.getLogger(__name__)


@dataclass
class HistoryMetrics:
    day_change_percent: float | None
    one_month_return_percent: float | None
    six_month_return_percent: float | None
    rsi_14: float | None
    support_level: float | None
    resistance_level: float | None
    trend_signal: str
    price_history: list[PricePoint]


@dataclass
class SnapshotCacheEntry:
    snapshot: StockSnapshot
    fetched_at: float


@dataclass
class FailureCacheEntry:
    message: str
    fetched_at: float


class StockService:
    cache_ttl_seconds = 60.0
    stale_cache_ttl_seconds = 900.0
    failure_cache_ttl_seconds = 900.0
    twelve_data_base_url = "https://api.twelvedata.com"
    yahoo_finance_chart_base_url = "https://query1.finance.yahoo.com/v8/finance/chart"
    company_name_overrides = {
        "AAPL": "Apple",
        "ADANIENT": "Adani Enterprises",
        "ASIANPAINT": "Asian Paints",
        "AXISBANK": "Axis Bank",
        "BAJFINANCE": "Bajaj Finance",
        "BHARTIARTL": "Bharti Airtel",
        "HDFCBANK": "HDFC Bank",
        "ICICIBANK": "ICICI Bank",
        "INFY": "Infosys",
        "ITC": "ITC",
        "KOTAKBANK": "Kotak Mahindra Bank",
        "LT": "Larsen & Toubro",
        "MARUTI": "Maruti Suzuki",
        "RELIANCE": "Reliance Industries",
        "SBIN": "State Bank of India",
        "SUNPHARMA": "Sun Pharma",
        "TCS": "Tata Consultancy Services",
        "TITAN": "Titan",
        "ULTRACEMCO": "UltraTech Cement",
        "WIPRO": "Wipro",
    }
    sector_overrides = {
        "AAPL": "Technology",
        "AXISBANK": "Financials",
        "BAJFINANCE": "Financials",
        "BHARTIARTL": "Telecom",
        "HDFCBANK": "Financials",
        "ICICIBANK": "Financials",
        "INFY": "Technology",
        "ITC": "Consumer Defensive",
        "KOTAKBANK": "Financials",
        "LT": "Industrials",
        "MARUTI": "Consumer Cyclical",
        "RELIANCE": "Energy",
        "SBIN": "Financials",
        "SUNPHARMA": "Healthcare",
        "TCS": "Technology",
        "TITAN": "Consumer Cyclical",
        "ULTRACEMCO": "Basic Materials",
        "WIPRO": "Technology",
    }

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._snapshot_cache: dict[str, SnapshotCacheEntry] = {}
        self._failure_cache: dict[str, FailureCacheEntry] = {}
        self._cache_lock = Lock()

    @property
    def market_data_source_label(self) -> str:
        return "Market data via Twelve Data or Yahoo Finance"

    async def get_snapshot(self, ticker: str) -> StockSnapshot:
        cached_snapshot = self._get_cached_snapshot(ticker)
        if cached_snapshot is not None:
            return cached_snapshot

        stale_snapshot = self._get_cached_snapshot(ticker, allow_stale=True)
        cached_failure = self._get_cached_failure(ticker)
        if cached_failure is not None:
            if stale_snapshot is not None:
                logger.warning("Serving stale cached snapshot for %s after cached provider failure.", ticker)
                return stale_snapshot
            raise ValueError(cached_failure)

        try:
            snapshot = await self._fetch_snapshot_with_fallback(ticker)
        except ValueError as exc:
            return self._return_stale_or_raise(ticker, str(exc))
        except Exception as exc:
            if stale_snapshot is not None:
                logger.warning("Serving stale cached snapshot for %s after unexpected Twelve Data failure.", ticker, exc_info=exc)
                return stale_snapshot
            logger.exception("Failed to fetch market data for %s", ticker)
            raise ValueError(f"Could not fetch market data for {ticker}.") from exc

        self._clear_failure(ticker)
        self._store_snapshot(snapshot)
        return snapshot

    async def get_watchlist(self, tickers: list[str]) -> list[StockSnapshot]:
        if not self.settings.twelve_data_api_key:
            return self._collect_watchlist_snapshots(await self._fetch_watchlist_with_yahoo_finance(tickers))

        snapshots_by_ticker: dict[str, StockSnapshot] = {}
        failures: list[ValueError] = []
        pending_tickers: list[str] = []

        for ticker in tickers:
            cached_snapshot = self._get_cached_snapshot(ticker)
            if cached_snapshot is not None:
                snapshots_by_ticker[ticker] = cached_snapshot
                continue

            stale_snapshot = self._get_cached_snapshot(ticker, allow_stale=True)
            cached_failure = self._get_cached_failure(ticker)
            if cached_failure is not None:
                if stale_snapshot is not None:
                    snapshots_by_ticker[ticker] = stale_snapshot
                else:
                    failures.append(ValueError(cached_failure))
                continue

            pending_tickers.append(ticker)

        if pending_tickers:
            try:
                batch_payload = await self._fetch_twelve_data_time_series_batch(pending_tickers)
                for ticker in pending_tickers:
                    payload = batch_payload.get(self._to_twelve_data_symbol(ticker)[2])
                    try:
                        snapshots_by_ticker[ticker] = await self._build_snapshot_from_batch_payload(ticker, payload)
                    except ValueError as exc:
                        failures.append(exc)
            except ValueError as exc:
                logger.warning("Batch watchlist fetch failed; falling back to Yahoo Finance snapshots.", exc_info=exc)
                for item in await self._fetch_watchlist_with_yahoo_finance(pending_tickers):
                    if isinstance(item, ValueError):
                        failures.append(item)
                    else:
                        snapshots_by_ticker[item.ticker] = item

        snapshots = [snapshots_by_ticker[ticker] for ticker in tickers if ticker in snapshots_by_ticker]
        if not snapshots and failures:
            raise failures[0]
        return snapshots

    async def _get_twelve_data_snapshot(self, ticker: str) -> StockSnapshot:
        symbol, _, api_symbol = self._to_twelve_data_symbol(ticker)
        payload = await self._fetch_twelve_data_time_series(api_symbol, ticker)
        snapshot = self._build_snapshot_from_twelve_data(
            ticker,
            payload,
            self._resolve_company_name(ticker, symbol, payload),
        )
        return snapshot

    async def _fetch_snapshot_with_fallback(self, ticker: str) -> StockSnapshot:
        if not self.settings.twelve_data_api_key:
            logger.info("TWELVE_DATA_API_KEY not configured; using Yahoo Finance fallback for %s.", ticker)
            return await self._get_yahoo_finance_snapshot(ticker)

        try:
            return await self._get_twelve_data_snapshot(ticker)
        except ValueError as exc:
            logger.warning(
                "Twelve Data snapshot failed for %s; falling back to Yahoo Finance.",
                ticker,
                exc_info=exc,
            )
            return await self._get_yahoo_finance_snapshot(ticker)

    async def _get_yahoo_finance_snapshot(self, ticker: str) -> StockSnapshot:
        payload = await self._fetch_yahoo_finance_chart(ticker)
        snapshot = self._build_snapshot_from_yahoo_finance(ticker, payload)
        return snapshot

    async def _fetch_yahoo_finance_chart(self, ticker: str) -> dict:
        params = {
            "range": "1y",
            "interval": "1d",
            "includePrePost": "false",
        }

        try:
            payload = await self._get_json_with_retries(
                f"{self.yahoo_finance_chart_base_url}/{ticker}",
                params=params,
                headers={"User-Agent": "Mozilla/5.0"},
                attempts=self.settings.market_data_retry_attempts,
            )
        except httpx.HTTPError as exc:
            raise ValueError(f"Could not reach Yahoo Finance for {ticker}.") from exc

        chart = payload.get("chart", {}) if isinstance(payload, dict) else {}
        if chart.get("error"):
            description = str(chart["error"].get("description") or "").strip()
            raise ValueError(description or f"Yahoo Finance rejected {ticker}.")

        result = chart.get("result")
        if not isinstance(result, list) or not result:
            raise ValueError(f"No Yahoo Finance history returned for {ticker}.")

        return result[0]

    async def _fetch_twelve_data_time_series(self, api_symbol: str, ticker: str) -> dict:
        params = {
            "symbol": api_symbol,
            "interval": "1day",
            "outputsize": 140,
            "apikey": self.settings.twelve_data_api_key,
        }
        try:
            payload = await self._get_json_with_retries(
                f"{self.twelve_data_base_url}/time_series",
                params=params,
                attempts=self.settings.market_data_retry_attempts,
            )
        except httpx.HTTPError as exc:
            raise ValueError(f"Could not reach Twelve Data for {ticker}.") from exc
        if payload.get("status") == "error":
            raise ValueError(self._format_provider_error(ticker, payload.get("message")))
        if not payload.get("values"):
            raise ValueError(f"No Twelve Data history returned for {ticker}.")
        return payload

    async def _fetch_twelve_data_time_series_batch(self, tickers: list[str]) -> dict[str, dict]:
        api_symbols = [self._to_twelve_data_symbol(ticker)[2] for ticker in tickers]
        params = {
            "symbol": ",".join(api_symbols),
            "interval": "1day",
            "outputsize": 140,
            "apikey": self.settings.twelve_data_api_key,
        }

        try:
            payload = await self._get_json_with_retries(
                f"{self.twelve_data_base_url}/time_series",
                params=params,
                attempts=self.settings.market_data_retry_attempts,
            )
        except httpx.HTTPError as exc:
            raise ValueError("Could not reach Twelve Data for the watchlist.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Unexpected Twelve Data response for the watchlist.")
        if len(api_symbols) == 1 and payload.get("status") in {"ok", "error"}:
            return {api_symbols[0]: payload}
        if payload.get("status") == "error":
            raise ValueError(self._format_provider_error("watchlist", payload.get("message")))
        return payload

    async def _fetch_watchlist_individually(self, tickers: list[str]) -> list[StockSnapshot | ValueError]:
        semaphore = asyncio.Semaphore(3)

        async def fetch_one(ticker: str) -> StockSnapshot | ValueError:
            try:
                async with semaphore:
                    return await self.get_snapshot(ticker)
            except ValueError as exc:
                return exc

        return await asyncio.gather(*(fetch_one(ticker) for ticker in tickers))

    async def _fetch_watchlist_with_yahoo_finance(self, tickers: list[str]) -> list[StockSnapshot | ValueError]:
        semaphore = asyncio.Semaphore(3)

        async def fetch_one(ticker: str) -> StockSnapshot | ValueError:
            try:
                async with semaphore:
                    return await self._get_yahoo_finance_snapshot(ticker)
            except ValueError as exc:
                return exc

        return await asyncio.gather(*(fetch_one(ticker) for ticker in tickers))

    @staticmethod
    def _collect_watchlist_snapshots(results: list[StockSnapshot | ValueError]) -> list[StockSnapshot]:
        failures = [item for item in results if isinstance(item, ValueError)]
        snapshots = [item for item in results if isinstance(item, StockSnapshot)]
        if not snapshots and failures:
            raise failures[0]
        return snapshots

    async def _build_snapshot_from_batch_payload(self, ticker: str, payload: dict | None) -> StockSnapshot:
        if not isinstance(payload, dict):
            return await self._build_fallback_snapshot(ticker, f"No Twelve Data history returned for {ticker}.")

        if payload.get("status") == "error":
            return await self._build_fallback_snapshot(ticker, self._format_provider_error(ticker, payload.get("message")))

        symbol, _, _ = self._to_twelve_data_symbol(ticker)
        try:
            snapshot = self._build_snapshot_from_twelve_data(
                ticker,
                payload,
                self._resolve_company_name(ticker, symbol, payload),
            )
        except ValueError as exc:
            return await self._build_fallback_snapshot(ticker, str(exc))

        self._clear_failure(ticker)
        self._store_snapshot(snapshot)
        return snapshot

    async def _build_fallback_snapshot(self, ticker: str, message: str) -> StockSnapshot:
        try:
            snapshot = await self._get_yahoo_finance_snapshot(ticker)
        except ValueError as exc:
            return self._return_stale_or_raise(ticker, str(exc))
        logger.warning("Using Yahoo Finance fallback for %s after Twelve Data failure: %s", ticker, message)
        self._clear_failure(ticker)
        self._store_snapshot(snapshot)
        return snapshot

    def _build_snapshot_from_yahoo_finance(self, ticker: str, payload: dict) -> StockSnapshot:
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        timestamps = payload.get("timestamp", []) if isinstance(payload, dict) else []
        quote_list = payload.get("indicators", {}).get("quote", []) if isinstance(payload, dict) else []
        quote = quote_list[0] if isinstance(quote_list, list) and quote_list else {}

        closes = quote.get("close", []) if isinstance(quote, dict) else []
        highs = quote.get("high", []) if isinstance(quote, dict) else []
        lows = quote.get("low", []) if isinstance(quote, dict) else []
        volumes = quote.get("volume", []) if isinstance(quote, dict) else []

        records: list[tuple[pd.Timestamp, float, float | None, float | None, int | None]] = []
        for raw_timestamp, raw_close, raw_high, raw_low, raw_volume in zip(timestamps, closes, highs, lows, volumes):
            close = self._parse_float(raw_close)
            if close is None:
                continue

            timestamp = pd.to_datetime(raw_timestamp, unit="s")
            high = self._parse_float(raw_high)
            low = self._parse_float(raw_low)
            volume = self._parse_int(raw_volume)
            records.append((timestamp, close, high, low, volume))

        if not records:
            raise ValueError(f"No Yahoo Finance history returned for {ticker}.")

        close_values = [item[1] for item in records]
        high_values = [item[2] for item in records if item[2] is not None]
        low_values = [item[3] for item in records if item[3] is not None]
        close_series = pd.Series(close_values, index=[item[0] for item in records])
        metrics = self._build_history_metrics(close_series)

        latest_close = close_values[-1]
        latest_price = self._parse_float(meta.get("regularMarketPrice")) or latest_close
        previous_close = close_values[-2] if len(close_values) > 1 else None
        valid_volumes = [item[4] for item in records if item[4] is not None]
        latest_volume = self._parse_int(meta.get("regularMarketVolume")) or (valid_volumes[-1] if valid_volumes else None)
        average_volume = int(round(sum(valid_volumes[-20:]) / min(len(valid_volumes), 20))) if valid_volumes else None
        ticker_root = self._to_twelve_data_symbol(ticker)[0]
        company_name = (
            self._clean_company_name(meta.get("longName"))
            or self._clean_company_name(meta.get("shortName"))
            or self.company_name_overrides.get(ticker_root)
            or ticker_root
        )
        exchange = self._clean_company_name(meta.get("fullExchangeName")) or self._clean_company_name(meta.get("exchangeName"))
        fifty_two_week_high = self._parse_float(meta.get("fiftyTwoWeekHigh"))
        fifty_two_week_low = self._parse_float(meta.get("fiftyTwoWeekLow"))
        pe_ratio = self._parse_float(meta.get("trailingPE"))
        valuation_signal = self._valuation_signal(pe_ratio)
        support_level = metrics.support_level or self._round_optional(min(close_values[-20:]))
        resistance_level = metrics.resistance_level or self._round_optional(max(close_values[-20:]))
        risk_score = self._risk_score(
            trend_signal=metrics.trend_signal,
            one_month_return_percent=metrics.one_month_return_percent,
            day_change_percent=metrics.day_change_percent,
            rsi_14=metrics.rsi_14,
            valuation_signal=valuation_signal,
        )
        summary = self._build_summary(
            company_name,
            latest_price,
            metrics.day_change_percent,
            pe_ratio,
            metrics.trend_signal,
        )
        ai_summary = self._build_ai_summary(
            company_name,
            metrics.trend_signal,
            metrics.rsi_14,
            support_level,
            resistance_level,
            risk_score,
        )

        return StockSnapshot(
            ticker=ticker,
            company_name=company_name,
            currency=self._clean_company_name(meta.get("currency")),
            exchange=exchange,
            sector=self.sector_overrides.get(ticker_root),
            current_price=round(latest_price, 2),
            previous_close=round(previous_close, 2) if previous_close is not None else None,
            day_change_percent=metrics.day_change_percent,
            market_cap=self._parse_float(meta.get("marketCap")),
            pe_ratio=round(pe_ratio, 2) if pe_ratio is not None else None,
            volume=latest_volume,
            average_volume=average_volume,
            fifty_two_week_high=self._round_optional(
                fifty_two_week_high if fifty_two_week_high is not None else (max(high_values) if high_values else max(close_values))
            ),
            fifty_two_week_low=self._round_optional(
                fifty_two_week_low if fifty_two_week_low is not None else (min(low_values) if low_values else min(close_values))
            ),
            one_month_return_percent=metrics.one_month_return_percent,
            six_month_return_percent=metrics.six_month_return_percent,
            rsi_14=metrics.rsi_14,
            support_level=support_level,
            resistance_level=resistance_level,
            risk_score=risk_score,
            trend_signal=metrics.trend_signal,
            valuation_signal=valuation_signal,
            summary=summary,
            ai_summary=ai_summary,
            price_history=metrics.price_history,
        )

    def _return_stale_or_raise(self, ticker: str, message: str) -> StockSnapshot:
        if self._should_cache_failure(message):
            self._store_failure(ticker, message)

        stale_snapshot = self._get_cached_snapshot(ticker, allow_stale=True)
        if stale_snapshot is not None:
            logger.warning("Serving stale cached snapshot for %s after fetch failure.", ticker)
            return stale_snapshot
        raise ValueError(message)

    def _build_snapshot_from_twelve_data(self, ticker: str, payload: dict, company_name: str | None) -> StockSnapshot:
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        values = payload.get("values", []) if isinstance(payload, dict) else []
        if not isinstance(values, list) or not values:
            raise ValueError(f"No Twelve Data history returned for {ticker}.")

        ordered_values = list(reversed(values))
        closes: list[float] = []
        highs: list[float] = []
        lows: list[float] = []
        volumes: list[int] = []
        dates: list[pd.Timestamp] = []

        for item in ordered_values:
            close = self._parse_float(item.get("close"))
            if close is None:
                continue

            parsed_date = pd.to_datetime(item.get("datetime"))
            closes.append(close)
            dates.append(parsed_date)

            high = self._parse_float(item.get("high"))
            if high is not None:
                highs.append(high)

            low = self._parse_float(item.get("low"))
            if low is not None:
                lows.append(low)

            volume = self._parse_int(item.get("volume"))
            if volume is not None:
                volumes.append(volume)

        if not closes:
            raise ValueError(f"Twelve Data did not return usable close prices for {ticker}.")

        closes_series = pd.Series(closes, index=dates)
        metrics = self._build_history_metrics(closes_series)
        latest_price = closes[-1]
        previous_close = closes[-2] if len(closes) > 1 else None
        latest_volume = volumes[-1] if volumes else None
        average_volume = int(round(sum(volumes[-20:]) / min(len(volumes), 20))) if volumes else None
        clean_company_name = company_name or self._clean_company_name(meta.get("symbol")) or ticker
        currency = meta.get("currency")
        exchange = meta.get("exchange") or meta.get("mic_code")
        valuation_signal = self._valuation_signal(None)
        symbol, _, _ = self._to_twelve_data_symbol(ticker)
        support_level = metrics.support_level or self._round_optional(min(closes[-20:]))
        resistance_level = metrics.resistance_level or self._round_optional(max(closes[-20:]))
        risk_score = self._risk_score(
            trend_signal=metrics.trend_signal,
            one_month_return_percent=metrics.one_month_return_percent,
            day_change_percent=metrics.day_change_percent,
            rsi_14=metrics.rsi_14,
            valuation_signal=valuation_signal,
        )
        summary = self._build_summary(
            clean_company_name,
            latest_price,
            metrics.day_change_percent,
            None,
            metrics.trend_signal,
        )
        ai_summary = self._build_ai_summary(
            clean_company_name,
            metrics.trend_signal,
            metrics.rsi_14,
            support_level,
            resistance_level,
            risk_score,
        )

        return StockSnapshot(
            ticker=ticker,
            company_name=clean_company_name,
            currency=currency,
            exchange=exchange,
            sector=self.sector_overrides.get(symbol),
            current_price=round(latest_price, 2),
            previous_close=round(previous_close, 2) if previous_close is not None else None,
            day_change_percent=metrics.day_change_percent,
            market_cap=None,
            pe_ratio=None,
            volume=latest_volume,
            average_volume=average_volume,
            fifty_two_week_high=self._round_optional(max(highs) if highs else max(closes)),
            fifty_two_week_low=self._round_optional(min(lows) if lows else min(closes)),
            one_month_return_percent=metrics.one_month_return_percent,
            six_month_return_percent=metrics.six_month_return_percent,
            rsi_14=metrics.rsi_14,
            support_level=support_level,
            resistance_level=resistance_level,
            risk_score=risk_score,
            trend_signal=metrics.trend_signal,
            valuation_signal=valuation_signal,
            summary=summary,
            ai_summary=ai_summary,
            price_history=metrics.price_history,
        )

    def _resolve_company_name(self, ticker: str, symbol: str, payload: dict) -> str:
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        company_name = self.company_name_overrides.get(symbol)
        if company_name:
            return company_name

        meta_symbol = self._clean_company_name(meta.get("symbol"))
        if meta_symbol and meta_symbol != symbol:
            return meta_symbol

        return symbol or ticker

    def _get_cached_snapshot(self, ticker: str, allow_stale: bool = False) -> StockSnapshot | None:
        with self._cache_lock:
            entry = self._snapshot_cache.get(ticker)
            if entry is None:
                return None
            age = monotonic() - entry.fetched_at
            if age > self.stale_cache_ttl_seconds:
                self._snapshot_cache.pop(ticker, None)
                return None
            if not allow_stale and age > self.cache_ttl_seconds:
                return None
            return entry.snapshot

    def _get_cached_failure(self, ticker: str) -> str | None:
        with self._cache_lock:
            entry = self._failure_cache.get(ticker)
            if entry is None:
                return None
            age = monotonic() - entry.fetched_at
            if age > self.failure_cache_ttl_seconds:
                self._failure_cache.pop(ticker, None)
                return None
            return entry.message

    def _store_snapshot(self, snapshot: StockSnapshot) -> None:
        with self._cache_lock:
            self._snapshot_cache[snapshot.ticker] = SnapshotCacheEntry(snapshot=snapshot, fetched_at=monotonic())
            self._failure_cache.pop(snapshot.ticker, None)

    def _store_failure(self, ticker: str, message: str) -> None:
        with self._cache_lock:
            self._failure_cache[ticker] = FailureCacheEntry(message=message, fetched_at=monotonic())

    def _clear_failure(self, ticker: str) -> None:
        with self._cache_lock:
            self._failure_cache.pop(ticker, None)

    @staticmethod
    def _to_twelve_data_symbol(ticker: str) -> tuple[str, str | None, str]:
        normalized = ticker.strip().upper()
        if normalized.endswith(".NS"):
            symbol = normalized[:-3]
            return symbol, "NSE", f"{symbol}:NSE"
        if normalized.endswith(".BO"):
            symbol = normalized[:-3]
            return symbol, "BSE", f"{symbol}:BSE"
        if ":" in normalized:
            symbol, exchange = normalized.split(":", 1)
            return symbol, exchange, normalized
        return normalized, None, normalized

    @staticmethod
    def _clean_company_name(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    async def _get_json_with_retries(
        self,
        url: str,
        *,
        params: dict[str, object],
        attempts: int,
        headers: dict[str, str] | None = None,
    ) -> dict:
        last_error: httpx.HTTPError | None = None

        for attempt in range(1, attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=self.settings.market_data_timeout_seconds) as client:
                    response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Unexpected provider response.")
                return payload
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= attempts:
                    raise
                await asyncio.sleep(0.25 * attempt)

        if last_error is not None:
            raise last_error
        raise ValueError("No provider response received.")

    @staticmethod
    def _format_provider_error(ticker: str, provider_message: object) -> str:
        raw_message = str(provider_message or "").strip()
        lowered = raw_message.lower()
        if "run out of api credits" in lowered or "current limit being" in lowered:
            return "Twelve Data rate limit reached. Wait a minute and try again."
        if "not available with your plan" in lowered or "available starting with the grow or venture plan" in lowered:
            return f"{ticker} is not available with your current Twelve Data plan."
        if "invalid symbol" in lowered:
            return f"{ticker} is not a valid Twelve Data symbol."
        return raw_message or f"Twelve Data rejected {ticker}."

    @staticmethod
    def _should_cache_failure(message: str) -> bool:
        lowered = message.lower()
        return "not a valid twelve data symbol" in lowered or "no yahoo finance history returned" in lowered

    @staticmethod
    def _parse_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if pd.notna(number):
            return number
        return None

    @staticmethod
    def _parse_int(value: object) -> int | None:
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _round_optional(value: float | None) -> float | None:
        return round(value, 2) if value is not None else None

    def _build_history_metrics(self, closes: pd.Series) -> HistoryMetrics:
        latest = float(closes.iloc[-1])
        previous = float(closes.iloc[-2]) if len(closes) > 1 else latest
        sma_20 = float(closes.tail(20).mean()) if len(closes) >= 20 else latest
        sma_50 = float(closes.tail(50).mean()) if len(closes) >= 50 else sma_20

        day_change = ((latest - previous) / previous) * 100 if previous else None
        one_month_return = self._pct_return(closes, 22)
        six_month_return = self._pct_return(closes, min(len(closes) - 1, 126))

        if latest > sma_20 > sma_50:
            trend_signal = "bullish"
        elif latest < sma_20 < sma_50:
            trend_signal = "bearish"
        else:
            trend_signal = "sideways"

        rsi_14 = self._compute_rsi(closes, 14)
        support_level = round(float(closes.tail(20).min()), 2) if len(closes) >= 5 else round(latest, 2)
        resistance_level = round(float(closes.tail(20).max()), 2) if len(closes) >= 5 else round(latest, 2)

        history_points = [
            PricePoint(date=index.strftime("%Y-%m-%d"), close=round(float(price), 2))
            for index, price in closes.tail(30).items()
        ]

        return HistoryMetrics(
            day_change_percent=round(day_change, 2) if day_change is not None else None,
            one_month_return_percent=round(one_month_return, 2) if one_month_return is not None else None,
            six_month_return_percent=round(six_month_return, 2) if six_month_return is not None else None,
            rsi_14=rsi_14,
            support_level=support_level,
            resistance_level=resistance_level,
            trend_signal=trend_signal,
            price_history=history_points,
        )

    @staticmethod
    def _pct_return(closes: pd.Series, periods: int) -> float | None:
        if periods <= 0 or len(closes) <= periods:
            return None
        start_value = float(closes.iloc[-periods - 1])
        end_value = float(closes.iloc[-1])
        if start_value == 0:
            return None
        return ((end_value - start_value) / start_value) * 100

    @staticmethod
    def _valuation_signal(pe_ratio: float | None) -> str:
        if pe_ratio is None:
            return "unknown"
        if pe_ratio < 15:
            return "value-tilted"
        if pe_ratio <= 30:
            return "balanced"
        return "expensive"

    @staticmethod
    def _compute_rsi(closes: pd.Series, periods: int) -> float | None:
        if len(closes) <= periods:
            return None
        delta = closes.diff().dropna()
        gains = delta.clip(lower=0)
        losses = -delta.clip(upper=0)
        average_gain = gains.tail(periods).mean()
        average_loss = losses.tail(periods).mean()
        if average_loss == 0:
            return 100.0
        relative_strength = average_gain / average_loss
        return round(float(100 - (100 / (1 + relative_strength))), 2)

    @staticmethod
    def _risk_score(
        trend_signal: str,
        one_month_return_percent: float | None,
        day_change_percent: float | None,
        rsi_14: float | None,
        valuation_signal: str,
    ) -> int:
        score = 50
        if trend_signal == "bearish":
            score += 15
        elif trend_signal == "bullish":
            score -= 8

        if one_month_return_percent is not None:
            if one_month_return_percent < -8:
                score += 12
            elif one_month_return_percent > 8:
                score -= 6

        if day_change_percent is not None and abs(day_change_percent) > 3:
            score += 6

        if rsi_14 is not None and (rsi_14 < 35 or rsi_14 > 70):
            score += 6

        if valuation_signal == "expensive":
            score += 8
        elif valuation_signal == "value-tilted":
            score -= 4

        return max(15, min(92, score))

    @staticmethod
    def _build_summary(
        company_name: str,
        current_price: float | None,
        day_change_percent: float | None,
        pe_ratio: float | None,
        trend_signal: str,
    ) -> str:
        price_text = f"{current_price:.2f}" if current_price is not None else "N/A"
        day_text = f"{day_change_percent:+.2f}%" if day_change_percent is not None else "N/A"
        pe_text = f"{pe_ratio:.1f}" if pe_ratio is not None else "unavailable"
        return (
            f"{company_name} trades at {price_text}, moved {day_text} on the latest session, "
            f"shows a {trend_signal} technical bias, and has a P/E of {pe_text}."
        )

    @staticmethod
    def _build_ai_summary(
        company_name: str,
        trend_signal: str,
        rsi_14: float | None,
        support_level: float | None,
        resistance_level: float | None,
        risk_score: int | None,
    ) -> str:
        momentum_text = f"RSI {rsi_14:.1f}" if rsi_14 is not None else "RSI unavailable"
        support_text = f"support near {support_level:.2f}" if support_level is not None else "support unknown"
        resistance_text = (
            f"resistance near {resistance_level:.2f}" if resistance_level is not None else "resistance unknown"
        )
        risk_text = f"risk score {risk_score}/100" if risk_score is not None else "risk score unavailable"
        return (
            f"{company_name} is in a {trend_signal} setup with {momentum_text}, "
            f"{support_text}, {resistance_text}, and {risk_text}."
        )
