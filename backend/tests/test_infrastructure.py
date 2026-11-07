import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import rate_limit, redis as redis_module
from app.core.errors import APIError, install_error_handlers
from app.core.logging import configure_logging, redact


def test_error_handlers_sanitize_validation_and_unexpected_errors() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/api-error")
    async def api_error() -> None:
        raise APIError(409, "conflict", "conflict")

    @app.get("/validation")
    async def validation(value: int) -> int:
        return value

    @app.get("/unexpected")
    async def unexpected() -> None:
        raise RuntimeError("private details")

    with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
        assert client.get("/api-error").json() == {"error": {"code": "conflict", "message": "conflict"}}
        validation_response = client.get("/validation", params={"value": "bad"})
        assert validation_response.status_code == 422
        assert validation_response.json() == {
            "error": {"code": "validation_error", "message": "Request validation failed"}
        }
        unexpected_response = client.get("/unexpected")
        assert unexpected_response.status_code == 500
        assert "private details" not in unexpected_response.text


@pytest.mark.asyncio
async def test_rate_limit_disabled_success_throttle_and_environment_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def over_limit(*_args: object, **_kwargs: object) -> int:
        return 4

    async def allowed(*_args: object, **_kwargs: object) -> int:
        return 1

    async def unavailable(*_args: object, **_kwargs: object) -> int:
        raise ConnectionError("redis offline")

    monkeypatch.setattr(rate_limit.settings, "rate_limit_enabled", False)
    await rate_limit.check_limit("disabled", limit=1, window=10)

    monkeypatch.setattr(rate_limit.settings, "rate_limit_enabled", True)
    monkeypatch.setattr(redis_module.redis_client, "eval", allowed)
    await rate_limit.check_limit("allowed", limit=2, window=10)

    monkeypatch.setattr(redis_module.redis_client, "eval", over_limit)
    with pytest.raises(APIError) as caught:
        await rate_limit.check_limit("throttled", limit=2, window=10)
    assert caught.value.status_code == 429

    monkeypatch.setattr(redis_module.redis_client, "eval", unavailable)
    monkeypatch.setattr(rate_limit.settings, "environment", "development")
    await rate_limit.check_limit("fail-open", limit=2, window=10)
    monkeypatch.setattr(rate_limit.settings, "environment", "production")
    with pytest.raises(APIError) as caught:
        await rate_limit.check_limit("fail-closed", limit=2, window=10)
    assert caught.value.status_code == 503


def test_logging_redacts_sensitive_fields_and_text() -> None:
    event = {
        "password": "secret-value",
        "details": "bearer abc123 email=player@example.com token:tok123",
        "count": 3,
    }
    redacted = redact(None, "event", event)
    assert redacted["password"] == "[REDACTED]"
    assert "abc123" not in str(redacted["details"])
    assert "player@example.com" not in str(redacted["details"])
    assert "tok123" not in str(redacted["details"])
    assert redacted["count"] == 3
    configure_logging()


def test_celery_uses_durable_default_queue_and_ignores_results() -> None:
    from app.core.celery_app import celery_app

    queue = celery_app.conf.task_queues[0]
    assert celery_app.conf.task_default_queue == "valorant"
    assert queue.name == "valorant"
    assert queue.durable is True
    assert celery_app.conf.task_ignore_result is True
    assert celery_app.conf.worker_enable_remote_control is False


