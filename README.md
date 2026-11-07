# VALORANT Strategy API

Secure backend-only API foundation. The frontend is a separate application. Phase 1 supplies auth, PostgreSQL schema/migrations, Redis-backed rate limits, and hardened FastAPI runtime. Strategy, team, player, ingestion, and analytics modules are planned for later phases.

## Run locally on Windows

1. Install Docker Desktop and enable Linux containers.
2. Copy `.env.example` to `.env`. Replace every placeholder with its own random 64-character hexadecimal value. In PowerShell, generate one with `[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))`. Use separate values for every password and signing key, then keep `.env` private.
3. Run `./scripts/doctor.ps1` and fix every reported issue.
4. Run `./scripts/smoke.ps1` to wipe the development Compose volumes, rebuild the images, start services, verify migrations/readiness, and exercise registration/login. This is destructive to the project's local Compose data; use only for a disposable development stack.
5. API docs are at `http://localhost:8000/docs` in development. API prefix: `/api/v1`.

The first Postgres initialization creates a limited runtime database role. A one-shot migration container applies schema changes using the bootstrap credential; the API container receives only the limited runtime credential. Database, Redis, RabbitMQ, and S3 storage ports bind to loopback only. Compose builds service URLs from the base username/password values in `.env`; do not add separate URL credentials. The local object store uses Silo, a maintained MinIO-compatible fork; the S3 API and `MINIO_*` settings remain compatible.

Create the initial administrator only when needed, after the stack is running. In PowerShell, set `SEED_ADMIN_EMAIL` and a unique `SEED_ADMIN_PASSWORD` (at least 16 characters) in the current shell, then run `docker compose run --rm -e SEED_ADMIN_EMAIL -e SEED_ADMIN_PASSWORD migrate python -m app.scripts.seed_admin`. This one-off command uses the migration container's bootstrap credential and refuses to create a second admin.

## API overview (Phase 1)

- `POST /api/v1/auth/register`: accepts email/password with a generic response to reduce account enumeration.
- `POST /api/v1/auth/login`: issues a 15 minute access token and rotating refresh token.
- `POST /api/v1/auth/refresh`: rotates refresh tokens; reuse revokes the token family.
- `POST /api/v1/auth/logout`: revokes all refresh sessions and invalidates outstanding access tokens.
- `POST /api/v1/auth/password`: changes password and revokes all sessions.
- `GET /api/v1/auth/discord/start` and `/discord/callback`: Discord OAuth with state, PKCE, and redirect URI allowlisting.
- `POST /api/v1/auth/realtime-token`: issues a two minute token for the separate collaboration service.
- `GET /health`, `/ready`, `/metrics`: liveness, dependency readiness, and Prometheus metrics.

## Tests and checks

On Windows, enter the backend directory and create a virtual environment using Python 3.13:

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip pip-tools==7.6.2
make install-dev
pytest --cov=app --cov-report=term-missing --cov-fail-under=80
make check
```

The `make` command on Windows requires GNU Make. `make install-dev` compiles a hash-locked `requirements.lock` from `pyproject.toml` and installs it. The individual checks are `ruff check app tests migrations`, `mypy app`, `bandit -c pyproject.toml -r app`, `pip-audit`, and the pytest command above.

The normal pytest command uses test-only URLs and secrets from `tests/conftest.py`; it does not require Docker. Tests that need external services carry the `integration` marker and are skipped by default. To run them against the Compose stack, first start the services and set the integration database URL to the host-mapped Postgres port:

```powershell
docker compose up -d
$env:RUN_INTEGRATION = "1"
$bootstrapPassword = (Get-Content .env | Where-Object { $_ -match '^POSTGRES_BOOTSTRAP_PASSWORD=' }) -replace '^POSTGRES_BOOTSTRAP_PASSWORD=', ''
$env:MIGRATION_TEST_DATABASE_URL = "postgresql+asyncpg://postgres_admin:$bootstrapPassword@127.0.0.1:5432/valorant"
pytest -m integration
```

The Postgres URL uses the Compose bootstrap username/password and host port `5432`. Redis-dependent integration tests, if added, should use the host-mapped Redis port `6379` and its `.env` password.

## Development roadmap

Work proceeds by explicit phases: strategies/storage, teams, players/ingestion/workers, analytics and final hardening. This checkout currently contains Phase 1 only.
