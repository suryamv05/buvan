import os

import pytest


_TEST_ENV = {
    "ENVIRONMENT": "test",
    "POSTGRES_DB": "valorant_test",
    "POSTGRES_BOOTSTRAP_USER": "test_bootstrap",
    "POSTGRES_BOOTSTRAP_PASSWORD": "0" * 64,
    "APP_DB_USER": "test_app",
    "APP_DB_PASSWORD": "1" * 64,
    "REDIS_PASSWORD": "2" * 64,
    "RABBITMQ_USER": "test_worker",
    "RABBITMQ_PASSWORD": "3" * 64,
    "MINIO_ROOT_USER": "test_storage",
    "MINIO_ROOT_PASSWORD": "4" * 64,
    "JWT_SECRET": "5" * 64,
    "REALTIME_JWT_SECRET": "6" * 64,
    "DATABASE_URL": "postgresql+asyncpg://test:test@127.0.0.1:5432/valorant_test",
    "MIGRATION_DATABASE_URL": "postgresql+asyncpg://test:test@127.0.0.1:5432/valorant_test",
    "REDIS_URL": "redis://:test@127.0.0.1:6379/0",
    "CELERY_BROKER_URL": "amqp://test:test@127.0.0.1:5672//",
}
for _name, _value in _TEST_ENV.items():
    os.environ.setdefault(_name, _value)

def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if os.environ.get("RUN_INTEGRATION") == "1":
        return
    skip_integration = pytest.mark.skip(reason="set RUN_INTEGRATION=1 to run integration tests")
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip_integration)
