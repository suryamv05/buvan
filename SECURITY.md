# Security

## Phase 1 protections

- Password hashing uses Argon2id; request passwords are write-only secret fields and common weak values are rejected.
- JWT validation pins HS256 and requires issuer, audience, expiration, issued-at, subject, and token ID claims. Realtime tokens use a separate key and a two minute lifetime.
- Refresh secrets are random, stored only as SHA-256 digests, rotated at use, and family-revoked on reuse. Logout and password change revoke all sessions and increment a token version so outstanding access tokens stop working.
- Login and registration rate limits use Redis per IP and account; login has progressive account lockout and a constant invalid-credentials response.
- Discord OAuth uses cryptographic state, PKCE S256, one-time Redis state, fixed Discord hosts, and an exact redirect URI allowlist.
- Authorization resolves the account from the database on each request and checks roles centrally. No user-controlled role is accepted.
- API errors use a consistent envelope; unexpected exceptions do not expose details. Request IDs and security headers are applied centrally.
- Runtime DB credentials have DML rights only; migrations use a separate bootstrap credential. Secret values are environment configuration and `.env` is ignored.
- Containers use non-root users; exposed service ports bind to `127.0.0.1`.

## Production checklist

- Set `ENVIRONMENT=production`; provide unique random `JWT_SECRET` and `REALTIME_JWT_SECRET` values of at least 48 characters.
- Set exact `CORS_ORIGINS`, `TRUSTED_HOSTS`, and OAuth redirect allowlist values. Disable docs with `ENABLE_DOCS=false`.
- Store production credentials in a managed secret store; rotate bootstrap/database, Redis, RabbitMQ, object-storage, Riot, and OAuth credentials.
- Terminate TLS at a trusted ingress, enforce HTTPS, and configure proxy trust safely before deployment.
- Configure managed PostgreSQL/Redis/RabbitMQ/object storage with private networking, TLS, least privilege, monitoring, and tested restore procedures.
- Back up the database and object data on a schedule; encrypt backups and regularly test recovery.
- Configure production alerting for auth failures, rate limits, readiness, database capacity, and audit events.
- Review dependency vulnerability reports and update pinned dependencies through a reviewed change.
