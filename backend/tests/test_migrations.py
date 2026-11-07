import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_TEST_URL = os.environ.get("MIGRATION_TEST_DATABASE_URL")


@pytest.mark.skipif(not MIGRATION_TEST_URL, reason="requires a fresh PostgreSQL test database")
def test_fresh_postgres_upgrade_has_no_model_drift() -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = MIGRATION_TEST_URL or ""
    environment["MIGRATION_DATABASE_URL"] = MIGRATION_TEST_URL or ""
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
