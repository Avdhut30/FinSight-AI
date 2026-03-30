from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.settings import Settings, get_settings
from app.db.session import SessionLocal

if TYPE_CHECKING:
    from app.agents.stock_agent import StockAnalysisAgent
    from app.services.alert_service import AlertService
    from app.services.auth_service import AuthService
    from app.services.llm_service import LLMService
    from app.services.memory_service import MemoryService
    from app.services.news_service import NewsService
    from app.services.portfolio_service import PortfolioService
    from app.services.sentiment_service import SentimentService
    from app.services.stock_service import StockService
    from app.services.ticker_resolver import TickerResolver


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@lru_cache
def get_stock_service() -> StockService:
    from app.services.stock_service import StockService

    settings = get_settings()
    return StockService(settings)


@lru_cache
def get_news_service() -> NewsService:
    from app.services.news_service import NewsService

    settings = get_settings()
    return NewsService(settings)


@lru_cache
def get_sentiment_service() -> SentimentService:
    from app.services.sentiment_service import SentimentService

    settings = get_settings()
    return SentimentService(settings)


@lru_cache
def get_llm_service() -> LLMService:
    from app.services.llm_service import LLMService

    settings = get_settings()
    return LLMService(settings)


@lru_cache
def get_auth_service() -> AuthService:
    from app.services.auth_service import AuthService

    settings = get_settings()
    return AuthService(settings)


@lru_cache
def get_memory_service() -> MemoryService:
    from app.services.memory_service import MemoryService

    return MemoryService()


@lru_cache
def get_ticker_resolver() -> TickerResolver:
    from app.services.ticker_resolver import TickerResolver

    return TickerResolver()


@lru_cache
def get_alert_service() -> AlertService:
    from app.services.alert_service import AlertService

    return AlertService(get_stock_service())


@lru_cache
def get_portfolio_service() -> PortfolioService:
    from app.services.portfolio_service import PortfolioService

    return PortfolioService(
        stock_service=get_stock_service(),
        news_service=get_news_service(),
        sentiment_service=get_sentiment_service(),
        ticker_resolver=get_ticker_resolver(),
    )


@lru_cache
def get_stock_agent() -> StockAnalysisAgent:
    from app.agents.stock_agent import StockAnalysisAgent

    settings: Settings = get_settings()
    return StockAnalysisAgent(
        stock_service=get_stock_service(),
        news_service=get_news_service(),
        sentiment_service=get_sentiment_service(),
        llm_service=get_llm_service(),
        ticker_resolver=get_ticker_resolver(),
        memory_service=get_memory_service(),
        news_limit=settings.news_limit,
    )
