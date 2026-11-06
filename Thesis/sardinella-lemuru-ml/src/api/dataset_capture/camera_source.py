"""One independently owned camera handle in a terminable worker process.

No inspection imports, device probing, backend fallback, or shared buffers.
The worker drains its camera continuously and answers each request using a
subsequent read, rather than returning a cached preview frame.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import multiprocessing
from time import monotonic
from typing import Any
from uuid import uuid4

from .errors import CaptureError


@dataclass
class FramePacket:
    frame: Any
    frame_id: int
    captured_monotonic: float
    generation: str
    captured_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    readbacks: dict[str, Any] = field(default_factory=dict)


def _worker(connection, device_index: int, width: int, height: int, backend: str, generation: str):
    capture = None
    try:
        import cv2
        backend_ids = {"dshow": "CAP_DSHOW", "msmf": "CAP_MSMF", "v4l2": "CAP_V4L2"}
        if backend == "default":
            capture = cv2.VideoCapture(device_index)
        else:
            backend_id = getattr(cv2, backend_ids[backend], None)
            if backend_id is None:
                raise RuntimeError("The selected camera backend is unavailable on this platform.")
            capture = cv2.VideoCapture(device_index, backend_id)
        if not capture.isOpened():
            connection.send(("error", "CAMERA_UNAVAILABLE", "Camera in use or unavailable — stop inspection manually or choose a different camera."))
            return
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        properties = {"width": "CAP_PROP_FRAME_WIDTH", "height": "CAP_PROP_FRAME_HEIGHT", "fps": "CAP_PROP_FPS", "exposure": "CAP_PROP_EXPOSURE", "focus": "CAP_PROP_FOCUS", "auto_exposure": "CAP_PROP_AUTO_EXPOSURE", "auto_white_balance": "CAP_PROP_AUTO_WB"}
        readbacks = {}
        for name, constant in properties.items():
            prop = getattr(cv2, constant, None)
            if prop is not None:
                value = float(capture.get(prop))
                if math.isfinite(value):
                    readbacks[name] = value
        try:
            actual_backend = capture.getBackendName()
        except Exception:
            actual_backend = backend
        readbacks.update(backend=actual_backend, device_index=device_index,
                         device_name=f"Camera #{device_index}", device_name_verified=False,
                         property_support_note="Driver readbacks; zero does not establish property support.")
        connection.send(("opened", readbacks))
        pending = False
        frame_id = 0
        first_at = monotonic()
        while True:
            if connection.poll():
                command = connection.recv()
                if command == "close":
                    return
                pending = command == "read"
            ok, frame = capture.read()
            captured_at = monotonic()
            if not ok or frame is None:
                connection.send(("error", "CAMERA_DISCONNECTED", "Camera stopped returning frames. Reconnect it and start the capture camera again."))
                return
            frame_id += 1
            if frame.ndim != 3 or frame.shape[2] != 3 or frame.shape[0] * frame.shape[1] > 32_000_000:
                connection.send(("error", "INVALID_FRAME", "Camera returned an unsupported or excessively large frame."))
                return
            if pending:
                details = dict(readbacks, width=frame.shape[1], height=frame.shape[0],
                               camera_fps=frame_id / max(captured_at - first_at, .001))
                connection.send(("frame", FramePacket(frame, frame_id, captured_at, generation,
                                                       readbacks=details)))
                pending = False
    except (EOFError, BrokenPipeError):
        pass
    except Exception:
        try:
            connection.send(("error", "CAMERA_DRIVER_ERROR", "Capture camera driver failed. Check the selected backend, connection and device isolation."))
        except (EOFError, BrokenPipeError, OSError):
            pass
    finally:
        if capture is not None:
            capture.release()
        connection.close()


class ProcessCameraSource:
    def __init__(self, *, device_index: int, width: int, height: int, backend: str,
                 open_timeout: float = 6.0, read_timeout: float = 2.0):
        self.config = (device_index, width, height, backend)
        self.open_timeout = open_timeout
        self.read_timeout = read_timeout
        self.generation = uuid4().hex
        self._process = None
        self._connection = None
        self.readbacks = {}

    def _receive(self, timeout: float):
        try:
            if self._connection is None or not self._connection.poll(timeout):
                raise CaptureError(504, "CAMERA_TIMEOUT", "Camera driver did not respond; its capture worker was released. Restart the camera to retry.")
            result = self._connection.recv()
            if result[0] == "error":
                raise CaptureError(409 if result[1] == "CAMERA_UNAVAILABLE" else 503, result[1], result[2])
            return result
        except CaptureError:
            self.close()
            raise
        except (EOFError, BrokenPipeError, OSError):
            self.close()
            raise CaptureError(503, "CAMERA_DISCONNECTED", "Capture camera worker disconnected. Restart the capture camera.") from None

    def start(self):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        self._connection = parent
        self._process = context.Process(target=_worker, args=(child, *self.config, self.generation),
                                        name="dataset-camera", daemon=True)
        try:
            self._process.start()
            child.close()
            result = self._receive(self.open_timeout)
            if result[0] != "opened":
                raise CaptureError(503, "CAMERA_PROTOCOL", "Camera startup returned an invalid response.")
            self.readbacks = result[1]
            return self.readbacks
        except Exception:
            child.close()
            self.close()
            raise

    def read(self):
        try:
            self._connection.send("read")
        except (AttributeError, EOFError, BrokenPipeError, OSError):
            self.close()
            raise CaptureError(503, "CAMERA_DISCONNECTED", "Capture camera is unavailable.") from None
        result = self._receive(self.read_timeout)
        if result[0] != "frame":
            self.close()
            raise CaptureError(503, "CAMERA_PROTOCOL", "Camera returned an invalid frame response.")
        self.readbacks = result[1].readbacks
        return result[1]

    def close(self):
        process, connection = self._process, self._connection
        self._connection = None
        if connection is not None:
            try:
                connection.send("close")
            except (EOFError, BrokenPipeError, OSError):
                pass
        if process is not None and getattr(process, "pid", True) is not None:
            process.join(.25)
            if process.is_alive():
                process.terminate()
                process.join(.75)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(.75)
            if process.is_alive():
                if connection is not None:
                    connection.close()
                raise CaptureError(503, "CAMERA_RELEASE_FAILED", "Capture worker could not be released; do not reopen this device until the administrator resolves it.")
        self._process = None
        if connection is not None:
            connection.close()

