from collections import defaultdict, deque
import logging
from threading import Lock
from time import monotonic

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int, window_seconds: int) -> None:
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    async def dispatch(self, request: Request, call_next):
        if request.url.path.endswith("/health") or request.method == "OPTIONS":
            return await call_next(request)

        client_ip = request.client.host if request.client else "anonymous"
        now = monotonic()

        with self._lock:
            bucket = self._hits[client_ip]
            while bucket and now - bucket[0] > self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                logger.warning(
                    "Rate limit exceeded client_ip=%s method=%s path=%s max_requests=%s window_seconds=%s",
                    client_ip,
                    request.method,
                    request.url.path,
                    self.max_requests,
                    self.window_seconds,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": f"Rate limit exceeded: max {self.max_requests} requests every {self.window_seconds} seconds."
                    },
                )
            bucket.append(now)

        return await call_next(request)
