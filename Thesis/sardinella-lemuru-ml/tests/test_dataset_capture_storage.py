"""Synthetic source photos stay isolated, durable and auditable."""
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
import zipfile

import cv2
import numpy as np
import pytest

from src.api.dataset_capture.errors import CaptureError
from src.api.dataset_capture.storage import CaptureStore


def frame_metadata(index=1, generation="synthetic-reader"):
    return {"frame_id": index, "generation": generation, "captured_monotonic": float(index),
            "captured_utc": "2026-11-06T00:00:00+00:00", "camera": {"device_index": 0,
            "backend": "synthetic", "readbacks": {"width": 640, "height": 480}}}


def frame(index=1):
    image = np.full((480, 640, 3), 80 + index, dtype=np.uint8)
    image[100:200, 200:300] = (10, 90 + index, 160)
    return image


@pytest.fixture
def store(tmp_path):
    value = CaptureStore(tmp_path / "new-captures", min_free_bytes=0)
    yield value
    value.close()


def test_native_manual_and_automatic_share_durable_saved_queue(store):
    session = store.create_session({"session_name": "synthetic", "provisional_grade": "A"})
    source = frame()
    original_pixels = source.copy()
    first = store.save_frame(session["id"], source, frame_metadata(), "manual")
    second = store.save_frame(session["id"], frame(2), frame_metadata(2), "automatic", 2.0)
    assert first["id"] != second["id"] and first["sequence"] == 1 and second["sequence"] == 2
    assert first["capture_mode"] == "manual" and second["capture_mode"] == "automatic"
    assert first["sync_status"] == second["sync_status"] == "queued"
    assert first["width"] == 640 and first["height"] == 480 and first["jpeg_quality"] == 95
    assert np.array_equal(source, original_pixels)
    saved = store.media_path(session["id"], first["id"])
    assert cv2.imread(str(saved)).shape == source.shape
    assert hashlib.sha256(saved.read_bytes()).hexdigest() == first["sha256"]
    assert store.queue_status()["queued"] == 2


def test_same_camera_frame_is_rejected_but_genuine_same_scene_retained(store):
    session = store.create_session({})["id"]
    first = store.save_frame(session, frame(), frame_metadata(), "manual")
    with pytest.raises(CaptureError, match="already") as caught:
        store.save_frame(session, frame(), frame_metadata(), "manual")
    assert caught.value.status_code == 409
    second = store.save_frame(session, frame(), frame_metadata(2), "manual")
    assert "IDENTICAL_PIXELS_REVIEW" in second["quality"]["warnings"]
    assert second["id"] != first["id"] and store.items(session)["total"] == 2


def test_confirmed_specimens_and_provisional_grade_are_distinct_from_frames(store):
    session = store.create_session({"specimen_id": "fish-1", "specimen_confirmed": True,
                                    "provisional_grade": "B", "source_code": "synthetic"})["id"]
    for index in range(1, 4):
        store.save_frame(session, frame(index), frame_metadata(index), "manual")
    stats = store.stats(session)
    assert stats["raw_frames"] == 3 and stats["unique_specimens_confirmed"] == 1
    assert stats["specimens_per_provisional_grade"]["B"] == 1
    store.update_session(session, {"specimen_confirmed": False})
    store.save_frame(session, frame(4), frame_metadata(4), "manual")
    assert store.stats(session)["unique_specimens_confirmed"] == 1


def test_review_is_non_destructive_and_bulk_metadata_transactional(store):
    session = store.create_session({})["id"]
    image = store.save_frame(session, frame(), frame_metadata(), "manual")
    path = store.media_path(session, image["id"])
    before = path.read_bytes()
    updated = store.update_items(session, [image["id"]], {"review_state": "exclude", "training_state": "exclude"})
    assert updated["updated"] == 1 and store.stats(session)["reviewed_photos"] == 1
    assert path.read_bytes() == before
    with pytest.raises(CaptureError):
        store.update_items(session, [image["id"], "a" * 32], {"notes": "must not partially apply"})
    assert store.item(session, image["id"])["metadata"].get("notes") is None


@pytest.mark.parametrize("patch", [{"provisional_grade": "Expert A"}, {"review_state": "delete"},
                                    {"specimen_confirmed": "yes"}, {"credentials": "secret"},
                                    {"review_thresholds": {"focus_min": float("nan")}}, {"consent": "yes"}])
def test_invalid_metadata_is_rejected_without_creating_sessions(store, patch):
    with pytest.raises(CaptureError):
        store.create_session(patch)
    assert store.list_sessions() == []


def test_consent_is_explicit_boolean_and_last_saved_timestamp_is_persistent(store):
    session = store.create_session({"consent": True})["id"]
    assert store.session(session)["metadata"]["consent"] is True
    assert store.stats(session)["last_capture_utc"] is None
    image = store.save_frame(session, frame(), frame_metadata(), "manual")
    assert store.stats(session)["last_capture_utc"] == image["captured_utc"]


def test_paths_are_id_derived_and_thumbnails_do_not_change_originals(store):
    session = store.create_session({})["id"]
    image = store.save_frame(session, frame(), frame_metadata(), "manual")
    original = store.media_path(session, image["id"])
    checksum = hashlib.sha256(original.read_bytes()).hexdigest()
    thumb = store.media_path(session, image["id"], thumbnail=True)
    assert max(cv2.imread(str(thumb)).shape[:2]) <= 320
    assert hashlib.sha256(original.read_bytes()).hexdigest() == checksum
    with pytest.raises(CaptureError):
        store.media_path("../outside", image["id"])
    with pytest.raises(CaptureError):
        store.media_path(session, "../outside")


