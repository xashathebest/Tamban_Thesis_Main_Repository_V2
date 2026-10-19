"""LAN access controls must fail closed while local mode remains usable."""
from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from src.api import lan_security


@pytest.fixture
def secure(monkeypatch):
    monkeypatch.setenv("FISH_LAN_AUTH", "1")
    monkeypatch.setenv("FISH_LAN_VIEWER_TOKEN", "v" * 40)
    monkeypatch.setenv("FISH_LAN_OPERATOR_TOKEN", "o" * 40)
    monkeypatch.setenv("FISH_LAN_ADMIN_TOKEN", "a" * 40)
    monkeypatch.delenv("FISH_LAN_DEBUG", raising=False)
    with lan_security._lock:
        lan_security._sessions.clear()
        lan_security._login_attempts.clear()
    app = importlib.import_module("src.api.app")
    return TestClient(app.app, base_url="https://testserver")


def bearer(token):
    return {"Authorization": f"Bearer {token * 40}"}


def test_local_default_and_remote_requests_without_profile(monkeypatch):
    monkeypatch.delenv("FISH_LAN_AUTH", raising=False)
    app = importlib.import_module("src.api.app")
    local = TestClient(app.app)
    assert local.get("/api/status/live").status_code == 200
    assert local.post("/api/reviews/3", json={}).status_code == 422
    remote = TestClient(app.app, client=("192.0.2.100", 1234))
    assert remote.get("/api/status/live").status_code == 403
    assert remote.post("/api/settings", json={}).status_code == 403


def test_lan_denies_unauthorized_reads_and_mutations(secure):
    assert secure.get("/api/auth/mode").json()["lan_security"] is True
    for path in ("/api/status/live", "/api/history", "/api/sessions", "/api/reviews", "/api/analytics", "/api/video-feed"):
        assert secure.get(path).status_code == 401
    for path in ("/api/inspection/start", "/api/inspection/stop", "/api/settings", "/api/models/select", "/api/session/reset", "/api/reviews/1", "/api/camera/settings", "/api/export", "/api/analyze-image"):
        assert secure.post(path, json={}).status_code == 401
    assert secure.post("/api/settings", headers={"Authorization": "Bearer wrong"}, json={}).status_code == 401


def test_roles_limit_writes_and_allow_private_reads(secure, monkeypatch):
    assert secure.get("/api/status/live", headers=bearer("v")).status_code == 200
    assert secure.get("/api/history", headers=bearer("v")).status_code == 200
    assert secure.post("/api/export", headers=bearer("v"), json={}).status_code == 422
    assert secure.post("/api/settings", headers=bearer("v"), json={}).status_code == 403
    assert secure.post("/api/reviews/1", headers=bearer("v"), json={}).status_code == 403
    assert secure.post("/api/reviews/1", headers=bearer("o"), json={}).status_code == 422
    assert secure.get("/api/debug/runtime", headers=bearer("a")).status_code == 404
    monkeypatch.setenv("FISH_LAN_DEBUG", "1")
    assert secure.get("/api/debug/runtime", headers=bearer("o")).status_code == 403
    assert secure.get("/api/debug/runtime", headers=bearer("a")).status_code == 200
    assert secure.get("/api/status/live", headers=bearer("v")).json()["runtime_diagnostics"] == {"enabled": False}
    assert "artifacts" in secure.get("/api/status/live", headers=bearer("a")).json()["runtime_diagnostics"]
    assert secure.get("/api/history", headers=bearer("v")).headers["cache-control"] == "no-store"


def test_browser_cookie_csrf_rotation_and_logout(secure, monkeypatch):
    assert secure.post("/api/auth/login", json={"token": "o" * 40}).status_code == 403
    assert secure.post("/api/auth/login", headers={"Origin": "https://evil.example"}, json={"token": "o" * 40}).status_code == 403
    login = secure.post("/api/auth/login", headers={"Origin": "https://testserver"}, json={"token": "o" * 40})
    assert login.status_code == 200
    cookie = login.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    csrf = login.json()["csrf_token"]
    assert secure.get("/api/history").status_code == 200
    assert secure.post("/api/settings", json={}).status_code == 403
    assert secure.post("/api/settings", headers={"Origin": "https://evil.example", "X-CSRF-Token": csrf}, json={}).status_code == 403
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}
    assert secure.post("/api/reviews/1", headers=headers, json={}).status_code == 422
    assert secure.post("/api/auth/logout", headers=headers).status_code == 200
    assert secure.get("/api/history").status_code == 401
    secure.post("/api/auth/login", headers={"Origin": "https://testserver"}, json={"token": "o" * 40})
    monkeypatch.setenv("FISH_LAN_OPERATOR_TOKEN", "n" * 40)
    assert secure.get("/api/history").status_code == 401


