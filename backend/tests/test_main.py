import base64
import hashlib
import re
from fastapi.testclient import TestClient

from app import main


def test_health_docs_and_self_hosted_docs_csp() -> None:
    with TestClient(main.app, base_url="http://localhost") as client:
        health = client.get("/health", headers={"X-Request-ID": "smoke.test-1"})
        assert health.json() == {"status": "ok"}
        assert health.headers["X-Request-ID"] == "smoke.test-1"

        docs = client.get("/docs")
        assert docs.status_code == 200
        assert "/static/swagger-ui/swagger-ui-bundle.js" in docs.text
        assert "/static/swagger-ui/swagger-ui.css" in docs.text
        assert "/static/swagger-ui/favicon-32x32.png" in docs.text
        assert '"validatorUrl": null' in docs.text
        assert "cdn.jsdelivr.net" not in docs.text
        scripts = [value for value in re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", docs.text, re.DOTALL) if value.strip()]
        assert len(scripts) == 1
        digest = base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode()
        policy = docs.headers["Content-Security-Policy"]
        assert f"'sha256-{digest}'" in policy
        assert "'self'" in policy
        assert "unsafe-inline" not in policy

        for path in (
            "/static/swagger-ui/swagger-ui-bundle.js",
            "/static/swagger-ui/swagger-ui.css",
            "/static/swagger-ui/favicon-32x32.png",
        ):
            assert client.get(path).status_code == 200


def test_ready_reports_dependency_state(monkeypatch) -> None:
    class Connection:
        async def __aenter__(self) -> "Connection":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def execute(self, _query: object) -> int:
            return 1

    class Engine:
        def connect(self) -> Connection:
            return Connection()

    async def ping() -> bool:
        return True

    monkeypatch.setattr(main, "get_engine", Engine)
    monkeypatch.setattr(main.redis_client, "ping", ping)
    with TestClient(main.app, base_url="http://localhost") as client:
        assert client.get("/ready").json() == {"status": "ready"}

    class FailedEngine:
        def connect(self) -> Connection:
            raise ConnectionError("database unavailable")

    monkeypatch.setattr(main, "get_engine", FailedEngine)
    with TestClient(main.app, base_url="http://localhost") as client:
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready"}


def test_metrics_and_invalid_request_id() -> None:
    with TestClient(main.app, base_url="http://localhost") as client:
        response = client.get("/metrics", headers={"X-Request-ID": "bad request id"})
        assert response.status_code == 200
        assert "api_http_requests_total" in response.text
        assert re.fullmatch(r"[0-9a-f-]{36}", response.headers["X-Request-ID"])
