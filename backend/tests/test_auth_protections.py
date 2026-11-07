from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.errors import APIError
from app.core.middleware import RequestBodyLimitMiddleware
from app.core.security import require_roles
from app.modules.auth import service as auth_service_module
from app.modules.auth.models import User
from app.modules.auth.service import AuthService


@pytest.mark.asyncio
async def test_reused_refresh_token_revokes_its_family(monkeypatch: pytest.MonkeyPatch) -> None:
    family_id = uuid4()
    user_id = uuid4()
    record = SimpleNamespace(revoked_at=datetime.now(UTC), family_id=family_id, user_id=user_id)
    calls: list[str] = []

    class FakeRepository:
        async def refresh_by_hash(self, *_: object, **__: object) -> object:
            return record

        async def revoke_family(self, family: object) -> None:
            assert family == family_id
            calls.append("revoke")

        async def audit(self, actor: object, event: str) -> None:
            assert actor == user_id and event == "token_reuse"
            calls.append("audit")

    class FakeSession:
        async def commit(self) -> None:
            calls.append("commit")

    monkeypatch.setattr(auth_service_module, "AuthRepository", lambda _: FakeRepository())
    with pytest.raises(APIError) as caught:
        await AuthService(FakeSession()).refresh("reused-refresh-token")  # type: ignore[arg-type]
    assert caught.value.status_code == 401
    assert calls == ["revoke", "audit", "commit"]


@pytest.mark.asyncio
async def test_progressive_login_lockout(monkeypatch: pytest.MonkeyPatch) -> None:
    user = SimpleNamespace(
        id=uuid4(), is_active=True, locked_until=None, failed_login_count=0,
        password_hash="stored-hash", token_version=0,
    )
    events: list[str] = []

    class FakeRepository:
        async def by_email(self, *_: object, **__: object) -> object:
            return user

        async def audit(self, *_: object, **__: object) -> None:
            events.append("audit")

    class FakeSession:
        async def commit(self) -> None:
            events.append("commit")

    class FakeHash:
        def verify(self, *_: object) -> bool:
            return False

    async def no_limit(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(auth_service_module, "AuthRepository", lambda _: FakeRepository())
    monkeypatch.setattr(auth_service_module, "password_hash", FakeHash())
    monkeypatch.setattr(auth_service_module, "check_limit", no_limit)
    request = SimpleNamespace(client=SimpleNamespace(host="192.0.2.9"))
    service = AuthService(FakeSession())  # type: ignore[arg-type]
    for _ in range(5):
        with pytest.raises(APIError) as caught:
            await service.login("player@example.com", "incorrect-password", request)  # type: ignore[arg-type]
        assert caught.value.status_code == 401
    assert user.failed_login_count == 5
    assert user.locked_until > datetime.now(UTC)
    assert len(events) == 10


@pytest.mark.asyncio
async def test_role_dependency_denies_escalation() -> None:
    admin = User(id=uuid4(), email="admin@example.com", password_hash="hash", role="admin")
    with pytest.raises(APIError) as caught:
        await require_roles("user")(admin)
    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_body_limit_rejects_chunked_oversize_payload() -> None:
    async def inner(scope, receive, send) -> None:
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    messages = [
        {"type": "http.request", "body": b"four", "more_body": False},
    ]

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    sent: list[dict[str, object]] = []

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    await RequestBodyLimitMiddleware(inner, max_bytes=3)({"type": "http", "method": "POST"}, receive, send)  # type: ignore[arg-type]
    assert sent[0]["status"] == 413
