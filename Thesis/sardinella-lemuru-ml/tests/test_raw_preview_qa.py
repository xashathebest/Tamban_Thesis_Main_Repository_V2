"""Model-free checks of the optional raw preview and its stream lifecycle."""
from threading import Event, Thread
from time import monotonic, sleep
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi import HTTPException

from src.api.raw_preview import RawPreview


def wait_frame(preview, previous=0):
    deadline = monotonic() + 2
    while monotonic() < deadline:
        jpeg, version = preview.frame()
        if jpeg is not None and version > previous:
            return jpeg, version
        sleep(.01)
    raise AssertionError("preview frame was not published")


def test_disabled_or_unsubscribed_never_buffers():
    for enabled in (False, True):
        preview = RawPreview(enabled)
        preview.offer(np.zeros((10, 10, 3), dtype=np.uint8), monotonic())
        assert preview._queue.snapshot()["depth"] == 0
        assert preview.frame() == (None, 0)


def test_shared_encoder_copies_raw_frames_clears_and_restarts():
    preview, stop = RawPreview(True), Event()
    preview.subscribe()
    preview.subscribe()
    preview.start(stop, cv2)
    try:
        frame = np.zeros((20, 20, 3), dtype=np.uint8)
        preview.offer(frame, monotonic())
        frame[:] = 255  # Simulate a later in-place inference overlay.
        jpeg, version = wait_frame(preview)
        decoded = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert np.max(decoded) == 0
        preview.unsubscribe()
        assert preview.frame()[0] == jpeg  # One subscriber remains.
        preview.unsubscribe()
        assert preview.frame()[0] is None
    finally:
        stop.set()
        preview.finish()
    stop.clear()
    preview.subscribe()
    preview.start(stop, cv2)
    try:
        assert preview.frame()[0] is None
        preview.offer(np.full((20, 20, 3), 100, dtype=np.uint8), monotonic())
        _, newer = wait_frame(preview, version)
        assert newer > version
    finally:
        stop.set()
        preview.finish()
        preview.unsubscribe()


def test_backpressure_keeps_only_latest_frame():
    preview = RawPreview(True, max_fps=1000)
    preview.subscribe()
    preview.offer(np.zeros((2, 2, 3), dtype=np.uint8), 1.0)
    preview.offer(np.ones((2, 2, 3), dtype=np.uint8), 2.0)
    assert preview._queue.snapshot()["depth"] == 1
    assert preview._queue.snapshot()["dropped_frames"] == 1
    assert np.all(preview._queue.take(timeout=0).frame[1] == 1)
    preview.unsubscribe()


def test_preview_advances_while_inference_queue_is_not_consumed():
    from src.api.camera import CameraInspectionService
    from src.api.domain import InspectionState, TrackingConfig

    class Capture:
        def __init__(self):
            self.count = 0

        def read(self):
            sleep(.08)
            self.count += 1
            return True, np.full((8, 8, 3), self.count, dtype=np.uint8)

    service = CameraInspectionService(InspectionState(TrackingConfig()), SimpleNamespace())
    service.raw_preview = RawPreview(True)
    service.raw_preview.subscribe()
    service.raw_preview.start(service._stop_event, cv2)
    capture = Thread(target=service._capture_frames, args=(Capture(),))
    capture.start()
    try:
        _, first = wait_frame(service.raw_preview)
        _, second = wait_frame(service.raw_preview, first)
        assert second > first
        assert service._latest_frames.snapshot()["depth"] == 1
        assert service._latest_frames.snapshot()["dropped_frames"] >= 1
    finally:
        service._stop_event.set()
        capture.join(timeout=2)
        service.raw_preview.finish()
        service.raw_preview.unsubscribe()
    assert not capture.is_alive()


def test_disconnect_discards_encoder_output_from_old_subscription():
    started, release, stop = Event(), Event(), Event()
    class SlowEncoder:
        IMWRITE_JPEG_QUALITY = cv2.IMWRITE_JPEG_QUALITY

        @staticmethod
        def imencode(*args):
            started.set()
            assert release.wait(2)
            return cv2.imencode(*args)

    preview = RawPreview(True)
    preview.subscribe()
    preview.start(stop, SlowEncoder)
    try:
        preview.offer(np.zeros((4, 4, 3), dtype=np.uint8), monotonic())
        assert started.wait(2)
        preview.unsubscribe()
        preview.subscribe()
        release.set()
        sleep(.1)
        assert preview.frame()[0] is None
        preview.offer(np.ones((4, 4, 3), dtype=np.uint8), monotonic())
        wait_frame(preview)
    finally:
        release.set()
        stop.set()
        preview.finish()
        preview.unsubscribe()


def test_repeated_preview_start_stop_joins_worker():
    preview = RawPreview(True)
    for _ in range(20):
        stop = Event()
        preview.subscribe()
        preview.start(stop, cv2)
        worker = preview._thread
        stop.set()
        preview.finish()
        preview.unsubscribe()
        assert worker is not None and not worker.is_alive()
        assert preview._thread is None and preview.frame()[0] is None


def test_closed_stream_unsubscribes_and_revocation_stops(monkeypatch):
    import asyncio
    import src.api.app as api

    preview = RawPreview(True)
    stop = Event()
    preview.start(stop, cv2)
    monkeypatch.setattr(api, "service", SimpleNamespace(raw_preview=preview))
    authorized = [True]
    monkeypatch.setattr(api.lan_security, "stream_authorized", lambda request: authorized[0])
    async def exercise():
        stream = api._raw_mjpeg_frames(None)
        # Generator subscribes when first iterated; publish from its polling callback.
        original_sleep = asyncio.sleep
        async def publish(_delay):
            preview.offer(np.zeros((4, 4, 3), dtype=np.uint8), monotonic())
            await original_sleep(.02)
        with monkeypatch.context() as patch:
            patch.setattr(api.asyncio, "sleep", publish)
            try:
                assert (await anext(stream)).startswith(b"--frame\r\n")
                assert preview._subscribers == 1
                authorized[0] = False
                with pytest.raises(StopAsyncIteration):
                    await anext(stream)
                assert preview._subscribers == 0
            finally:
                await stream.aclose()
    try:
        asyncio.run(exercise())
    finally:
        stop.set()
        preview.finish()


def test_idle_stream_can_be_cancelled_without_waiting_for_a_frame(monkeypatch):
    import asyncio
    import src.api.app as api

    monkeypatch.setattr(api.lan_security, "stream_authorized", lambda request: True)
    monkeypatch.setattr(api, "state", SimpleNamespace(frame=lambda: (None, 0), inspection_status="running"))

    async def exercise():
        stream = api._mjpeg_frames(None)
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(.05)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, timeout=1)
        await stream.aclose()

    asyncio.run(exercise())


def test_disabled_route_returns_404(monkeypatch):
    import src.api.app as api
    monkeypatch.setattr(api, "service", SimpleNamespace(raw_preview=RawPreview(False)))
    with pytest.raises(HTTPException) as exc:
        api.raw_video_feed(None)
    assert exc.value.status_code == 404
