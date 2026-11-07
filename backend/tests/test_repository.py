from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.auth.models import AuditEvent, RefreshSession, User
from app.modules.auth.repository import AuthRepository


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.executed: list[object] = []
        self.scalar_result: object | None = None
        self.get_result: object | None = None
        self.flush_count = 0

    async def scalar(self, query: object) -> object | None:
        self.executed.append(query)
        return self.scalar_result

    async def get(self, model: type[object], key: object) -> object | None:
        self.executed.append((model, key))
        return self.get_result

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_count += 1

    async def execute(self, query: object) -> None:
        self.executed.append(query)


@pytest.mark.asyncio
async def test_repository_queries_and_adds_entities() -> None:
    session = FakeSession()
    repository = AuthRepository(session)  # type: ignore[arg-type]
    user_id = uuid4()

    await repository.by_email("Player@Example.com", lock=True)
    assert "FOR UPDATE" in str(session.executed[-1])
    session.get_result = User(id=user_id, email="player@example.com", password_hash="hash")
    assert await repository.by_id(user_id) is session.get_result

    user = await repository.create_user("Player@Example.com", "password-hash")
    assert isinstance(user, User)
    assert user.email == "player@example.com"
    assert session.flush_count == 1

    refresh = RefreshSession(
        user_id=user_id,
        token_hash="a" * 64,
        family_id=uuid4(),
        expires_at=datetime.now(UTC),
    )
    await repository.add_session(refresh)
    await repository.revoke_family(refresh.family_id)
    await repository.revoke_user_sessions(user_id)
    await repository.audit(user_id, "test_event")
    assert refresh in session.added
    assert isinstance(session.added[-1], AuditEvent)
    assert session.added[-1].event_data == {}
    assert len(session.executed) == 4
    assert session.flush_count == 2
