import logging
from contextvars import ContextVar, Token
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import MutableHeaders

REQUEST_ID_HEADER = "X-Request-ID"
_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

logger = logging.getLogger(__name__)


def get_request_id() -> str:
    return _request_id_ctx.get()


def set_request_id(request_id: str) -> Token[str]:
    return _request_id_ctx.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    _request_id_ctx.reset(token)


class RequestContextMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = MutableHeaders(scope=scope)
        request_id = headers.get(REQUEST_ID_HEADER, str(uuid4()))
        token = set_request_id(request_id)
        scope.setdefault("state", {})["request_id"] = request_id

        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "")
        client = scope.get("client")
        client_ip = client[0] if client else "anonymous"
        started_at = perf_counter()
        status_code = 500

        logger.info("Request started method=%s path=%s client_ip=%s", method, path, client_ip)

        async def send_wrapper(message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_headers = MutableHeaders(raw=message.setdefault("headers", []))
                response_headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            duration_ms = (perf_counter() - started_at) * 1000
            logger.exception(
                "Request failed method=%s path=%s status_code=%s duration_ms=%.2f client_ip=%s",
                method,
                path,
                status_code,
                duration_ms,
                client_ip,
            )
            raise
        else:
            duration_ms = (perf_counter() - started_at) * 1000
            logger.info(
                "Request completed method=%s path=%s status_code=%s duration_ms=%.2f client_ip=%s",
                method,
                path,
                status_code,
                duration_ms,
                client_ip,
            )
        finally:
            reset_request_id(token)
