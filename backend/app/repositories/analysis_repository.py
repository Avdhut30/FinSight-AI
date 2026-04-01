from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import AnalysisRecord
from app.models.schemas import AnalyzeResponse


def save_analysis(db: Session, response: AnalyzeResponse, user_id: Optional[str] = None) -> AnalysisRecord:
    record = AnalysisRecord(
        id=response.analysis_id,
        user_id=user_id,
        query=response.query,
        ticker=response.stock.ticker,
        recommendation=response.recommendation,
        confidence=response.confidence,
        answer=response.answer,
        payload=response.model_dump(mode="json"),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_analysis(db: Session, analysis_id: str) -> Optional[AnalysisRecord]:
    return db.get(AnalysisRecord, analysis_id)
