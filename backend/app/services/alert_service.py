from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AlertRecord
from app.models.schemas import AlertResponse, StockSnapshot
from app.services.stock_service import StockService


class AlertService:
    def __init__(self, stock_service: StockService) -> None:
        self.stock_service = stock_service

    def create_alert(self, db: Session, user_id: str, ticker: str, alert_type: str, threshold_value: float) -> AlertResponse:
        record = AlertRecord(
            user_id=user_id,
            ticker=self._normalize_ticker(ticker),
            alert_type=alert_type,
            threshold_value=threshold_value,
            active=True,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return AlertResponse(
            id=record.id,
            ticker=record.ticker,
            alert_type=record.alert_type,
            threshold_value=record.threshold_value,
            active=record.active,
            triggered=False,
            current_price=None,
            message="Alert created.",
            created_at=record.created_at,
        )

    async def list_alerts(self, db: Session, user_id: str) -> list[AlertResponse]:
        rows = db.execute(
            select(AlertRecord).where(AlertRecord.user_id == user_id).order_by(AlertRecord.created_at.desc())
        ).scalars()
        results: list[AlertResponse] = []
        for row in rows:
            snapshot = await self.stock_service.get_snapshot(row.ticker)
            triggered, message = self._evaluate(row, snapshot)
            if triggered and row.triggered_at is None:
                row.triggered_at = datetime.now(timezone.utc)
                row.active = False
            results.append(
                AlertResponse(
                    id=row.id,
                    ticker=row.ticker,
                    alert_type=row.alert_type,
                    threshold_value=row.threshold_value,
                    active=row.active,
                    triggered=triggered,
                    current_price=snapshot.current_price,
                    message=message,
                    created_at=row.created_at,
                )
            )
        db.commit()
        return results

    @staticmethod
    def _evaluate(alert: AlertRecord, snapshot: StockSnapshot) -> tuple[bool, str]:
        current_price = snapshot.current_price
        triggered = False

        if alert.alert_type == "price_above":
            triggered = current_price >= alert.threshold_value
            message = f"{snapshot.ticker} is at {current_price:.2f}; alert triggers above {alert.threshold_value:.2f}."
        elif alert.alert_type == "price_below":
            triggered = current_price <= alert.threshold_value
            message = f"{snapshot.ticker} is at {current_price:.2f}; alert triggers below {alert.threshold_value:.2f}."
        else:
            day_change = snapshot.day_change_percent or 0.0
            triggered = day_change <= -abs(alert.threshold_value)
            message = (
                f"{snapshot.ticker} moved {day_change:+.2f}% today; "
                f"alert triggers on a drop of {alert.threshold_value:.2f}% or more."
            )

        if triggered:
            return True, f"Triggered: {message}"
        return False, message

    @staticmethod
    def _normalize_ticker(ticker: str) -> str:
        symbol = ticker.strip().upper()
        if symbol.endswith(".NS") or symbol.endswith(".BO"):
            return symbol
        return f"{symbol}.NS"
