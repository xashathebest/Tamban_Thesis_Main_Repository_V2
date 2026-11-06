from concurrent.futures import ThreadPoolExecutor
import threading

import numpy as np
import pytest

from src.api.dataset_capture.drive_queue import DriveSyncQueue
from src.api.dataset_capture.errors import CaptureError
from src.api.dataset_capture.storage import CaptureStore


class FakeDrive:
    def __init__(self):
        self.files = {}
        self.uploads = 0
        self.failures = []
        self.lose_first_response = False

    def find_file(self, idempotency_key, folder_id):
        if self.failures:
            raise self.failures.pop(0)
        return self.files.get(idempotency_key)

    def upload_file(self, path, **values):
        self.uploads += 1
        result = {"id": "remote-" + values["idempotency_key"], "sha256": values["sha256"]}
        self.files[values["idempotency_key"]] = result
        if self.lose_first_response:
            self.lose_first_response = False
            raise ConnectionError("synthetic response loss")
        return result


@pytest.fixture
def capture(tmp_path):
    store = CaptureStore(tmp_path / "capture", min_free_bytes=0)
    session = store.create_session({})["id"]
    for index, mode in enumerate(("manual", "automatic"), 1):
        store.save_frame(session, np.full((480, 640, 3), 60 + index, np.uint8),
                         {"frame_id": index, "generation": "synthetic", "captured_monotonic": index,
                          "captured_utc": "2026-11-06T00:00:00+00:00"}, mode)
    yield store, session
    store.close()


def test_disconnected_keeps_both_modes_locally_queued(capture):
    store, _ = capture
    queue = DriveSyncQueue(store)
    assert not queue.status()["connected"] and queue.status()["queue"]["queued"] == 2
    with pytest.raises(CaptureError, match="not connected"):
        queue.sync_now()
    assert store.queue_status()["synced"] == 0


def test_both_modes_use_one_verified_mapping_and_never_duplicate(capture):
    store, session = capture
    drive = FakeDrive()
    queue = DriveSyncQueue(store, drive, "authorized_synthetic_folder")
    assert queue.sync_now()["synced"] == 2
    assert queue.sync_now()["processed"] == 0 and drive.uploads == 2
    assert {i["sync_status"] for i in store.items(session)["items"]} == {"synced"}
    assert all(i["drive_file_id"] for i in store.items(session)["items"])


def test_lost_response_retry_finds_remote_and_prevents_duplicate(capture):
    store, _ = capture
    now = [100.0]
    drive = FakeDrive()
    drive.lose_first_response = True
    queue = DriveSyncQueue(store, drive, "authorized_synthetic_folder", clock=lambda: now[0])
    result = queue.sync_now(limit=1)
    assert result["queued_for_retry"] == 1 and drive.uploads == 1
    assert queue.sync_now(limit=1)["synced"] == 1  # Other image can progress during backoff.
    now[0] = 103
    assert queue.sync_now()["synced"] == 1 and drive.uploads == 2
    assert store.queue_status()["synced"] == 2


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_http_errors_back_off_and_are_bounded(capture, status):
    store, _ = capture
    drive, now = FakeDrive(), [100.0]
    drive.failures = [CaptureError(status, "TRANSIENT", "synthetic") for _ in range(10)]
    queue = DriveSyncQueue(store, drive, "authorized_synthetic_folder", clock=lambda: now[0], max_attempts=2)
    assert queue.sync_now()["queued_for_retry"] == 2
    assert queue.sync_now()["processed"] == 0
    now[0] = 103
    assert queue.sync_now()["failed"] == 2
    now[0] = 1000
    assert queue.sync_now()["processed"] == 0 and store.queue_status()["failed"] == 2


@pytest.mark.parametrize("status", [401, 403])
def test_auth_and_permission_failures_require_operator_retry(capture, status):
    store, _ = capture
    drive = FakeDrive()
    drive.failures = [CaptureError(status, "AUTH_REQUIRED", "synthetic") for _ in range(2)]
    queue = DriveSyncQueue(store, drive, "authorized_synthetic_folder")
    assert queue.sync_now()["failed"] == 2 and store.queue_status()["failed"] == 2
    assert queue.retry_failed()["retried"] == 2
    assert queue.sync_now()["synced"] == 2


