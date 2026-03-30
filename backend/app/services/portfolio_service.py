from __future__ import annotations

import statistics
from datetime import datetime, timezone

from app.agents.specialists import FundamentalAgent, NewsAgent, TechnicalAgent
from app.models.schemas import (
    PortfolioAnalysisResponse,
    PortfolioAnalyzeRequest,
    PortfolioHoldingAnalysis,
)
from app.services.news_service import NewsService
from app.services.sentiment_service import SentimentService
from app.services.stock_service import StockService
from app.services.ticker_resolver import TickerResolver


class PortfolioService:
    def __init__(
        self,
        stock_service: StockService,
        news_service: NewsService,
        sentiment_service: SentimentService,
        ticker_resolver: TickerResolver,
    ) -> None:
        self.stock_service = stock_service
        self.news_service = news_service
        self.sentiment_service = sentiment_service
        self.ticker_resolver = ticker_resolver
        self.technical_agent = TechnicalAgent()
        self.news_agent = NewsAgent()
        self.fundamental_agent = FundamentalAgent()

    async def analyze(self, request: PortfolioAnalyzeRequest) -> PortfolioAnalysisResponse:
        normalized_holdings = self._normalize_weights(request)
        analyses: list[PortfolioHoldingAnalysis] = []

        for holding in normalized_holdings:
            ticker = self.ticker_resolver.normalize(holding["ticker"])
            stock = await self.stock_service.get_snapshot(ticker)
            news = await self.news_service.get_news(stock.ticker, stock.company_name, 4)
            sentiment = await self.sentiment_service.analyze(news)

            technical = self.technical_agent.analyze(stock)
            news_signal = self.news_agent.analyze(sentiment)
            fundamental = self.fundamental_agent.analyze(stock)
            aggregate_score = technical.score + news_signal.score + fundamental.score

            recommendation = "buy" if aggregate_score > 1.1 else "sell" if aggregate_score < -1.1 else "hold"
            analyses.append(
                PortfolioHoldingAnalysis(
                    ticker=stock.ticker,
                    company_name=stock.company_name,
                    weight=holding["weight"],
                    risk_score=stock.risk_score or 50,
                    trend_signal=stock.trend_signal,
                    sentiment_label=sentiment.overall_label,
                    recommendation=recommendation,
                    summary=f"{stock.company_name}: {stock.ai_summary or stock.summary}",
                )
            )

        weights = [item.weight for item in analyses]
        risk_scores = [item.risk_score for item in analyses]
        average_risk = int(round(sum(risk_scores) / len(risk_scores)))
        diversification_score = self._compute_diversification_score(weights, analyses)
        concentration_score = min(100, int(round(max(weights) * 100)))
        overexposed = [item.ticker for item in analyses if item.weight >= 0.4]

        if average_risk >= 70:
            risk_level = "high"
        elif average_risk >= 45:
            risk_level = "medium"
        else:
            risk_level = "low"

        suggestions = self._build_suggestions(analyses, diversification_score, overexposed, average_risk)

        return PortfolioAnalysisResponse(
            generated_at=datetime.now(timezone.utc),
            risk_level=risk_level,
            diversification_score=diversification_score,
            concentration_score=concentration_score,
            overexposed_tickers=overexposed,
            suggestions=suggestions,
            holdings=analyses,
        )

    @staticmethod
    def _normalize_weights(request: PortfolioAnalyzeRequest) -> list[dict[str, float | str]]:
        explicit_weights = [item.weight for item in request.holdings if item.weight is not None]
        if explicit_weights and len(explicit_weights) == len(request.holdings):
            total = sum(explicit_weights)
            if total <= 0:
                equal_weight = 1 / len(request.holdings)
                return [{"ticker": item.ticker, "weight": equal_weight} for item in request.holdings]
            return [{"ticker": item.ticker, "weight": (item.weight or 0) / total} for item in request.holdings]

        equal_weight = 1 / len(request.holdings)
        return [{"ticker": item.ticker, "weight": equal_weight} for item in request.holdings]

    @staticmethod
    def _compute_diversification_score(weights: list[float], analyses: list[PortfolioHoldingAnalysis]) -> int:
        if len(weights) == 1:
            return 20
        balance_score = 100 - int(round((max(weights) - min(weights)) * 100))
        risk_dispersion = statistics.pstdev(item.risk_score for item in analyses) if len(analyses) > 1 else 0
        adjusted = max(10, min(100, balance_score - int(round(risk_dispersion / 2))))
        return adjusted

    @staticmethod
    def _build_suggestions(
        analyses: list[PortfolioHoldingAnalysis],
        diversification_score: int,
        overexposed: list[str],
        average_risk: int,
    ) -> list[str]:
        suggestions: list[str] = []
        if diversification_score < 55:
            suggestions.append("Diversification is weak. Consider balancing exposure across more than one market driver.")
        if overexposed:
            suggestions.append(f"Position sizing is concentrated in {', '.join(overexposed)}.")
        if average_risk >= 70:
            suggestions.append("Portfolio risk is elevated. Pair aggressive names with steadier holdings or reduce size.")
        if not suggestions:
            suggestions.append("Exposure looks balanced for a starter portfolio, but keep monitoring catalyst risk.")
        return suggestions
