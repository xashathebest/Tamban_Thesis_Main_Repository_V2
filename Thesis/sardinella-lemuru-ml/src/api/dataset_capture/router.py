"""Independent collection endpoints; no inspection service or model imports."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
from threading import Event, RLock, Thread
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.routing import APIRoute

from .drive import DriveHTTPError, FOLDER_RE, GoogleDriveClient, OAuthManager
from .errors import CaptureError
from .schemas import CameraInput, DriveSettings, DriveTest, ItemPatch, MetadataInput, RunInput


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class CaptureRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                response = await original(request)
            except CaptureError as exc:
                response = JSONResponse({"detail": exc.detail, "code": exc.code}, status_code=exc.status_code)
            except DriveHTTPError as exc:
                response = JSONResponse({"detail": str(exc), "code": "DRIVE_AUTHORIZATION" if exc.status_code in {401, 403} else "DRIVE_REQUEST_FAILED"}, status_code=exc.status_code)
            except OSError:
                response = JSONResponse({"detail": "Capture storage is unavailable. Check free space and local permissions.", "code": "STORAGE_UNAVAILABLE"}, status_code=507)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response

        return handler


def capture_write_guard(request: Request):
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise CaptureError(403, "SAME_ORIGIN_REQUIRED", "Capture changes require a same-origin request.")
    origin = request.headers.get("origin")
    if origin:
        try:
            source, target = urlsplit(origin), urlsplit(str(request.base_url))
            def port(value):
                return value.port or (443 if value.scheme == "https" else 80)
            same = (source.scheme, source.hostname, port(source)) == (target.scheme, target.hostname, port(target))
            same = same and not (source.username or source.password or source.path or source.query or source.fragment)
        except ValueError:
            same = False
        if not same:
            raise CaptureError(403, "SAME_ORIGIN_REQUIRED", "Capture changes require a same-origin request.")
    if request.headers.get("x-capture-request") != "1":
        raise CaptureError(403, "CAPTURE_HEADER_REQUIRED", "A capture request header is required for local browser safety.")


class CaptureContext:
    """Lazy, capture-only runtime, independently cleaned up by router lifespan."""
    def __init__(self, root=None, *, hardware_enabled=False, service=None, store=None, oauth=None, folder_id=None):
        self.root = Path(root or os.getenv("FISH_CAPTURE_ROOT") or PROJECT_ROOT / "data/capture_sessions").resolve()
        self.hardware_enabled = hardware_enabled
        self._service, self._store, self._oauth = service, store, oauth
        self._queue = None
        self._lock, self._shutdown = RLock(), Event()
        self._worker = None
        self.folder_id = folder_id
        self._folder_verified = False
        self._auto_sync = False
        self._last_sync_error = None
        self._closed = False

    def _initialize(self):
        with self._lock:
            if self._closed:
                raise CaptureError(503, "CAPTURE_CLOSED", "Capture is shutting down.")
            if self._store is None:
                from .storage import CaptureStore
                self._store = CaptureStore(self.root)
            if self._service is None:
                from .service import DatasetCaptureService
                self._service = DatasetCaptureService(self._store, hardware_enabled=self.hardware_enabled)
            if self._oauth is None:
                self._oauth = OAuthManager(self.root / "private")
            if self._queue is None:
                from .drive_queue import DriveSyncQueue
                config_path = PROJECT_ROOT / ".capture-private/config.json"
                config = {}
                if config_path.exists() and config_path.stat().st_size <= 65536:
                    try:
                        config = json.loads(config_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        pass
                self.folder_id = self.folder_id or os.getenv("FISH_CAPTURE_DRIVE_FOLDER_ID") or config.get("drive_folder_id")
                if self.folder_id and not FOLDER_RE.fullmatch(str(self.folder_id)):
                    raise CaptureError(422, "INVALID_DRIVE_FOLDER", "The configured Drive folder ID is invalid.")
                self._queue = DriveSyncQueue(self._store, destination_id=self.folder_id)
                settings = self.root / "capture-settings.json"
                if settings.exists():
                    try:
                        self._auto_sync = json.loads(settings.read_text(encoding="utf-8")).get("auto_sync") is True
                    except (OSError, ValueError):
                        pass
                self._worker = Thread(target=self._sync_worker, name="capture-drive-queue", daemon=True)
                self._worker.start()

    @property
    def service(self):
        self._initialize()
        return self._service

    @property
    def store(self):
        self._initialize()
        return self._store

    @property
    def oauth(self):
        self._initialize()
        return self._oauth

    def _drive_client(self):
        if not self.folder_id or not self._oauth.status()["connected"]:
            raise CaptureError(409, "DRIVE_NOT_CONNECTED", "Connect Google Drive and test destination access; originals remain saved locally and queued.")
        if self._queue.client is None:
            self._queue.client = GoogleDriveClient(self._oauth, self.folder_id)
        return self._queue.client

    def drive_status(self):
        self._initialize()
        state = self._oauth.status()
        connected = state["connected"] and bool(self.folder_id)
        return {**self._queue.status(), **state, "connected": connected, "state": "Connected" if connected else "Drive not connected",
                "can_upload": connected and self._folder_verified, "destination_configured": bool(self.folder_id),
                "folder_url": "https://drive.google.com/drive/folders/" + self.folder_id if self.folder_id else None,
                "auto_sync": self._auto_sync, "last_sync_error": self._last_sync_error,
                "setup_message": ("Create a Google Desktop OAuth client and set FISH_CAPTURE_OAUTH_CLIENT_FILE on the server. Credentials stay server-side."
                                  if not state["oauth_configured"] else "Connect Google, then Test access before syncing." if not self._folder_verified else "Destination verified. Auto-sync is opt-in.")}

    def status(self):
        data = self.service.status()
        camera = data["camera"]
        requested, actual = camera.get("requested", {}), camera.get("readbacks", {})
        camera.update({key: actual.get(key, requested.get(key)) for key in ("device_index", "width", "height", "backend")})
        camera["error"] = data.get("last_error")
        run = data["run"]
        run["next_shot_in"] = run.get("next_shot_seconds")
        stats = data.get("stats", {})
        stats.update(frames=stats.get("raw_frames", 0), manual=stats.get("manual_photos", 0),
                     reviewed=stats.get("reviewed_photos", 0), confirmed_specimens=stats.get("unique_specimens_confirmed", 0),
                     provisional_grades=stats.get("specimens_per_provisional_grade", {}), backlog=stats.get("upload_backlog", 0))
        data["drive"] = self.drive_status()
        return data

    def sync(self):
        self._initialize()
        client = self._drive_client()
        if not self._folder_verified:
            client.test_access()
            self._folder_verified = True
        result = self._queue.sync_now()
        self._last_sync_error = None
        return {**result, "drive": self.drive_status()}

    def _sync_worker(self):
        while not self._shutdown.wait(1):
            if self._auto_sync:
                try:
                    self.sync()
                except (CaptureError, DriveHTTPError) as exc:
                    self._last_sync_error = getattr(exc, "code", "DRIVE_AUTHORIZATION_REQUIRED")
                except Exception:
                    self._last_sync_error = "DRIVE_SYNC_UNAVAILABLE"

    def set_auto_sync(self, value):
        self._initialize()
        if value:
            self._drive_client().test_access()
            self._folder_verified = True
        path = self.root / "capture-settings.json"
        temporary = path.with_suffix("." + secrets.token_hex(6) + ".tmp")
        temporary.write_text(json.dumps({"auto_sync": value}), encoding="utf-8")
        os.replace(temporary, path)
        self._auto_sync = value
        return self.drive_status()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._shutdown.set()
        if self._queue:
            self._queue.close()
        if self._service:
            self._service.close()
        if self._oauth:
            self._oauth.close()
        if self._worker:
            self._worker.join(timeout=2)
        if self._store:
            if self._worker and self._worker.is_alive():
                # An accepted upload may still finish its bounded HTTP request.
                # Retain its database until the worker finishes reconciliation.
                def finish_close():
                    self._worker.join()
                    self._store.close()
                Thread(target=finish_close, name="capture-store-cleanup", daemon=True).start()
            else:
                self._store.close()


def create_router(context: CaptureContext):
    @asynccontextmanager
    async def lifespan(_app):
        yield
        context.close()

    router = APIRouter(prefix="/api/capture", tags=["Dataset capture"], route_class=CaptureRoute,
                       dependencies=[Depends(capture_write_guard)], lifespan=lifespan)

    @router.get("/status")
    def status():
        return context.status()

    @router.get("/devices")
    def devices():
        return {"devices": [{"device_index": index, "name": f"Camera index {index} (unverified)"} for index in range(12)],
                "probed": False, "detail": "Indexes are selectable addresses, not verified physical names. No device was opened for enumeration."}

    @router.post("/camera/start")
    def start_camera(payload: CameraInput):
        context.service.start_camera(**payload.model_dump())
        return context.status()

    @router.post("/camera/stop")
    def stop_camera():
        context.service.stop_camera()
        return context.status()

    @router.get("/preview.jpg")
    def preview():
        image = context.service.preview()
        if image is None:
            raise CaptureError(409, "CAPTURE_CAMERA_CLOSED", "Open the independently owned capture camera first.")
        return Response(image, media_type="image/jpeg")

    @router.post("/sessions", status_code=201)
    def create_session(payload: MetadataInput):
        return context.service.create_session(payload.metadata)

    @router.get("/sessions")
    def sessions(limit: int = Query(default=100, ge=1, le=100)):
        return {"sessions": context.store.list_sessions(limit)}

    @router.post("/sessions/{session_id}/select")
    def select_session(session_id: str):
        context.service.select_session(session_id)
        return context.status()

    @router.patch("/sessions/{session_id}/metadata")
    def update_session(session_id: str, payload: MetadataInput):
        return context.store.update_session(session_id, payload.metadata)

    @router.get("/sessions/{session_id}/items")
    def items(session_id: str, limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
        return context.store.items(session_id, limit, offset)

    @router.patch("/sessions/{session_id}/items")
    def update_items(session_id: str, payload: ItemPatch):
        return context.store.update_items(session_id, payload.item_ids, payload.metadata)

    @router.get("/sessions/{session_id}/items/{item_id}/image")
    def image(session_id: str, item_id: str, thumbnail: bool = False):
        path = context.store.media_path(session_id, item_id, thumbnail)
        return FileResponse(path, media_type="image/png" if path.suffix == ".png" else "image/jpeg")

    @router.get("/sessions/{session_id}/export")
    def export(session_id: str, format: str = Query(default="zip", pattern="^(zip|json|csv)$")):
        path = context.store.export(session_id, format)
        mime = {"zip": "application/zip", "csv": "text/csv", "json": "application/json"}[format]
        return FileResponse(path, filename=path.name, media_type=mime)

    @router.post("/snapshot", status_code=201)
    def snapshot():
        return context.service.snapshot()

    @router.post("/session/start")
    def start_run(payload: RunInput):
        context.service.start_run(**payload.model_dump())
        return context.status()

    @router.post("/session/pause")
    def pause():
        context.service.pause()
        return context.status()

    @router.post("/session/resume")
    def resume():
        context.service.resume()
        return context.status()

    @router.post("/session/stop")
    def stop():
        context.service.stop_run()
        return context.status()

    @router.get("/drive/status")
    def drive_status():
        return context.drive_status()

    @router.post("/drive/connect")
    def connect_drive(request: Request):
        peer = request.client.host if request.client else ""
        if peer not in {"127.0.0.1", "::1", "testclient"}:
            raise CaptureError(403, "LOOPBACK_REQUIRED", "Desktop OAuth consent must start from the capture computer's local browser.")
        if not context.drive_status()["destination_configured"]:
            raise CaptureError(409, "DRIVE_DESTINATION_REQUIRED", "Configure the authorized Drive folder on the server first.")
        return context.oauth.start_authorization()

    @router.post("/drive/test")
    def test_drive(payload: DriveTest):
        context.drive_status()
        client = context._drive_client()
        result = client.test_access()
        context._folder_verified = True
        if payload.write_test:
            import cv2
            import numpy as np
            import hashlib
            image = np.full((32, 32, 3), 190, dtype=np.uint8)
            ok, data = cv2.imencode(".png", image)
            if not ok:
                raise CaptureError(500, "TEST_ENCODING_FAILED", "Connection-test image could not be encoded.")
            identity = "connection-test-" + secrets.token_hex(12)
            path = context.root / "private" / (identity + ".png")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data.tobytes())
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            remote = client.upload_file(path, filename=path.name, folder_id=context.folder_id, idempotency_key=identity,
                                       sha256=digest, metadata={"session_id": identity, "captured_utc": datetime.now(timezone.utc).isoformat()})
            if remote.get("sha256") != digest:
                raise CaptureError(409, "REMOTE_CHECKSUM_UNVERIFIED", "Test media was not checksum-verified; Drive sync remains unconfirmed.")
            result["test_file_id"] = remote["id"]
            result["write_test_verified"] = True
        return result

    @router.patch("/drive/settings")
    def drive_settings(payload: DriveSettings):
        return context.set_auto_sync(payload.auto_sync)

    @router.post("/drive/sync")
    def sync():
        return context.sync()

    @router.post("/drive/retry")
    def retry():
        context.drive_status()
        return context._queue.retry_failed()

    @router.post("/drive/pause")
    def pause_sync():
        context.drive_status()
        context.set_auto_sync(False)
        return context._queue.pause()

    @router.post("/drive/resume")
    def resume_sync():
        context.drive_status()
        return context._queue.resume()

    return router
