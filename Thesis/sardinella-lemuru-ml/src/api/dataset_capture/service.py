"""Independent capture ownership, fresh manual saves and monotonic scheduling."""
from __future__ import annotations

import math
from threading import Event, RLock, Thread
import time

from .camera_source import FramePacket, ProcessCameraSource
from .errors import CaptureError
from .ownership import ISOLATION_MESSAGE, require_isolated_hardware


class DatasetCaptureService:
    MAX_RUN_SECONDS = 3600
    MAX_RUN_COUNT = 10000

    def __init__(self, store, source_factory=None, clock=time.monotonic,
                 background=True, hardware_enabled=False):
        self.store = store
        self._factory = source_factory or ProcessCameraSource
        self._synthetic = source_factory is not None
        self._hardware_enabled = bool(hardware_enabled)
        self._clock = clock
        self._lock = RLock()
        self._source = None
        self._camera_state = "closed"
        self._camera_config = {}
        self._readbacks = {}
        self._last_frame = None
        self._last_saved = None
        self._last_error = None
        self._release_failed = False
        self._session_id = None
        self._preview = None
        self._manual_count = 0
        self._saved_times = []
        self._run = {"state": "idle", "captured": 0, "scheduled": 0,
                     "skipped": 0, "late": 0}
        self._shutdown = Event()
        self._thread = None
        if background:
            self._thread = Thread(target=self._loop, name="dataset-capture-scheduler", daemon=True)
            self._thread.start()

    def _loop(self):
        while not self._shutdown.wait(.025):
            try:
                with self._lock:
                    self._tick_locked()
            except CaptureError:
                # The failure is retained in status; never pretend a shot saved.
                pass

    def _error(self, exc):
        self._last_error = {"code": exc.code, "detail": exc.detail}

    def _close_source(self):
        source = self._source
        if source is not None:
            try:
                source.close()
            except Exception:
                self._release_failed = True
                self._camera_state = "error"
                raise CaptureError(503, "CAMERA_RELEASE_FAILED", "Capture worker could not be released. Ask the administrator to resolve it before reopening this device.") from None
        self._source = None
        self._last_frame = self._last_saved = self._preview = None

    def status(self):
        with self._lock:
            now = self._clock()
            run = dict(self._run)
            reference = run.get("paused_at", now) if run["state"] == "paused" else now
            if run["state"] in {"running", "countdown", "paused"}:
                run["countdown_remaining"] = max(0., run["capture_start"] - reference)
                run["next_shot_seconds"] = max(0., run["next_due"] - reference)
                run["duration_remaining"] = max(0., run["end_due"] - reference)
            else:
                run.update(countdown_remaining=0., next_shot_seconds=None, duration_remaining=0.)
            times = self._saved_times
            fps = ((len(times) - 1) / (times[-1] - times[0])) if len(times) > 1 and times[-1] > times[0] else 0.
            stats = self.store.stats(self._session_id) if self._session_id else self.store.stats()
            available = self._camera_state == "open" and self._session_id is not None
            return {
                "camera": {"state": self._camera_state, "readbacks": dict(self._readbacks),
                           "requested": dict(self._camera_config),
                           "hardware_enabled": self._hardware_enabled,
                           "isolation_required": not self._hardware_enabled and not self._synthetic,
                           "isolation_note": ISOLATION_MESSAGE if not self._hardware_enabled else "Administrator-declared isolated deployment; this setting is not an OS ownership guarantee."},
                "camera_state": self._camera_state,
                "readbacks": dict(self._readbacks), "session_id": self._session_id,
                "manual_available": available, "manual_count": stats.get("manual_photos", self._manual_count),
                "manual_unavailable_reason": None if available else (self._last_error or {}).get("detail", "Open the capture camera and select a capture session first."),
                "run": run, "stats": stats, "last_error": self._last_error,
                "camera_fps": self._readbacks.get("camera_fps"), "capture_fps": round(fps, 3),
                "capture_fps_scope": "Saved-photo interval rate for the current session; not AI FPS.",
                "drive": {"connected": False, "status": "Drive not connected", "auto_sync": False},
            }

    def start_camera(self, device_index=0, width=1920, height=1080, backend="dshow"):
        with self._lock:
            if self._release_failed:
                raise CaptureError(503, "CAMERA_RELEASE_FAILED", "Previous capture worker was not released; administrator intervention is required.")
            if self._source is not None:
                raise CaptureError(409, "CAPTURE_CAMERA_OPEN", "Stop the capture camera before changing its configuration.")
            if isinstance(device_index, bool) or not isinstance(device_index, int) or not 0 <= device_index <= 11:
                raise CaptureError(422, "INVALID_DEVICE", "Choose a numeric camera index from 0 to 11. Indexes do not prove physical device identity.")
            if any(isinstance(v, bool) or not isinstance(v, int) or not 64 <= v <= 4096 for v in (width, height)):
                raise CaptureError(422, "INVALID_RESOLUTION", "Requested width and height must be integers from 64 to 4096.")
            if backend not in {"default", "dshow", "msmf", "v4l2"}:
                raise CaptureError(422, "INVALID_BACKEND", "Choose default, dshow, msmf or v4l2; automatic probing is disabled.")
            if not self._synthetic:
                try:
                    require_isolated_hardware(self._hardware_enabled)
                except CaptureError as exc:
                    self._error(exc)
                    raise
            source = None
            try:
                source = self._factory(device_index=device_index, width=width, height=height, backend=backend)
                readbacks = source.start() or {}
                self._source = source
                self._camera_config = {"device_index": device_index, "width": width, "height": height, "backend": backend}
                self._readbacks = dict(readbacks)
                self._last_frame = self._last_saved = self._preview = None
                self._camera_state = "open"
                self._last_error = None
            except Exception as exc:
                if source is not None:
                    try:
                        source.close()
                    except Exception:
                        self._release_failed = True
                self._camera_state = "error"
                error = exc if isinstance(exc, CaptureError) else CaptureError(503, "CAMERA_UNAVAILABLE", "Capture camera could not start. Check connection, backend and exclusive device access.")
                self._error(error)
                raise error from None
            return self.status()

    def stop_camera(self):
        with self._lock:
            self.stop_run()
            try:
                self._close_source()
                self._camera_state = "closed"
            except CaptureError as exc:
                self._error(exc)
                raise
            return self.status()

    def create_session(self, metadata):
        with self._lock:
            if self._run["state"] in {"running", "countdown", "paused"}:
                raise CaptureError(409, "RUN_ACTIVE", "Stop the automatic run before creating or selecting a different session.")
            session = self.store.create_session(metadata)
            self.select_session(session["id"])
            return session

    def select_session(self, session_id):
        with self._lock:
            if self._run["state"] in {"running", "countdown", "paused"}:
                raise CaptureError(409, "RUN_ACTIVE", "Stop the automatic run before changing sessions.")
            session = self.store.session(session_id)
            self._session_id = session["id"]
            self._manual_count = 0
            self._saved_times = []
            return session

    def _require_ready(self):
        if self._source is None or self._camera_state != "open":
            raise CaptureError(409, "CAPTURE_CAMERA_CLOSED", "Capture camera is closed or unavailable. Open its independent camera first.")
        if self._session_id is None:
            raise CaptureError(409, "CAPTURE_SESSION_REQUIRED", "Create or select a capture session before saving photos.")

    def _fresh_packet(self):
        requested_at = self._clock()
        try:
            packet = self._source.read()
            if not isinstance(packet, FramePacket):
                raise CaptureError(503, "INVALID_FRAME", "Capture reader returned an invalid frame packet.")
            identity = (packet.generation, packet.frame_id)
            if (not packet.generation or isinstance(packet.frame_id, bool) or not isinstance(packet.frame_id, int)
                    or packet.frame_id < 1 or not math.isfinite(packet.captured_monotonic)
                    or packet.captured_monotonic < requested_at - .001
                    or packet.captured_monotonic > self._clock() + .05):
                raise CaptureError(409, "STALE_FRAME", "Camera did not return a fresh frame for this request; no photo was saved.")
            if self._last_frame is not None:
                generation, frame_id = self._last_frame
                if packet.generation != generation or packet.frame_id <= frame_id:
                    raise CaptureError(409, "STALE_FRAME", "Camera returned an old or duplicate frame; no photo was saved.")
            shape = getattr(packet.frame, "shape", ())
            if len(shape) != 3 or shape[2] != 3 or shape[0] * shape[1] > 32_000_000 or shape[0] < 1 or shape[1] < 1:
                raise CaptureError(503, "INVALID_FRAME", "Camera returned an invalid or excessively large native frame.")
            self._last_frame = identity
            self._readbacks.update(packet.readbacks)
            self._readbacks.update(width=shape[1], height=shape[0])
            return packet
        except Exception as exc:
            error = exc if isinstance(exc, CaptureError) else CaptureError(503, "CAMERA_DISCONNECTED", "Capture camera failed to read a new frame. Reconnect and restart its camera.")
            self._error(error)
            if error.code != "STALE_FRAME":
                self._camera_state = "error"
                try:
                    self._close_source()
                except CaptureError as release_error:
                    self._error(release_error)
            raise error from None

    def _save(self, mode, scheduled=None):
        self._require_ready()
        packet = self._fresh_packet()
        metadata = {
            "generation": packet.generation, "frame_id": packet.frame_id,
            "captured_monotonic": packet.captured_monotonic, "captured_utc": packet.captured_utc,
            "device_index": self._camera_config["device_index"],
            "backend": self._readbacks.get("backend", self._camera_config["backend"]),
            "readbacks": dict(self._readbacks), "camera_profile": "Independent dataset capture",
            "scheduled_monotonic": scheduled,
        }
        try:
            item = self.store.save_frame(self._session_id, packet.frame, metadata, mode,
                                         scheduled_monotonic=scheduled)
        except Exception as exc:
            error = exc if isinstance(exc, CaptureError) else CaptureError(507 if isinstance(exc, OSError) else 500, "LOCAL_SAVE_FAILED", "Photo could not be saved locally. Check available disk space; no successful capture was recorded.")
            self._error(error)
            raise error from None
        self._last_saved = (packet.generation, packet.frame_id)
        self._saved_times.append(packet.captured_monotonic)
        self._saved_times = self._saved_times[-120:]
        if mode == "manual":
            self._manual_count += 1
        self._last_error = None
        return item

    def snapshot(self):
        with self._lock:
            # A manual click may not starve an already-due scheduled shot.
            self._tick_locked()
            item = self._save("manual")
            self._tick_locked()
            return item

    def start_run(self, countdown=0, interval=1, duration=None, target_count=None, session_id=None):
        with self._lock:
            if self._run["state"] in {"running", "countdown", "paused"}:
                raise CaptureError(409, "RUN_ACTIVE", "An automatic capture run is already active.")
            if session_id is not None:
                self.select_session(session_id)
            self._require_ready()
            if isinstance(countdown, bool) or countdown not in {0, 5, 10}:
                raise CaptureError(422, "INVALID_COUNTDOWN", "Countdown must be 0, 5 or 10 seconds.")
            if isinstance(interval, bool) or interval not in {1, 2, 5}:
                raise CaptureError(422, "INVALID_INTERVAL", "Capture interval must be 1, 2 or 5 seconds.")
            if duration is not None and (isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or not 0 < duration <= self.MAX_RUN_SECONDS):
                raise CaptureError(422, "INVALID_DURATION", "Capture duration must be positive and no longer than one hour.")
            if target_count is not None and (isinstance(target_count, bool) or not isinstance(target_count, int) or not 1 <= target_count <= self.MAX_RUN_COUNT):
                raise CaptureError(422, "INVALID_TARGET", "Target count must be an integer from 1 to 10000.")
            now = self._clock()
            self._run = {"state": "countdown" if countdown else "running", "countdown": countdown,
                         "interval": interval, "duration": duration, "target_count": target_count,
                         "started_monotonic": now, "capture_start": now + countdown,
                         "next_due": now + countdown,
                         "end_due": now + countdown + (duration if duration is not None else self.MAX_RUN_SECONDS),
                         "captured": 0, "scheduled": 0, "skipped": 0, "late": 0,
                         "last_capture_monotonic": None, "last_lateness_seconds": None,
                         "stop_reason": None}
            return self.status()

    def _tick_locked(self):
        run = self._run
        if run["state"] not in {"countdown", "running"}:
            return
        now = self._clock()
        if now < run["capture_start"]:
            return
        run["state"] = "running"
        if now >= run["end_due"]:
            remaining = max(0, math.ceil((run["end_due"] - run["next_due"]) / run["interval"]))
            run["scheduled"] += remaining
            run["skipped"] += remaining
            run.update(state="completed", stop_reason="duration" if run["duration"] is not None else "safety_limit")
            return
        if now < run["next_due"]:
            return
        missed = max(0, math.floor((now - run["next_due"]) / run["interval"]))
        due = run["next_due"] + missed * run["interval"]
        run["scheduled"] += missed + 1
        run["skipped"] += missed
        run["next_due"] = due + run["interval"]
        try:
            self._save("automatic", due)
        except CaptureError:
            run["skipped"] += 1
            run.update(state="error", stop_reason=(self._last_error or {}).get("code", "CAPTURE_FAILED"))
            raise
        actual = self._saved_times[-1]
        lateness = max(0., actual - due)
        run["captured"] += 1
        run["last_capture_monotonic"] = actual
        run["last_lateness_seconds"] = round(lateness, 6)
        if lateness > .05:
            run["late"] += 1
        if run["captured"] >= (run["target_count"] or self.MAX_RUN_COUNT):
            run.update(state="completed", stop_reason="target_count" if run["target_count"] else "safety_limit")

    def tick(self):
        with self._lock:
            self._tick_locked()
            return self.status()

    def pause(self):
        with self._lock:
            if self._run["state"] not in {"countdown", "running"}:
                raise CaptureError(409, "RUN_NOT_ACTIVE", "There is no active automatic run to pause.")
            self._run.update(state="paused", paused_at=self._clock())
            return self.status()

    def resume(self):
        with self._lock:
            if self._run["state"] != "paused":
                raise CaptureError(409, "RUN_NOT_PAUSED", "There is no paused automatic run to resume.")
            paused_for = self._clock() - self._run.pop("paused_at")
            for key in ("capture_start", "next_due", "end_due"):
                self._run[key] += paused_for
            self._run["state"] = "countdown" if self._clock() < self._run["capture_start"] else "running"
            return self.status()

    def stop_run(self):
        with self._lock:
            if self._run["state"] in {"running", "countdown", "paused"}:
                self._run.update(state="stopped", stop_reason="operator")
            return self.status()

    def preview(self):
        with self._lock:
            if self._source is None or self._camera_state != "open":
                return None
            packet = self._fresh_packet()
            import cv2
            frame = packet.frame
            if frame.shape[1] > 1280:
                frame = cv2.resize(frame, (1280, max(1, round(frame.shape[0] * 1280 / frame.shape[1]))))
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                raise CaptureError(503, "PREVIEW_ENCODING_FAILED", "Capture preview could not be encoded.")
            self._preview = encoded.tobytes()
            return self._preview

    def close(self):
        self._shutdown.set()
        with self._lock:
            self.stop_camera()
        if self._thread is not None:
            self._thread.join(timeout=3.)

