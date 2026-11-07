import hashlib
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.errors import APIError
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository

bearer = HTTPBearer(auto_error=False)
_DEV_JWT_SECRET = secrets.token_urlsafe(48)
_DEV_REALTIME_SECRET = secrets.token_urlsafe(48)


def _secret(raw: str, label: str) -> str:
    if len(raw) >= 32:
        return raw
    if settings.environment == "production":
        raise RuntimeError(f"{label} is not configured securely")
    if not raw and settings.environment != "production":
        return _DEV_REALTIME_SECRET if label == "REALTIME_JWT_SECRET" else _DEV_JWT_SECRET
    return raw


def create_access_token(user_id: UUID, token_version: int = 0) -> str:
    now = datetime.now(UTC)
    claims = {"sub": str(user_id), "token_version": token_version, "iss": settings.jwt_issuer, "aud": settings.jwt_audience,
              "iat": now, "exp": now + timedelta(minutes=settings.access_token_minutes), "jti": secrets.token_urlsafe(18)}
    return jwt.encode(claims, _secret(settings.jwt_secret, "JWT_SECRET"), algorithm="HS256")


def create_realtime_token(user_id: UUID, token_version: int = 0) -> str:
    now = datetime.now(UTC)
    claims = {"sub": str(user_id), "token_version": token_version, "iss": settings.realtime_issuer, "aud": settings.realtime_audience,
              "iat": now, "exp": now + timedelta(minutes=2), "jti": secrets.token_urlsafe(18)}
    return jwt.encode(claims, _secret(settings.realtime_jwt_secret, "REALTIME_JWT_SECRET"), algorithm="HS256")


def verify_access_token(token: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(token, _secret(settings.jwt_secret, "JWT_SECRET"), algorithms=["HS256"],
                            audience=settings.jwt_audience, issuer=settings.jwt_issuer,
                            options={"require": ["exp", "iat", "jti", "aud", "iss", "sub"]})
        UUID(claims["sub"])
        return claims
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise APIError(401, "invalid_token", "Authentication is required") from exc


async def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), session: AsyncSession = Depends(get_session)) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise APIError(401, "invalid_token", "Authentication is required")
    claims = verify_access_token(credentials.credentials)
    user = await AuthRepository(session).by_id(UUID(claims["sub"]))
    if user is None or not user.is_active or claims.get("token_version") != user.token_version:
        raise APIError(401, "invalid_token", "Authentication is required")
    return user


def require_roles(*roles: str) -> Callable[..., Awaitable[User]]:
    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise APIError(403, "forbidden", "You do not have permission to perform this action")
        return user
    return dependency


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
