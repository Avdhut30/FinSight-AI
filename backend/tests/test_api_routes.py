from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.dependencies import get_db, get_settings, get_stock_agent, get_stock_service
from app.main import app
from app.models.schemas import AnalyzeResponse, NewsItem, SentimentSummary, StockSnapshot


def _make_stock(ticker: str = "INFY.NS") -> StockSnapshot:
    return StockSnapshot(
        ticker=ticker,
        company_name="Infosys Ltd",
        currency="INR",
        exchange="NSI",
        sector="Technology",
        current_price=1500.0,
        previous_close=1480.0,
        day_change_percent=1.35,
        market_cap=1000000.0,
        pe_ratio=24.0,
        volume=12000,
        average_volume=10000,
        fifty_two_week_high=1700.0,
        fifty_two_week_low=1200.0,
        one_month_return_percent=9.2,
        six_month_return_percent=18.3,
        trend_signal="bullish",
        valuation_signal="balanced",
        summary="Infosys trades above its 20D and 50D averages.",
        price_history=[],
    )


def _make_sentiment() -> SentimentSummary:
    return SentimentSummary(
        overall_label="positive",
        score=0.4,
        confidence=0.72,
        positive_count=4,
        negative_count=1,
        neutral_count=1,
        summary="Headline sentiment is positive.",
    )


def _parse_sse_events(payload: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in payload.strip().split("\n\n"):
        lines = block.splitlines()
        event = "message"
        data = None
        for line in lines:
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = line.split(":", 1)[1].strip()
        if data is not None:
            import json

            events.append((event, json.loads(data)))
    return events


@pytest.fixture
def client():
    original_overrides = app.dependency_overrides.copy()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides = original_overrides


def test_watchlist_route_returns_items_from_overridden_service(client: TestClient):
    stock = _make_stock("TCS.NS")

    class StubStockService:
        def __init__(self) -> None:
            self.requested_tickers: list[str] | None = None

        async def get_watchlist(self, tickers: list[str]) -> list[StockSnapshot]:
            self.requested_tickers = tickers
            return [stock]

    stub_service = StubStockService()
    settings = Settings(_env_file=None, default_watchlist=["TCS.NS", "INFY.NS"])

    app.dependency_overrides[get_stock_service] = lambda: stub_service
    app.dependency_overrides[get_settings] = lambda: settings

    response = client.get("/api/v1/watchlist")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    payload = response.json()
    assert payload["items"][0]["ticker"] == "TCS.NS"
    assert stub_service.requested_tickers == ["TCS.NS", "INFY.NS"]


def test_analyze_route_returns_agent_response(client: TestClient):
    stock = _make_stock()
    sentiment = _make_sentiment()

    class StubAgent:
        def __init__(self) -> None:
            self.received_query: str | None = None
            self.received_db = None

        async def analyze(self, payload, db):
            self.received_query = payload.query
            self.received_db = db
            return AnalyzeResponse(
                analysis_id="analysis-123",
                created_at=datetime(2026, 3, 27, tzinfo=timezone.utc),
                query=payload.query,
                recommendation="hold",
                confidence=0.71,
                answer="Hold for now while momentum and sentiment stay constructive.",
                generation_mode="heuristic",
                stock=stock,
                sentiment=sentiment,
                news=[NewsItem(title="Infosys gains after strong quarter")],
                thesis_points=["Trend is constructive."],
                risk_factors=["Valuation is not cheap."],
                data_sources=["Twelve Data market data"],
            )

    stub_agent = StubAgent()
    stub_db = object()

    def override_db():
        yield stub_db

    app.dependency_overrides[get_stock_agent] = lambda: stub_agent
    app.dependency_overrides[get_db] = override_db

    response = client.post("/api/v1/analyze", json={"query": "Should I buy Infosys now?", "use_llm": False})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    payload = response.json()
    assert payload["analysis_id"] == "analysis-123"
    assert payload["recommendation"] == "hold"
    assert payload["stock"]["ticker"] == "INFY.NS"
    assert stub_agent.received_query == "Should I buy Infosys now?"
    assert stub_agent.received_db is stub_db


def test_analyze_stream_route_emits_sse_events(client: TestClient):
    response_payload = AnalyzeResponse(
        analysis_id="analysis-stream-123",
        created_at=datetime(2026, 3, 27, tzinfo=timezone.utc),
        query="Should I buy Infosys now?",
        recommendation="hold",
        confidence=0.71,
        answer="Hold for now while momentum and sentiment stay constructive.",
        generation_mode="heuristic",
        stock=_make_stock(),
        sentiment=_make_sentiment(),
        news=[NewsItem(title="Infosys gains after strong quarter")],
        thesis_points=["Trend is constructive."],
        risk_factors=["Valuation is not cheap."],
        data_sources=["Twelve Data market data"],
    )

    class StubStreamingAgent:
        async def stream_analysis(self, payload, db):
            assert payload.query == "Should I buy Infosys now?"
            assert db is stub_db
            yield {"event": "status", "data": {"stage": "resolve_ticker", "message": "Resolving company and ticker..."}}
            yield {"event": "answer_delta", "data": {"delta": "Hold for now "}}
            yield {"event": "answer_delta", "data": {"delta": "while momentum stays constructive."}}
            yield {"event": "complete", "data": response_payload.model_dump(mode="json")}

    stub_db = object()

    def override_db():
        yield stub_db

    app.dependency_overrides[get_stock_agent] = lambda: StubStreamingAgent()
    app.dependency_overrides[get_db] = override_db

    response = client.post("/api/v1/analyze/stream", json={"query": "Should I buy Infosys now?", "use_llm": False})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse_events(response.text)
    assert events[0][0] == "status"
    assert events[0][1]["stage"] == "resolve_ticker"
    assert events[1] == ("answer_delta", {"delta": "Hold for now "})
    assert events[2] == ("answer_delta", {"delta": "while momentum stays constructive."})
    assert events[3][0] == "complete"
    assert events[3][1]["analysis_id"] == "analysis-stream-123"
