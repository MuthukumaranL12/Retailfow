import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from pymongo.errors import PyMongoError
from fastapi.testclient import TestClient

from app import security_controls
from app.config import Settings


class CounterCollection:
    def __init__(self):
        self.counts = {}

    def find_one_and_update(self, query, update, **kwargs):
        key = query["_id"]
        self.counts[key] = self.counts.get(key, 0) + 1
        return {"count": self.counts[key]}


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "raw_path": b"/api/v1/auth/login",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "scheme": "http",
            "server": ("testserver", 80),
            "http_version": "1.1",
        }
    )


def test_rate_limiter_rejects_requests_over_limit(monkeypatch):
    monkeypatch.setattr(security_controls, "db", SimpleNamespace(rate_limits=CounterCollection()))
    enforce = security_controls.rate_limit(2, 60)

    asyncio.run(enforce(_request()))
    asyncio.run(enforce(_request()))
    with pytest.raises(HTTPException) as error:
        asyncio.run(enforce(_request()))

    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"]


def test_rate_limiter_fails_closed_when_database_is_unavailable(monkeypatch):
    class UnavailableCollection:
        def find_one_and_update(self, *args, **kwargs):
            raise PyMongoError("database unavailable")

    monkeypatch.setattr(
        security_controls,
        "db",
        SimpleNamespace(rate_limits=UnavailableCollection()),
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(security_controls.rate_limit(2, 60)(_request()))

    assert error.value.status_code == 503


def test_production_settings_reject_the_development_secret():
    with pytest.raises(ValueError, match="Production requires"):
        Settings(APP_ENV="production", SECRET_KEY="development-secret-key")


def test_api_sets_security_headers():
    from app.main import app

    response = TestClient(app).get("/")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
