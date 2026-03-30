import json
import logging
import asyncio

from openai import AsyncOpenAI

from app.core.model_config import LLMModelConfig
from app.core.settings import Settings
from app.models.schemas import NewsItem, SentimentSummary, StockSnapshot
from app.prompts import load_prompt

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_config = LLMModelConfig.from_settings(settings)
        self.client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self.system_prompt = load_prompt(self.model_config.system_prompt_file)
        self.analysis_prompt_template = load_prompt(self.model_config.analysis_prompt_file)

    @property
    def enabled(self) -> bool:
        return self.client is not None

    async def render_answer(
        self,
        query: str,
        stock: StockSnapshot,
        sentiment: SentimentSummary,
        news: list[NewsItem],
        recommendation: str,
        confidence: float,
        thesis_points: list[str],
        risk_factors: list[str],
        fallback_answer: str,
        use_llm: bool,
    ) -> tuple[str, str]:
        if not self.enabled or not use_llm:
            return fallback_answer, "heuristic"

        payload = {
            "query": query,
            "stock": stock.model_dump(mode="json"),
            "sentiment": sentiment.model_dump(mode="json"),
            "recommendation": recommendation,
            "confidence": confidence,
            "thesis_points": thesis_points,
            "risk_factors": risk_factors,
            "headlines": [item.model_dump(mode="json") for item in news[:5]],
        }

        try:
            user_prompt = self.analysis_prompt_template.format(
                query=query,
                payload_json=json.dumps(payload, indent=2),
            )
            completion = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model_config.model,
                    temperature=self.model_config.temperature,
                    max_tokens=self.model_config.max_tokens,
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                ),
                timeout=self.model_config.timeout_seconds,
            )
            message = completion.choices[0].message.content
            if not message:
                return fallback_answer, "heuristic"
            return message.strip(), "llm"
        except Exception:
            logger.warning("LLM answer generation failed; using heuristic output instead.", exc_info=True)
            return fallback_answer, "heuristic"
