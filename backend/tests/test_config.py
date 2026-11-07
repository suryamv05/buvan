import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_csv_settings_are_parsed_without_json_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,https://web.example.com")
    monkeypatch.setenv("TRUSTED_HOSTS", "localhost,api")
    settings = Settings(_env_file=None)
    assert settings.cors_origins == ["http://localhost:3000", "https://web.example.com"]
    assert settings.trusted_hosts == ["localhost", "api"]


def test_settings_name_missing_secret() -> None:
    settings = Settings(_env_file=None)
    with pytest.raises(ValueError, match="POSTGRES_DB"):
        settings.validate_runtime()


def test_settings_name_placeholder_secret() -> None:
    settings = Settings(
        _env_file=None,
        postgres_db="valorant",
        postgres_bootstrap_user="postgres_admin",
        postgres_bootstrap_password="REPLACE_WITH_SECRET",
        app_db_user="valorant_app",
        app_db_password="app-pass",
        redis_password="redis-pass",
        rabbitmq_user="worker",
        rabbitmq_password="rabbit-pass",
        minio_root_user="storage-admin",
        minio_root_password="storage-pass",
        jwt_secret="jwt-pass",
        realtime_jwt_secret="realtime-pass",
        database_url="postgresql+asyncpg://postgres_admin:pass@postgres/valorant",
        redis_url="redis://:pass@redis/0",
        celery_broker_url="amqp://worker:pass@rabbitmq:5672//",
    )
    with pytest.raises(ValueError, match="POSTGRES_BOOTSTRAP_PASSWORD.*REPLACE_WITH"):
        settings.validate_runtime()
