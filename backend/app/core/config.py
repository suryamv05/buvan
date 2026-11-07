from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        enable_decoding=False,
        extra="ignore",
    )
    environment: str = "development"
    postgres_db: str = ""
    postgres_bootstrap_user: str = ""
    postgres_bootstrap_password: str = ""
    app_db_user: str = ""
    app_db_password: str = ""
    redis_password: str = ""
    rabbitmq_user: str = ""
    rabbitmq_password: str = ""
    minio_root_user: str = ""
    minio_root_password: str = ""
    database_url: str = ""
    migration_database_url: str = ""
    redis_url: str = ""
    celery_broker_url: str = ""
    jwt_secret: str = ""
    realtime_jwt_secret: str = ""
    jwt_issuer: str = "valorant-api"
    jwt_audience: str = "valorant-client"
    realtime_issuer: str = "valorant-api"
    realtime_audience: str = "valorant-realtime"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    cors_origins: list[str] = []
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "api"]
    enable_docs: bool = True
    max_request_bytes: int = 1_048_576
    rate_limit_enabled: bool = True
    discord_client_id: str = ""
    discord_client_secret: str = ""
    oauth_redirect_allowlist: list[str] = []

    @field_validator("cors_origins", "trusted_hosts", "oauth_redirect_allowlist", mode="before")
    @classmethod
    def parse_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    def validate_runtime(self, *, require_migration: bool = False, require_worker: bool = True) -> None:
        required = {
            "POSTGRES_DB": self.postgres_db,
            "POSTGRES_BOOTSTRAP_USER": self.postgres_bootstrap_user,
            "POSTGRES_BOOTSTRAP_PASSWORD": self.postgres_bootstrap_password,
            "APP_DB_USER": self.app_db_user,
            "APP_DB_PASSWORD": self.app_db_password,
            "REDIS_PASSWORD": self.redis_password,
            "RABBITMQ_USER": self.rabbitmq_user,
            "RABBITMQ_PASSWORD": self.rabbitmq_password,
            "MINIO_ROOT_USER": self.minio_root_user,
            "MINIO_ROOT_PASSWORD": self.minio_root_password,
            "JWT_SECRET": self.jwt_secret,
            "REALTIME_JWT_SECRET": self.realtime_jwt_secret,
            "DATABASE_URL": self.database_url,
        }
        if require_migration:
            required["MIGRATION_DATABASE_URL"] = self.migration_database_url
        if require_worker:
            required["REDIS_URL"] = self.redis_url
            required["CELERY_BROKER_URL"] = self.celery_broker_url
        for name, value in required.items():
            if not value:
                raise ValueError(f"Missing required environment variable {name}.")
            if "replace_with" in value.lower():
                raise ValueError(f"Environment variable {name} still contains REPLACE_WITH; replace it with a generated value.")
        if self.environment == "production":
            for label, secret in (("JWT_SECRET", self.jwt_secret), ("REALTIME_JWT_SECRET", self.realtime_jwt_secret)):
                if len(secret) < 48 or secret.lower() in {"changeme", "secret", "password"}:
                    raise ValueError(f"{label} must be a generated secret of at least 48 characters")
            if "*" in self.cors_origins:
                raise ValueError("Wildcard CORS origins are forbidden in production")
            if not self.trusted_hosts:
                raise ValueError("TRUSTED_HOSTS must be configured in production")
            if self.jwt_secret == self.realtime_jwt_secret:
                raise ValueError("JWT_SECRET and REALTIME_JWT_SECRET must be different")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
