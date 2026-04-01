import asyncio
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

from app.agents.stock_agent import StockAnalysisAgent
from app.models.schemas import AnalyzeRequest, SentimentSummary, StockSnapshot


def _make_stock(**overrides):
    payload = {
        "ticker": "INFY.NS",
        "company_name": "Infosys Ltd",
        "currency": "INR",
        "exchange": "NSI",
        "sector": "Technology",
        "current_price": 1500.0,
        "previous_close": 1480.0,
        "day_change_percent": 1.35,
        "market_cap": 1000000.0,
        "pe_ratio": 24.0,
        "volume": 12000,
        "average_volume": 10000,
        "fifty_two_week_high": 1700.0,
        "fifty_two_week_low": 1200.0,
        "one_month_return_percent": 9.2,
        "six_month_return_percent": 18.3,
        "trend_signal": "bullish",
        "valuation_signal": "balanced",
        "summary": "Infosys trades above its 20D and 50D averages.",
        "price_history": [],
    }
    payload.update(overrides)
    return StockSnapshot(**payload)


def _make_sentiment(**overrides):
    payload = {
        "overall_label": "positive",
        "score": 0.4,
        "confidence": 0.72,
        "positive_count": 4,
        "negative_count": 1,
        "neutral_count": 1,
        "summary": "Headline sentiment is positive.",
    }
    payload.update(overrides)
    return SentimentSummary(**payload)


def test_build_view_accumulate_signal():
    agent = StockAnalysisAgent(None, None, None, None, None, 5)
    specialists = agent._run_specialists(_make_stock(), _make_sentiment())
    recommendation, confidence, thesis, risks, decision = agent._build_view(_make_stock(), _make_sentiment(), specialists)
    assert recommendation == "buy"
    assert decision.decision == "BUY"
    assert confidence >= 0.7
    assert thesis
    assert risks


def test_build_fast_draft_uses_neutral_sentiment_first_pass():
    agent = StockAnalysisAgent(None, None, None, None, None, 5)
    draft = agent._build_fast_draft(type("Request", (), {"query": "Should I buy Infosys now?"})(), _make_stock())

    assert draft.generation_mode == "heuristic-fast"
    assert draft.sentiment.overall_label == "neutral"
    assert draft.news == []
    assert "first pass is based on price action and trend" in draft.sentiment.summary
    assert draft.answer


def test_persist_response_does_not_raise_when_database_save_fails(monkeypatch):
    agent = StockAnalysisAgent(None, None, None, None, None, 5)
    response = type(
        "Response",
        (),
        {
            "analysis_id": "analysis-1",
            "stock": type("Stock", (), {"ticker": "INFY.NS"})(),
        },
    )()

    class StubSession:
        def __init__(self):
            self.rolled_back = False

        def rollback(self):
            self.rolled_back = True

    def failing_save_analysis(db, payload):
        raise SQLAlchemyError("db down")

    monkeypatch.setattr("app.agents.stock_agent.save_analysis", failing_save_analysis)

    session = StubSession()
    agent._persist_response(session, response)

    assert session.rolled_back is True


def test_stream_analysis_completes_with_fast_draft_when_refinement_fails(monkeypatch):
    stock = _make_stock()

    class StubStockService:
        market_data_source_label = "Twelve Data market data"

        async def get_snapshot(self, ticker: str):
            assert ticker == "INFY.NS"
            return stock

    class StubNewsService:
        async def get_news(self, ticker: str, company_name: str, limit: int):
            raise RuntimeError("news provider down")

    class StubSentimentService:
        async def analyze(self, news_items):
            return _make_sentiment()

    class StubLLMService:
        async def render_answer(self, **kwargs):
            return "refined answer", "heuristic"

    class StubTickerResolver:
        def resolve(self, query: str, explicit_ticker: Optional[str] = None):
            return "INFY.NS"

    class StubDb:
        def rollback(self):
            pass

    monkeypatch.setattr("app.agents.stock_agent.save_analysis", lambda db, response: None)

    agent = StockAnalysisAgent(
        StubStockService(),
        StubNewsService(),
        StubSentimentService(),
        StubLLMService(),
        StubTickerResolver(),
        5,
    )

    async def collect_events():
        request = AnalyzeRequest(query="Give me a short-term view on Infosys", use_llm=False)
        events = []
        async for event in agent.stream_analysis(request, StubDb()):
            events.append(event)
        return events

    events = asyncio.run(collect_events())

    answer_text = "".join(event["data"]["delta"] for event in events if event["event"] == "answer_delta")
    complete_payload = next(event["data"] for event in events if event["event"] == "complete")

    assert all(event["event"] != "error" for event in events)
    assert complete_payload["answer"] == answer_text
    assert complete_payload["generation_mode"] == "heuristic-fast"
