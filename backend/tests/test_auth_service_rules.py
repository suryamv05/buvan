import pytest

from app.core.config import settings
from app.core.errors import APIError
from app.modules.auth.service import AuthService


def test_rejects_short_password() -> None:
    with pytest.raises(APIError) as caught:
        AuthService._validate_password("short")
    assert caught.value.code == "weak_password"


def test_rejects_common_password() -> None:
    with pytest.raises(APIError) as caught:
        AuthService._validate_password("password123")
    assert caught.value.code == "weak_password"


def test_accepts_long_non_common_password() -> None:
    AuthService._validate_password("green-foxes-win-at-sunset")


def test_oauth_redirect_must_match_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "oauth_redirect_allowlist", ["https://app.example.com/oauth/discord"])
    AuthService._validate_redirect_uri("https://app.example.com/oauth/discord")
    with pytest.raises(APIError):
        AuthService._validate_redirect_uri("https://attacker.example/redirect")
