import asyncio
from time import monotonic

import pandas as pd
import pytest

from app.core.settings import Settings
from app.models.schemas import StockSnapshot
from app.services.stock_service import SnapshotCacheEntry, StockService


def _twelve_data_payload(symbol: str = "INFY") -> dict:
    values = []
    for index in range(140):
        close = 1000 + index
        values.append(
            {
                "datetime": (pd.Timestamp("2025-01-01") + pd.Timedelta(days=index)).strftime("%Y-%m-%d"),
                "open": str(close - 5),
                "high": str(close + 10),
                "low": str(close - 10),
                "close": str(close),
                "volume": str(100000 + index * 100),
            }
        )

    return {
        "meta": {
            "symbol": symbol,
            "interval": "1day",
            "currency": "INR",
            "exchange": "NSE",
            "mic_code": "XNSE",
        },
        "values": list(reversed(values)),
        "status": "ok",
    }


def _plan_error_payload(symbol: str) -> dict:
    return {
        "status": "error",
        "code": 403,
        "message": f"**symbol** {symbol} is not available with your plan. You may select the appropriate plan at https://twelvedata.com/pricing",
    }


def _yahoo_finance_payload(symbol: str = "INFY.NS", name: str = "Infosys Ltd") -> dict:
    timestamps: list[int] = []
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    volumes: list[int] = []

    for index in range(140):
        close = 1000 + index
        timestamps.append(int(pd.Timestamp("2025-01-01", tz="UTC").timestamp()) + index * 86400)
        closes.append(float(close))
        highs.append(float(close + 10))
        lows.append(float(close - 10))
        volumes.append(100000 + index * 100)

    return {
        "meta": {
            "currency": "INR",
            "symbol": symbol,
            "exchangeName": "NSI",
            "fullExchangeName": "NSE",
            "instrumentType": "EQUITY",
            "regularMarketPrice": closes[-1],
            "regularMarketVolume": volumes[-1],
            "fiftyTwoWeekHigh": max(highs),
            "fiftyTwoWeekLow": min(lows),
            "longName": name,
        },
        "timestamp": timestamps,
        "indicators": {
            "quote": [
                {
                    "close": closes,
                    "high": highs,
                    "low": lows,
                    "volume": volumes,
                }
            ]
        },
    }


def _cached_snapshot(ticker: str = "TCS.NS") -> StockSnapshot:
    return StockSnapshot(
        ticker=ticker,
        company_name="Cached Ltd",
        currency="INR",
        exchange="NSE",
        sector=None,
        current_price=100.0,
        previous_close=99.0,
        day_change_percent=1.01,
        market_cap=None,
        pe_ratio=None,
        volume=100,
        average_volume=90,
        fifty_two_week_high=120.0,
        fifty_two_week_low=80.0,
        one_month_return_percent=5.0,
        six_month_return_percent=12.0,
        trend_signal="bullish",
        valuation_signal="unknown",
        summary="Cached stock snapshot.",
        price_history=[],
    )


def test_get_snapshot_uses_twelve_data_when_api_key_is_configured(monkeypatch: pytest.MonkeyPatch):
    service = StockService(Settings(_env_file=None, twelve_data_api_key="test-key"))

    async def fake_fetch_twelve_data_time_series(api_symbol: str, ticker: str) -> dict:
        assert api_symbol == "INFY:NSE"
        assert ticker == "INFY.NS"
        return _twelve_data_payload("INFY")

    monkeypatch.setattr(service, "_fetch_twelve_data_time_series", fake_fetch_twelve_data_time_series)

    snapshot = asyncio.run(service.get_snapshot("INFY.NS"))

    assert snapshot.ticker == "INFY.NS"
    assert snapshot.company_name == "Infosys"
    assert snapshot.exchange == "NSE"
    assert snapshot.currency == "INR"
    assert snapshot.current_price == 1139.0
    assert snapshot.previous_close == 1138.0
    assert snapshot.volume == 113900
    assert snapshot.average_volume is not None
    assert snapshot.valuation_signal == "unknown"
    assert snapshot.price_history


def test_get_snapshot_requires_twelve_data_api_key(monkeypatch: pytest.MonkeyPatch):
    service = StockService(Settings(_env_file=None))

    async def fake_fetch_yahoo_finance_chart(ticker: str) -> dict:
        assert ticker == "TCS.NS"
        return _yahoo_finance_payload("TCS.NS", "Tata Consultancy Services")

    monkeypatch.setattr(service, "_fetch_yahoo_finance_chart", fake_fetch_yahoo_finance_chart)

    snapshot = asyncio.run(service.get_snapshot("TCS.NS"))

    assert snapshot.ticker == "TCS.NS"
    assert snapshot.company_name == "Tata Consultancy Services"
    assert snapshot.exchange == "NSE"


def test_get_snapshot_returns_recent_cached_value(monkeypatch: pytest.MonkeyPatch):
    service = StockService(Settings(_env_file=None, twelve_data_api_key="test-key"))
    calls = {"count": 0}

    async def fake_get_twelve_data_snapshot(ticker: str) -> StockSnapshot:
        calls["count"] += 1
        return _cached_snapshot(ticker)

    monkeypatch.setattr(service, "_get_twelve_data_snapshot", fake_get_twelve_data_snapshot)

    first = asyncio.run(service.get_snapshot("TCS.NS"))
    second = asyncio.run(service.get_snapshot("TCS.NS"))

    assert first == second
    assert calls["count"] == 1


