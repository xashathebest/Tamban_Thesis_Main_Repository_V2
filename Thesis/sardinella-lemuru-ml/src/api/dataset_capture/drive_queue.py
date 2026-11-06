"""Durable, idempotent Drive sync via an injected server-side transport.

The queue does not implement OAuth, discover accounts or make network calls.
Without an authorized transport and destination it preserves queued local files.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from typing import Protocol

from .errors import CaptureError


class DriveTransport(Protocol):
    def find_file(self, idempotency_key: str, folder_id: str) -> dict | None: ...

    def upload_file(self, path, *, filename: str, folder_id: str,
                    idempotency_key: str, sha256: str, metadata: dict) -> dict: ...


class DriveSyncQueue:
    def __init__(self, store, client: DriveTransport | None = None,
                 destination_id: str | None = None, *, clock=time.time,
                 max_attempts: int = 5, lease_seconds: float = 120):
        if destination_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", destination_id):
            raise CaptureError(422, "INVALID_DRIVE_FOLDER", "Invalid authorized Drive folder identifier.")
        if max_attempts < 1 or lease_seconds < 1:
            raise ValueError("Queue attempts and lease must be positive.")
        self.store, self.client, self.destination_id = store, client, destination_id
        self.clock, self.max_attempts, self.lease_seconds = clock, max_attempts, lease_seconds
        self._lock = threading.Lock()
        self._paused = False
        self._closed = False

    def status(self) -> dict:
        connected = self.client is not None and self.destination_id is not None
        return {"connected": connected, "paused": self._paused,
                "state": "Paused" if self._paused else "Connected" if connected else "Drive not connected",
                "auto_sync": False, "queue": self.store.queue_status(),
                "warning": "Queued photos are saved locally; only verified remote files are synced."}

    def pause(self):
        self._paused = True
        return self.status()

    def resume(self):
        self._paused = False
        return self.status()

    def retry_failed(self):
        return {"retried": self.store.retry_failed(), **self.status()}

    def sync_now(self, limit: int = 25) -> dict:
        if not self.client or not self.destination_id:
            raise CaptureError(409, "DRIVE_NOT_CONNECTED", "Drive is not connected; local photos remain queued.")
        if self._closed or self._paused:
            return {"processed": 0, "synced": 0, "failed": 0, "paused": True}
        if not self._lock.acquire(blocking=False):
            return {"processed": 0, "synced": 0, "failed": 0, "busy": True}
        result = {"processed": 0, "synced": 0, "failed": 0, "queued_for_retry": 0}
        try:
            for _ in range(max(1, min(int(limit), 100))):
                if self._paused or self._closed:
                    break
                job = self.store.claim_upload(self.clock(), self.lease_seconds)
                if not job:
                    break
                result["processed"] += 1
                item = job["item"]
                heartbeat_stop = threading.Event()
                lease_lost = threading.Event()
                def heartbeat(image_id=item["id"], lease_id=job["lease_id"], stop=heartbeat_stop, lost=lease_lost):
                    while not stop.wait(min(30.0, self.lease_seconds / 3.0)):
                        try:
                            if not self.store.renew_upload(image_id, lease_id, self.clock(), self.lease_seconds):
                                lost.set()
                                return
                        except Exception:
                            lost.set()
                            return
                lease_thread = threading.Thread(target=heartbeat, name="capture-upload-lease", daemon=True)
                lease_thread.start()
                try:
                    path = self.store.media_path(item["session_id"], item["id"])
                    digest = hashlib.sha256()
                    with path.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != item["sha256"]:
                        raise CaptureError(409, "CHECKSUM_MISMATCH", "The saved original changed; upload refused.")
                    # A previously successful remote upload may outlive a lost local response.
                    remote = self.client.find_file(job["idempotency_key"], self.destination_id)
                    if remote is None:
                        if lease_lost.is_set():
                            raise CaptureError(409, "UPLOAD_LEASE_LOST", "Upload ownership was lost before remote creation.")
                        remote = self.client.upload_file(path, filename=item["filename"],
                            folder_id=self.destination_id, idempotency_key=job["idempotency_key"],
                            sha256=item["sha256"], metadata={"capture_session_id": item["session_id"],
                                "session_id": item["session_id"], "captured_utc": item["captured_utc"],
                                "capture_image_id": item["id"], "capture_mode": item["capture_mode"]})
                    if not isinstance(remote, dict) or not isinstance(remote.get("id"), str) or not remote["id"]:
                        raise CaptureError(502, "INVALID_DRIVE_RESPONSE", "Drive did not confirm a remote file identifier.")
                    if remote.get("sha256", remote.get("sha256Checksum")) != item["sha256"]:
                        raise CaptureError(409, "REMOTE_CHECKSUM_UNVERIFIED", "Remote checksum was missing or differed; sync remains unconfirmed.")
                    if self.store.complete_upload(item["id"], job["lease_id"], remote["id"]):
                        result["synced"] += 1
                except Exception as error:
                    status = getattr(error, "status_code", getattr(error, "status", None))
                    code = getattr(error, "code", None)
                    if not isinstance(code, str):
                        code = f"HTTP_{status}" if status else "DRIVE_UNAVAILABLE"
                    retryable = (status == 429 or (isinstance(status, int) and status >= 500)
                                 or isinstance(error, (OSError, TimeoutError, ConnectionError)))
                    if isinstance(error, CaptureError) and error.code in {
                            "REMOTE_CHECKSUM_UNVERIFIED", "CHECKSUM_MISMATCH", "ORIGINAL_UNAVAILABLE"}:
                        retryable = False
                    if status in {401, 403}:
                        retryable = False
                    retry_at = None
                    if retryable and job["attempts"] < self.max_attempts:
                        try:
                            retry_after = max(0.0, float(getattr(error, "retry_after", 0) or 0))
                        except (ValueError, TypeError, OverflowError):
                            retry_after = 0.0
                        retry_at = self.clock() + min(300, max(2 ** job["attempts"], retry_after))
                    self.store.fail_upload(item["id"], job["lease_id"], code, retry_at)
                    result["queued_for_retry" if retry_at is not None else "failed"] += 1
                finally:
                    heartbeat_stop.set()
                    lease_thread.join(timeout=2)
            return result
        finally:
            self._lock.release()

    def close(self):
        self._closed = True
        self._paused = True
