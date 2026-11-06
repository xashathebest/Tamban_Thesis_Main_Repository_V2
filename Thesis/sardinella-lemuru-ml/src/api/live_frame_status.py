"""Small, always-on frame health counters for the operator's live workspace."""
from collections import deque
from threading import Lock
from time import monotonic


class LiveFrameStatus:
    """Measure acquisition and successful inference independently of diagnostics."""

    def __init__(self):
        self._lock = Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self._captured = deque(maxlen=600)
            self._processed = deque(maxlen=600)
            self._resolution = None

    def capture(self, width, height, *, when=None):
        with self._lock:
            self._captured.append(monotonic() if when is None else when)
            self._resolution = [int(width), int(height)]

    def processed(self, *, when=None):
        with self._lock:
            self._processed.append(monotonic() if when is None else when)

    def snapshot(self, *, active, connected, loading=False, paused=False, now=None):
        now = monotonic() if now is None else now
        with self._lock:
            captured, processed = list(self._captured), list(self._processed)
            resolution = list(self._resolution) if self._resolution else None
        capture_age = max(0.0, now - captured[-1]) if captured else None
        processed_age = max(0.0, now - processed[-1]) if processed else None
        capture_fresh = active and capture_age is not None and capture_age <= 3.0
        processing_fresh = capture_fresh and processed_age is not None and processed_age <= 5.0 and not paused
        camera_state = "active" if capture_fresh else "loading" if loading else "stalled" if active and connected else "disconnected"
        ai_state = "paused" if active and paused else "running" if processing_fresh else "waiting" if active else "stopped"
        return {
            "camera_state": camera_state,
            "ai_state": ai_state,
            "capture_fps": float(sum(now - 1.0 < stamp <= now for stamp in captured)) if capture_fresh else 0.0,
            "processing_fps": float(sum(now - 1.0 < stamp <= now for stamp in processed)) if processing_fresh else 0.0,
            "capture_frame_age_seconds": round(capture_age, 3) if capture_age is not None else None,
            "processed_frame_age_seconds": round(processed_age, 3) if processed_age is not None else None,
            "capture_resolution": resolution,
            "rate_window_seconds": 1.0,
        }
