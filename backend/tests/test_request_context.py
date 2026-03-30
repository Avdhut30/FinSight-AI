import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging import configure_logging
from app.core.request_context import REQUEST_ID_HEADER, RequestContextMiddleware, get_request_id


def create_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ping")
    async def ping():
        logging.getLogger("test.request_context").info("Inside handler")
        return {"request_id": get_request_id()}

    return app


def test_request_context_adds_request_id_header():
    configure_logging("INFO")
    client = TestClient(create_app())

    response = client.get("/ping")

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER]
    assert response.json()["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_request_context_preserves_incoming_request_id(caplog):
    configure_logging("INFO")
    client = TestClient(create_app())

    with caplog.at_level(logging.INFO):
        response = client.get("/ping", headers={REQUEST_ID_HEADER: "req-123"})

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "req-123"
    assert response.json()["request_id"] == "req-123"
    assert any(getattr(record, "request_id", None) == "req-123" for record in caplog.records)
