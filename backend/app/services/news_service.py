import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from threading import Lock
from time import monotonic
from urllib.parse import quote_plus

import feedparser

from app.core.settings import Settings, get_settings
from app.models.schemas import NewsItem

logger = logging.getLogger(__name__)


@dataclass
class NewsCacheEntry:
    items: list[NewsItem]
    fetched_at: float


class NewsService:
    cache_ttl_seconds = 300.0

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._cache: dict[str, NewsCacheEntry] = {}
        self._cache_lock = Lock()

    async def get_news(self, ticker: str, company_name: str, limit: int) -> list[NewsItem]:
        cache_key = f"{ticker}:{limit}"
        cached_items = self._get_cached_news(cache_key)
        if cached_items is not None:
            logger.info("News cache hit ticker=%s count=%s", ticker, len(cached_items))
            return [item.model_copy(deep=True) for item in cached_items]

        try:
            google_news = await self._fetch_google_news_with_retries(ticker, company_name, limit)
        except Exception:
            logger.warning("Google News fetch failed for %s", ticker, exc_info=True)
            return []
        self._store_cached_news(cache_key, google_news)
        logger.info("News fetched ticker=%s source=google_news count=%s", ticker, len(google_news))
        return [item.model_copy(deep=True) for item in google_news]

    async def _fetch_google_news_with_retries(self, ticker: str, company_name: str, limit: int) -> list[NewsItem]:
        last_error: Exception | None = None
        for attempt in range(1, self.settings.news_retry_attempts + 1):
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._fetch_google_news, ticker, company_name, limit),
                    timeout=self.settings.news_fetch_timeout_seconds,
                )
            except Exception as exc:
                last_error = exc
                if attempt >= self.settings.news_retry_attempts:
                    raise
                await asyncio.sleep(0.2 * attempt)

        if last_error is not None:
            raise last_error
        return []

    def _fetch_google_news(self, ticker: str, company_name: str, limit: int) -> list[NewsItem]:
        query = quote_plus(f"{company_name} {ticker} stock India")
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en")
        items: list[NewsItem] = []

        for entry in feed.entries[:limit]:
            items.append(
                NewsItem(
                    title=entry.get("title", "").strip(),
                    summary=self._strip_html(entry.get("summary")),
                    publisher=self._extract_google_source(entry),
                    link=entry.get("link"),
                    published_at=self._to_iso(entry.get("published")),
                )
            )
        return [item for item in items if item.title]

    @staticmethod
    def _strip_html(value: str | None) -> str | None:
        if not value:
            return None
        cleaned = re.sub(r"<[^>]+>", "", value)
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def _extract_google_source(entry) -> str | None:
        source = entry.get("source")
        if isinstance(source, dict):
            return source.get("title")
        return None

    @staticmethod
    def _to_iso(value) -> str | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        if isinstance(value, str):
            try:
                return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
            except Exception:
                try:
                    return datetime.fromisoformat(value).astimezone(timezone.utc).isoformat()
                except Exception:
                    return value
        return None

    def _get_cached_news(self, cache_key: str) -> list[NewsItem] | None:
        with self._cache_lock:
            entry = self._cache.get(cache_key)
            if entry is None:
                return None
            if monotonic() - entry.fetched_at > self.cache_ttl_seconds:
                self._cache.pop(cache_key, None)
                return None
            return entry.items

    def _store_cached_news(self, cache_key: str, items: list[NewsItem]) -> None:
        with self._cache_lock:
            self._cache[cache_key] = NewsCacheEntry(
                items=[item.model_copy(deep=True) for item in items],
                fetched_at=monotonic(),
            )
