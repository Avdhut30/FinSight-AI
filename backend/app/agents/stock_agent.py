from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.agents.specialists import FundamentalAgent, NewsAgent, TechnicalAgent
from app.models.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    ChartInsight,
    DecisionPayload,
    HistoricalContext,
    MemoryInsight,
    NewsItem,
    SentimentSummary,
    SpecialistSignal,
    StockSnapshot,
)
from app.repositories.analysis_repository import save_analysis

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.llm_service import LLMService
    from app.services.memory_service import MemoryService
    from app.services.news_service import NewsService
    from app.services.sentiment_service import SentimentService
    from app.services.stock_service import StockService
    from app.services.ticker_resolver import TickerResolver


@dataclass
class AnalysisDraft:
    stock: StockSnapshot
    sentiment: SentimentSummary
    news: list[NewsItem]
    recommendation: str
    confidence: float
    answer: str
    generation_mode: str
    thesis_points: list[str]
    risk_factors: list[str]
    decision: DecisionPayload
    specialists: list[SpecialistSignal]
    chart_insight: ChartInsight
    historical_context: HistoricalContext
    memory_context: list[MemoryInsight]


class StockAnalysisAgent:
    def __init__(
        self,
        stock_service: StockService,
        news_service: NewsService,
        sentiment_service: SentimentService,
        llm_service: LLMService,
        ticker_resolver: TickerResolver,
        news_limit: int,
        memory_service: Optional[MemoryService] = None,
    ) -> None:
        self.stock_service = stock_service
        self.news_service = news_service
        self.sentiment_service = sentiment_service
        self.llm_service = llm_service
        self.ticker_resolver = ticker_resolver
        self.memory_service = memory_service
        self.news_limit = news_limit
        self.technical_agent = TechnicalAgent()
        self.news_agent = NewsAgent()
        self.fundamental_agent = FundamentalAgent()

    async def analyze(self, request: AnalyzeRequest, db: Session, user_id: Optional[str] = None) -> AnalyzeResponse:
        query_text = self._truncate_for_log(request.query)
        self._log_analysis_request(query_text, request)

        ticker = self._resolve_ticker(request, query_text)
        stock = await self._fetch_stock_snapshot(ticker)
        news = await self._fetch_news(stock)
        sentiment = await self._analyze_sentiment(stock, news)
        memory_context = self._retrieve_memory_context(db, request.query, stock.ticker, user_id=user_id)
        draft = await self._build_analysis_draft(request, stock, news, sentiment, memory_context)
        response = self._build_response(request, draft)
        self._persist_response(db, response, user_id=user_id)
        return response

    async def stream_analysis(
        self,
        request: AnalyzeRequest,
        db: Session,
        user_id: Optional[str] = None,
    ) -> AsyncIterator[dict[str, object]]:
        query_text = self._truncate_for_log(request.query)
        self._log_analysis_request(query_text, request)

        yield self._stream_event("status", {"stage": "resolve_ticker", "message": "Resolving company and ticker..."})
        ticker = self._resolve_ticker(request, query_text)

        yield self._stream_event(
            "status",
            {"stage": "fetch_market_data", "message": f"Loading market data for {ticker}..."},
        )
        stock = await self._fetch_stock_snapshot(ticker)
        news_task = asyncio.create_task(self._fetch_news(stock))

        yield self._stream_event(
            "status",
            {"stage": "technical_agent", "message": f"Technical Agent is scoring {stock.company_name}..."},
        )
        fast_draft = self._build_fast_draft(request, stock)

        for chunk in self._chunk_text(fast_draft.answer):
            yield self._stream_event("answer_delta", {"delta": chunk})
            await asyncio.sleep(0)

        draft = fast_draft
        try:
            yield self._stream_event(
                "status",
                {
                    "stage": "news_agent",
                    "message": "News Agent is collecting and ranking recent headlines...",
                },
            )
            news = await news_task

            yield self._stream_event(
                "status",
                {"stage": "news_sentiment", "message": "Scoring headline sentiment and event tone..."},
            )
            sentiment = await self._analyze_sentiment(stock, news)

            yield self._stream_event(
                "status",
                {"stage": "memory_agent", "message": "Retrieving prior analyses and portfolio memory..."},
            )
            memory_context = self._retrieve_memory_context(db, request.query, stock.ticker, user_id=user_id)

            yield self._stream_event(
                "status",
                {"stage": "generate_answer", "message": "Synthesizing Technical, News, and Fundamental agents..."},
            )
            draft = await self._build_analysis_draft(request, stock, news, sentiment, memory_context)
        except Exception:
            logger.warning(
                "Refinement failed after fast answer; returning fast draft. ticker=%s",
                stock.ticker,
                exc_info=True,
            )

        response = self._build_response(request, draft)
        self._persist_response(db, response, user_id=user_id)

        yield self._stream_event("complete", response.model_dump(mode="json"))

    def _resolve_ticker(self, request: AnalyzeRequest, query_text: str) -> str:
        ticker = self.ticker_resolver.resolve(request.query, request.ticker)
        if not ticker:
            raise ValueError("Could not infer a stock ticker. Try asking about a specific company or pass `ticker`.")

        logger.info("Ticker resolved query=%r ticker=%s", query_text, ticker)
        return ticker

    async def _fetch_stock_snapshot(self, ticker: str) -> StockSnapshot:
        stock = await self.stock_service.get_snapshot(ticker)
        logger.info(
            "Stock snapshot fetched ticker=%s price=%.2f trend=%s valuation=%s",
            stock.ticker,
            stock.current_price,
            stock.trend_signal,
            stock.valuation_signal,
        )
        return stock

    async def _fetch_news(self, stock: StockSnapshot) -> list[NewsItem]:
        return await self.news_service.get_news(stock.ticker, stock.company_name, self.news_limit)

    async def _analyze_sentiment(self, stock: StockSnapshot, news: list[NewsItem]) -> SentimentSummary:
        sentiment = await self.sentiment_service.analyze(news)
        logger.info(
            "Sentiment computed ticker=%s label=%s score=%.2f positive=%s negative=%s neutral=%s",
            stock.ticker,
            sentiment.overall_label,
            sentiment.score,
            sentiment.positive_count,
            sentiment.negative_count,
            sentiment.neutral_count,
        )
        return sentiment

    async def _build_analysis_draft(
        self,
        request: AnalyzeRequest,
        stock: StockSnapshot,
        news: list[NewsItem],
        sentiment: SentimentSummary,
        memory_context: list[MemoryInsight],
    ) -> AnalysisDraft:
        specialists = self._run_specialists(stock, sentiment)
        recommendation, confidence, thesis_points, risk_factors, decision = self._build_view(stock, sentiment, specialists)
        chart_insight = self._build_chart_insight(stock)
        historical_context = self._build_historical_context(stock, sentiment, news)
        fallback_answer = self._build_heuristic_answer(
            request.query,
            stock,
            sentiment,
            recommendation,
            confidence,
            thesis_points,
            risk_factors,
            decision,
        )
        answer, generation_mode = await self.llm_service.render_answer(
            query=request.query,
            stock=stock,
            sentiment=sentiment,
            news=news,
            recommendation=recommendation,
            confidence=confidence,
            thesis_points=thesis_points,
            risk_factors=risk_factors,
            fallback_answer=fallback_answer,
            use_llm=request.use_llm,
        )
        logger.info(
            "Answer generated ticker=%s mode=%s recommendation=%s confidence=%.2f",
            stock.ticker,
            generation_mode,
            recommendation,
            confidence,
        )
        return AnalysisDraft(
            stock=stock,
            sentiment=sentiment,
            news=news,
            recommendation=recommendation,
            confidence=confidence,
            answer=answer,
            generation_mode=generation_mode,
            thesis_points=thesis_points,
            risk_factors=risk_factors,
            decision=decision,
            specialists=specialists,
            chart_insight=chart_insight,
            historical_context=historical_context,
            memory_context=memory_context,
        )

    def _build_response(self, request: AnalyzeRequest, draft: AnalysisDraft) -> AnalyzeResponse:
        return AnalyzeResponse(
            analysis_id=str(uuid4()),
            created_at=datetime.now(timezone.utc),
            query=request.query,
            recommendation=draft.recommendation,
            confidence=draft.confidence,
            answer=draft.answer,
            generation_mode=draft.generation_mode,
            stock=draft.stock,
            sentiment=draft.sentiment,
            news=draft.news,
            thesis_points=draft.thesis_points,
            risk_factors=draft.risk_factors,
            data_sources=[
                self.stock_service.market_data_source_label,
                "Google News RSS headlines",
                "Local analysis memory",
            ],
            decision=draft.decision,
            specialists=draft.specialists,
            chart_insight=draft.chart_insight,
            historical_context=draft.historical_context,
            memory_context=draft.memory_context,
        )

    def _persist_response(self, db: Session, response: AnalyzeResponse, user_id: Optional[str] = None) -> None:
        try:
            if user_id is None:
                save_analysis(db, response)
            else:
                save_analysis(db, response, user_id=user_id)
        except SQLAlchemyError:
            logger.warning(
                "Analysis persistence failed; returning response without saving. analysis_id=%s ticker=%s",
                response.analysis_id,
                response.stock.ticker,
                exc_info=True,
            )
            db.rollback()
            return
        logger.info("Analysis persisted analysis_id=%s ticker=%s", response.analysis_id, response.stock.ticker)

    def _build_view(
        self,
        stock: StockSnapshot,
        sentiment: SentimentSummary,
        specialists: list[SpecialistSignal],
    ) -> tuple[str, float, list[str], list[str], DecisionPayload]:
        aggregate_score = sum(signal.score * signal.confidence for signal in specialists)

        if aggregate_score > 1.0:
            recommendation = "buy"
            decision_label = "BUY"
        elif aggregate_score < -1.0:
            recommendation = "sell"
            decision_label = "SELL"
        else:
            recommendation = "hold"
            decision_label = "HOLD"

        confidence = round(min(0.95, 0.58 + abs(aggregate_score) * 0.1), 2)
        thesis_points = self._build_thesis_points(stock, sentiment, specialists)
        risk_factors = self._build_risk_factors(stock, sentiment)
        decision = DecisionPayload(
            decision=decision_label,
            confidence=int(round(confidence * 100)),
            reasons=thesis_points[:3],
            risks=risk_factors[:3],
        )
        return recommendation, confidence, thesis_points, risk_factors, decision

    def _build_fast_draft(self, request: AnalyzeRequest, stock: StockSnapshot) -> AnalysisDraft:
        sentiment = self._neutral_sentiment()
        specialists = self._run_specialists(stock, sentiment)
        recommendation, confidence, thesis_points, risk_factors, decision = self._build_view(stock, sentiment, specialists)
        answer = self._build_heuristic_answer(
            request.query,
            stock,
            sentiment,
            recommendation,
            confidence,
            thesis_points,
            risk_factors,
            decision,
        )
        return AnalysisDraft(
            stock=stock,
            sentiment=sentiment,
            news=[],
            recommendation=recommendation,
            confidence=confidence,
            answer=answer,
            generation_mode="heuristic-fast",
            thesis_points=thesis_points,
            risk_factors=risk_factors,
            decision=decision,
            specialists=specialists,
            chart_insight=self._build_chart_insight(stock),
            historical_context=self._build_historical_context(stock, sentiment, []),
            memory_context=[],
        )

    @staticmethod
    def _build_thesis_points(
        stock: StockSnapshot,
        sentiment: SentimentSummary,
        specialists: list[SpecialistSignal],
    ) -> list[str]:
        points = [stock.ai_summary or stock.summary, sentiment.summary]
        for specialist in specialists:
            if specialist.reasons:
                points.append(f"{specialist.agent_name}: {specialist.reasons[0]}")
        if stock.one_month_return_percent is not None:
            points.append(f"One-month return is {stock.one_month_return_percent:+.2f}%, which supports the current trend view.")
        if stock.valuation_signal != "unknown":
            points.append(f"Valuation looks {stock.valuation_signal} based on the available P/E data.")
        return points[:6]

    @staticmethod
    def _build_risk_factors(stock: StockSnapshot, sentiment: SentimentSummary) -> list[str]:
        risks: list[str] = []
        if stock.valuation_signal == "expensive":
            risks.append("The stock screens as expensive on P/E, so execution misses can trigger de-rating.")
        if stock.trend_signal == "bearish":
            risks.append("Price action is below key moving averages, which can keep short-term momentum weak.")
        if sentiment.overall_label == "negative":
            risks.append("Recent headlines are skewing negative and can weigh on sentiment until the narrative improves.")
        if stock.risk_score is not None and stock.risk_score >= 70:
            risks.append(f"Composite risk score is elevated at {stock.risk_score}/100.")
        if not risks:
            risks.append("Macro volatility, earnings surprises, or sector rotation can still invalidate the current view.")
        return risks[:3]

    @staticmethod
    def _build_heuristic_answer(
        query: str,
        stock: StockSnapshot,
        sentiment: SentimentSummary,
        recommendation: str,
        confidence: float,
        thesis_points: list[str],
        risk_factors: list[str],
        decision: DecisionPayload,
    ) -> str:
        lead = f"{decision.decision} {stock.company_name} ({stock.ticker}) with {decision.confidence}% confidence."
        reasons = " ".join(f"- {point}" for point in thesis_points[:3])
        risks = " ".join(f"- {risk}" for risk in risk_factors[:2])
        return (
            f"{lead} Buy/Hold/Sell rationale for '{query}': {reasons} "
            f"Key risks: {risks} This is an analytical view, not investment advice."
        )

    @staticmethod
    def _neutral_sentiment() -> SentimentSummary:
        return SentimentSummary(
            overall_label="neutral",
            score=0.0,
            confidence=0.3,
            positive_count=0,
            negative_count=0,
            neutral_count=0,
            summary="Recent headlines have not been incorporated yet, so the first pass is based on price action and trend.",
        )

    def _run_specialists(self, stock: StockSnapshot, sentiment: SentimentSummary) -> list[SpecialistSignal]:
        return [
            self.technical_agent.analyze(stock),
            self.news_agent.analyze(sentiment),
            self.fundamental_agent.analyze(stock),
        ]

    @staticmethod
    def _build_chart_insight(stock: StockSnapshot) -> ChartInsight:
        momentum = "bullish" if stock.trend_signal == "bullish" else "bearish" if stock.trend_signal == "bearish" else "neutral"
        support_text = f"support near {stock.support_level:.2f}" if stock.support_level is not None else "support is unclear"
        resistance_text = (
            f"resistance near {stock.resistance_level:.2f}" if stock.resistance_level is not None else "resistance is unclear"
        )
        rsi_text = f"RSI is {stock.rsi_14:.1f}" if stock.rsi_14 is not None else "RSI is unavailable"
        return ChartInsight(
            momentum=momentum,
            support_level=stock.support_level,
            resistance_level=stock.resistance_level,
            rsi_14=stock.rsi_14,
            summary=f"Chart reads {momentum}; {rsi_text}, with {support_text} and {resistance_text}.",
        )

    @staticmethod
    def _build_historical_context(
        stock: StockSnapshot,
        sentiment: SentimentSummary,
        news: list[NewsItem],
    ) -> HistoricalContext:
        key_events = [item.title for item in news[:3]]
        return_percent = stock.six_month_return_percent
        if sentiment.overall_label == "positive":
            sentiment_shift = "improving"
        elif sentiment.overall_label == "negative":
            sentiment_shift = "deteriorating"
        else:
            sentiment_shift = "stable"
        summary = (
            f"Over the last six months, {stock.company_name} returned "
            f"{return_percent:+.2f}%." if return_percent is not None else f"Recent six-month return data is unavailable for {stock.company_name}."
        )
        return HistoricalContext(
            period="6m",
            return_percent=return_percent,
            sentiment_shift=sentiment_shift,
            key_events=key_events,
            summary=summary,
        )

    def _retrieve_memory_context(
        self,
        db: Session,
        query: str,
        ticker: str,
        user_id: Optional[str] = None,
    ) -> list[MemoryInsight]:
        if self.memory_service is None:
            return []
        return self.memory_service.retrieve_similar(db, query, ticker, user_id=user_id)

    @staticmethod
    def _log_analysis_request(query_text: str, request: AnalyzeRequest) -> None:
        logger.info(
            "Analysis requested query=%r explicit_ticker=%s use_llm=%s",
            query_text,
            request.ticker,
            request.use_llm,
        )

    @staticmethod
    def _stream_event(event: str, data: dict[str, object]) -> dict[str, object]:
        return {"event": event, "data": data}

    @staticmethod
    def _chunk_text(value: str, max_chunk_size: int = 48) -> list[str]:
        if not value:
            return [""]

        chunks: list[str] = []
        current = ""
        for token in re.findall(r"\S+\s*", value):
            if current and len(current) + len(token) > max_chunk_size:
                chunks.append(current)
                current = token
            else:
                current += token

        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _truncate_for_log(value: str, max_length: int = 120) -> str:
        if len(value) <= max_length:
            return value
        return f"{value[: max_length - 3]}..."
