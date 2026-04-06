from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.db.models import AnalysisRecord, SavedWatchlistRecord, SessionRecord, UserRecord
from app.models.schemas import UserHistoryItem, UserProfileResponse, WatchlistItemResponse


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def register(self, db: Session, email: str, password: str, name: str) -> UserRecord:
        normalized_email = email.strip().lower()
        existing = db.execute(select(UserRecord).where(UserRecord.email == normalized_email)).scalar_one_or_none()
        if existing is not None:
            raise ValueError("An account with that email already exists.")

        user = UserRecord(
            email=normalized_email,
            name=name.strip(),
            password_hash=self._hash_password(password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def login(self, db: Session, email: str, password: str) -> tuple[UserRecord, str]:
        normalized_email = email.strip().lower()
        user = db.execute(select(UserRecord).where(UserRecord.email == normalized_email)).scalar_one_or_none()
        if user is None or not self._verify_password(password, user.password_hash):
            raise ValueError("Invalid email or password.")

        expires_at = datetime.now(timezone.utc) + timedelta(hours=self.settings.auth_session_hours)
        token = self._sign_token(user.id, expires_at)
        # Optional: persist for audit, but not required for validation (stateless token)
        session = SessionRecord(
            user_id=user.id,
            token_hash=self._hash_token(token),
            expires_at=expires_at,
        )
        db.add(session)
        db.commit()
        return user, token

    def authenticate(self, db: Session, token: Optional[str]) -> Optional[UserRecord]:
        if not token:
            return None

        user_id, expires_at = self._verify_signed_token(token)
        if user_id is None or expires_at < datetime.now(timezone.utc):
            return None
        return db.get(UserRecord, user_id)

    def list_watchlist(self, db: Session, user_id: str) -> list[WatchlistItemResponse]:
        rows = db.execute(
            select(SavedWatchlistRecord)
            .where(SavedWatchlistRecord.user_id == user_id)
            .order_by(SavedWatchlistRecord.created_at.desc())
        ).scalars()
        return [WatchlistItemResponse(ticker=row.ticker, created_at=row.created_at) for row in rows]

    def add_watchlist_item(self, db: Session, user_id: str, ticker: str) -> WatchlistItemResponse:
        normalized_ticker = self._normalize_ticker(ticker)
        existing = db.execute(
            select(SavedWatchlistRecord).where(
                SavedWatchlistRecord.user_id == user_id,
                SavedWatchlistRecord.ticker == normalized_ticker,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return WatchlistItemResponse(ticker=existing.ticker, created_at=existing.created_at)

        record = SavedWatchlistRecord(user_id=user_id, ticker=normalized_ticker)
        db.add(record)
        db.commit()
        db.refresh(record)
        return WatchlistItemResponse(ticker=record.ticker, created_at=record.created_at)

    def get_history(self, db: Session, user_id: str, limit: int = 12) -> list[UserHistoryItem]:
        rows = db.execute(
            select(AnalysisRecord)
            .where(AnalysisRecord.user_id == user_id)
            .order_by(AnalysisRecord.created_at.desc())
            .limit(limit)
        ).scalars()
        return [
            UserHistoryItem(
                analysis_id=row.id,
                created_at=row.created_at,
                query=row.query,
                ticker=row.ticker,
                recommendation=row.recommendation,
                confidence=row.confidence,
                answer=row.answer,
            )
            for row in rows
        ]

    @staticmethod
    def to_profile(user: UserRecord) -> UserProfileResponse:
        return UserProfileResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            created_at=user.created_at,
        )

    def _hash_password(self, password: str) -> str:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            120_000,
        ).hex()
        return f"{salt}${digest}"

    def _verify_password(self, password: str, encoded: str) -> bool:
        salt, digest = encoded.split("$", 1)
        expected = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            120_000,
        ).hex()
        return hmac.compare_digest(expected, digest)

    def _hash_token(self, token: str) -> str:
        return hmac.new(self.settings.auth_secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()

    def _sign_token(self, user_id: str, expires_at: datetime) -> str:
        payload = f"{user_id}.{int(expires_at.timestamp())}.{secrets.token_hex(8)}"
        signature = hmac.new(self.settings.auth_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def _verify_signed_token(self, token: str) -> tuple[Optional[str], Optional[datetime]]:
        parts = token.split(".")
        if len(parts) < 4:
            return None, None
        signature = parts[-1]
        payload = ".".join(parts[:-1])
        expected = hmac.new(self.settings.auth_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None, None
        try:
            user_id, exp_ts, _nonce = payload.split(".", 2)
            expires_at = datetime.fromtimestamp(int(exp_ts), tz=timezone.utc)
            return user_id, expires_at
        except Exception:
            return None, None

    @staticmethod
    def _normalize_ticker(ticker: str) -> str:
        symbol = ticker.strip().upper()
        if symbol.endswith(".NS") or symbol.endswith(".BO"):
            return symbol
        if symbol.endswith(".NSE"):
            return f"{symbol[:-4]}.NS"
        if symbol.endswith(".BSE"):
            return f"{symbol[:-4]}.BO"
        return f"{symbol}.NS"
