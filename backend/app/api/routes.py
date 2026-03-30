import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.dependencies import (
    get_alert_service,
    get_auth_service,
    get_db,
    get_portfolio_service,
    get_settings,
    get_stock_agent,
    get_stock_service,
)
from app.models.schemas import (
    AlertCreateRequest,
    AlertResponse,
    AnalyzeRequest,
    AnalyzeResponse,
    AuthResponse,
    PortfolioAnalysisResponse,
    PortfolioAnalyzeRequest,
    SavedWatchlistResponse,
    UserHistoryResponse,
    UserLoginRequest,
    UserProfileResponse,
    UserRegisterRequest,
    WatchlistResponse,
    WatchlistUpdateRequest,
)
from app.repositories.analysis_repository import get_analysis
from app.services.stock_service import StockService

logger = logging.getLogger(__name__)

router = APIRouter()


def _format_sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _parse_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def _resolve_optional_user(db: Session, auth_service, authorization: str | None):
    return auth_service.authenticate(db, _parse_bearer_token(authorization))


def _require_user(db: Session, auth_service, authorization: str | None):
    user = _resolve_optional_user(db, auth_service, authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


@router.get("/health")
async def health_check():
    return {"status": "ok"}


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_stock(
    payload: AnalyzeRequest,
    db: Session = Depends(get_db),
    agent=Depends(get_stock_agent),
    auth_service=Depends(get_auth_service),
    authorization: str | None = Header(default=None),
):
    user = _resolve_optional_user(db, auth_service, authorization)
    if user is None:
        return await agent.analyze(payload, db)
    return await agent.analyze(payload, db, user_id=user.id)


@router.post("/analyze/stream")
async def analyze_stock_stream(
    payload: AnalyzeRequest,
    db: Session = Depends(get_db),
    agent=Depends(get_stock_agent),
    auth_service=Depends(get_auth_service),
    authorization: str | None = Header(default=None),
):
    user = _resolve_optional_user(db, auth_service, authorization)

    async def event_stream():
        try:
            stream = agent.stream_analysis(payload, db) if user is None else agent.stream_analysis(payload, db, user_id=user.id)
            async for item in stream:
                yield _format_sse(item["event"], item["data"])
        except ValueError as exc:
            yield _format_sse("error", {"detail": str(exc)})
        except Exception:
            logger.exception("Streaming analysis failed")
            yield _format_sse("error", {"detail": "Unexpected server error."})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/analyses/{analysis_id}", response_model=AnalyzeResponse)
async def fetch_analysis(analysis_id: str, db: Session = Depends(get_db)):
    record = get_analysis(db, analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return record.payload


@router.get("/watchlist", response_model=WatchlistResponse)
async def get_watchlist(
    stock_service: StockService = Depends(get_stock_service),
    db: Session = Depends(get_db),
    auth_service=Depends(get_auth_service),
    settings=Depends(get_settings),
    authorization: str | None = Header(default=None),
):
    tickers = settings.default_watchlist
    user = _resolve_optional_user(db, auth_service, authorization)
    if user is not None:
        saved_items = auth_service.list_watchlist(db, user.id)
        if saved_items:
            tickers = [item.ticker for item in saved_items]
    items = await stock_service.get_watchlist(tickers)
    return WatchlistResponse(generated_at=datetime.now(timezone.utc), items=items)


@router.post("/portfolio/analyze", response_model=PortfolioAnalysisResponse)
async def analyze_portfolio(
    payload: PortfolioAnalyzeRequest,
    portfolio_service=Depends(get_portfolio_service),
):
    return await portfolio_service.analyze(payload)


@router.post("/auth/register", response_model=AuthResponse)
async def register_user(
    payload: UserRegisterRequest,
    db: Session = Depends(get_db),
    auth_service=Depends(get_auth_service),
):
    user = auth_service.register(db, payload.email, payload.password, payload.name)
    user, token = auth_service.login(db, payload.email, payload.password)
    return AuthResponse(token=token, user=auth_service.to_profile(user))


@router.post("/auth/login", response_model=AuthResponse)
async def login_user(
    payload: UserLoginRequest,
    db: Session = Depends(get_db),
    auth_service=Depends(get_auth_service),
):
    user, token = auth_service.login(db, payload.email, payload.password)
    return AuthResponse(token=token, user=auth_service.to_profile(user))


@router.get("/auth/me", response_model=UserProfileResponse)
async def get_current_user_profile(
    db: Session = Depends(get_db),
    auth_service=Depends(get_auth_service),
    authorization: str | None = Header(default=None),
):
    user = _require_user(db, auth_service, authorization)
    return auth_service.to_profile(user)


@router.get("/me/history", response_model=UserHistoryResponse)
async def get_user_history(
    db: Session = Depends(get_db),
    auth_service=Depends(get_auth_service),
    authorization: str | None = Header(default=None),
):
    user = _require_user(db, auth_service, authorization)
    return UserHistoryResponse(items=auth_service.get_history(db, user.id))


@router.get("/me/watchlist", response_model=SavedWatchlistResponse)
async def get_saved_watchlist(
    db: Session = Depends(get_db),
    auth_service=Depends(get_auth_service),
    authorization: str | None = Header(default=None),
):
    user = _require_user(db, auth_service, authorization)
    return SavedWatchlistResponse(items=auth_service.list_watchlist(db, user.id))


@router.post("/me/watchlist", response_model=SavedWatchlistResponse)
async def add_saved_watchlist_item(
    payload: WatchlistUpdateRequest,
    db: Session = Depends(get_db),
    auth_service=Depends(get_auth_service),
    authorization: str | None = Header(default=None),
):
    user = _require_user(db, auth_service, authorization)
    auth_service.add_watchlist_item(db, user.id, payload.ticker)
    return SavedWatchlistResponse(items=auth_service.list_watchlist(db, user.id))


@router.post("/alerts", response_model=AlertResponse)
async def create_alert(
    payload: AlertCreateRequest,
    db: Session = Depends(get_db),
    auth_service=Depends(get_auth_service),
    alert_service=Depends(get_alert_service),
    authorization: str | None = Header(default=None),
):
    user = _require_user(db, auth_service, authorization)
    return alert_service.create_alert(db, user.id, payload.ticker, payload.alert_type, payload.threshold_value)


@router.get("/alerts", response_model=list[AlertResponse])
async def list_alerts(
    db: Session = Depends(get_db),
    auth_service=Depends(get_auth_service),
    alert_service=Depends(get_alert_service),
    authorization: str | None = Header(default=None),
):
    user = _require_user(db, auth_service, authorization)
    return await alert_service.list_alerts(db, user.id)