@pytest.mark.parametrize("checksum", [None, "0" * 64])
def test_mismatched_or_missing_remote_checksum_is_not_synced(capture, checksum):
    store, _ = capture
    drive = FakeDrive()
    drive.upload_file = lambda *args, **kwargs: {"id": "remote-with-unverified-checksum", "sha256": checksum}
    queue = DriveSyncQueue(store, drive, "authorized_synthetic_folder")
    assert queue.sync_now()["failed"] == 2
    assert store.queue_status()["synced"] == 0


def test_retry_after_is_respected_and_bounded(capture):
    store, _ = capture
    drive = FakeDrive()
    error = CaptureError(429, "THROTTLED", "synthetic")
    error.retry_after = 1000
    drive.failures = [error, error]
    queue = DriveSyncQueue(store, drive, "authorized_synthetic_folder", clock=lambda: 100)
    assert queue.sync_now()["queued_for_retry"] == 2
    next_times = store._connection.execute("SELECT next_attempt FROM capture_sync_queue").fetchall()
    assert [row[0] for row in next_times] == [400, 400]


def test_offline_outage_preserves_queue_and_upload_metadata_has_utc_lineage(capture):
    store, session = capture
    drive, now = FakeDrive(), [100.0]
    drive.failures = [ConnectionError("offline"), ConnectionError("offline")]
    queue = DriveSyncQueue(store, drive, "authorized_synthetic_folder", clock=lambda: now[0])
    assert queue.sync_now()["queued_for_retry"] == 2 and drive.uploads == 0
    original_upload = drive.upload_file
    seen = []
    def upload(path, **values):
        seen.append(values["metadata"])
        return original_upload(path, **values)
    drive.upload_file = upload
    now[0] = 103
    assert queue.sync_now()["synced"] == 2
    assert all(value["session_id"] == session and value["captured_utc"].endswith("+00:00") for value in seen)


def test_local_checksum_mismatch_never_reaches_drive(capture):
    store, session = capture
    item = store.items(session)["items"][0]
    store.media_path(session, item["id"]).write_bytes(b"synthetic corruption")
    drive = FakeDrive()
    queue = DriveSyncQueue(store, drive, "authorized_synthetic_folder")
    assert queue.sync_now()["failed"] == 1 and drive.uploads == 1


def test_unexpired_claim_survives_second_store_and_expired_claim_reconciles(capture):
    store, session = capture
    first = store.claim_upload(100, 10)
    second_store = CaptureStore(store.root, min_free_bytes=0)
    next_job = second_store.claim_upload(100, 10)
    assert first["image_id"] != next_job["image_id"]
    assert second_store.claim_upload(105) is None
    reclaimed = second_store.claim_upload(111)
    assert reclaimed["image_id"] == first["image_id"]
    assert not store.complete_upload(first["image_id"], first["lease_id"], "stale-owner")
    assert not store.renew_upload(first["image_id"], first["lease_id"], 111, 10)
    assert second_store.renew_upload(reclaimed["image_id"], reclaimed["lease_id"], 111, 30)
    second_store.close()


def test_pause_cancel_and_invalid_folder(capture):
    store, _ = capture
    drive = FakeDrive()
    with pytest.raises(CaptureError):
        DriveSyncQueue(store, drive, "../../outside")
    queue = DriveSyncQueue(store, drive, "authorized_synthetic_folder")
    queue.pause()
    assert queue.sync_now()["processed"] == 0
    queue.resume()
    queue.close()
    assert queue.sync_now()["processed"] == 0 and drive.uploads == 0


def test_pause_during_upload_finishes_current_mapping_and_preserves_remaining(capture):
    store, _ = capture
    drive = FakeDrive()
    queue = DriveSyncQueue(store, drive, "authorized_synthetic_folder")
    original_upload = drive.upload_file
    def upload(path, **values):
        queue.pause()
        return original_upload(path, **values)
    drive.upload_file = upload
    assert queue.sync_now()["synced"] == 1
    assert store.queue_status()["queued"] == 1 and store.queue_status()["synced"] == 1