def test_login_attempt_limit_and_active_stream_revocation(secure):
    origin = {"Origin": "https://testserver"}
    login = secure.post("/api/auth/login", headers=origin, json={"token": "o" * 40})
    csrf = login.json()["csrf_token"]
    cookie = f"{lan_security.COOKIE}={secure.cookies.get(lan_security.COOKIE)}".encode("ascii")
    request = Request({"type": "http", "method": "GET", "scheme": "https", "path": "/api/video-feed",
                       "headers": [(b"cookie", cookie)], "server": ("testserver", 443), "client": ("testclient", 1)})
    assert lan_security.stream_authorized(request)
    secure.post("/api/auth/logout", headers={**origin, "X-CSRF-Token": csrf})
    assert not lan_security.stream_authorized(request)
    for _ in range(9):
        assert secure.post("/api/auth/login", headers=origin, json={"token": "wrong"}).status_code == 401
    assert secure.post("/api/auth/login", headers=origin, json={"token": "wrong"}).status_code == 429


def test_signing_in_again_revokes_previous_cookie(secure):
    origin = {"Origin": "https://testserver"}
    secure.post("/api/auth/login", headers=origin, json={"token": "o" * 40})
    old_cookie = secure.cookies.get(lan_security.COOKIE)
    secure.post("/api/auth/login", headers=origin, json={"token": "v" * 40})
    app = importlib.import_module("src.api.app")
    old_client = TestClient(app.app, base_url="https://testserver", cookies={lan_security.COOKIE: old_cookie})
    assert old_client.get("/api/history").status_code == 401
    assert secure.get("/api/history").status_code == 200
    assert secure.post("/api/settings", json={}).status_code == 403


def test_https_and_valid_configuration_are_required(secure, monkeypatch):
    app = importlib.import_module("src.api.app")
    insecure = TestClient(app.app, base_url="http://testserver")
    assert insecure.get("/api/history", headers=bearer("v")).status_code == 403
    monkeypatch.setenv("FISH_LAN_OPERATOR_TOKEN", "short")
    assert secure.get("/api/history", headers=bearer("v")).status_code == 503
    monkeypatch.setenv("FISH_LAN_OPERATOR_TOKEN", "v" * 40)
    assert secure.get("/api/history", headers=bearer("v")).status_code == 503


def test_launcher_requires_auth_and_tls_on_network_bind(monkeypatch, tmp_path):
    launcher = importlib.import_module("src.api.__main__")
    monkeypatch.setenv("LEMURU_HOST", "0.0.0.0")
    monkeypatch.delenv("FISH_LAN_AUTH", raising=False)
    monkeypatch.delenv("LEMURU_TLS_CERTFILE", raising=False)
    monkeypatch.delenv("LEMURU_TLS_KEYFILE", raising=False)
    with pytest.raises(SystemExit, match="FISH_LAN_AUTH"):
        launcher.main()
    monkeypatch.setenv("FISH_LAN_AUTH", "1")
    monkeypatch.setenv("FISH_LAN_OPERATOR_TOKEN", "o" * 40)
    monkeypatch.delenv("FISH_LAN_VIEWER_TOKEN", raising=False)
    monkeypatch.delenv("FISH_LAN_ADMIN_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="TLS"):
        launcher.main()
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert.write_text("fake", encoding="utf-8")
    key.write_text("fake", encoding="utf-8")
    monkeypatch.setenv("LEMURU_TLS_CERTFILE", str(cert))
    monkeypatch.setenv("LEMURU_TLS_KEYFILE", str(key))
    with patch.object(launcher.uvicorn, "run") as run:
        launcher.main()
    assert run.call_args.kwargs["host"] == "0.0.0.0"
    assert run.call_args.kwargs["ssl_certfile"] == str(cert)
