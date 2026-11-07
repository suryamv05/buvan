import pytest

from app.core.config import settings
from app.scripts import seed_admin as seed_module


@pytest.mark.asyncio
async def test_seed_admin_rejects_missing_email_or_short_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEED_ADMIN_EMAIL", raising=False)
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "short")
    with pytest.raises(SystemExit, match="SEED_ADMIN_EMAIL"):
        await seed_module.seed_admin()


@pytest.mark.asyncio
async def test_seed_admin_requires_migration_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "long-enough-password")
    monkeypatch.setattr(settings, "migration_database_url", "")
    with pytest.raises(SystemExit, match="MIGRATION_DATABASE_URL"):
        await seed_module.seed_admin()


@pytest.mark.asyncio
async def test_seed_admin_creates_audited_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "  Admin@Example.com ")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "long-enough-password")
    monkeypatch.setattr(settings, "migration_database_url", "postgresql+asyncpg://test@localhost/test")

    class FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.committed = False

        async def scalar(self, _query: object) -> None:
            return None

        def add(self, item: object) -> None:
            self.added.append(item)

        async def flush(self) -> None:
            return None

        async def commit(self) -> None:
            self.committed = True

        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    session = FakeSession()
    disposed = False

    class FakeEngine:
        async def dispose(self) -> None:
            nonlocal disposed
            disposed = True

    class FakePasswordHash:
        @classmethod
        def recommended(cls) -> "FakePasswordHash":
            return cls()

        def hash(self, password: str) -> str:
            return f"hashed:{password}"

    monkeypatch.setattr(seed_module, "create_async_engine", lambda *_args, **_kwargs: FakeEngine())
    monkeypatch.setattr(seed_module, "async_sessionmaker", lambda *_args, **_kwargs: lambda: session)
    monkeypatch.setattr(seed_module, "PasswordHash", FakePasswordHash)

    await seed_module.seed_admin()

    assert session.committed
    assert disposed
    assert session.added[0].email == "admin@example.com"
    assert session.added[0].password_hash == "hashed:long-enough-password"
    assert session.added[1].event_type == "admin_seed"


@pytest.mark.asyncio
async def test_seed_admin_refuses_duplicate_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "long-enough-password")
    monkeypatch.setattr(settings, "migration_database_url", "postgresql+asyncpg://test@localhost/test")

    class Session:
        async def scalar(self, _query: object) -> object:
            return object()

        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    class Engine:
        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(seed_module, "create_async_engine", lambda *_args, **_kwargs: Engine())
    monkeypatch.setattr(seed_module, "async_sessionmaker", lambda *_args, **_kwargs: lambda: Session())
    with pytest.raises(SystemExit, match="already exists"):
        await seed_module.seed_admin()
