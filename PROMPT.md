Build a production-quality, SECURE BACKEND ONLY for a VALORANT strategy/stats platform (stats tracker + strat board + team/coaching features). The frontend (Next.js) is separate; don't build it.

SETUP: The current folder is the project root. Create everything inside it: a `backend/` directory for all API code, and `docker-compose.yml`, `.env.example`, `.gitignore`, `README.md` at the root. Do not touch anything outside this folder. I'm on Windows with Docker Desktop (Linux containers) and I'm a Python developer, so keep code simple and readable.

STACK: Python 3.13 (Dockerfile `python:3.13-slim`, pyproject.toml `requires-python ">=3.13,<3.14"`), FastAPI, SQLAlchemy 2.0 async + Alembic, Pydantic v2, PostgreSQL 16, Redis 7, Celery + RabbitMQ, S3-compatible storage via boto3 (MinIO in dev, Cloudflare R2 in prod), pytest + httpx. Compose services: api, worker, postgres, redis, rabbitmq, minio. Config via env vars only (pydantic-settings). Pin all dependency versions.

ARCHITECTURE: modular monolith, one FastAPI app, API under /api/v1. One package per module under backend/app/modules/: auth, players, teams, strategies, ingestion, analytics. Each has router, schemas, service, repository, models. Modules call each other's service functions only, never each other's tables. Shared code in backend/app/core (config, db, security, logging, errors, rate limiting).

MODULES:
- auth: email+password, JWT access (15 min) + refresh-token rotation, Discord OAuth, roles (user, coach, admin), endpoint issuing a short-lived token for a separate realtime collaboration server.
- players: lookup by Riot name#tag, profile + recent matches. Redis cache with TTL; stale data returns the cached result and enqueues a background refresh.
- ingestion: Riot API client behind an interface, MockRiotClient for dev/tests. Redis token-bucket rate limiter, retries with backoff, raw JSON to object storage, then normalized into match/round/player_stats tables. Idempotent. Don't invent Riot endpoints you're unsure of; mark them TODO.
- strategies: CRUD for strat boards (map, agent/ability placements as JSONB), version history, folders/tags, visibility (private/team/public), unguessable share slugs, image upload via presigned URLs, pagination + search.
- teams: teams, members, roles, invites, team-shared strategies.
- analytics: aggregate endpoints (win rate by agent/map/rank, trends) from Postgres, behind an interface so ClickHouse can replace it later.

SECURITY (treat as requirements, not extras):
- Passwords: argon2id, min length 10, check against a common-password list, never log or return hashes.
- Tokens: JWT with explicit algorithm (HS256 or RS256), exp/iat/jti/aud/iss claims, reject "none". Store refresh tokens HASHED in the DB, rotate on every use, and detect reuse (reuse revokes the whole token family). Logout and password change revoke all sessions.
- Login protection: per-IP and per-account rate limits, progressive lockout, identical error messages for wrong email vs wrong password, no user enumeration on register/reset.
- OAuth: use `state` and PKCE, validate redirect URIs against an allowlist.
- Authorization: central permission checks (dependency functions) on EVERY resource; prevent IDOR by always filtering by owner/team membership. Admin routes require the admin role. Default deny.
- Input: strict Pydantic schemas with max lengths, `extra="forbid"`, separate request/response models (no mass assignment, never return internal fields). Limit request body size, and limit JSONB canvas size and nesting depth.
- Database: ORM or parameterized queries only, no raw string SQL. Use a least-privilege DB user for the app.
- Uploads: presigned URLs with a short expiry, allowlisted content types (png/jpg/webp), max size, random object keys, never trust client filenames, private bucket by default.
- HTTP hardening: strict CORS allowlist from env (no "*" with credentials), TrustedHost middleware, security headers (HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, CSP for API), disable /docs and /openapi.json in production via env flag.
- Errors: one consistent error format; never leak stack traces, SQL, or internal paths. Log details server-side only.
- Secrets: nothing hardcoded; fail startup if required secrets are missing or weak in production; .env in .gitignore; Riot API key and OAuth secrets never returned or logged. Redact tokens, passwords, and emails in logs.
- Outbound calls: timeouts on all HTTP calls, and only to allowlisted hosts (SSRF-safe).
- Audit log table for security events (login, failed login, password change, role change, token reuse, team membership changes).
- Docker: run containers as a non-root user, pinned base image tags, minimal image, no dev ports exposed except the API (Postgres, Redis, RabbitMQ, MinIO bound to 127.0.0.1 or internal network only), strong generated passwords in .env.example placeholders, healthchecks.
- Tooling: ruff, mypy, bandit, and pip-audit configured, with a single `make check` (or script) that runs them plus tests.
- Security tests: IDOR attempts, expired/tampered/reused tokens, rate-limit lockout, oversize payloads, role escalation, upload validation.

CROSS-CUTTING: pagination on every list endpoint, consistent validation, Redis rate limiting, structured JSON logging with request IDs, /health and /ready endpoints, Prometheus metrics, no N+1 queries, indexes for hot queries, Alembic migrations for all schema.

QUALITY: type hints everywhere, small functions, comments only for non-obvious logic, no placeholder code. Tests for auth, permissions, strategies CRUD, ingestion idempotency (80%+ coverage on services).

DELIVERABLES: working docker-compose, backend/Dockerfile, .env.example, seed script, README with exact Windows-friendly run/test commands, an API overview, and a SECURITY.md listing what is protected and the production checklist (HTTPS, secrets, backups).

PROCESS: work in phases and STOP after each:
1) skeleton, docker-compose, DB, migrations, auth + all security foundations above
2) strategies + storage
3) teams
4) players + ingestion + workers
5) analytics + hardening + docs
After each phase: run tests and `make check`, fix failures, give a 5-line summary and the exact verify commands. Start with Phase 1 only.