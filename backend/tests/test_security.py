from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from app.core.config import settings
from app.core.errors import APIError
from app.core.security import _secret, create_access_token, hash_token, verify_access_token
from app.modules.auth.schemas import LoginRequest, RegisterRequest


def test_access_token_round_trip() -> None:
    token = create_access_token(uuid4())
    claims = verify_access_token(token)
    assert claims["aud"] == settings.jwt_audience
    assert claims["iss"] == settings.jwt_issuer
    assert claims["jti"]


def test_reject_tampered_token() -> None:
    token = create_access_token(uuid4()) + "tampered"
    with pytest.raises(APIError):
        verify_access_token(token)


def test_reject_expired_token() -> None:
    now = datetime.now(UTC)
    token = jwt.encode({"sub": str(uuid4()), "iss": settings.jwt_issuer, "aud": settings.jwt_audience,
                        "iat": now - timedelta(minutes=2), "exp": now - timedelta(minutes=1), "jti": "expired"},
                       _secret(settings.jwt_secret, "JWT_SECRET"), algorithm="HS256")
    with pytest.raises(APIError):
        verify_access_token(token)


def test_reject_none_algorithm() -> None:
    now = datetime.now(UTC)
    token = jwt.encode({"sub": str(uuid4()), "iss": settings.jwt_issuer, "aud": settings.jwt_audience,
                        "iat": now, "exp": now + timedelta(minutes=1), "jti": "abc"}, key=None, algorithm="none")
    with pytest.raises(APIError):
        verify_access_token(token)


def test_refresh_token_hash_is_one_way_and_deterministic() -> None:
    token = "a-long-random-refresh-secret"
    assert hash_token(token) == hash_token(token)
    assert hash_token(token) != token


def test_passwords_are_secret_and_extra_fields_are_rejected() -> None:
    body = RegisterRequest(email="person@example.com", password="valid-looking-passphrase")
    assert body.password.get_secret_value() == "valid-looking-passphrase"
    with pytest.raises(ValueError):
        LoginRequest(email="person@example.com", password="password", role="admin")


def test_production_secret_refuses_weak_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(RuntimeError):
        _secret("short", "JWT_SECRET")
