import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import Request
from pwdlib import PasswordHash
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import APIError
from app.core.rate_limit import check_limit
from app.core.security import create_access_token, hash_token
from app.modules.auth.models import OAuthIdentity, RefreshSession, User
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import TokenPair

password_hash = PasswordHash.recommended()
_DUMMY_HASH = password_hash.hash("not-a-real-password-1")
COMMON_PASSWORDS = {
    "1234567890", "12345678910", "12345678912", "password123", "password1234",
    "qwerty12345", "qwertyuiop", "letmein1234", "welcome1234", "admin123456",
    "iloveyou123", "changeme123", "valorant123", "sunshine123", "football123",
    "monkeymonkey", "dragon12345", "baseball123", "trustno1234", "passw0rd123",
    "abc123456789", "qazwsxedc123", "1q2w3e4r5t", "123qweasdzxc", "p@ssword123",
    "password!23", "whatever1234", "superman123", "michael1234", "shadow12345",
    "master12345", "freedom12345", "starwars1234", "hello1234567", "welcome2024",
    "welcome2025", "welcome2026", "qwerty123456", "9876543210", "1111111111",
    "0000000000", "1212121212", "1122334455", "6543210987", "6543211234",
    "loveyou12345", "iloveyou2024", "iloveyou2025", "iloveyou2026", "whatever2024",
}


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = AuthRepository(session)
        self.session = session

    async def rate_limit(self, request: Request, action: str) -> None:
        ip = request.client.host if request.client else "unknown"
        await check_limit(f"auth:{action}:ip:{ip}", limit=5, window=60)

    async def register(self, email: str, password: str) -> User:
        await self.rate_limit_email("register", email)
        self._validate_password(password)
        existing = await self.repo.by_email(email)
        if existing:
            # Same success response prevents account enumeration.
            return existing
        try:
            user = await self.repo.create_user(email, password_hash.hash(password))
            await self.repo.audit(user.id, "register")
            await self.session.commit()
            return user
        except IntegrityError:
            await self.session.rollback()
            existing = await self.repo.by_email(email)
            if existing:
                return existing
            raise APIError(500, "internal_error", "The request could not be completed") from None

    async def login(self, email: str, password: str, request: Request) -> TokenPair:
        await self.rate_limit(request, "login")
        normalized = email.lower()
        await check_limit(f"auth:account:{hashlib.sha256(normalized.encode()).hexdigest()}", limit=10, window=900)
        user = await self.repo.by_email(normalized, lock=True)
        if user is None:
            password_hash.verify(password, _DUMMY_HASH)
            await self.repo.audit(None, "login_failed")
            await self.session.commit()
            raise APIError(401, "invalid_credentials", "Email or password is incorrect")
        now = datetime.now(UTC)
        if user.locked_until and user.locked_until > now:
            password_hash.verify(password, _DUMMY_HASH)
            await self.repo.audit(user.id, "login_failed")
            await self.session.commit()
            raise APIError(401, "invalid_credentials", "Email or password is incorrect")
        if not password_hash.verify(password, user.password_hash):
            user.failed_login_count += 1
            if user.failed_login_count >= 5:
                delay = min(2 ** min(user.failed_login_count - 5, 8), 300)
                user.locked_until = now + timedelta(seconds=delay)
            await self.repo.audit(user.id, "login_failed")
            await self.session.commit()
            raise APIError(401, "invalid_credentials", "Email or password is incorrect")
        user.failed_login_count = 0
        user.locked_until = None
        await self.repo.audit(user.id, "login")
        pair = await self._new_pair(user.id, token_version=user.token_version)
        await self.session.commit()
        return pair

    async def refresh(self, raw_token: str) -> TokenPair:
        record = await self.repo.refresh_by_hash(hash_token(raw_token), lock=True)
        if record is None:
            raise APIError(401, "invalid_token", "Refresh token is invalid")
        if record.revoked_at:
            await self.repo.revoke_family(record.family_id)
            await self.repo.audit(record.user_id, "token_reuse")
            await self.session.commit()
            raise APIError(401, "invalid_token", "Refresh token is invalid")
        if record.expires_at <= datetime.now(UTC):
            raise APIError(401, "invalid_token", "Refresh token is invalid")
        record.revoked_at = datetime.now(UTC)
        user = await self.repo.by_id(record.user_id)
        if user is None or not user.is_active:
            raise APIError(401, "invalid_token", "Refresh token is invalid")
        pair = await self._new_pair(user.id, family_id=record.family_id, token_version=user.token_version)
        await self.session.flush()
        replacement = await self.repo.refresh_by_hash(hash_token(pair.refresh_token))
        record.replaced_by_id = replacement.id if replacement else None
        await self.session.commit()
        return pair

    async def logout(self, user: User) -> None:
        user.token_version += 1
        await self.repo.revoke_user_sessions(user.id)
        await self.repo.audit(user.id, "logout")
        await self.session.commit()

    async def change_password(self, user: User, current_password: str, new_password: str) -> None:
        if not password_hash.verify(current_password, user.password_hash):
            raise APIError(400, "invalid_credentials", "Current password is incorrect")
        self._validate_password(new_password)
        user.password_hash = password_hash.hash(new_password)
        user.token_version += 1
        await self.repo.revoke_user_sessions(user.id)
        await self.repo.audit(user.id, "password_change")
        await self.session.commit()

    async def rate_limit_email(self, action: str, email: str) -> None:
        digest = hashlib.sha256(email.lower().encode()).hexdigest()
        await check_limit(f"auth:{action}:account:{digest}", limit=5, window=3600)

    async def discord_authorize_url(self, redirect_uri: str) -> str:
        from app.core.redis import redis_client

        self._validate_redirect_uri(redirect_uri)
        if not settings.discord_client_id:
            raise APIError(503, "oauth_unavailable", "Discord sign-in is not configured")
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        await redis_client.setex(f"oauth:discord:{hashlib.sha256(state.encode()).hexdigest()}", 600, verifier + "\n" + redirect_uri)
        query = urlencode({"client_id": settings.discord_client_id, "redirect_uri": redirect_uri, "response_type": "code",
                           "scope": "identify email", "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
        return "https://discord.com/oauth2/authorize?" + query

    async def discord_callback(self, code: str, state: str, redirect_uri: str) -> TokenPair:
        from app.core.redis import redis_client

        self._validate_redirect_uri(redirect_uri)
        key = f"oauth:discord:{hashlib.sha256(state.encode()).hexdigest()}"
        saved = await redis_client.get(key)
        await redis_client.delete(key)
        if not saved:
            raise APIError(400, "invalid_oauth_state", "OAuth request expired or invalid")
        verifier, expected_redirect = saved.split("\n", maxsplit=1)
        if not secrets.compare_digest(expected_redirect, redirect_uri):
            raise APIError(400, "invalid_oauth_state", "OAuth request expired or invalid")
        import httpx

        timeout = httpx.Timeout(8.0, connect=3.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            token_response = await client.post("https://discord.com/api/oauth2/token", data={
                "client_id": settings.discord_client_id, "client_secret": settings.discord_client_secret,
                "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            }, headers={"Content-Type": "application/x-www-form-urlencoded"})
            if token_response.status_code != 200:
                raise APIError(401, "oauth_failed", "Discord sign-in failed")
            access_token = token_response.json().get("access_token")
            if not isinstance(access_token, str):
                raise APIError(401, "oauth_failed", "Discord sign-in failed")
            profile_response = await client.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {access_token}"})
        if profile_response.status_code != 200:
            raise APIError(401, "oauth_failed", "Discord sign-in failed")
        profile = profile_response.json()
        subject = profile.get("id")
        email = profile.get("email")
        if not isinstance(subject, str) or not isinstance(email, str) or not profile.get("verified"):
            raise APIError(401, "oauth_failed", "Discord sign-in failed")
        try:
            email = str(TypeAdapter(EmailStr).validate_python(email)).lower()
        except ValidationError as exc:
            raise APIError(401, "oauth_failed", "Discord sign-in failed") from exc
        identity = await self.session.scalar(select(OAuthIdentity).where(OAuthIdentity.provider == "discord", OAuthIdentity.provider_subject == subject))
        if identity:
            user = await self.repo.by_id(identity.user_id)
        else:
            user = await self.repo.by_email(email)
            if user is not None:
                raise APIError(401, "oauth_failed", "Discord sign-in failed")
            user = await self.repo.create_user(email, password_hash.hash(secrets.token_urlsafe(64)))
            identity = OAuthIdentity(user_id=user.id, provider="discord", provider_subject=subject)
            self.session.add(identity)
        if user is None or not user.is_active:
            raise APIError(401, "oauth_failed", "Discord sign-in failed")
        await self.repo.audit(user.id, "oauth_login", {"provider": "discord"})
        pair = await self._new_pair(user.id, token_version=user.token_version)
        await self.session.commit()
        return pair

    @staticmethod
    def _validate_redirect_uri(uri: str) -> None:
        if uri not in settings.oauth_redirect_allowlist or not uri.startswith("https://") and settings.environment == "production":
            raise APIError(400, "invalid_redirect_uri", "OAuth redirect URI is not allowed")

    @staticmethod
    def _validate_password(value: str) -> None:
        if len(value) < 10 or value.lower() in COMMON_PASSWORDS:
            raise APIError(422, "weak_password", "Password does not meet security requirements")

    async def _new_pair(self, user_id: UUID, family_id: UUID | None = None, token_version: int = 0) -> TokenPair:
        refresh = secrets.token_urlsafe(48)
        record = RefreshSession(
            user_id=user_id,
            token_hash=hash_token(refresh),
            family_id=family_id or uuid4(),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        )
        await self.repo.add_session(record)
        return TokenPair(
            access_token=create_access_token(user_id, token_version),
            refresh_token=refresh,
            expires_in=settings.access_token_minutes * 60,
        )
