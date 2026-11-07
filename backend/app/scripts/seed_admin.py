import asyncio
import os

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.modules.auth.models import AuditEvent, User


async def seed_admin() -> None:
    email = os.environ.get("SEED_ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("SEED_ADMIN_PASSWORD", "")
    if not email or len(password) < 16:
        raise SystemExit("Set SEED_ADMIN_EMAIL and a unique SEED_ADMIN_PASSWORD of at least 16 characters")
    if not settings.migration_database_url:
        raise SystemExit("MIGRATION_DATABASE_URL must be configured for the one-time administrator seed")
    engine = create_async_engine(settings.migration_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        existing = await session.scalar(select(User).where(User.role == "admin"))
        if existing:
            raise SystemExit("An administrator already exists; refusing to seed another one")
        user = User(email=email, password_hash=PasswordHash.recommended().hash(password), role="admin")
        session.add(user)
        await session.flush()
        session.add(AuditEvent(actor_id=user.id, event_type="admin_seed", event_data={}))
        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_admin())
