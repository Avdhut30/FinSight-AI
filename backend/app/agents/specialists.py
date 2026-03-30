from __future__ import annotations

from app.models.schemas import SentimentSummary, SpecialistSignal, StockSnapshot


class TechnicalAgent:
    def analyze(self, stock: StockSnapshot) -> SpecialistSignal:
        score = 0.0
        reasons: list[str] = []

        if stock.trend_signal == "bullish":
            score += 1.2
            reasons.append("Trend structure is bullish across the recent price history.")
        elif stock.trend_signal == "bearish":
            score -= 1.2
            reasons.append("Trend structure remains bearish and below key moving averages.")
        else:
            reasons.append("Trend is range-bound rather than decisively directional.")

        if stock.rsi_14 is not None:
            if stock.rsi_14 >= 60:
                score += 0.7
                reasons.append(f"RSI is {stock.rsi_14:.1f}, which supports bullish momentum.")
            elif stock.rsi_14 <= 40:
                score -= 0.7
                reasons.append(f"RSI is {stock.rsi_14:.1f}, which reflects weak momentum.")
            else:
                reasons.append(f"RSI is {stock.rsi_14:.1f}, which suggests neutral momentum.")

        if stock.current_price and stock.support_level and stock.current_price > stock.support_level:
            reasons.append(f"Price is holding above support near {stock.support_level:.2f}.")
        if stock.current_price and stock.resistance_level and stock.current_price < stock.resistance_level:
            reasons.append(f"Resistance is clustered near {stock.resistance_level:.2f}.")

        stance = "bullish" if score > 0.55 else "bearish" if score < -0.55 else "neutral"
        confidence = min(0.92, 0.5 + abs(score) * 0.12)
        return SpecialistSignal(
            agent_name="Technical Agent",
            stance=stance,
            confidence=round(confidence, 2),
            score=round(score, 2),
            reasons=reasons[:4],
        )


class NewsAgent:
    def analyze(self, sentiment: SentimentSummary) -> SpecialistSignal:
        reasons = [sentiment.summary]
        score = sentiment.score * 2
        if sentiment.overall_label == "positive":
            reasons.append("News flow is supportive and can reinforce the current thesis.")
        elif sentiment.overall_label == "negative":
            reasons.append("Negative headlines can cap upside until the narrative improves.")
        else:
            reasons.append("News flow is balanced, so sentiment is not a decisive edge.")

        stance = "bullish" if sentiment.overall_label == "positive" else "bearish" if sentiment.overall_label == "negative" else "neutral"
        return SpecialistSignal(
            agent_name="News Agent",
            stance=stance,
            confidence=round(sentiment.confidence, 2),
            score=round(score, 2),
            reasons=reasons[:3],
        )


class FundamentalAgent:
    def analyze(self, stock: StockSnapshot) -> SpecialistSignal:
        score = 0.0
        reasons: list[str] = []

        if stock.valuation_signal == "value-tilted":
            score += 0.9
            reasons.append("Valuation screens as value-tilted versus the available P/E context.")
        elif stock.valuation_signal == "expensive":
            score -= 0.9
            reasons.append("Valuation looks rich, which raises de-rating risk.")
        else:
            reasons.append("Valuation is balanced or incomplete, so fundamentals are mixed.")

        if stock.six_month_return_percent is not None:
            if stock.six_month_return_percent > 12:
                score += 0.6
                reasons.append(f"Six-month return of {stock.six_month_return_percent:+.2f}% supports durable strength.")
            elif stock.six_month_return_percent < -12:
                score -= 0.6
                reasons.append(f"Six-month return of {stock.six_month_return_percent:+.2f}% signals weak operating momentum.")

        if stock.risk_score is not None:
            if stock.risk_score >= 70:
                score -= 0.5
                reasons.append("The composite risk score is elevated.")
            elif stock.risk_score <= 40:
                score += 0.4
                reasons.append("The composite risk score is relatively contained.")

        stance = "bullish" if score > 0.45 else "bearish" if score < -0.45 else "neutral"
        confidence = min(0.9, 0.48 + abs(score) * 0.15)
        return SpecialistSignal(
            agent_name="Fundamental Agent",
            stance=stance,
            confidence=round(confidence, 2),
            score=round(score, 2),
            reasons=reasons[:4],
        )
