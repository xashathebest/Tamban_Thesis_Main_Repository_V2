"""Independent acquisition contracts with a deterministic clock and fake frames."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from src.api.dataset_capture.camera_source import FramePacket, ProcessCameraSource
from src.api.dataset_capture.errors import CaptureError
from src.api.dataset_capture.service import DatasetCaptureService


class Clock:
    def __init__(self):
        self.now = 100.

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Store:
    def __init__(self):
        self.sessions = {}
        self.photos = []
        self.fail_save = False

    def create_session(self, metadata):
        result = {"id": f"session-{len(self.sessions) + 1}", "metadata": metadata}
        self.sessions[result["id"]] = result
        return result

    def session(self, session_id):
        if session_id not in self.sessions:
            raise CaptureError(404, "SESSION_NOT_FOUND", "Capture session does not exist.")
        return self.sessions[session_id]

    def stats(self, session_id=None):
        return {"raw_frames": sum(1 for photo in self.photos if session_id is None or photo["session_id"] == session_id)}

    def save_frame(self, session_id, frame, frame_metadata, capture_mode, scheduled_monotonic=None):
        if self.fail_save:
            raise OSError("synthetic disk full")
        item = {"id": f"photo-{len(self.photos) + 1}", "session_id": session_id,
                "capture_mode": capture_mode, "metadata": deepcopy(frame_metadata),
                "scheduled_monotonic": scheduled_monotonic, "sync_status": "queued",
                "local_status": "saved", "pixels": frame.copy()}
        self.photos.append(item)
        return item


class Source:
    def __init__(self, clock, number):
        self.clock = clock
        self.number = number
        self.generation = f"generation-{number}"
        self.frame_id = 0
        self.closed = False
        self.error = None
        self.stale = False
        self.read_delay = 0.

    def start(self):
        return {"backend": "synthetic", "width": 8, "height": 8}

    def read(self):
        if self.error:
            raise self.error
        if not self.stale:
            self.frame_id += 1
        self.clock.advance(self.read_delay)
        return FramePacket(np.full((8, 8, 3), self.frame_id % 255, dtype=np.uint8),
                           self.frame_id, self.clock(), self.generation,
                           captured_utc="2026-11-05T12:00:00+00:00")

    def close(self):
        self.closed = True


@pytest.fixture
def rig():
    clock, store, sources = Clock(), Store(), []

    def factory(**config):
        source = Source(clock, len(sources) + 1)
        sources.append(source)
        return source

    service = DatasetCaptureService(store, factory, clock, background=False)
    service.create_session({"provisional_grade": "Unknown"})
    service.start_camera()
    yield service, clock, store, sources
    service.close()


def test_manual_only_one_click_saves_one_fresh_native_frame_and_queues(rig):
    service, _, store, sources = rig
    first = service.snapshot()
    second = service.snapshot()
    assert len(sources) == 1 and len(store.photos) == 2
    assert first["id"] != second["id"]
    assert [p["metadata"]["frame_id"] for p in store.photos] == [1, 2]
    assert all(p["capture_mode"] == "manual" and p["sync_status"] == "queued" for p in store.photos)
    assert all(p["pixels"].shape == (8, 8, 3) for p in store.photos)
    assert not np.array_equal(first["pixels"], second["pixels"])
    assert service.status()["manual_count"] == 2
    assert service.status()["run"]["state"] == "idle"
    assert not service.status()["drive"]["connected"]


def test_hardware_isolation_refuses_before_constructing_any_driver(monkeypatch):
    import src.api.dataset_capture.service as module
    calls = []
    monkeypatch.setattr(module, "ProcessCameraSource", lambda **kwargs: calls.append(kwargs))
    service = DatasetCaptureService(Store(), background=False)
    with pytest.raises(CaptureError) as raised:
        service.start_camera()
    assert raised.value.status_code == 409
    assert raised.value.code == "PHYSICAL_ISOLATION_REQUIRED"
    assert calls == []
    assert not service.status()["manual_available"]
    service.close()


def test_second_start_refuses_without_second_handle_or_stopping_existing_camera(rig):
    service, _, _, sources = rig
    with pytest.raises(CaptureError) as raised:
        service.start_camera(device_index=1)
    assert raised.value.status_code == 409
    assert len(sources) == 1 and not sources[0].closed
    assert service.status()["manual_available"]


def test_stale_reader_packet_never_creates_a_second_file(rig):
    service, _, store, sources = rig
    service.snapshot()
    sources[0].stale = True
    with pytest.raises(CaptureError, match="old or duplicate"):
        service.snapshot()
    assert len(store.photos) == 1
    assert service.status()["manual_count"] == 1


def test_older_timestamp_is_rejected_even_with_a_new_frame_id(rig):
    service, clock, store, sources = rig
    original = sources[0].read
    def old_frame():
        packet = original()
        packet.captured_monotonic = clock() - 2
        return packet
    sources[0].read = old_frame
    with pytest.raises(CaptureError) as raised:
        service.snapshot()
    assert raised.value.code == "STALE_FRAME"
    assert store.photos == []


def test_preview_and_parallel_manual_requests_keep_one_reader_and_distinct_frames(rig):
    service, _, store, sources = rig
    assert service.preview().startswith(b"\xff\xd8")
    assert store.photos == []
    with ThreadPoolExecutor(max_workers=4) as pool:
        photos = list(pool.map(lambda _: service.snapshot(), range(8)))
    assert len(sources) == 1
    assert len(photos) == len(store.photos) == 8
    assert sorted(p["metadata"]["frame_id"] for p in photos) == list(range(2, 10))
    assert all(p["capture_mode"] == "manual" for p in photos)


def test_disconnect_releases_and_restart_uses_a_new_generation(rig):
    service, _, store, sources = rig
    service.snapshot()
    sources[0].error = CaptureError(503, "CAMERA_DISCONNECTED", "Synthetic disconnect")
    with pytest.raises(CaptureError):
        service.snapshot()
    assert sources[0].closed and not service.status()["manual_available"]
    assert service.preview() is None
    service.start_camera()
    service.snapshot()
    assert [p["metadata"]["generation"] for p in store.photos] == ["generation-1", "generation-2"]


def test_disk_full_never_counts_or_reports_a_successful_manual_photo(rig):
    service, _, store, _ = rig
    store.fail_save = True
    with pytest.raises(CaptureError) as raised:
        service.snapshot()
    assert raised.value.status_code == 507
    assert store.photos == [] and service.status()["manual_count"] == 0
    assert service.status()["last_error"]["code"] == "LOCAL_SAVE_FAILED"


def test_failed_start_releases_only_its_new_source():
    clock, source = Clock(), Source(Clock(), 1)
    def start():
        raise CaptureError(409, "CAMERA_UNAVAILABLE", "Camera in use")
    source.start = start
    service = DatasetCaptureService(Store(), lambda **kwargs: source, clock, background=False)
    with pytest.raises(CaptureError, match="Camera in use"):
        service.start_camera()
    assert source.closed and not service.status()["manual_available"]
    service.close()


def test_failed_release_latches_refusal_instead_of_opening_a_competing_handle():
    clock, sources = Clock(), []
    def factory(**kwargs):
        source = Source(clock, len(sources) + 1)
        sources.append(source)
        return source
    service = DatasetCaptureService(Store(), factory, clock, background=False)
    service.start_camera()
    def failed_close():
        raise RuntimeError("synthetic stuck worker")
    sources[0].close = failed_close
    with pytest.raises(CaptureError) as raised:
        service.stop_camera()
    assert raised.value.code == "CAMERA_RELEASE_FAILED"
    with pytest.raises(CaptureError):
        service.start_camera()
    assert len(sources) == 1
    sources[0].close = lambda: None
    service.close()


def test_process_source_forces_release_when_native_reader_is_unresponsive():
    class Process:
        alive = True
        waits = []
        terminated = False
        def join(self, timeout):
            self.waits.append(timeout)
        def is_alive(self):
            return self.alive
        def terminate(self):
            self.terminated = True
            self.alive = False
    class Connection:
        closed = False
        def send(self, value):
            pass
        def close(self):
            self.closed = True
    source = ProcessCameraSource(device_index=0, width=1920, height=1080, backend="default")
    process, connection = Process(), Connection()
    source._process, source._connection = process, connection
    source.close()
    assert process.terminated and connection.closed
    assert sum(process.waits) <= 1.


def test_real_store_manual_and_automatic_share_durable_queue_and_persistent_counter(tmp_path):
    from src.api.dataset_capture.storage import CaptureStore
    clock = Clock()
    store = CaptureStore(tmp_path / "capture-only", min_free_bytes=0)
    service = DatasetCaptureService(store, lambda **kwargs: Source(clock, 1), clock, background=False)
    try:
        session = service.create_session({"specimen_id": "specimen-1", "specimen_confirmed": True})
        service.start_camera()
        manual = service.snapshot()
        service.start_run(target_count=1)
        service.tick()
        service.select_session(session["id"])
        stats = service.status()
        assert stats["manual_count"] == 1
        assert stats["stats"]["raw_frames"] == 2
        assert stats["stats"]["automatic_photos"] == 1
        assert stats["stats"]["unique_specimens_confirmed"] == 1
        assert stats["stats"]["sync"]["queued"] == 2
        assert manual["sync_status"] == "queued"
        assert manual["local_status"] == "saved"
    finally:
        service.close()
        store.close()


def test_capture_package_and_service_do_not_import_inspection_modules():
    from pathlib import Path
    root = Path(__file__).parents[1] / "src" / "api" / "dataset_capture"
    for name in ("__init__.py", "service.py", "camera_source.py", "ownership.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "from src.api.camera" not in text
        assert "from src.api.app" not in text
        assert "from src.inference" not in text