def test_exports_preserve_originals_and_provenance_without_excel_formulas(store):
    session = store.create_session({"notes": "=HYPERLINK(synthetic)", "provisional_grade": "Unknown"})["id"]
    image = store.save_frame(session, frame(), frame_metadata(), "manual")
    original = store.media_path(session, image["id"]).read_bytes()
    manifest = json.loads(store.export(session, "json").read_text(encoding="utf-8"))
    assert manifest["items"][0]["sha256"] == image["sha256"]
    with store.export(session, "csv").open(encoding="utf-8", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["capture_mode"] == "manual" and row["metadata"].startswith("{")
    with zipfile.ZipFile(store.export(session, "zip")) as archive:
        assert {"manifest.json", "manifest.csv"} <= set(archive.namelist())
        assert archive.read("raw/" + image["filename"]) == original
        assert all(".." not in name for name in archive.namelist())


def test_count_and_disk_limits_do_not_falsely_save(store, monkeypatch):
    session = store.create_session({})["id"]
    store.max_items = 1
    store.save_frame(session, frame(), frame_metadata(), "manual")
    with pytest.raises(CaptureError) as caught:
        store.save_frame(session, frame(2), frame_metadata(2), "manual")
    assert caught.value.code == "ITEM_LIMIT"
    store.max_items = 10
    monkeypatch.setattr("src.api.dataset_capture.storage.shutil.disk_usage", lambda _: type("Disk", (), {"free": 0})())
    with pytest.raises(CaptureError) as caught:
        store.save_frame(session, frame(2), frame_metadata(2), "manual")
    assert caught.value.code == "STORAGE_LIMIT" and store.items(session)["total"] == 1


def test_restart_recovers_published_image_before_queue_commit_and_preserves_partial(tmp_path, monkeypatch):
    root = tmp_path / "independent"
    store = CaptureStore(root, min_free_bytes=0)
    session = store.create_session({})["id"]
    real_finish = store._finish_save
    monkeypatch.setattr(store, "_finish_save", lambda _: (_ for _ in ()).throw(OSError("synthetic crash")))
    with pytest.raises(CaptureError):
        store.save_frame(session, frame(), frame_metadata(), "manual")
    assert store.queue_status()["queued"] == 0
    store.close()
    restarted = CaptureStore(root, min_free_bytes=0)
    assert len(restarted.recovery["recovered"]) == 1
    assert restarted.queue_status()["queued"] == 1
    assert restarted.items(session)["items"][0]["local_status"] == "saved"
    monkeypatch.setattr("src.api.dataset_capture.storage.os.link", lambda *_: (_ for _ in ()).throw(OSError("disk failure")))
    with pytest.raises(CaptureError):
        restarted.save_frame(session, frame(2), frame_metadata(2), "manual")
    assert list(root.glob("*/raw/*.pending"))
    restarted.close()
    again = CaptureStore(root, min_free_bytes=0)
    assert again.recovery["interrupted"] and list(root.glob("*/raw/*.pending"))
    assert again.stats(session)["raw_frames"] == 1
    again.close()


def test_missing_or_modified_original_is_failed_and_not_uploaded_after_restart(tmp_path):
    root = tmp_path / "capture"
    store = CaptureStore(root, min_free_bytes=0)
    session = store.create_session({})["id"]
    image = store.save_frame(session, frame(), frame_metadata(), "manual")
    store.media_path(session, image["id"]).write_bytes(b"synthetic corruption")
    store.close()
    reopened = CaptureStore(root, min_free_bytes=0)
    assert reopened.queue_status()["failed"] == 1
    assert reopened.item(session, image["id"])["local_status"] == "missing_or_changed"
    assert reopened.claim_upload(0) is None
    reopened.close()


def test_two_store_instances_allocate_distinct_sequences_and_claim_one_job(tmp_path):
    root = tmp_path / "capture"
    one, two = CaptureStore(root, min_free_bytes=0), CaptureStore(root, min_free_bytes=0)
    session = one.create_session({})["id"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(store.save_frame, session, frame(i), frame_metadata(i), "manual")
                   for i, store in enumerate((one, two), 1)]
        images = [future.result() for future in futures]
    assert {i["sequence"] for i in images} == {1, 2}
    job_one, job_two = one.claim_upload(100), two.claim_upload(100)
    assert job_one["image_id"] != job_two["image_id"]
    assert two.claim_upload(100) is None
    one.close()
    two.close()


def test_real_store_service_and_queue_share_manual_and_scheduled_pipeline(store):
    from src.api.dataset_capture.drive_queue import DriveSyncQueue
    from src.api.dataset_capture.service import DatasetCaptureService
    from test_dataset_capture_service import Clock, Source
    clock = Clock()
    source = Source(clock, 1)
    service = DatasetCaptureService(store, lambda **_: source, clock, background=False)
    session = service.create_session({"consent": True})["id"]
    try:
        service.start_camera()
        first, second = service.snapshot(), service.snapshot()
        assert first["id"] != second["id"] and service.status()["run"]["state"] == "idle"
        service.start_run(target_count=2)
        service.snapshot()  # Due automatic shot is serialized before this manual shot.
        clock.advance(1)
        service.tick()
        assert store.stats(session)["manual_photos"] == 3
        assert store.stats(session)["automatic_photos"] == 2
        assert store.queue_status()["queued"] == 5
        class Transport:
            def find_file(self, key, folder):
                return None
            def upload_file(self, path, **values):
                assert values["metadata"]["session_id"] == session
                return {"id": "verified-" + values["idempotency_key"], "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        queue = DriveSyncQueue(store, Transport(), "synthetic_authorized_folder")
        assert queue.sync_now()["synced"] == 5
        assert {item["sync_status"] for item in store.items(session)["items"]} == {"synced"}
    finally:
        service.close()
