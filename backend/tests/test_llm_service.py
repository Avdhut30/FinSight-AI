import asyncio
from types import SimpleNamespace

from app.core.settings import Settings
from app.prompts import load_prompt
from app.services.llm_service import LLMService
from app.models.schemas import NewsItem, SentimentSummary, StockSnapshot


def _make_stock() -> StockSnapshot:
    return StockSnapshot(
        ticker="INFY.NS",
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


class StubChatCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Configured LLM answer."))]
        )


class StubClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=StubChatCompletions())


def test_render_answer_uses_prompt_files_and_model_config():
    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        openai_model="gpt-4o-mini",
        openai_temperature=0.35,
        openai_max_tokens=180,
    )
    service = LLMService(settings)
    service.client = StubClient()

    answer, mode = asyncio.run(
        service.render_answer(
            query="Should I buy Infosys now?",
            stock=_make_stock(),
            sentiment=_make_sentiment(),
            news=[NewsItem(title="Infosys gains after strong quarter")],
            recommendation="hold",
            confidence=0.71,
            thesis_points=["Trend is constructive."],
            risk_factors=["Valuation is not cheap."],
            fallback_answer="Fallback answer.",
            use_llm=True,
        )
    )

    call = service.client.chat.completions.calls[0]
    assert answer == "Configured LLM answer."
    assert mode == "llm"
    assert call["model"] == "gpt-4o-mini"
    assert call["temperature"] == 0.35
    assert call["max_tokens"] == 180
    assert call["messages"][0]["content"] == load_prompt("system_prompt.txt")
    assert "Should I buy Infosys now?" in call["messages"][1]["content"]
    assert '"recommendation": "hold"' in call["messages"][1]["content"]


def test_render_answer_returns_fallback_when_llm_is_disabled():
    settings = Settings(_env_file=None)
    service = LLMService(settings)

    answer, mode = asyncio.run(
        service.render_answer(
            query="Should I buy Infosys now?",
            stock=_make_stock(),
            sentiment=_make_sentiment(),
            news=[],
            recommendation="hold",
            confidence=0.71,
            thesis_points=["Trend is constructive."],
            risk_factors=["Valuation is not cheap."],
            fallback_answer="Fallback answer.",
            use_llm=False,
        )
    )

    assert answer == "Fallback answer."
    assert mode == "heuristic"
