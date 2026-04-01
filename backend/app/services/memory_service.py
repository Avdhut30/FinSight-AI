from __future__ import annotations

import math
import re
from collections import Counter
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AnalysisRecord
from app.models.schemas import MemoryInsight


class MemoryService:
    def retrieve_similar(
        self,
        db: Session,
        query: str,
        ticker: str,
        user_id: Optional[str] = None,
        limit: int = 3,
    ) -> list[MemoryInsight]:
        statement = select(AnalysisRecord).where(AnalysisRecord.ticker == ticker).order_by(AnalysisRecord.created_at.desc()).limit(20)
        if user_id is not None:
            statement = (
                select(AnalysisRecord)
                .where(AnalysisRecord.ticker == ticker, AnalysisRecord.user_id == user_id)
                .order_by(AnalysisRecord.created_at.desc())
                .limit(20)
            )

        rows = db.execute(statement).scalars().all()
        query_vector = self._vectorize(query)
        scored: list[tuple[float, AnalysisRecord]] = []

        for row in rows:
            similarity = self._cosine_similarity(query_vector, self._vectorize(f"{row.query} {row.answer}"))
            if similarity > 0:
                scored.append((similarity, row))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            MemoryInsight(
                analysis_id=row.id,
                ticker=row.ticker,
                query=row.query,
                recommendation=row.recommendation,
                summary=row.answer[:180].strip(),
            )
            for _, row in scored[:limit]
        ]

    @staticmethod
    def _vectorize(text: str) -> Counter[str]:
        return Counter(re.findall(r"[a-z]{3,}", text.lower()))

    @staticmethod
    def _cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
        if not left or not right:
            return 0.0

        dot = sum(left[token] * right[token] for token in left.keys() & right.keys())
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)
