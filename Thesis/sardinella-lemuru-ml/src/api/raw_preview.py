"""Optional, bounded raw-camera preview; never carries inference overlays."""
from __future__ import annotations

import logging
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any

from src.api.runtime_diagnostics import LatestFrameQueue

LOGGER = logging.getLogger(__name__)


class RawPreview:
    """One encoder shared by subscribers, with at most one waiting frame."""

    def __init__(self, enabled: bool, max_fps: float = 15.0) -> None:
        self.enabled = enabled
        self._interval = 1.0 / max_fps
        self._lock = Lock()
        self._queue = LatestFrameQueue()
        self._subscribers = 0
        self._generation = 0
        self._jpeg: bytes | None = None
        self._version = 0
        self._next_capture = 0.0
        self._thread: Thread | None = None

    def subscribe(self) -> None:
        with self._lock:
            self._subscribers += 1

    def unsubscribe(self) -> None:
        with self._lock:
            self._subscribers = max(0, self._subscribers - 1)
            if self._subscribers == 0:
                self._generation += 1
                self._jpeg = None
                self._queue.clear()

    def frame(self) -> tuple[bytes | None, int]:
        with self._lock:
            return self._jpeg, self._version

    def offer(self, frame: Any, captured_at: float) -> None:
        with self._lock:
            if not self.enabled or not self._subscribers or captured_at < self._next_capture:
                return
            self._next_capture = captured_at + self._interval
            # Copy before inference receives the original, even if a model mutates it.
            self._queue.offer((self._generation, frame.copy()), captured_at=captured_at)

    def start(self, stop: Event, cv2: Any) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._generation += 1
            self._jpeg = None
            self._next_capture = 0.0
            self._queue.clear()
        self._thread = Thread(target=self._encode, args=(stop, cv2), name="raw-preview", daemon=True)
        self._thread.start()

    def finish(self) -> None:
        thread = self._thread
        if thread is not None:
            # Do not permit a restart while an encoder still owns a frame.
            thread.join()
        self._thread = None
        with self._lock:
            self._generation += 1
            self._jpeg = None
            self._queue.clear()

    def _encode(self, stop: Event, cv2: Any) -> None:
        while not stop.is_set():
            packet = self._queue.take(timeout=0.1)
            if packet is None:
                continue
            generation, frame = packet.frame
            try:
                success, data = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
                if not success:
                    continue
                with self._lock:
                    if self._subscribers and generation == self._generation and not stop.is_set():
                        self._jpeg = data.tobytes()
                        self._version += 1
            except Exception:
                LOGGER.exception("Raw preview JPEG encoding failed")
