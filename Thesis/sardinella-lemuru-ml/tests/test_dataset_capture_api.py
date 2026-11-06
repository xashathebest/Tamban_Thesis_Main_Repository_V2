"""Capture-only HTTP contracts: fake acquisition, real durable local storage."""
import builtins
import hashlib
import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.capture_app import create_capture_app
from src.api.dataset_capture import router as router_module
from src.api.dataset_capture.errors import CaptureError
from src.api.dataset_capture.router import CaptureContext, create_router
from src.api.dataset_capture.service import DatasetCaptureService
from src.api.dataset_capture.storage import CaptureStore
from test_dataset_capture_service import Clock, Source


LOCAL_HEADERS = {"X-Capture-Request": "1"}
OPERATOR_TOKEN = "capture-test-operator-" + "o" * 32
VIEWER_TOKEN = "capture-test-viewer-" + "v" * 32


class NoCloud:
    def status(self):
        return {"connected": False, "oauth_configured": False,
                "authorization_pending": False, "error": None}

    def close(self):
        pass


@pytest.fixture(autouse=True)
def isolate_runtime(monkeypatch, tmp_path):
    import os
    for key in tuple(os.environ):
        if key.startswith(("FISH_LAN_", "FISH_CAPTURE_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(router_module, "PROJECT_ROOT", tmp_path / "no-private-project-config")
    def no_network(*args, **kwargs):
        raise AssertionError("Capture API tests must never contact Google.")
    monkeypatch.setattr(router_module.GoogleDriveClient, "test_access", no_network)
    monkeypatch.setattr(router_module.GoogleDriveClient, "upload_file", no_network)


@pytest.fixture
def api(tmp_path):
    clock, sources = Clock(), []
    def factory(**config):
        source = Source(clock, len(sources) + 1)
        sources.append(source)
        return source
    store = CaptureStore(tmp_path / "capture", min_free_bytes=0)
    service = DatasetCaptureService(store, factory, clock, background=False)
    context = CaptureContext(root=store.root, service=service, store=store, oauth=NoCloud())
    app = create_capture_app(context)
    yield app, context, service, clock, store, sources
    context.close()


def create_session(client, **metadata):
    response = client.post("/api/capture/sessions", json={"metadata": metadata}, headers=LOCAL_HEADERS)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def open_camera(client):
    response = client.post("/api/capture/camera/start", json={"device_index": 1, "backend": "default"}, headers=LOCAL_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def test_manual_api_two_clicks_save_native_files_and_same_persistent_queue(api):
    app, _, _, _, store, sources = api
    with TestClient(app) as client:
        session_id = create_session(client, session_name="Synthetic source", provisional_grade="Unknown")
        status = open_camera(client)
        assert status["manual_available"]
        photos = [client.post("/api/capture/snapshot", headers=LOCAL_HEADERS) for _ in range(2)]
        assert [p.status_code for p in photos] == [201, 201]
        first, second = (p.json() for p in photos)
        assert first["id"] != second["id"]
        assert first["frame_metadata"]["frame_id"] != second["frame_metadata"]["frame_id"]
        assert all(p["capture_mode"] == "manual" and p["local_status"] == "saved" and p["sync_status"] == "queued" for p in (first, second))
        assert len(sources) == 1
        items = client.get(f"/api/capture/sessions/{session_id}/items").json()
        assert items["total"] == 2
        state = client.get("/api/capture/status").json()
        assert state["manual_count"] == 2 and state["run"]["state"] == "idle"
        assert state["stats"]["raw_frames"] == 2
        assert not state["drive"]["connected"]
        assert state["drive"]["queue"]["queued"] == 2
        path = store.media_path(session_id, first["id"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == first["sha256"]


@pytest.mark.parametrize("countdown", [5, 10])
def test_http_run_distinguishes_countdown_duration_and_manual_capture(api, countdown):
    app, _, service, clock, _, _ = api
    with TestClient(app) as client:
        create_session(client)
        open_camera(client)
        response = client.post("/api/capture/session/start", json={"countdown": countdown, "interval": 1, "duration": 5}, headers=LOCAL_HEADERS)
        assert response.status_code == 200
        assert response.json()["run"]["countdown_remaining"] == countdown
        manual = client.post("/api/capture/snapshot", headers=LOCAL_HEADERS)
        assert manual.status_code == 201 and manual.json()["capture_mode"] == "manual"
        clock.advance(countdown)
        for _ in range(5):
            service.tick()
            clock.advance(1)
        service.tick()
        status = client.get("/api/capture/status").json()
        assert status["run"]["state"] == "completed"
        assert status["run"]["captured"] == 5
        assert status["stats"]["raw_frames"] == 6
        assert status["run"]["stop_reason"] == "duration"


def test_metadata_review_media_and_zip_json_csv_exports_keep_original_unchanged(api):
    app, _, _, _, store, _ = api
    with TestClient(app) as client:
        session_id = create_session(client, source_code="synthetic", specimen_id="confirmed-one", specimen_confirmed=True)
        open_camera(client)
        item = client.post("/api/capture/snapshot", headers=LOCAL_HEADERS).json()
        original = store.media_path(session_id, item["id"]).read_bytes()
        counters = client.get("/api/capture/status").json()["stats"]
        assert counters["confirmed_specimens"] == 1
        assert counters["provisional_grades"]["Unknown"] == 1
        image = client.get(f"/api/capture/sessions/{session_id}/items/{item['id']}/image")
        assert image.status_code == 200 and image.content == original
        assert image.headers["cache-control"] == "no-store"
        assert image.headers["x-content-type-options"] == "nosniff"
        thumbnail = client.get(f"/api/capture/sessions/{session_id}/items/{item['id']}/image?thumbnail=true")
        assert thumbnail.status_code == 200
        review = client.patch(f"/api/capture/sessions/{session_id}/items", json={"item_ids": [item["id"]], "metadata": {"review_state": "exclude", "notes": "Synthetic review"}}, headers=LOCAL_HEADERS)
        assert review.status_code == 200
        assert review.json()["items"][0]["metadata"]["review_state"] == "exclude"
        assert store.media_path(session_id, item["id"]).read_bytes() == original
        export_json = client.get(f"/api/capture/sessions/{session_id}/export?format=json")
        manifest = export_json.json()
        assert manifest["session"]["id"] == session_id
        assert manifest["items"][0]["sha256"] == item["sha256"]
        csv = client.get(f"/api/capture/sessions/{session_id}/export?format=csv")
        assert csv.status_code == 200 and b"sha256" in csv.content
        archive = client.get(f"/api/capture/sessions/{session_id}/export?format=zip")
        assert archive.status_code == 200
        with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
            assert any(name.endswith(item["filename"].split("/")[-1]) for name in bundle.namelist())
            assert any(name.endswith("manifest.json") for name in bundle.namelist())


def test_local_mutations_require_capture_header_and_same_origin(api):
    app, _, _, _, store, _ = api
    with TestClient(app) as client:
        assert client.post("/api/capture/sessions", json={"metadata": {}}).status_code == 403
        for headers in ({**LOCAL_HEADERS, "Origin": "https://untrusted.invalid"},
                        {**LOCAL_HEADERS, "Sec-Fetch-Site": "cross-site"}):
            response = client.post("/api/capture/sessions", json={"metadata": {}}, headers=headers)
            assert response.status_code == 403
            assert response.json()["code"] == "SAME_ORIGIN_REQUIRED"
        assert store.list_sessions() == []
        assert client.post("/api/capture/sessions", json={"metadata": {}}, headers={**LOCAL_HEADERS, "Origin": "http://testserver"}).status_code == 201


def test_remote_api_is_denied_without_secure_lan_mode(api):
    app, _, _, _, store, _ = api
    with TestClient(app, client=("192.0.2.12", 43000)) as client:
        assert client.get("/api/capture/status").status_code == 403
        assert client.post("/api/capture/sessions", json={"metadata": {}}, headers=LOCAL_HEADERS).status_code == 403
        assert store.list_sessions() == []


def test_lan_viewer_cannot_mutate_operator_requires_https_and_cookie_csrf(api, monkeypatch):
    app, _, _, _, _, _ = api
    monkeypatch.setenv("FISH_LAN_AUTH", "1")
    monkeypatch.setenv("FISH_LAN_OPERATOR_TOKEN", OPERATOR_TOKEN)
    monkeypatch.setenv("FISH_LAN_VIEWER_TOKEN", VIEWER_TOKEN)
    with TestClient(app, base_url="https://testserver") as client:
        viewer = {"Authorization": "Bearer " + VIEWER_TOKEN}
        assert client.get("/api/capture/status", headers=viewer).status_code == 200
        assert client.post("/api/capture/sessions", json={"metadata": {}}, headers={**viewer, **LOCAL_HEADERS}).status_code == 403
        login = client.post("/api/auth/login", json={"token": OPERATOR_TOKEN}, headers={"Origin": "https://testserver"})
        assert login.status_code == 200
        assert "__Host-tamban_capture_session=" in login.headers["set-cookie"]
        assert "HttpOnly" in login.headers["set-cookie"] and "Secure" in login.headers["set-cookie"]
        assert client.post("/api/capture/sessions", json={"metadata": {}}, headers=LOCAL_HEADERS).status_code == 403
        csrf = login.json()["csrf_token"]
        headers = {**LOCAL_HEADERS, "Origin": "https://testserver", "X-CSRF-Token": csrf}
        assert client.post("/api/capture/sessions", json={"metadata": {}}, headers=headers).status_code == 201
        assert client.post("/api/capture/snapshot", headers={**headers, "X-CSRF-Token": "wrong"}).status_code == 403
    with TestClient(app, base_url="http://testserver") as client:
        assert client.get("/api/capture/status", headers={"Authorization": "Bearer " + OPERATOR_TOKEN}).status_code == 403


def test_capture_auth_does_not_accept_or_overwrite_inspection_sessions(api, monkeypatch):
    from src.api import lan_security
    app, _, _, _, _, _ = api
    auth = app.state.capture_auth
    assert auth is not lan_security and auth._sessions is not lan_security._sessions
    assert auth.COOKIE != lan_security.COOKIE
    monkeypatch.setenv("FISH_LAN_AUTH", "1")
    monkeypatch.setenv("FISH_LAN_OPERATOR_TOKEN", OPERATOR_TOKEN)
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set(lan_security.COOKIE, "inspection-cookie-placeholder")
        assert client.get("/api/capture/status").status_code == 401
        login = client.post("/api/auth/login", json={"token": OPERATOR_TOKEN}, headers={"Origin": "https://testserver"})
        assert login.status_code == 200
        assert client.cookies.get(lan_security.COOKIE) == "inspection-cookie-placeholder"
        assert client.cookies.get(auth.COOKIE)
        assert client.get("/api/capture/status").status_code == 200


def test_invalid_ids_paths_and_unknown_schema_never_write_outside_capture(api):
    app, _, _, _, store, _ = api
    with TestClient(app) as client:
        assert client.post("/api/capture/sessions", json={"metadata": {"secret_path": "../outside"}}, headers=LOCAL_HEADERS).status_code == 422
        assert client.post("/api/capture/camera/start", json={"device_index": 0, "steal_inspection": True}, headers=LOCAL_HEADERS).status_code == 422
        assert client.post("/api/capture/camera/start", json={"device_index": True}, headers=LOCAL_HEADERS).status_code == 422
        for fake_id in ("not-a-session", "..%5Coutside", "f" * 32):
            assert client.get(f"/api/capture/sessions/{fake_id}/items").status_code in {404, 422}
        assert client.get("/api/capture/sessions/..%2Foutside/export").status_code == 404
        assert store.list_sessions() == []


def test_disconnected_camera_disables_shutter_and_missing_drive_preserves_files(api):
    app, _, _, _, store, sources = api
    with TestClient(app) as client:
        session_id = create_session(client)
        open_camera(client)
        item = client.post("/api/capture/snapshot", headers=LOCAL_HEADERS).json()
        sources[0].error = CaptureError(503, "CAMERA_DISCONNECTED", "Synthetic disconnected camera")
        failed = client.post("/api/capture/snapshot", headers=LOCAL_HEADERS)
        assert failed.status_code == 503 and failed.json()["code"] == "CAMERA_DISCONNECTED"
        status = client.get("/api/capture/status").json()
        assert not status["manual_available"] and status["stats"]["raw_frames"] == 1
        assert client.get("/api/capture/preview.jpg").status_code == 409
        for endpoint, body in (("/drive/sync", None), ("/drive/test", {}), ("/drive/settings", {"auto_sync": True})):
            response = client.request("PATCH" if endpoint.endswith("settings") else "POST", "/api/capture" + endpoint, json=body, headers=LOCAL_HEADERS)
            assert response.status_code == 409
            assert response.json()["code"] == "DRIVE_NOT_CONNECTED"
        assert store.media_path(session_id, item["id"]).exists()
        assert store.queue_status()["queued"] == 1


def test_default_main_mount_remains_hardware_disabled_and_has_no_inspection_imports(tmp_path, monkeypatch):
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name == "src.api.camera" or name == "src.api.app" or name.startswith("src.inference"):
            raise AssertionError("Capture-only operation imported protected inspection or models.")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    context = CaptureContext(root=tmp_path / "main-mount", hardware_enabled=False, oauth=NoCloud())
    app = FastAPI()
    app.include_router(create_router(context))
    with TestClient(app) as client:
        response = client.post("/api/capture/camera/start", json={}, headers=LOCAL_HEADERS)
        assert response.status_code == 409
        assert response.json()["code"] == "PHYSICAL_ISOLATION_REQUIRED"
        assert not client.get("/api/capture/status").json()["manual_available"]
        assert not any(path.name.endswith(".pt") for path in context.root.rglob("*"))
    context.close()


def test_context_cleanup_is_idempotent_and_releases_camera_before_store(api):
    app, context, service, _, store, sources = api
    with TestClient(app) as client:
        create_session(client)
        open_camera(client)
        client.post("/api/capture/snapshot", headers=LOCAL_HEADERS)
        assert context._worker.is_alive()
    assert sources[0].closed
    assert context._closed and not context._worker.is_alive()
    context.close()
    assert service._shutdown.is_set()

