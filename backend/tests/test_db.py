from collections.abc import AsyncIterator

import pytest

from app.core import db


def test_engine_creation_is_lazy_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    engine = object()

    def create_engine(url: str, **options: object) -> object:
        calls.append((url, options))
        return engine

    db.get_session_factory.cache_clear()
    db.get_engine.cache_clear()
    monkeypatch.setattr(db.settings, "database_url", "postgresql+asyncpg://unit:test@localhost/test")
    monkeypatch.setattr(db, "create_async_engine", create_engine)
    try:
        assert db.get_engine.cache_info().currsize == 0
        assert db.get_engine() is engine
        assert db.get_engine() is engine
        assert calls == [("postgresql+asyncpg://unit:test@localhost/test", {
            "pool_pre_ping": True, "pool_size": 10, "max_overflow": 20,
        })]
    finally:
        db.get_session_factory.cache_clear()
        db.get_engine.cache_clear()


@pytest.mark.asyncio
async def test_get_session_yields_and_closes_session(monkeypatch: pytest.MonkeyPatch) -> None:
    class SessionContext:
        async def __aenter__(self) -> str:
            return "session"

        async def __aexit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(db, "get_session_factory", lambda: lambda: SessionContext())
    generator: AsyncIterator[object] = db.get_session()
    assert await anext(generator) == "session"
    with pytest.raises(StopAsyncIteration):
        await anext(generator)


@pytest.mark.asyncio
async def test_dispose_engine_only_disposes_initialized_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    db.get_engine.cache_clear()
    await db.dispose_engine()
    disposed = False

    class FakeEngine:
        async def dispose(self) -> None:
            nonlocal disposed
            disposed = True

    monkeypatch.setattr(db, "create_async_engine", lambda *_args, **_kwargs: FakeEngine())
    db.get_engine()
    await db.dispose_engine()
    assert disposed
    db.get_engine.cache_clear()


def test_session_factory_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    factory = object()
    monkeypatch.setattr(db, "get_engine", lambda: "engine")
    monkeypatch.setattr(db, "async_sessionmaker", lambda engine, **_options: calls.append(engine) or factory)
    db.get_session_factory.cache_clear()
    assert db.get_session_factory() is factory
    assert db.get_session_factory() is factory
    assert calls == ["engine"]
    db.get_session_factory.cache_clear()
