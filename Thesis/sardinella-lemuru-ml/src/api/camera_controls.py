"""Hardware-backed controls for the single inspection camera.

OpenCV does not expose a portable UVC capability/range API. Discovery is strictly
read-only: writing even the current exposure or white balance can disable the
driver's automatic adjustments. Write acceptance and readback verification are
reported separately. This module never alters image pixels.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from math import isfinite
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

import yaml


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CameraProperty:
    """One camera property exposed by OpenCV when a backend supports it."""

    key: str
    label: str
    cv2_name: str
    automatic: bool = False


CAMERA_PROPERTIES = (
    CameraProperty("frame_width", "Frame Width", "CAP_PROP_FRAME_WIDTH"),
    CameraProperty("frame_height", "Frame Height", "CAP_PROP_FRAME_HEIGHT"),
    CameraProperty("fps", "Frame Rate (FPS)", "CAP_PROP_FPS"),
    CameraProperty("exposure", "Exposure", "CAP_PROP_EXPOSURE"),
    CameraProperty("gain", "Gain", "CAP_PROP_GAIN"),
    CameraProperty("brightness", "Brightness", "CAP_PROP_BRIGHTNESS"),
    CameraProperty("gamma", "Gamma", "CAP_PROP_GAMMA"),
    CameraProperty("contrast", "Contrast", "CAP_PROP_CONTRAST"),
    CameraProperty("saturation", "Saturation", "CAP_PROP_SATURATION"),
    CameraProperty("sharpness", "Sharpness", "CAP_PROP_SHARPNESS"),
    CameraProperty("white_balance", "White Balance", "CAP_PROP_WB_TEMPERATURE"),
    CameraProperty("focus", "Focus", "CAP_PROP_FOCUS"),
    CameraProperty("auto_exposure", "Auto Exposure", "CAP_PROP_AUTO_EXPOSURE", automatic=True),
    CameraProperty("auto_white_balance", "Auto White Balance", "CAP_PROP_AUTO_WB", automatic=True),
    CameraProperty("autofocus", "Autofocus", "CAP_PROP_AUTOFOCUS", automatic=True),
)
PROPERTY_BY_KEY = {item.key: item for item in CAMERA_PROPERTIES}
AUTOMATIC_PARTNERS = {
    "exposure": "auto_exposure", "gain": "auto_exposure",
    "white_balance": "auto_white_balance", "focus": "autofocus",
}
CONTROL_SCHEMA_VERSION = 2

# These are operator-recorded installation facts, not inferred camera values.
# Keeping the vocabulary fixed makes a saved profile useful in a future
# independent study without pretending that OpenCV can measure physical setup.
REQUIRED_INSTALLATION_FIELDS = (
    "device_identity",
    "camera_height",
    "camera_angle",
    "conveyor_position",
    "lighting_position",
)


class CameraControlError(RuntimeError):
    """A requested control is unavailable, locked, or rejected by the driver."""


class CameraHardwareController:
    """Operate an already-open ``cv2.VideoCapture`` safely.

    The owner of the capture object attaches it once at worker startup and
    detaches it before releasing it.  Every property operation shares ``lock``
    with frame reads so an API request cannot race the capture loop.
    """

    def __init__(self, camera_index: int, profile_path: Path) -> None:
        self.camera_index = camera_index
        self.profile_path = profile_path
        self.lock = RLock()
        self._capture: Any | None = None
        self._cv2: Any | None = None
        self._backend = "Unavailable"
        self._capabilities: dict[str, dict[str, object]] = {}
        self._opened_settings: dict[str, object] = {}
        self._property_ids: dict[str, int | None] = {}
        self._auto_requests: dict[str, bool] = {}
        self._startup: dict[str, object] = {}
        self._profile: dict[str, object] = self._read_profile()

    @property
    def connected(self) -> bool:
        with self.lock:
            return self._capture is not None

    def attach(self, capture: Any, cv2: Any, backend: str) -> None:
        """Attach the capture already opened by the inference worker."""

        with self.lock:
            self._capture = capture
            self._cv2 = cv2
            self._backend = backend or "OpenCV"
            self._property_ids = {}
            self._auto_requests = {}
            self._startup = {}
            self._capabilities = self._probe_capabilities()
            self._opened_settings = {
                key: value for key, value in self._read_all_settings().items()
                if value is not None and self._capabilities.get(key, {}).get("supported")
            }
        LOGGER.info("[CAMERA] Device opened successfully")
        LOGGER.info("[CAMERA] Backend: %s", self._backend)
        details = self.camera_details()
        LOGGER.info("[CAMERA] Resolution: %sx%s", details["capture_resolution"][0], details["capture_resolution"][1])
        LOGGER.info("[CAMERA] FPS: %s", details["fps"])

    def detach(self, capture: Any | None = None) -> None:
        """Forget a capture only if it is the one owned by this controller."""

        with self.lock:
            if capture is not None and self._capture is not capture:
                return
            self._capture = None
            self._cv2 = None
            self._capabilities = {}
            self._auto_requests = {}

    def _property_id(self, item: CameraProperty) -> int | None:
        if item.key in self._property_ids:
            return self._property_ids[item.key]
        # DirectShow changed its temperature property ID between OpenCV
        # versions. Both constants may exist even when only one is implemented.
        if item.key == "white_balance" and self._capture is not None:
            for name in ("CAP_PROP_WB_TEMPERATURE", "CAP_PROP_TEMPERATURE", "CAP_PROP_WHITE_BALANCE_BLUE_U"):
                candidate = getattr(self._cv2, name, None)
                if not isinstance(candidate, (int, float)):
                    continue
                try:
                    raw = float(self._capture.get(int(candidate)))
                except Exception:
                    continue
                if isfinite(raw) and raw > 1:
                    self._property_ids[item.key] = int(candidate)
                    return int(candidate)
            self._property_ids[item.key] = None
            return None
        value = getattr(self._cv2, item.cv2_name, None) if self._cv2 is not None else None
        return int(value) if isinstance(value, (int, float)) else None

    def _read_raw(self, item: CameraProperty) -> float | None:
        prop_id = self._property_id(item)
        if self._capture is None or prop_id is None:
            return None
        try:
            value = float(self._capture.get(prop_id))
        except Exception:
            return None
        # DirectShow returns -1 for unimplemented getters (including AE).
        # Negative exposure itself is a valid log2 shutter value.
        if (item.automatic and value < 0) or ("DSHOW" in self._backend.upper() and value == -1 and item.key != "exposure"):
            return None
        return value if isfinite(value) else None

    @staticmethod
    def _number(value: float | None) -> float | int | None:
        if value is None:
            return None
        rounded = round(value, 4)
        return int(rounded) if rounded.is_integer() else rounded

    def _auto_value(self, key: str, raw: float | None) -> bool | None:
        if raw is None:
            return None
        if raw < 0:
            return None
        if "DSHOW" in self._backend.upper() and key == "autofocus":
            # IAMCameraControl flags, not a boolean: Auto=1, Manual=2.
            return bool(int(raw) & 1)
        if key == "auto_exposure" and "V4L" in self._backend.upper():
            return raw == 0.75
        return raw > 0.5

    def _read_value(self, item: CameraProperty) -> object:
        raw = self._read_raw(item)
        return self._auto_value(item.key, raw) if item.automatic else self._number(raw)

    def _read_all_settings(self) -> dict[str, object]:
        return {item.key: self._read_value(item) for item in CAMERA_PROPERTIES if item.key in self._capabilities or self._capture is not None}

    def _probe_capabilities(self) -> dict[str, dict[str, object]]:
        """Inspect getters only; even a same-value write can select manual mode.

        A readable property is a candidate control, not proof of write support.
        DirectShow AE is known to be write-only in OpenCV. Actual requests always
        check the driver's return value and verify readback where available.
        """

        capabilities: dict[str, dict[str, object]] = {}
        for item in CAMERA_PROPERTIES:
            prop_id = self._property_id(item)
            raw = self._read_raw(item)
            if prop_id is None:
                capabilities[item.key] = {
                    "label": item.label,
                    "supported": False,
                    "reason": "Not exposed by this OpenCV backend",
                    "range": None,
                    "step": None,
                    "control": "toggle" if item.automatic else "number",
                }
                continue
            write_only_ae = item.key == "auto_exposure" and "DSHOW" in self._backend.upper()
            if raw is None and not write_only_ae:
                capabilities[item.key] = {
                    "label": item.label,
                    "supported": False,
                    "reason": "Not supported by this camera/backend",
                    "range": None,
                    "step": None,
                    "control": "toggle" if item.automatic else "number",
                }
                continue
            capabilities[item.key] = {
                "label": item.label,
                "supported": True,
                "readable": raw is not None,
                "write_verified": False,
                "reason": "Write support is checked when requested; OpenCV does not expose control ranges",
                # These are intentionally null. OpenCV's VideoCapture API does
                # not report property min/max/step reliably across UVC drivers.
                "range": None,
                "step": None,
                "control": "toggle" if item.automatic else "number",
            }
        return capabilities

    def camera_details(self) -> dict[str, object]:
        with self.lock:
            width = self._read_raw(CameraProperty("width", "Width", "CAP_PROP_FRAME_WIDTH")) or 0
            height = self._read_raw(CameraProperty("height", "Height", "CAP_PROP_FRAME_HEIGHT")) or 0
            fps = self._read_raw(CameraProperty("fps", "FPS", "CAP_PROP_FPS"))
            return {
                "device_index": self.camera_index,
                # VideoCapture has no standard device-name getter. Do not claim
                # a guessed EMEET model name when the driver has not exposed one.
                "device_name": f"Camera #{self.camera_index}",
                "device_name_reported": False,
                "backend": self._backend,
                "capture_resolution": [int(width), int(height)],
                "fps": self._number(fps),
                "pixel_format": self._pixel_format(),
                "convert_rgb": self._read_raw(CameraProperty("convert_rgb", "Color conversion", "CAP_PROP_CONVERT_RGB")),
                "output_color_order": "BGR (OpenCV decoded frames)",
                "profile_name": self._profile.get("profile_name") or ("Inspection Profile" if self.profile_path.exists() else None),
            }

    def _pixel_format(self) -> dict[str, object]:
        raw = self._read_raw(CameraProperty("fourcc", "Pixel format", "CAP_PROP_FOURCC"))
        if raw is None or raw <= 0:
            return {"fourcc": None, "code": self._number(raw)}
        code = int(raw)
        label = "".join(chr((code >> (8 * index)) & 0xff) for index in range(4))
        return {"fourcc": label if label.isprintable() else None, "code": code}

    def capabilities(self) -> dict[str, object]:
        with self.lock:
            if self._capture is None:
                unavailable = {
                    item.key: {
                        "label": item.label,
                        "supported": False,
                        "reason": "Start the inspection camera to query this control",
                        "range": None,
                        "step": None,
                        "control": "toggle" if item.automatic else "number",
                    }
                    for item in CAMERA_PROPERTIES
                }
                return {"available": False, "reason": "Camera is not running.", "properties": unavailable}
            return {"available": True, "properties": {key: dict(value) for key, value in self._capabilities.items()}}

    def get_camera_capabilities(self) -> dict[str, object]:
        """Named public API for callers that should not inspect internals."""

        return self.capabilities()

    def settings(self) -> dict[str, object]:
        with self.lock:
            return {
                "available": self._capture is not None,
                "actual": self._read_all_settings() if self._capture is not None else {},
                "requested_automatic": dict(self._auto_requests),
                "startup": dict(self._startup),
                "camera": self.camera_details(),
                "profile_drift": self.profile_drift(),
            }

    def get_camera_settings(self) -> dict[str, object]:
        """Named public API for current physical-camera readbacks."""

        return self.settings()

    def _require_supported(self, key: str) -> CameraProperty:
        item = PROPERTY_BY_KEY.get(key)
        if item is None:
            raise CameraControlError(f"Unknown camera property: {key}")
        if self._capture is None:
            raise CameraControlError("Camera is not running. Start inspection before changing camera settings.")
        capability = self._capabilities.get(key, {})
        if not capability.get("supported"):
            raise CameraControlError(str(capability.get("reason") or "Not supported by this camera/backend"))
        return item

    def set_camera_property(self, key: str, value: object) -> dict[str, object]:
        """Set one numeric property and return the hardware readback."""

        with self.lock:
            item = self._require_supported(key)
            if item.automatic:
                raise CameraControlError(f"{item.label} must be set as an on/off control.")
            try:
                requested = float(value)
            except (TypeError, ValueError):
                raise CameraControlError(f"{item.label} must be a number.") from None
            if not isfinite(requested):
                raise CameraControlError(f"{item.label} must be finite.")
            prop_id = self._property_id(item)
            assert prop_id is not None
            current = self._read_raw(item)
            if key in {"frame_width", "frame_height", "fps"} and current is not None and self._same_setting(requested, current):
                return {"success": True, "property": key, "requested": self._number(requested),
                        "actual": self._number(current), "skipped": True, "reason": "Already at the requested acquisition setting"}
            try:
                driver_accepted = bool(self._capture.set(prop_id, requested))
            except Exception:
                driver_accepted = False
            actual_raw = self._read_raw(item)
            actual = self._number(actual_raw)
            accepted = bool(driver_accepted and actual_raw is not None and abs(actual_raw - requested) <= max(0.001, abs(requested) * 0.0001))
            if driver_accepted:
                self._capabilities[key]["write_verified"] = True
                partner = AUTOMATIC_PARTNERS.get(key)
                if partner:
                    # A manual write invalidates any earlier automatic request.
                    self._auto_requests.pop(partner, None)
            LOGGER.info("[CAMERA] %s requested=%s actual=%s accepted=%s", item.label, requested, actual, accepted)
            return {
                "success": accepted,
                "property": key,
                "requested": self._number(requested),
                "actual": actual,
                "reason": None if accepted else "Camera/backend did not accept the requested value",
            }

    def _set_auto_property(self, key: str, enabled: object) -> dict[str, object]:
        with self.lock:
            item = self._require_supported(key)
            if not item.automatic:
                raise CameraControlError(f"{item.label} is a numeric control.")
            if not isinstance(enabled, bool):
                raise CameraControlError(f"{item.label} must be true or false.")
            prop_id = self._property_id(item)
            assert prop_id is not None
            # DSHOW/MSMF use 1/0. The fractional convention belongs to V4L2,
            # not DirectShow. Do not try unrelated values on a rejected write.
            candidate = (0.75 if enabled else 0.25) if key == "auto_exposure" and "V4L" in self._backend.upper() else float(enabled)
            driver_accepted = False
            raw: float | None = None
            try:
                driver_accepted = bool(self._capture.set(prop_id, candidate))
            except Exception:
                driver_accepted = False
            raw = self._read_raw(item)
            actual = self._auto_value(key, raw)
            accepted = bool(driver_accepted and (actual is None or actual == enabled))
            if accepted:
                self._auto_requests[key] = enabled
            self._capabilities[key]["write_verified"] = driver_accepted
            LOGGER.info("[CAMERA] %s requested=%s actual=%s raw=%s accepted=%s", item.label, enabled, actual, self._number(raw), accepted)
            return {
                "success": accepted,
                "property": key,
                "requested": enabled,
                "actual": actual,
                "actual_raw": self._number(raw),
                "driver_accepted": driver_accepted,
                "verified": actual is not None and actual == enabled,
                "reason": None if accepted else "Camera/backend did not accept the requested automatic mode",
            }

    def set_auto_exposure(self, enabled: bool) -> dict[str, object]:
        return self._set_auto_property("auto_exposure", enabled)

    def set_auto_white_balance(self, enabled: bool) -> dict[str, object]:
        return self._set_auto_property("auto_white_balance", enabled)

    def set_autofocus(self, enabled: bool) -> dict[str, object]:
        return self._set_auto_property("autofocus", enabled)

    def validate_settings(self, values: dict[str, object]) -> dict[str, str]:
        """Check the entire request without writing to the camera."""
        errors: dict[str, str] = {}
        with self.lock:
            for key, value in values.items():
                try:
                    item = self._require_supported(key)
                    if item.automatic:
                        if not isinstance(value, bool):
                            raise CameraControlError(f"{item.label} must be true or false.")
                    else:
                        if isinstance(value, bool):
                            raise CameraControlError(f"{item.label} must be a finite number.")
                        try:
                            number = float(value)
                        except (TypeError, ValueError):
                            raise CameraControlError(f"{item.label} must be a finite number.") from None
                        if not isfinite(number):
                            raise CameraControlError(f"{item.label} must be a finite number.")
                except CameraControlError as exc:
                    errors[key] = str(exc)
        return errors

    def apply_settings(self, values: dict[str, object]) -> dict[str, object]:
        """Preflight all controls and report best-effort rollback of rejected writes."""
        with self.lock:
            requested = dict(values)
            before = self.settings()["actual"]
            before_requests = dict(self._auto_requests)
            # Auto-controlled numeric readings are observations, not setpoints.
            # Replaying them disables the automatic mode on Windows drivers.
            skipped = {key for key, partner in AUTOMATIC_PARTNERS.items()
                       if key in values and values.get(partner) is True}
            effective = {key: value for key, value in values.items() if key not in skipped}
            errors = self.validate_settings(effective)
            results: dict[str, dict[str, object]] = {}
            rollback: dict[str, dict[str, object]] = {}
            if errors:
                for key, value in values.items():
                    results[key] = {"success": False, "property": key, "requested": value,
                                    "actual": before.get(key), "reason": errors.get(key, "Not applied because another setting is invalid.")}
            else:
                for key in skipped:
                    results[key] = {"success": True, "property": key, "requested": values[key],
                                    "actual": before.get(key), "skipped": True,
                                    "reason": "Managed by the requested automatic camera mode"}
                attempted: list[str] = []
                # Resolution/FPS and manual values can reset camera modes.
                # Apply automatic flags last, independent of JSON/YAML order.
                ordered = sorted(effective.items(), key=lambda entry: PROPERTY_BY_KEY[entry[0]].automatic)
                for key, value in ordered:
                    item = PROPERTY_BY_KEY[key]
                    attempted.append(key)
                    try:
                        result = self._set_auto_property(key, value) if item.automatic else self.set_camera_property(key, value)
                    except Exception as exc:
                        result = {"success": False, "property": key, "requested": value, "actual": self._read_value(item), "reason": str(exc)}
                    results[key] = result
                    if not result["success"]:
                        restore_keys = list(reversed(attempted))
                        for manual in attempted:
                            partner = AUTOMATIC_PARTNERS.get(manual)
                            if partner and self._capabilities.get(partner, {}).get("supported") and partner not in restore_keys:
                                restore_keys.append(partner)
                        restore_keys.sort(key=lambda name: PROPERTY_BY_KEY[name].automatic)
                        for prior in restore_keys:
                            previous = before.get(prior)
                            if previous is None:
                                previous = before_requests.get(prior)
                            if previous is None:
                                rollback[prior] = {"success": False, "reason": "Previous readback unavailable."}
                                continue
                            try:
                                item = PROPERTY_BY_KEY[prior]
                                rollback[prior] = self._set_auto_property(prior, previous) if item.automatic else self.set_camera_property(prior, previous)
                            except Exception as exc:
                                rollback[prior] = {"success": False, "reason": str(exc)}
                        for pending, pending_value in values.items():
                            if pending not in results:
                                results[pending] = {"success": False, "property": pending, "requested": pending_value,
                                                    "actual": before.get(pending), "reason": "Not applied after another setting failed."}
                        break
            actual = self.settings()["actual"]
            observed = set(values) | {AUTOMATIC_PARTNERS[key] for key in values if key in AUTOMATIC_PARTNERS}
            changed = any(before.get(key) != actual.get(key) for key in observed)
            changed = changed or before_requests != self._auto_requests
            return {"success": bool(results) and all(bool(result["success"]) for result in results.values()),
                    "requested": requested, "before": before, "actual": actual, "results": results,
                    "rollback": rollback, "changed": changed}

    def initialize_camera_settings(self) -> dict[str, object]:
        """Restore explicit calibration or request the driver's AE/AWB defaults.

        Old unlocked, unconfirmed profiles were captured after destructive
        probing and can contain invented 'auto off' states. They are not safe
        startup setpoints. Locked/confirmed calibrations remain explicit policy;
        newly saved profiles carry the corrected control schema version.
        """

        with self.lock:
            profile = self._profile
            confirmation = profile.get("operator_confirmation")
            explicit = (profile.get("control_schema_version") == CONTROL_SCHEMA_VERSION
                        or profile.get("locked") is True
                        or isinstance(confirmation, Mapping) and confirmation.get("confirmed") is True)
            same_device = profile.get("device_index", self.camera_index) == self.camera_index
            explicit = explicit and same_device
            if explicit and isinstance(profile.get("settings"), Mapping) and profile["settings"]:
                result = self.load_camera_profile()
                policy = "saved_profile"
            else:
                results = {}
                for key in ("auto_exposure", "auto_white_balance"):
                    if self._capabilities.get(key, {}).get("supported"):
                        results[key] = self._set_auto_property(key, True)
                    else:
                        results[key] = {"success": False, "property": key,
                                        "reason": "Automatic control is not exposed by this camera/backend"}
                result = {"success": all(item["success"] for item in results.values()),
                          "results": results, "actual": self._read_all_settings(), "profile": dict(profile)}
                policy = ("automatic_defaults" if not profile else "different_device_automatic_defaults"
                          if not same_device else "legacy_profile_automatic_defaults")
            self._startup = {"policy": policy, "success": result["success"], "results": result["results"]}
            LOGGER.info("[CAMERA] Startup adjustment policy: %s; results=%s", policy, result["results"])
            return result

    def reset_camera_settings(self) -> dict[str, object]:
        """Restore the values reported when this camera was opened, never defaults."""

        if not self._opened_settings:
            raise CameraControlError("No camera values are available to restore yet.")
        values = dict(self._opened_settings)
        for key, partner in AUTOMATIC_PARTNERS.items():
            if key in values and partner not in values:
                if partner in self._auto_requests:
                    values[partner] = self._auto_requests[partner]
                else:
                    # The original automatic mode cannot be reconstructed.
                    # Replaying its numeric observation would force manual mode.
                    values.pop(key, None)
        return self.apply_settings(values)

    @staticmethod
    def _profile_metadata(value: Mapping[str, object] | None, *, label: str) -> dict[str, object]:
        """Accept JSON/YAML-safe operator metadata without inventing values."""

        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise CameraControlError(f"{label} must be an object.")
        result: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip()
            if not key:
                raise CameraControlError(f"{label} contains an empty field name.")
            if isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
                result[key] = raw_value
            else:
                raise CameraControlError(f"{label}.{key} must be a scalar value.")
        return result

    @classmethod
    def _reference_scene_records(cls, value: Mapping[str, object] | None) -> dict[str, dict[str, object]]:
        """Validate reference-scene records while retaining their measured stats."""

        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise CameraControlError("reference_scenes must be an object.")
        records: dict[str, dict[str, object]] = {}
        for raw_name, raw_record in value.items():
            name = str(raw_name).strip()
            if not name or not isinstance(raw_record, Mapping):
                raise CameraControlError("Each reference scene needs a non-empty name and object record.")
            record: dict[str, object] = {}
            for raw_key, raw_value in raw_record.items():
                key = str(raw_key).strip()
                if not key:
                    raise CameraControlError(f"reference_scenes.{name} contains an empty field name.")
                if key == "statistics" and isinstance(raw_value, Mapping):
                    statistics: dict[str, object] = {}
                    for raw_statistic, raw_statistic_value in raw_value.items():
                        statistic = str(raw_statistic).strip()
                        if not statistic:
                            raise CameraControlError(f"reference_scenes.{name}.statistics contains an empty field name.")
                        if isinstance(raw_statistic_value, Mapping):
                            statistics[statistic] = cls._profile_metadata(
                                raw_statistic_value,
                                label=f"reference_scenes.{name}.statistics.{statistic}",
                            )
                        elif isinstance(raw_statistic_value, (str, int, float, bool)) or raw_statistic_value is None:
                            statistics[statistic] = raw_statistic_value
                        else:
                            raise CameraControlError(
                                f"reference_scenes.{name}.statistics.{statistic} must be a scalar or object."
                            )
                    record[key] = statistics
                elif isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
                    record[key] = raw_value
                else:
                    raise CameraControlError(f"reference_scenes.{name}.{key} must be a scalar or statistics object.")
            records[name] = record
        return records

    @staticmethod
    def _resolution(value: object) -> list[int] | None:
        if value is None:
            return None
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise CameraControlError("processing_resolution must contain [width, height].")
        try:
            width, height = (int(value[0]), int(value[1]))
        except (TypeError, ValueError) as exc:
            raise CameraControlError("processing_resolution must contain integer dimensions.") from exc
        if width <= 0 or height <= 0:
            raise CameraControlError("processing_resolution dimensions must be positive.")
        return [width, height]

    @staticmethod
    def _same_setting(expected: object, actual: object) -> bool:
        if isinstance(expected, bool):
            return actual is expected
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            if not isinstance(actual, (int, float)) or isinstance(actual, bool):
                return False
            return abs(float(expected) - float(actual)) <= max(0.001, abs(float(expected)) * 0.0001)
        return expected == actual

    @classmethod
    def _calibration_material_changed(
        cls,
        existing: Mapping[str, object],
        candidate: Mapping[str, object],
    ) -> bool:
        """Return whether a saved calibration confirmation is no longer valid.

        Lock state and the live monitoring reference are intentionally excluded:
        locking/unlocking a profile must not make an operator repeat calibration.
        Hardware readbacks, acquisition details, and recorded reference scenes
        are calibration evidence, so a change to any of them requires a new
        explicit operator confirmation.
        """

        expected_settings = existing.get("settings")
        actual_settings = candidate.get("settings")
        if not isinstance(expected_settings, Mapping) or not isinstance(actual_settings, Mapping):
            return True
        if set(expected_settings) != set(actual_settings):
            return True
        if any(
            not cls._same_setting(expected_settings[key], actual_settings[key])
            for key in expected_settings
        ):
            return True

        for field in (
            "preferred_backend",
            "camera_identity",
            "capture_resolution",
            "processing_resolution",
            "fps",
            "unsupported_properties",
            "reference_scenes",
        ):
            if existing.get(field) != candidate.get(field):
                return True
        return False

    def profile_drift(self) -> dict[str, object]:
        """Report profile reproducibility warnings without changing camera or grade.

        This intentionally does not attempt to repair a changed camera.  A
        validation operator needs a visible warning and a new session/profile,
        not an unrecorded automatic adjustment.
        """

        with self.lock:
            profile = dict(self._profile)
            if not profile:
                return {"profile_available": False, "reproducible": None, "warnings": []}
            warnings: list[dict[str, object]] = []
            if self._capture is None:
                warnings.append(
                    {
                        "code": "CAMERA_DISCONNECTED",
                        "message": "A saved inspection profile exists but the camera is not connected.",
                    }
                )
                return {"profile_available": True, "reproducible": False, "warnings": warnings}

            expected_backend = str(profile.get("preferred_backend") or "").strip()
            if expected_backend and expected_backend != self._backend:
                warnings.append(
                    {
                        "code": "CAMERA_BACKEND_CHANGED",
                        "expected": expected_backend,
                        "actual": self._backend,
                        "message": "The active camera backend differs from the saved inspection profile.",
                    }
                )
            expected_settings = profile.get("settings")
            actual_settings = self._read_all_settings()
            if isinstance(expected_settings, Mapping):
                for raw_key, expected in expected_settings.items():
                    key = str(raw_key)
                    partner = AUTOMATIC_PARTNERS.get(key)
                    if partner and expected_settings.get(partner) is True:
                        # Exposure/gain/WB/focus naturally vary under automation.
                        continue
                    actual = actual_settings.get(key)
                    if key in self._auto_requests and actual is None and self._auto_requests[key] == expected:
                        warnings.append({
                            "code": "CAMERA_PROPERTY_UNVERIFIED", "property": key,
                            "expected": expected, "actual": None,
                            "message": f"The driver accepted {key!r}, but this backend cannot read its state back.",
                        })
                        continue
                    if actual is None:
                        warnings.append(
                            {
                                "code": "CAMERA_PROPERTY_UNAVAILABLE",
                                "property": key,
                                "expected": expected,
                                "actual": actual,
                                "message": f"Saved camera property {key!r} is unavailable on the active device/backend.",
                            }
                        )
                    elif not self._same_setting(expected, actual):
                        warnings.append(
                            {
                                "code": "CAMERA_PROPERTY_CHANGED",
                                "property": key,
                                "expected": expected,
                                "actual": actual,
                                "message": f"Saved camera property {key!r} differs from its hardware readback.",
                            }
                        )
            expected_resolution = profile.get("capture_resolution")
            actual_resolution = self.camera_details().get("capture_resolution")
            if isinstance(expected_resolution, list) and expected_resolution and expected_resolution != actual_resolution:
                warnings.append(
                    {
                        "code": "CAMERA_RESOLUTION_CHANGED",
                        "expected": expected_resolution,
                        "actual": actual_resolution,
                        "message": "Capture resolution differs from the saved inspection profile.",
                    }
                )
            return {"profile_available": True, "reproducible": not warnings, "warnings": warnings}

    def _read_profile(self) -> dict[str, object]:
        if not self.profile_path.exists():
            return {}
        try:
            payload = yaml.safe_load(self.profile_path.read_text(encoding="utf-8")) or {}
            camera = payload.get("camera") if isinstance(payload, dict) else None
            return dict(camera) if isinstance(camera, dict) else {}
        except (OSError, yaml.YAMLError) as exc:
            LOGGER.warning("[CAMERA] Could not read inspection profile %s: %s", self.profile_path, exc)
            return {}

    def save_camera_profile(
        self,
        reference: dict[str, object] | None = None,
        *,
        locked: bool = False,
        reference_scenes: Mapping[str, object] | None = None,
        processing_resolution: object = None,
    ) -> dict[str, object]:
        """Persist actual readbacks and explicit operator-recorded context.

        Saving a profile never marks calibration complete.  Explicit operator
        confirmation is a separate action so future studies can distinguish a
        saved driver profile from a reviewed physical inspection setup.
        """

        with self.lock:
            if self._capture is None:
                raise CameraControlError("Camera is not running. Start inspection before saving a profile.")
            actual = self._read_all_settings()
            settings = {
                key: actual.get(key)
                for key, capability in self._capabilities.items()
                if capability.get("supported") and actual.get(key) is not None
            }
            setting_sources = {key: "hardware_readback" for key in settings}
            for key, requested in self._auto_requests.items():
                if actual.get(key) is None:
                    settings[key] = requested
                    setting_sources[key] = "driver_accepted_request"
            for key, partner in AUTOMATIC_PARTNERS.items():
                if settings.get(partner) is True:
                    settings.pop(key, None)
                    setting_sources.pop(key, None)
            unsupported_properties = {
                key: str(capability.get("reason") or "Not supported by this camera/backend")
                for key, capability in self._capabilities.items()
                if not capability.get("supported")
            }
            existing = dict(self._profile)
            existing_reference = existing.get("reference") if isinstance(existing.get("reference"), Mapping) else {}
            existing_scenes = existing.get("reference_scenes") if isinstance(existing.get("reference_scenes"), Mapping) else {}
            merged_scenes = {str(name): dict(record) for name, record in existing_scenes.items() if isinstance(record, Mapping)}
            if reference_scenes is not None:
                merged_scenes.update(self._reference_scene_records(reference_scenes))
            # ``camera_details`` uses the currently persisted profile to
            # decorate status with a display name. Normalize that display-only
            # field before comparing/saving identity so a lock transition does
            # not look like a physical camera change on the first re-save.
            details = dict(self.camera_details())
            details["profile_name"] = str(existing.get("profile_name") or "Inspection Profile")
            resolved_processing_resolution = self._resolution(processing_resolution)
            if resolved_processing_resolution is None:
                prior_resolution = existing.get("processing_resolution")
                resolved_processing_resolution = list(prior_resolution) if isinstance(prior_resolution, list) else None
            candidate = {
                "control_schema_version": CONTROL_SCHEMA_VERSION,
                "profile_id": str(existing.get("profile_id") or f"camera-{self.camera_index}-{uuid4().hex[:12]}"),
                "profile_name": str(existing.get("profile_name") or "Inspection Profile"),
                "device_index": self.camera_index,
                "preferred_backend": self._backend,
                "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "locked": bool(locked),
                "camera_identity": details,
                "capture_resolution": list(details.get("capture_resolution") or []),
                "processing_resolution": resolved_processing_resolution,
                "fps": details.get("fps"),
                "settings": settings,
                "setting_sources": setting_sources,
                "unsupported_properties": unsupported_properties,
                "reference": dict(reference if reference is not None else existing_reference),
                "reference_scenes": merged_scenes,
                "installation": self._profile_metadata(
                    existing.get("installation") if isinstance(existing.get("installation"), Mapping) else None,
                    label="installation",
                ),
                "operator_confirmation": dict(existing.get("operator_confirmation") or {
                    "confirmed": False,
                    "confirmed_at": None,
                    "operator_name": None,
                }),
            }
            existing_confirmation = existing.get("operator_confirmation")
            if (
                isinstance(existing_confirmation, Mapping)
                and bool(existing_confirmation.get("confirmed"))
                and self._calibration_material_changed(existing, candidate)
            ):
                candidate["operator_confirmation"] = {
                    "confirmed": False,
                    "confirmed_at": None,
                    "operator_name": None,
                }
                LOGGER.info(
                    "[CAMERA] Cleared prior calibration confirmation because calibration evidence changed."
                )
            self._profile = candidate
            payload = {"camera": self._profile}
            try:
                self.profile_path.parent.mkdir(parents=True, exist_ok=True)
                self.profile_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            except OSError as exc:
                raise CameraControlError(f"Could not save camera profile: {exc}") from exc
            LOGGER.info("[CAMERA] Saved inspection profile to %s", self.profile_path)
            return {"success": True, "profile": dict(self._profile), "actual": actual}

    def confirm_camera_profile(
        self,
        *,
        operator_confirmed: object,
        operator_name: object = None,
        installation: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Record an explicit, auditable operator confirmation of calibration.

        The caller must first save a profile and record an empty-conveyor
        reference.  This does not alter hardware values or grading behavior.
        """

        if operator_confirmed is not True:
            raise CameraControlError("operator_confirmed must be true to confirm an inspection camera profile.")
        with self.lock:
            profile = dict(self._profile or self._read_profile())
            if not profile:
                raise CameraControlError("Save an inspection camera profile before confirming calibration.")
            scenes = profile.get("reference_scenes")
            if not isinstance(scenes, Mapping) or not isinstance(scenes.get("empty_conveyor"), Mapping):
                raise CameraControlError("Record an empty_conveyor reference scene before confirming calibration.")
            combined_installation = self._profile_metadata(
                profile.get("installation") if isinstance(profile.get("installation"), Mapping) else None,
                label="installation",
            )
            combined_installation.update(self._profile_metadata(installation, label="installation"))
            missing = [name for name in REQUIRED_INSTALLATION_FIELDS if not str(combined_installation.get(name) or "").strip()]
            if missing:
                raise CameraControlError(
                    "Operator confirmation requires installation metadata for: " + ", ".join(missing) + "."
                )
            name = str(operator_name).strip() if operator_name is not None else ""
            profile["installation"] = combined_installation
            profile["operator_confirmation"] = {
                "confirmed": True,
                "confirmed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "operator_name": name or None,
            }
            profile["saved_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            self._profile = profile
            try:
                self.profile_path.parent.mkdir(parents=True, exist_ok=True)
                self.profile_path.write_text(yaml.safe_dump({"camera": profile}, sort_keys=False), encoding="utf-8")
            except OSError as exc:
                raise CameraControlError(f"Could not update camera profile confirmation: {exc}") from exc
            return {"success": True, "profile": dict(profile)}

    def load_camera_profile(self) -> dict[str, object]:
        """Apply a saved profile to the attached camera and read every value back."""

        self._profile = self._read_profile()
        if self._profile.get("device_index", self.camera_index) != self.camera_index:
            raise CameraControlError("The saved inspection profile belongs to a different camera index. Save a profile for the active camera first.")
        values = self._profile.get("settings") if isinstance(self._profile.get("settings"), dict) else {}
        if not values:
            raise CameraControlError("No saved inspection profile was found.")
        result = self.apply_settings(dict(values))
        LOGGER.info("[CAMERA] Loaded inspection profile: success=%s", result["success"])
        return {**result, "profile": dict(self._profile)}

    def profile(self) -> dict[str, object]:
        with self.lock:
            return dict(self._profile)
