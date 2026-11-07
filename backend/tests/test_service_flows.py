from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.errors import APIError
from app.core import redis as redis_module
from app.modules.auth import service as service_module
from app.modules.auth.service import AuthService


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0
        self.added: list[object] = []
        self.scalar_result: object | None = None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def flush(self) -> None:
        self.flushes += 1

    def add(self, item: object) -> None:
        self.added.append(item)

    async def scalar(self, _query: object) -> object | None:
        return self.scalar_result


class FakeHash:
    def __init__(self, valid: bool = True) -> None:
        self.valid = valid

    def verify(self, *_args: object) -> bool:
        return self.valid

    def hash(self, value: str) -> str:
        return f"hash:{value}"


def patch_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allowed(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(service_module, "check_limit", allowed)


@pytest.mark.asyncio
async def test_register_success_duplicate_and_integrity_race(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_limits(monkeypatch)
    monkeypatch.setattr(service_module, "password_hash", FakeHash())
    user = SimpleNamespace(id=uuid4(), email="player@example.com")
    session = FakeSession()

    class Repo:
        existing: object | None = None
        create_error = False

        def __init__(self, _session: object) -> None:
            self.lookups = 0

        async def by_email(self, _email: str) -> object | None:
            self.lookups += 1
            return self.existing

        async def create_user(self, _email: str, password_hash: str) -> object:
            assert password_hash == "hash:good password"
            if self.create_error:
                raise IntegrityError("insert", {}, RuntimeError("duplicate"))
            return user

        async def audit(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(service_module, "AuthRepository", Repo)
    service = AuthService(session)  # type: ignore[arg-type]
    assert await service.register("player@example.com", "good password") is user
    assert session.commits == 1

    Repo.existing = user
    assert await service.register("player@example.com", "good password") is user

    Repo.existing = None
    Repo.create_error = True
    with pytest.raises(APIError) as caught:
        await service.register("player@example.com", "good password")
    assert caught.value.status_code == 500
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_login_success_resets_lockout_and_issues_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_limits(monkeypatch)
    monkeypatch.setattr(service_module, "password_hash", FakeHash())
    user = SimpleNamespace(
        id=uuid4(), is_active=True, locked_until=datetime.now(UTC) - timedelta(seconds=1),
        failed_login_count=4, password_hash="saved", token_version=2,
    )
    events: list[str] = []

    class Repo:
        def __init__(self, _session: object) -> None:
            pass

        async def by_email(self, email: str, *, lock: bool = False) -> object:
            assert email == "player@example.com" and lock
            return user

        async def audit(self, _user_id: object, event: str) -> None:
            events.append(event)

        async def add_session(self, record: object) -> None:
            events.append("session")

    monkeypatch.setattr(service_module, "AuthRepository", Repo)
    session = FakeSession()
    service = AuthService(session)  # type: ignore[arg-type]
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    pair = await service.login("PLAYER@example.com", "correct-password", request)  # type: ignore[arg-type]
    assert pair.access_token and pair.refresh_token
    assert user.failed_login_count == 0
    assert user.locked_until is None
    assert events == ["login", "session"]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_refresh_success_and_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = uuid4()
    family_id = uuid4()
    user = SimpleNamespace(id=user_id, is_active=True, token_version=0)
    record = SimpleNamespace(
        revoked_at=None, expires_at=datetime.now(UTC) + timedelta(hours=1),
        family_id=family_id, user_id=user_id, replaced_by_id=None,
    )

    class Repo:
        def __init__(self, _session: object) -> None:
            self.lookups = 0

        async def refresh_by_hash(self, *_args: object, **_kwargs: object) -> object:
            self.lookups += 1
            return record if self.lookups == 1 else SimpleNamespace(id=uuid4())

        async def by_id(self, _user_id: object) -> object:
            return user

        async def add_session(self, _record: object) -> None:
            return None

    monkeypatch.setattr(service_module, "AuthRepository", Repo)
    session = FakeSession()
    pair = await AuthService(session).refresh("valid-refresh-token")  # type: ignore[arg-type]
    assert pair.refresh_token
    assert record.revoked_at is not None and record.replaced_by_id is not None
    assert session.flushes == session.commits == 1

    expired = SimpleNamespace(
        revoked_at=None, expires_at=datetime.now(UTC) - timedelta(seconds=1),
        family_id=family_id, user_id=user_id,
    )

    class ExpiredRepo(Repo):
        async def refresh_by_hash(self, *_args: object, **_kwargs: object) -> object:
            return expired

    monkeypatch.setattr(service_module, "AuthRepository", ExpiredRepo)
    with pytest.raises(APIError) as caught:
        await AuthService(FakeSession()).refresh("expired-refresh-token")  # type: ignore[arg-type]
    assert caught.value.status_code == 401


@pytest.mark.asyncio
async def test_logout_password_change_and_invalid_current_password(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_limits(monkeypatch)
    monkeypatch.setattr(service_module, "password_hash", FakeHash())
    calls: list[str] = []

    class Repo:
        def __init__(self, _session: object) -> None:
            pass

        async def revoke_user_sessions(self, _user_id: object) -> None:
            calls.append("revoke")

        async def audit(self, _user_id: object, event: str) -> None:
            calls.append(event)

    monkeypatch.setattr(service_module, "AuthRepository", Repo)
    session = FakeSession()
    service = AuthService(session)  # type: ignore[arg-type]
    user = SimpleNamespace(id=uuid4(), token_version=0, password_hash="old")
    await service.logout(user)  # type: ignore[arg-type]
    assert user.token_version == 1
    await service.change_password(user, "old", "new-long-password")  # type: ignore[arg-type]
    assert user.password_hash == "hash:new-long-password"
    assert user.token_version == 2
    assert session.commits == 2
    assert calls == ["revoke", "logout", "revoke", "password_change"]

    monkeypatch.setattr(service_module, "password_hash", FakeHash(valid=False))
    with pytest.raises(APIError) as caught:
        await service.change_password(user, "wrong", "new-long-password")  # type: ignore[arg-type]
    assert caught.value.status_code == 400


@pytest.mark.asyncio
async def test_discord_authorize_and_callback_reject_missing_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "oauth_redirect_allowlist", ["https://client.example/callback"])
    monkeypatch.setattr(settings, "discord_client_id", "client-id")
    saved: list[tuple[object, ...]] = []

    async def setex(*args: object) -> None:
        saved.append(args)

    async def get(_key: str) -> None:
        return None

    async def delete(_key: str) -> None:
        return None

    monkeypatch.setattr(redis_module.redis_client, "setex", setex)
    monkeypatch.setattr(redis_module.redis_client, "get", get)
    monkeypatch.setattr(redis_module.redis_client, "delete", delete)
    service = AuthService(FakeSession())  # type: ignore[arg-type]
    url = await service.discord_authorize_url("https://client.example/callback")
    assert url.startswith("https://discord.com/oauth2/authorize?")
    assert len(saved) == 1 and saved[0][1] == 600
    with pytest.raises(APIError) as caught:
        await service.discord_callback("code", "s" * 32, "https://client.example/callback")
    assert caught.value.code == "invalid_oauth_state"

    monkeypatch.setattr(settings, "discord_client_id", "")
    with pytest.raises(APIError) as caught:
        await service.discord_authorize_url("https://client.example/callback")
    assert caught.value.status_code == 503
