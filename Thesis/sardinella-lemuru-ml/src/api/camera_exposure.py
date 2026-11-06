"""Session-local exposure controls and display-only, color-preserving EV.

Only DirectShow's documented integer log2 shutter units are mapped to native
EV. Other backends use software because OpenCV offers no portable range/unit
query (V4L properties may also be normalized). Pixel processing belongs at the
preview boundary: never pass its output into detection, segmentation or grading.
"""

from __future__ import annotations

from math import ceil, isfinite, log2, trunc
from threading import RLock
from time import monotonic
from typing import Any

import cv2
import numpy as np

from .camera_controls import CameraControlError, CameraHardwareController


class CameraExposureController:
    """Use an existing capture; construction/status/clear never write to it."""

    def __init__(self, hardware: CameraHardwareController) -> None:
        self.hardware = hardware
        self._lock = RLock()
        self.clear()

    def clear(self) -> None:
        """Forget session adjustments without touching the capture or profile.

        The owner calls this after opening/releasing/reconfiguring a camera, or
        when committing native calibration settings to the inspection session.
        """
        with self._lock:
            self._mode = "auto"
            self._ev = 0.0
            self._native_ev = 0.0
            self._software_ev = 0.0
            self._software_target = 0.0
            self._baseline: dict[str, Any] | None = None
            self._native_changed = False
            self._hardware_changed = False
            self._success = True
            self._source = "none"
            self._reason = "Camera acquisition defaults; preview compensation is off."
            self._last_time: float | None = None
            self._lut_key: float | None = None
            self._lut: np.ndarray | None = None

    def status(self) -> dict[str, object]:
        """Return cached state without camera calls or pixel processing."""
        with self._lock:
            return {
                "mode": self._mode,
                "ev": self._ev,
                "applied_ev": round(self._native_ev + self._software_ev, 3),
                "native_ev": self._native_ev,
                "native_active": self._native_changed,
                "software_ev": round(self._software_ev, 3),
                "source": self._source,
                "reason": self._reason,
                "hardware_changed": self._hardware_changed,
                "success": self._success,
                "grading_input": "original_capture",
                "software_display_only": True,
            }

    @staticmethod
    def _validate(mode: str | None, ev: float | None) -> None:
        if mode is not None and mode not in {"auto", "manual"}:
            raise CameraControlError("Exposure mode must be auto or manual.")
        if ev is not None:
            if isinstance(ev, bool) or not isinstance(ev, (int, float)) or not isfinite(ev) or not -2 <= ev <= 2:
                raise CameraControlError("EV must be a finite number from -2.0 to +2.0.")

    def configure(
        self, *, mode: str | None = None, ev: float | None = None,
        allow_native: bool = True,
    ) -> dict[str, object]:
        """Configure EV atomically with the shared camera's property lock.

        ``allow_native=False`` prohibits every hardware write, including reset
        and rollback. Native changes retained on leaving calibration become the
        acquisition baseline; live preview compensation remains display-only.
        """
        self._validate(mode, ev)
        with self.hardware.lock, self._lock:
            self._hardware_changed = False
            self._success = True
            target_mode = mode if mode is not None else ("manual" if ev is not None else self._mode)
            target_ev = float(ev) if ev is not None else self._ev
            if target_mode == "auto":
                target_ev = 0.0
            if not self.hardware.connected:
                raise CameraControlError("Start the inspection camera before adjusting exposure.")
            if not allow_native and self._native_changed:
                # The caller commits native calibration when returning to live
                # inspection. Never undo it through an ordinary preview action.
                self._baseline = None
                self._native_changed = False
                self._native_ev = 0.0
                self._software_ev = 0.0
            previous_total = self._native_ev + self._software_ev
            try:
                if target_mode == "auto":
                    if allow_native:
                        self._restore_native()
                        capabilities = self.hardware.capabilities().get("properties", {})
                        if capabilities.get("auto_exposure", {}).get("supported"):
                            result = self._write_auto(True)
                            self._success = bool(result.get("success"))
                            self._reason = ("Camera Auto Exposure requested; preview compensation is off."
                                            if self._success else
                                            "Camera rejected Auto Exposure; preview compensation is off.")
                        else:
                            self._reason = "Camera Auto Exposure is unavailable; preview compensation is off."
                    else:
                        self._reason = "Preview compensation is off; camera acquisition settings are retained."
                    self._native_ev = 0.0
                    self._baseline = None
                    self._native_changed = False
                    self._source = "none"
                else:
                    if allow_native:
                        self._configure_native(target_ev)
                    else:
                        self._native_ev = 0.0
                        self._source = "software" if target_ev else "none"
                        self._reason = "Display-only exposure; original camera frames are used for AI grading."
            except Exception as exc:
                # Expose a partial acquisition change to the owner so it can
                # rotate stale evidence and report the hardware failure.
                if not isinstance(exc, CameraControlError):
                    self._reason = "Camera exposure adjustment failed; review acquisition controls before inspection."
                self._success = False
                self._software_target = 0.0
                self._software_ev = 0.0
                return self.status()
            self._mode = target_mode
            self._ev = target_ev
            self._software_target = target_ev - self._native_ev
            # Counteract an integer hardware step at the preview boundary, then
            # approach the requested total EV smoothly on subsequent frames.
            self._software_ev = previous_total - self._native_ev
            self._last_time = monotonic()
            return self.status()

    def _write_auto(self, enabled: bool) -> dict[str, object]:
        self._hardware_changed = True  # A failed setter can still alter a device.
        return self.hardware.set_auto_exposure(enabled)

    def _write_exposure(self, value: float) -> dict[str, object]:
        self._hardware_changed = True
        return self.hardware.set_camera_property("exposure", value)

    def _snapshot(self) -> dict[str, Any]:
        settings = self.hardware.settings()
        actual = settings.get("actual", {})
        automatic = actual.get("auto_exposure")
        if automatic is None:
            automatic = settings.get("requested_automatic", {}).get("auto_exposure")
        return {
            "exposure": actual.get("exposure"), "auto_exposure": automatic,
            "backend": settings.get("camera", {}).get("backend", ""),
            "fps": settings.get("camera", {}).get("fps"),
        }

    def _configure_native(self, ev: float) -> None:
        baseline = self._baseline or self._snapshot()
        exposure = baseline.get("exposure")
        known = ("DSHOW" in str(baseline.get("backend", "")).upper()
                 and isinstance(exposure, (float, int)) and isfinite(exposure)
                 and -30 < exposure < 0 and abs(exposure - round(exposure)) < .001
                 and isinstance(baseline.get("auto_exposure"), bool))
        capabilities = self.hardware.capabilities().get("properties", {})
        known = known and bool(capabilities.get("exposure", {}).get("supported"))
        known = known and bool(capabilities.get("auto_exposure", {}).get("supported"))
        if not known:
            self._restore_native()
            self._source = "software" if ev else "none"
            self._reason = "Native EV units or restorable automatic state unavailable; using display-only exposure."
            self._native_ev = 0.0
            return
        # DirectShow accepts integer log2 seconds. Leave sub-stop EV in the
        # preview curve, and do not lengthen the shutter beyond one frame.
        shift = trunc(ev)
        fps = baseline.get("fps")
        if isinstance(fps, (int, float)) and isfinite(fps) and fps > 0:
            max_shutter = -ceil(log2(fps))
            shift = min(shift, max(0, int(max_shutter - exposure)))
        else:
            # Without a reliable frame interval, lengthening the shutter could
            # lower capture FPS. Software can provide positive EV instead.
            shift = min(shift, 0)
        requested = float(exposure + shift)
        if shift == 0 and not self._native_changed:
            self._native_ev = 0.0
            self._source = "software" if ev else "none"
            self._reason = "Display-only fine EV adjustment; native shutter has whole-stop steps and a frame-interval limit."
            return
        if self._native_changed and shift == self._native_ev:
            self._source = "native"
            return
        self._baseline = baseline
        self._native_changed = True  # Includes attempted writes needing rollback.
        try:
            result = self._write_auto(False)
            if result.get("success"):
                result = self._write_exposure(requested)
        except Exception:
            self._restore_native()
            raise
        if not result.get("success"):
            self._restore_native()
            self._native_ev = 0.0
            self._source = "software" if ev else "none"
            self._reason = "Camera rejected native EV; prior exposure restored, using display-only exposure."
            return
        self._native_ev = float(shift)
        self._source = "native" if shift else ("software" if ev else "none")
        self._reason = "Verified native shutter adjustment; fractional EV uses display-only compensation."

    def _restore_native(self) -> None:
        if not self._native_changed or self._baseline is None:
            return
        baseline = self._baseline
        automatic = baseline.get("auto_exposure")
        results = []
        current = self._snapshot().get("exposure")
        if current != baseline.get("exposure"):
            results.append(self._write_exposure(float(baseline["exposure"])))
        if isinstance(automatic, bool):
            results.append(self._write_auto(automatic))
        if not results or not all(result.get("success") for result in results):
            self._reason = "Camera could not restore its prior exposure; review acquisition controls before inspection."
            raise CameraControlError(self._reason)
        self._native_ev = 0.0
        self._native_changed = False

    def reset(self, *, allow_native: bool = True) -> dict[str, object]:
        """Restore pre-EV acquisition settings when allowed, and remove EV."""
        with self.hardware.lock, self._lock:
            self._hardware_changed = False
            self._success = True
            if allow_native:
                try:
                    self._restore_native()
                except Exception as exc:
                    if not isinstance(exc, CameraControlError):
                        self._reason = "Camera exposure reset failed; review acquisition controls before inspection."
                    self._success = False
                    return self.status()
            hardware_changed = self._hardware_changed
            self.clear()
            self._hardware_changed = hardware_changed
            self._reason = "Default preview restored (EV 0); pre-adjustment camera settings retained."
            return self.status()

    def apply(self, frame: np.ndarray, *, now: float | None = None) -> np.ndarray:
        """Return an enhanced BGR preview, leaving the original frame intact.

        An HSV value curve keeps hue and saturation rather than adding a gray
        brightness offset to every channel. One cached 256-entry LUT combines
        exposure gain, gentle gamma and a highlight shoulder/contrast rolloff.
        Black/white endpoints remain fixed. Work is independent of AI models.
        """
        with self._lock:
            timestamp = monotonic() if now is None else now
            elapsed = (1 / 30 if self._last_time is None
                       else max(0.0, min(.2, timestamp - self._last_time)))
            self._last_time = timestamp
            delta = self._software_target - self._software_ev
            self._software_ev += max(-5 * elapsed, min(5 * elapsed, delta))
            if abs(self._software_ev) < .005:
                self._software_ev = 0.0
                return frame
            key = round(self._software_ev, 2)
            if self._lut_key != key:
                x = np.arange(256, dtype=np.float32) / 255.0
                gamma = 2.0 ** (-.10 * key)
                gain = 2.0 ** (.85 * key)
                base = np.power(x, gamma)
                mapped = base * gain / (1.0 + (gain - 1.0) * base)
                self._lut = np.rint(np.clip(mapped, 0, 1) * 255).astype(np.uint8)
                self._lut_key = key
            lut = self._lut
        if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
            raise CameraControlError("Exposure preview requires an 8-bit BGR camera frame.")
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hsv[:, :, 2] = cv2.LUT(hsv[:, :, 2], lut)
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