def test_get_snapshot_serves_stale_cache_after_provider_failure(monkeypatch: pytest.MonkeyPatch):
    service = StockService(Settings(_env_file=None, twelve_data_api_key="test-key"))
    cached_snapshot = _cached_snapshot("TCS.NS")
    service._snapshot_cache["TCS.NS"] = SnapshotCacheEntry(
        snapshot=cached_snapshot,
        fetched_at=monotonic() - (service.cache_ttl_seconds + 1),
    )

    async def failing_get_twelve_data_snapshot(ticker: str) -> StockSnapshot:
        raise ValueError("provider timeout")

    async def failing_fetch_yahoo_finance_chart(ticker: str) -> dict:
        raise ValueError(f"Could not reach Yahoo Finance for {ticker}.")

    monkeypatch.setattr(service, "_get_twelve_data_snapshot", failing_get_twelve_data_snapshot)
    monkeypatch.setattr(service, "_fetch_yahoo_finance_chart", failing_fetch_yahoo_finance_chart)

    snapshot = asyncio.run(service.get_snapshot("TCS.NS"))

    assert snapshot == cached_snapshot


def test_get_snapshot_reuses_cached_provider_failure(monkeypatch: pytest.MonkeyPatch):
    service = StockService(Settings(_env_file=None, twelve_data_api_key="test-key"))
    calls = {"twelve_data": 0, "yahoo": 0}

    async def fake_fetch_twelve_data_time_series(api_symbol: str, ticker: str) -> dict:
        calls["twelve_data"] += 1
        raise ValueError("TCS.NS is not available with your current Twelve Data plan.")

    async def fake_fetch_yahoo_finance_chart(ticker: str) -> dict:
        calls["yahoo"] += 1
        return _yahoo_finance_payload("TCS.NS", "Tata Consultancy Services")

    monkeypatch.setattr(service, "_fetch_twelve_data_time_series", fake_fetch_twelve_data_time_series)
    monkeypatch.setattr(service, "_fetch_yahoo_finance_chart", fake_fetch_yahoo_finance_chart)

    first = asyncio.run(service.get_snapshot("TCS.NS"))
    second = asyncio.run(service.get_snapshot("TCS.NS"))

    assert first == second
    assert calls["twelve_data"] == 1
    assert calls["yahoo"] == 1


def test_get_watchlist_uses_batch_fetch_and_skips_failed_symbols(monkeypatch: pytest.MonkeyPatch):
    service = StockService(Settings(_env_file=None, twelve_data_api_key="test-key"))
    calls = {"count": 0}

    async def fake_fetch_twelve_data_time_series_batch(tickers: list[str]) -> dict[str, dict]:
        calls["count"] += 1
        assert tickers == ["TCS.NS", "INFY.NS"]
        return {
            "TCS:NSE": _plan_error_payload("TCS"),
            "INFY:NSE": _twelve_data_payload("INFY"),
        }

    async def fake_fetch_yahoo_finance_chart(ticker: str) -> dict:
        assert ticker == "TCS.NS"
        return _yahoo_finance_payload("TCS.NS", "Tata Consultancy Services")

    monkeypatch.setattr(service, "_fetch_twelve_data_time_series_batch", fake_fetch_twelve_data_time_series_batch)
    monkeypatch.setattr(service, "_fetch_yahoo_finance_chart", fake_fetch_yahoo_finance_chart)

    snapshots = asyncio.run(service.get_watchlist(["TCS.NS", "INFY.NS"]))

    assert calls["count"] == 1
    assert [item.ticker for item in snapshots] == ["TCS.NS", "INFY.NS"]
    assert service._get_cached_failure("TCS.NS") is None


def test_get_watchlist_raises_when_all_symbols_fail(monkeypatch: pytest.MonkeyPatch):
    service = StockService(Settings(_env_file=None, twelve_data_api_key="test-key"))

    async def fake_fetch_twelve_data_time_series_batch(tickers: list[str]) -> dict[str, dict]:
        return {
            "TCS:NSE": _plan_error_payload("TCS"),
            "INFY:NSE": _plan_error_payload("INFY"),
        }

    async def fake_fetch_yahoo_finance_chart(ticker: str) -> dict:
        raise ValueError(f"No Yahoo Finance history returned for {ticker}.")

    monkeypatch.setattr(service, "_fetch_twelve_data_time_series_batch", fake_fetch_twelve_data_time_series_batch)
    monkeypatch.setattr(service, "_fetch_yahoo_finance_chart", fake_fetch_yahoo_finance_chart)

    with pytest.raises(ValueError, match="No Yahoo Finance history returned"):
        asyncio.run(service.get_watchlist(["TCS.NS", "INFY.NS"]))


def test_market_data_source_label_is_twelve_data():
    assert StockService(Settings(_env_file=None, twelve_data_api_key="test-key")).market_data_source_label == (
        "Market data via Twelve Data or Yahoo Finance"
    )


def test_twelve_data_symbol_mapping_uses_exchange_suffix():
    service = StockService(Settings(_env_file=None, twelve_data_api_key="test-key"))
    assert service._to_twelve_data_symbol("TCS.NS") == ("TCS", "NSE", "TCS:NSE")
    assert service._to_twelve_data_symbol("INFY.NS") == ("INFY", "NSE", "INFY:NSE")


def test_provider_rate_limit_message_is_normalized():
    assert (
        StockService._format_provider_error(
            "watchlist",
            "You have run out of API credits for the current minute. 10 API credits were used.",
        )
        == "Twelve Data rate limit reached. Wait a minute and try again."
    )


def test_provider_plan_message_is_normalized():
    assert (
        StockService._format_provider_error(
            "TCS.NS",
            "This symbol is available starting with the Grow or Venture plan. Consider upgrading now at https://twelvedata.com/pricing",
        )
        == "TCS.NS is not available with your current Twelve Data plan."
    )
