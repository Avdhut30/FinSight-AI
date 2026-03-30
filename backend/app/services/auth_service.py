from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

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

        token = secrets.token_urlsafe(32)
        session = SessionRecord(
            user_id=user.id,
            token_hash=self._hash_token(token),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=self.settings.auth_session_hours),
        )
        db.add(session)
        db.commit()
        return user, token

    def authenticate(self, db: Session, token: str | None) -> UserRecord | None:
        if not token:
            return None

        now = datetime.now(timezone.utc)
        token_hash = self._hash_token(token)
        session = db.execute(
            select(SessionRecord).where(
                SessionRecord.token_hash == token_hash,
                SessionRecord.expires_at > now,
            )
        ).scalar_one_or_none()
        if session is None:
            return None

        return db.get(UserRecord, session.user_id)

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
