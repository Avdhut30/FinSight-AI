from dataclasses import dataclass

from app.core.settings import Settings


@dataclass(frozen=True)
class LLMModelConfig:
    model: str
    temperature: float
    max_tokens: int
    timeout_seconds: float
    system_prompt_file: str = "system_prompt.txt"
    analysis_prompt_file: str = "stock_analysis_prompt.txt"

    @classmethod
    def from_settings(cls, settings: Settings) -> "LLMModelConfig":
        return cls(
            model=settings.openai_model,
            temperature=settings.openai_temperature,
            max_tokens=settings.openai_max_tokens,
            timeout_seconds=settings.openai_timeout_seconds,
        )
