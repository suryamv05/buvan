from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import AuditEvent, RefreshSession, User


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_email(self, email: str, *, lock: bool = False) -> User | None:
        query = select(User).where(User.email == email.lower())
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def by_id(self, user_id: UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def create_user(self, email: str, password_hash: str) -> User:
        user = User(email=email.lower(), password_hash=password_hash)
        self.session.add(user)
        await self.session.flush()
        return user

    async def add_session(self, record: RefreshSession) -> None:
        self.session.add(record)
        await self.session.flush()

    async def refresh_by_hash(self, token_hash: str, *, lock: bool = False) -> RefreshSession | None:
        query = select(RefreshSession).where(RefreshSession.token_hash == token_hash)
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def revoke_family(self, family_id: UUID) -> None:
        await self.session.execute(update(RefreshSession).where(RefreshSession.family_id == family_id, RefreshSession.revoked_at.is_(None)).values(revoked_at=func.now()))

    async def revoke_user_sessions(self, user_id: UUID) -> None:
        await self.session.execute(update(RefreshSession).where(RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None)).values(revoked_at=func.now()))

    async def audit(self, actor_id: UUID | None, event_type: str, data: dict[str, str] | None = None) -> None:
        self.session.add(AuditEvent(actor_id=actor_id, event_type=event_type, event_data=data or {}))
