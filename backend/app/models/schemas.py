from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PricePoint(BaseModel):
    date: str
    close: float


class NewsItem(BaseModel):
    title: str
    summary: str | None = None
    publisher: str | None = None
    link: str | None = None
    published_at: str | None = None
    sentiment_label: str | None = None
    sentiment_score: float | None = None


class StockSnapshot(BaseModel):
    ticker: str
    company_name: str
    currency: str | None = None
    exchange: str | None = None
    sector: str | None = None
    current_price: float
    previous_close: float | None = None
    day_change_percent: float | None = None
    market_cap: float | None = None
    pe_ratio: float | None = None
    volume: int | None = None
    average_volume: int | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    one_month_return_percent: float | None = None
    six_month_return_percent: float | None = None
    rsi_14: float | None = None
    support_level: float | None = None
    resistance_level: float | None = None
    risk_score: int | None = None
    trend_signal: str
    valuation_signal: str
    summary: str
    ai_summary: str | None = None
    price_history: list[PricePoint] = Field(default_factory=list)


class SentimentSummary(BaseModel):
    overall_label: str
    score: float
    confidence: float
    positive_count: int
    negative_count: int
    neutral_count: int
    summary: str


class AnalyzeRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    ticker: str | None = Field(default=None, max_length=24)
    use_llm: bool = True


class DecisionPayload(BaseModel):
    decision: Literal["BUY", "HOLD", "SELL"]
    confidence: int = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class SpecialistSignal(BaseModel):
    agent_name: str
    stance: Literal["bullish", "neutral", "bearish"]
    confidence: float = Field(ge=0.0, le=1.0)
    score: float
    reasons: list[str] = Field(default_factory=list)


class ChartInsight(BaseModel):
    momentum: str
    support_level: float | None = None
    resistance_level: float | None = None
    rsi_14: float | None = None
    summary: str


class HistoricalContext(BaseModel):
    period: str
    return_percent: float | None = None
    sentiment_shift: str
    key_events: list[str] = Field(default_factory=list)
    summary: str


class MemoryInsight(BaseModel):
    analysis_id: str
    ticker: str
    query: str
    recommendation: str
    summary: str


class AnalyzeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: str
    created_at: datetime
    query: str
    recommendation: str
    confidence: float
    answer: str
    generation_mode: str
    stock: StockSnapshot
    sentiment: SentimentSummary
    news: list[NewsItem]
    thesis_points: list[str]
    risk_factors: list[str]
    data_sources: list[str]
    decision: DecisionPayload | None = None
    specialists: list[SpecialistSignal] = Field(default_factory=list)
    chart_insight: ChartInsight | None = None
    historical_context: HistoricalContext | None = None
    memory_context: list[MemoryInsight] = Field(default_factory=list)


class WatchlistResponse(BaseModel):
    generated_at: datetime
    items: list[StockSnapshot]


class PortfolioHoldingInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=24)
    weight: float | None = Field(default=None, ge=0.0, le=100.0)


class PortfolioAnalyzeRequest(BaseModel):
    holdings: list[PortfolioHoldingInput] = Field(min_length=1, max_length=12)


class PortfolioHoldingAnalysis(BaseModel):
    ticker: str
    company_name: str
    weight: float
    risk_score: int
    trend_signal: str
    sentiment_label: str
    recommendation: str
    summary: str


class PortfolioAnalysisResponse(BaseModel):
    generated_at: datetime
    risk_level: str
    diversification_score: int = Field(ge=0, le=100)
    concentration_score: int = Field(ge=0, le=100)
    overexposed_tickers: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    holdings: list[PortfolioHoldingAnalysis] = Field(default_factory=list)


class AlertCreateRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=24)
    alert_type: Literal["price_above", "price_below", "percent_drop"]
    threshold_value: float = Field(gt=0)


class AlertResponse(BaseModel):
    id: str
    ticker: str
    alert_type: str
    threshold_value: float
    active: bool
    triggered: bool
    current_price: float | None = None
    message: str
    created_at: datetime


class UserRegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=2, max_length=80)


class UserLoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class UserProfileResponse(BaseModel):
    id: str
    email: str
    name: str
    created_at: datetime


class AuthResponse(BaseModel):
    token: str
    user: UserProfileResponse


class WatchlistItemResponse(BaseModel):
    ticker: str
    created_at: datetime


class SavedWatchlistResponse(BaseModel):
    items: list[WatchlistItemResponse] = Field(default_factory=list)


class WatchlistUpdateRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=24)


class UserHistoryItem(BaseModel):
    analysis_id: str
    created_at: datetime
    query: str
    ticker: str
    recommendation: str
    confidence: float
    answer: str


class UserHistoryResponse(BaseModel):
    items: list[UserHistoryItem] = Field(default_factory=list)
