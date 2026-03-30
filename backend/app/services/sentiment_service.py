import asyncio
import logging
import re

from app.core.settings import Settings
from app.models.schemas import NewsItem, SentimentSummary

logger = logging.getLogger(__name__)


class SentimentService:
    positive_terms = {
        "beat",
        "beats",
        "bullish",
        "buyback",
        "growth",
        "improves",
        "gain",
        "gains",
        "record",
        "rise",
        "rises",
        "strong",
        "surge",
        "upgrade",
        "wins",
    }
    negative_terms = {
        "bearish",
        "cuts",
        "decline",
        "declines",
        "debt",
        "downgrade",
        "drop",
        "drops",
        "fall",
        "falls",
        "loss",
        "miss",
        "misses",
        "probe",
        "weak",
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._pipeline = None
        self._pipeline_attempted = False

    async def analyze(self, news_items: list[NewsItem]) -> SentimentSummary:
        if not news_items:
            return SentimentSummary(
                overall_label="neutral",
                score=0.0,
                confidence=0.3,
                positive_count=0,
                negative_count=0,
                neutral_count=0,
                summary="No recent headlines were available, so sentiment is treated as neutral.",
            )

        texts = [self._compose_text(item) for item in news_items]
        classifier = self._get_pipeline()
        article_scores = (
            await asyncio.to_thread(self._run_finbert, texts) if classifier is not None else self._run_lexicon(texts)
        )

        positive_count = 0
        negative_count = 0
        neutral_count = 0
        signed_scores: list[float] = []

        for item, result in zip(news_items, article_scores, strict=False):
            label = result["label"]
            score = float(result["score"])
            item.sentiment_label = label
            item.sentiment_score = round(score, 2)
            if label == "positive":
                positive_count += 1
                signed_scores.append(score)
            elif label == "negative":
                negative_count += 1
                signed_scores.append(-score)
            else:
                neutral_count += 1
                signed_scores.append(0.0)

        aggregate_score = round(sum(signed_scores) / len(signed_scores), 2)
        if aggregate_score > 0.15:
            overall = "positive"
        elif aggregate_score < -0.15:
            overall = "negative"
        else:
            overall = "neutral"

        confidence = round(min(0.95, 0.45 + abs(aggregate_score)), 2)
        summary = (
            f"Headline sentiment is {overall}: {positive_count} positive, "
            f"{negative_count} negative, and {neutral_count} neutral articles."
        )
        return SentimentSummary(
            overall_label=overall,
            score=aggregate_score,
            confidence=confidence,
            positive_count=positive_count,
            negative_count=negative_count,
            neutral_count=neutral_count,
            summary=summary,
        )

    def _get_pipeline(self):
        if self._pipeline_attempted:
            return self._pipeline

        self._pipeline_attempted = True
        if not self.settings.enable_transformers_sentiment:
            return None

        try:
            from transformers import pipeline

            self._pipeline = pipeline(
                "text-classification",
                model=self.settings.finbert_model_name,
                tokenizer=self.settings.finbert_model_name,
                truncation=True,
                max_length=256,
            )
        except Exception:
            logger.warning("Falling back to lexicon sentiment because FinBERT could not be loaded.", exc_info=True)
            self._pipeline = None
        return self._pipeline

    def _run_finbert(self, texts: list[str]) -> list[dict[str, float | str]]:
        results = self._pipeline(texts)
        mapped_results: list[dict[str, float | str]] = []
        for item in results:
            raw_label = str(item["label"]).lower()
            if "positive" in raw_label:
                label = "positive"
            elif "negative" in raw_label:
                label = "negative"
            else:
                label = "neutral"
            mapped_results.append({"label": label, "score": float(item["score"])})
        return mapped_results

    def _run_lexicon(self, texts: list[str]) -> list[dict[str, float | str]]:
        results: list[dict[str, float | str]] = []
        for text in texts:
            tokens = re.findall(r"[a-z]+", text.lower())
            positive_hits = sum(token in self.positive_terms for token in tokens)
            negative_hits = sum(token in self.negative_terms for token in tokens)
            raw_score = positive_hits - negative_hits
            if raw_score > 0:
                label = "positive"
            elif raw_score < 0:
                label = "negative"
            else:
                label = "neutral"
            confidence = min(0.9, 0.55 + 0.08 * abs(raw_score)) if label != "neutral" else 0.4
            results.append({"label": label, "score": round(confidence, 2)})
        return results

    @staticmethod
    def _compose_text(item: NewsItem) -> str:
        parts = [item.title]
        if item.summary:
            parts.append(item.summary)
        return ". ".join(parts)

