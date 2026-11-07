import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.integration
def test_fresh_postgres_upgrade_has_no_model_drift() -> None:
    migration_test_url = os.environ.get("MIGRATION_TEST_DATABASE_URL")
    if not migration_test_url:
        pytest.fail("Set MIGRATION_TEST_DATABASE_URL to the Compose PostgreSQL URL when RUN_INTEGRATION=1")
    environment = os.environ.copy()
    environment["DATABASE_URL"] = migration_test_url
    environment["MIGRATION_DATABASE_URL"] = migration_test_url
    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr

    drift = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=BACKEND_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert drift.returncode == 0, drift.stdout + drift.stderr
