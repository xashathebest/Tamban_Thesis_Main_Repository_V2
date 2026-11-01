"""Single-owner webcam and inference worker."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
import logging
import os
from pathlib import Path
from threading import Event, Lock, RLock, Thread, Thread as FinalizerThread, current_thread
from time import monotonic
from typing import Any, Mapping

import numpy as np

from src.api.camera_controls import CameraControlError, CameraHardwareController
from src.api.domain import InspectionState, QualitySummary
from src.api.runtime import PART_PREVIEW_MODE, WHOLE_FISH_MODE
from src.api.runtime_diagnostics import LatestFrameQueue, RuntimeDiagnostics
from src.api.raw_preview import RawPreview
from src.inference.association import ParentAnchor
from src.inference.body_width import boxes_overlap
from src.inference.yolo_fish_detector import YoloFishDetector
from src.inference.yolo_quality_model import MAX_QUALITY_ROI_PADDING, QUALITY_INFERENCE_MODES, FishQualityObservation, YoloQualityModel
from src.inference.part_types import PartDetection
from src.inference.part_model import YoloPartModel
from src.inference.preprocessing import CropBounds, crop_fish, generate_runtime_fish_mask, translate_bbox_to_frame
from src.features.damage import analyze_surface_damage


LOGGER = logging.getLogger(__name__)

PART_GRADE_COLORS = {
    "Class A": (76, 175, 80),
    "Class B": (255, 152, 0),
    "Class C": (170, 90, 205),
    "Rejected": (45, 45, 225),
}


def _draw_readable_label(image: Any, text: str, x: int, y: int, color: tuple[int, int, int], cv2: Any) -> None:
    """Draw a high-contrast label above a box, moving it inside the box when needed."""

    height, width = image.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 1.5
    thickness = 4
    padding = 12
    (text_width, text_height), baseline = cv2.getTextSize(text, font, scale, thickness)
    left = max(0, min(int(x), max(0, width - text_width - padding * 2)))
    top = int(y) - text_height - baseline - padding * 2
    if top < 0:
        top = min(max(0, int(y)), max(0, height - text_height - baseline - padding * 2))
    right = min(width - 1, left + text_width + padding * 2)
    bottom = min(height - 1, top + text_height + baseline + padding * 2)
    cv2.rectangle(image, (left, top), (right, bottom), (28, 35, 42), -1)
    cv2.rectangle(image, (left, top), (right, bottom), color, 2)
    cv2.putText(image, text, (left + padding, bottom - padding - baseline), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)


class CameraInspectionService:
    """Own exactly one camera reader and one inference loop."""

    def __init__(
        self,
        state: InspectionState,
        model: YoloFishDetector | YoloPartModel,
        camera_index: int = 0,
        runtime_mode: str = WHOLE_FISH_MODE,
        quality_model: YoloQualityModel | None = None,
        quality_interval: int = 3,
        quality_roi_padding: int = 0,
        quality_inference_mode: str = "crop",
        # Compatibility keyword for pre-existing mocked tests and an older
        # experimental adapter. Production passes ``quality_model``.
        segmenter: Any | None = None,
        segmentation_interval: int | None = None,
        segmentation_roi_padding: int | None = None,
        camera_profile_path: Path | None = None,
    ) -> None:
        if runtime_mode not in {WHOLE_FISH_MODE, PART_PREVIEW_MODE}:
            raise ValueError(f"Unsupported runtime mode: {runtime_mode}")
        if state.runtime_mode != runtime_mode:
            raise ValueError("Camera service and inspection state runtime modes must match.")
        self.state = state
        self.model = model
        self.camera_index = camera_index
        self.runtime_mode = runtime_mode
        self.quality_model = quality_model if quality_model is not None else segmenter
        if segmentation_interval is not None:
            quality_interval = segmentation_interval
        if segmentation_roi_padding is not None:
            quality_roi_padding = segmentation_roi_padding
        if quality_interval <= 0:
            raise ValueError("FISH_QUALITY_INTERVAL must be greater than zero.")
        if quality_inference_mode not in QUALITY_INFERENCE_MODES:
            raise ValueError(f"quality_inference_mode must be one of: {', '.join(QUALITY_INFERENCE_MODES)}.")
        if isinstance(quality_roi_padding, bool) or not isinstance(quality_roi_padding, int) or not 0 <= quality_roi_padding <= MAX_QUALITY_ROI_PADDING:
            raise ValueError(f"FISH_QUALITY_ROI_PADDING must be an integer between 0 and {MAX_QUALITY_ROI_PADDING}.")
        self.quality_interval = quality_interval
        self.quality_roi_padding = quality_roi_padding
        self.quality_inference_mode = quality_inference_mode
        self.debug_inference = os.getenv("LEMURU_DEBUG_INFERENCE", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.debug_enabled = os.getenv("LEMURU_RUNTIME_DIAGNOSTICS", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.debug_paused = False
        self.debug_capture_limit = max(1, int(os.getenv("LEMURU_DEBUG_CAPTURE_LIMIT", "50")))
        self._debug_capture_count = 0
        self._debug_session = datetime.now().astimezone().strftime("session_%Y%m%d_%H%M%S")
        self._debug_root = Path(__file__).resolve().parents[2] / "results" / "debug" / "model2" / self._debug_session
        self._hard_negative_root = Path(__file__).resolve().parents[2] / "results" / "hard_negatives" / self._debug_session
        self._hard_negative_records: dict[str, dict[str, object]] = {}
        # Startup-only experiment switch; does not change debug capture or inference.
        telemetry_recording = os.getenv("FISH_RUNTIME_TELEMETRY", "1").strip().lower() not in {"0", "false", "no", "off"}
        self._runtime_metrics = RuntimeDiagnostics(enabled=telemetry_recording)
        self._latest_frames = LatestFrameQueue()
        self.raw_preview = RawPreview(os.getenv("FISH_RAW_PREVIEW_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"})
        self._capture_thread: Thread | None = None
        self._latest_part_overlays: dict[int, tuple[FishQualityObservation, CropBounds, int]] = {}
        self._latest_damage_evidence: dict[int, dict[str, object]] = {}
        self._skipped_model2_reasons: dict[str, int] = {}
        self._last_model1_debug: list[dict[str, object]] = []
        self._frame_index = 0
        # The underlying tracker may restart its IDs at zero/one after Stop,
        # calibration, or a policy change. Completed events survive those
        # operations, so reserve a fresh range for each tracker epoch.
        self._highest_track_id: int | None = None
        self._track_id_epoch_offset = 0
        self._last_segmented_frame: dict[int, int] = {}
        self._track_grades: dict[int, QualitySummary] = {}
        self._model2_failure_count = 0
        self._model2_retry_after = 0.0
        self._lifecycle_lock = Lock()
        self._processing_lock = RLock()
        self._camera_state_lock = RLock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._finalizer_for: Thread | None = None
        self._models_prepared = False
        self._finalized = Event()
        self._finalized.set()
        self.on_worker_exit = None
        profile_path = camera_profile_path or Path(__file__).resolve().parents[2] / "configs" / "camera_settings.yaml"
        self.camera_controls = CameraHardwareController(camera_index, profile_path)
        self._calibration_mode = False
        initial_profile = self.camera_controls.profile()
        self._camera_locked = bool(initial_profile.get("locked", False))
        existing_scenes = initial_profile.get("reference_scenes")
        self._reference_scenes: dict[str, dict[str, object]] = (
            {
                str(name): dict(record)
                for name, record in existing_scenes.items()
                if isinstance(record, Mapping)
            }
            if isinstance(existing_scenes, Mapping)
            else {}
        )
        self._image_statistics: dict[str, object] = {}
        # Retain only the latest bounded camera-open diagnostics.  These are
        # hardware/operator facts; they never affect detection or grading.
        self._camera_open_attempts: list[dict[str, object]] = []
        if isinstance(self.quality_model, YoloQualityModel):
            self.quality_model.set_debug_raw_output(self.debug_enabled)

    def _reset_model_tracker(self) -> None:
        """Start a new ID range while preserving completed in-memory events."""
        reset_tracker = getattr(self.model, "reset_tracker", None)
        if callable(reset_tracker):
            reset_tracker()
        self._track_id_epoch_offset = self._highest_track_id if self._highest_track_id is not None else 0

    def _scope_tracker_ids(self, detections: list[Any]) -> list[Any]:
        """Keep native tracker IDs stable and distinct across tracker resets."""
        scoped = []
        for detection in detections:
            if detection.track_id is None:
                scoped.append(detection)
                continue
            native_id = int(detection.track_id)
            if native_id < 0:
                # Negative IDs denote untracked detections, not identities.
                scoped.append(replace(detection, track_id=None))
                continue
            track_id = native_id + self._track_id_epoch_offset
            self._highest_track_id = max(self._highest_track_id if self._highest_track_id is not None else track_id, track_id)
            scoped.append(replace(detection, track_id=track_id) if track_id != native_id else detection)
        return scoped

    def _clear_calibration_tracking(self) -> None:
        """Drop transient IDs so calibration frames can never become events."""

        with self._processing_lock:
            self._reset_model_tracker()
            self.state.tracking.reset_active_tracks()
            self._frame_index = 0
            self._model2_failure_count = 0
            self._model2_retry_after = 0.0
            self._last_segmented_frame.clear()
            self._track_grades.clear()
            self._latest_part_overlays.clear()
            self._latest_frames.clear()
            if self.quality_model is not None and hasattr(self.quality_model, "reset_tracks"):
                self.quality_model.reset_tracks()

    def reset_active_policy_evidence(self) -> None:
        """End all active fish evidence before a new acquisition policy starts.

        Completed counts/history remain intact; callers rotate the durable
        session snapshot after the physical-camera readback has succeeded.
        """

        self._clear_calibration_tracking()

    def calibration_mode(self) -> bool:
        with self._camera_state_lock:
            return self._calibration_mode

    def set_calibration_mode(self, enabled: bool) -> dict[str, object]:
        """Toggle the non-recording calibration path without restarting capture."""

        if not isinstance(enabled, bool):
            raise CameraControlError("calibration_mode must be true or false.")
        with self._camera_state_lock:
            if enabled and self._camera_locked:
                raise CameraControlError("Camera settings are locked. Unlock the inspection camera before calibration.")
            changed = self._calibration_mode != enabled
            self._calibration_mode = enabled
        if changed:
            # Clear state on both enter and exit, preventing a partial crossing
            # before/after calibration from ever appearing in history.
            self._clear_calibration_tracking()
        return self.camera_status()

    def lock_camera_settings(self, locked: bool) -> dict[str, object]:
        """Make calibration controls read-only until an operator unlocks them."""

        if not isinstance(locked, bool):
            raise CameraControlError("locked must be true or false.")
        # Retain lock state with the actual hardware readback so a restart does
        # not silently turn a deliberately locked inspection camera editable.
        if self.camera_controls.connected:
            self.camera_controls.save_camera_profile(
                self._image_statistics,
                locked=locked,
                reference_scenes=self._reference_scenes,
                processing_resolution=self._processing_resolution(),
            )
        with self._camera_state_lock:
            self._camera_locked = locked
            if locked:
                self._calibration_mode = False
        if locked:
            self._clear_calibration_tracking()
        return self.camera_status()

    def _require_camera_adjustment(self) -> None:
        with self._camera_state_lock:
            if self._camera_locked:
                raise CameraControlError("Camera settings are locked. Unlock the inspection camera before making changes.")
            if not self._calibration_mode:
                raise CameraControlError("Enable Calibration Mode before changing physical camera settings.")

    def update_camera_settings(self, values: dict[str, object]) -> dict[str, object]:
        self._require_camera_adjustment()
        return self.camera_controls.apply_settings(values)

    def reset_camera_settings(self) -> dict[str, object]:
        self._require_camera_adjustment()
        return self.camera_controls.reset_camera_settings()

    def _processing_resolution(self) -> list[int] | None:
        snapshot = self.state.snapshot()
        frame_size = snapshot.get("frame_size") if isinstance(snapshot, Mapping) else None
        if not isinstance(frame_size, (list, tuple)) or len(frame_size) != 2:
            return None
        try:
            width, height = int(frame_size[0]), int(frame_size[1])
        except (TypeError, ValueError):
            return None
        return [width, height] if width > 0 and height > 0 else None

    def save_camera_profile(self) -> dict[str, object]:
        self._require_camera_adjustment()
        return self.camera_controls.save_camera_profile(
            self._image_statistics,
            locked=self._camera_locked,
            reference_scenes=self._reference_scenes,
            processing_resolution=self._processing_resolution(),
        )

    def record_camera_reference(self, scene_type: object, note: object = None) -> dict[str, object]:
        """Retain measured, calibration-only reference-scene statistics.

        The operator declares the scene type; the service never guesses whether
        a frame is an empty conveyor or a representative fish.  The resulting
        data are informational acquisition evidence and never reach grading.
        """

        self._require_camera_adjustment()
        name = str(scene_type).strip()
        if name not in {"empty_conveyor", "representative_fish"}:
            raise CameraControlError("scene_type must be 'empty_conveyor' or 'representative_fish'.")
        comment = str(note).strip() if note is not None else ""
        with self._camera_state_lock:
            statistics = dict(self._image_statistics)
            if not statistics:
                raise CameraControlError("Capture at least one calibration frame before recording a reference scene.")
            record = {
                "scene_type": name,
                "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "operator_note": comment or None,
                "statistics": statistics,
            }
            self._reference_scenes[name] = record
        return {"success": True, "reference_scene": record, "pending_reference_scenes": dict(self._reference_scenes)}

    def confirm_camera_profile(
        self,
        *,
        operator_confirmed: object,
        operator_name: object = None,
        installation: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Persist explicit operator confirmation after a saved reference profile."""

        self._require_camera_adjustment()
        return self.camera_controls.confirm_camera_profile(
            operator_confirmed=operator_confirmed,
            operator_name=operator_name,
            installation=installation,
        )

    def load_camera_profile(self) -> dict[str, object]:
        self._require_camera_adjustment()
        result = self.camera_controls.load_camera_profile()
        with self._camera_state_lock:
            self._camera_locked = bool(result.get("profile", {}).get("locked", False)) if isinstance(result.get("profile"), dict) else False
            if self._camera_locked:
                self._calibration_mode = False
        return result

    def camera_status(self) -> dict[str, object]:
        """Return hardware readbacks and acquisition-monitoring warnings only."""

        data = self.camera_controls.settings()
        capabilities = self.camera_controls.capabilities()
        profile = self.camera_controls.profile()
        with self._camera_state_lock:
            calibration_mode = self._calibration_mode
            locked = self._camera_locked
            statistics = dict(self._image_statistics)
            pending_reference_scenes = dict(self._reference_scenes)
            open_attempts = [dict(item) for item in self._camera_open_attempts]
        warnings: list[dict[str, object]] = []
        drift = data.get("profile_drift") if isinstance(data.get("profile_drift"), Mapping) else {}
        for item in drift.get("warnings", []) if isinstance(drift, Mapping) else []:
            if isinstance(item, Mapping):
                warnings.append(dict(item))
        scenes = profile.get("reference_scenes") if isinstance(profile.get("reference_scenes"), Mapping) else {}
        empty = scenes.get("empty_conveyor") if isinstance(scenes, Mapping) else None
        empty_statistics = empty.get("statistics") if isinstance(empty, Mapping) and isinstance(empty.get("statistics"), Mapping) else {}
        reference = profile.get("reference") if isinstance(profile.get("reference"), Mapping) else {}
        reference_background = empty_statistics.get("background_mean_brightness") if isinstance(empty_statistics, Mapping) else None
        if reference_background is None and isinstance(reference, Mapping):
            reference_background = reference.get("background_brightness")
        background = statistics.get("background_mean_brightness", statistics.get("background_brightness"))
        if isinstance(reference_background, (int, float)) and isinstance(background, (int, float)):
            difference = abs(background - reference_background)
            threshold = max(15.0, abs(float(reference_background)) * 0.20)
            if difference >= threshold:
                warnings.append({
                    "code": "BACKGROUND_BRIGHTNESS_CHANGED",
                    "message": "Current background brightness differs significantly from the saved inspection reference.",
                    "difference": round(difference, 1),
                })
        return {
            **data,
            "capabilities": capabilities,
            "calibration_mode": calibration_mode,
            "locked": locked,
            "image_statistics": statistics,
            "pending_reference_scenes": pending_reference_scenes,
            "configured_camera_index": self.camera_index,
            "configured_camera_note": "Camera index is selected at backend startup; set LEMURU_CAMERA_INDEX and restart to change it.",
            "open_attempts": open_attempts,
            "condition_warning": warnings[0] if warnings else None,
            "condition_warnings": warnings,
            "profile": profile,
        }

    def set_runtime_diagnostics(self, updates: Mapping[str, object]) -> dict[str, object]:
        """Change debug-only capture/overlay controls without touching policy."""

        allowed = {"enabled", "paused"}
        unknown = set(updates) - allowed
        if unknown:
            raise CameraControlError(f"Unsupported runtime diagnostic setting(s): {', '.join(sorted(unknown))}.")
        for name in allowed:
            if name in updates and not isinstance(updates[name], bool):
                raise CameraControlError(f"Runtime diagnostic {name} must be boolean.")
        if "enabled" in updates:
            self.debug_enabled = bool(updates["enabled"])
            if isinstance(self.quality_model, YoloQualityModel):
                self.quality_model.set_debug_raw_output(self.debug_enabled)
        if "paused" in updates:
            self.debug_paused = bool(updates["paused"])
        return self.runtime_diagnostics()

    def mark_hard_negative(self, capture_id: str) -> dict[str, object]:
        """Operator-label a saved research crop without changing inference."""

        record = self._hard_negative_records.get(capture_id)
        if record is None:
            raise CameraControlError("Hard-negative capture was not found in this debug session.")
        record["operator_label"] = "NOT_FISH"
        record["labelled_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        metadata_path = record.get("metadata_path")
        if isinstance(metadata_path, str):
            try:
                Path(metadata_path).write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
            except OSError as exc:
                raise CameraControlError(f"Could not save NOT_FISH label: {exc}") from exc
        return dict(record)

    def surface_damage_evidence(self) -> dict[str, dict[str, object]]:
        """Return the latest conservative, non-grading damage evidence by track."""

        with self._processing_lock:
            return {str(track_id): dict(evidence) for track_id, evidence in self._latest_damage_evidence.items()}

    def runtime_diagnostics(self) -> dict[str, object]:
        """Expose only bounded debug telemetry; it is never used for grading."""

        raw_count = associated_count = rejected_count = unassigned_count = 0
        for observation, _bounds, _frame_id in self._latest_part_overlays.values():
            debug = observation.analysis.get("model2_debug") if isinstance(observation.analysis, Mapping) else None
            if isinstance(debug, Mapping):
                raw_count += len(debug.get("raw_detections", ())) if isinstance(debug.get("raw_detections"), list) else 0
                associated_count += len(debug.get("selected_detections", ())) if isinstance(debug.get("selected_detections"), list) else 0
                rejected_count += len(debug.get("rejected_detections", ())) if isinstance(debug.get("rejected_detections"), list) else 0
                unassigned_count += len(debug.get("unassigned_detections", ())) if isinstance(debug.get("unassigned_detections"), list) else 0
        return {
            "enabled": self.debug_enabled,
            "paused": self.debug_paused,
            "debug_capture_limit": self.debug_capture_limit,
            "debug_capture_count": self._debug_capture_count,
            "model2_raw_candidates": raw_count,
            "model2_associated_parts": associated_count,
            "model2_rejected_candidates": rejected_count,
            "model2_unassigned_candidates": unassigned_count,
            "model1_detections": list(self._last_model1_debug),
            "active_tracks": len(self.state.tracking.active_tracks()),
            "quality_inference_mode": self.quality_inference_mode,
            "camera_open_attempts": self._camera_open_attempts_snapshot(),
            "timing_provenance": {
                "model1_inference": "Host-observed model call duration; GPU work may be asynchronous.",
                "model2_inference": "Host-observed duration per successful Model 2 call; GPU work may be asynchronous.",
                "tracker": "Model 1 tracker update; separate from event_tracking.",
                "event_tracking": "Inspection state/counting update, including durable-event target capture and queue hand-off; normal SQLite work is excluded, but pathological ordered backpressure is included.",
                "roi_extraction": "Crop mode: per-fish extraction; full-frame mode: summed extraction per Model 2 invocation.",
                "part_assignment": "Summed full-frame per-fish part translation and association-summary preparation, excluding association and grading.",
                "hsv": "Per-fish evidence preparation including part scoring and optional image diagnostics; included in grading_engine.",
                "grading_engine": "Per-fish grading; includes hsv evidence preparation.",
                "total_processing": "Frame processing including stages and overlays, excluding JPEG and publication.",
                "capture_to_publish": "Capture timestamp to encoded JPEG publication in the server state; excludes client, network, and browser paint.",
                "first_detection_to_decision": "First persistent Model 1 detection to virtual count-line decision; not physical entry or actuator confirmation.",
                "event_persistence": "Background FIFO durable-event worker duration; normal SQLite work is outside frame processing and does not affect grading or counts.",
                "mjpeg_dispatch": "Generator yield-to-resume time, including consumer pacing; not browser paint or network latency.",
                "frontend_render": "Browser DOM render samples only while debug capture is enabled.",
                "note": "Stage windows overlap and do not sum to total processing. Counts and percentiles use bounded rolling samples.",
            },
            "skipped_model2_reasons": dict(self._skipped_model2_reasons),
            "frame_queue": self._latest_frames.snapshot(),
            "performance": self._runtime_metrics.snapshot(),
            "hard_negative_records": list(self._hard_negative_records.values())[-20:],
            "artifacts": {
                "model2_directory": str(self._debug_root),
                "hard_negative_directory": str(self._hard_negative_root),
                "note": "Debug artifacts are bounded and never enter production inspection history or inference.",
            },
        }

    def record_frontend_render(self, milliseconds: float) -> None:
        """Accept a bounded browser render measurement for diagnostics only."""

        if not self.debug_enabled or not 0.0 <= milliseconds <= 60_000.0:
            return
        self._runtime_metrics.record_latency("frontend_render", milliseconds / 1000.0)

    def record_stream_dispatch(self, seconds: float) -> None:
        """Record MJPEG generator pacing without claiming network completion."""

        self._runtime_metrics.record_latency("mjpeg_dispatch", seconds)
        self._runtime_metrics.record_call("mjpeg_dispatch")

    def record_event_persistence(self, seconds: float) -> None:
        """Record background durable-write work without changing inspection decisions."""

        self._runtime_metrics.record_latency("event_persistence", seconds)

    def _record_model2_skip(self, reason: str) -> None:
        self._skipped_model2_reasons[reason] = self._skipped_model2_reasons.get(reason, 0) + 1
        self._runtime_metrics.increment(f"model2_skipped_{reason}")

    @staticmethod
    def _letterbox_preview(image: Any, image_size: int, cv2: Any) -> tuple[Any, dict[str, object]]:
        """Create a documented visual approximation of YOLO's square input."""

        height, width = image.shape[:2]
        ratio = min(image_size / max(1, width), image_size / max(1, height))
        resized_width, resized_height = max(1, round(width * ratio)), max(1, round(height * ratio))
        resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
        left = (image_size - resized_width) // 2
        top = (image_size - resized_height) // 2
        preview = cv2.copyMakeBorder(
            resized,
            top,
            image_size - resized_height - top,
            left,
            image_size - resized_width - left,
            cv2.BORDER_CONSTANT,
            value=(114, 114, 114),
        )
        return preview, {
            "resize_method": "YOLO-compatible letterbox preview; model.predict performs the authoritative internal preprocessing",
            "scale": round(ratio, 8),
            "padding": {"left": left, "top": top, "right": image_size - resized_width - left, "bottom": image_size - resized_height - top},
        }

    def _save_debug_artifacts(
        self,
        frame: Any,
        crop: Any,
        detection: Any,
        bounds: CropBounds,
        observation: FishQualityObservation,
    ) -> None:
        """Save a bounded, research-only record of an exact Model 2 input."""

        if not self.debug_enabled or self._debug_capture_count >= self.debug_capture_limit:
            return
        try:
            import cv2

            directory = self._debug_root / f"fish_{int(detection.track_id)}"
            directory.mkdir(parents=True, exist_ok=True)
            token = f"frame_{self._frame_index:06d}"
            original = frame.copy()
            left, top, right, bottom = (int(round(value)) for value in detection.bbox)
            cv2.rectangle(original, (left, top), (right, bottom), (0, 220, 255), 2)
            cv2.putText(original, f"Fish #{detection.track_id}", (max(0, left), max(18, top - 5)), cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 220, 255), 2, cv2.LINE_AA)
            rendered = crop.copy()
            debug = observation.analysis.get("model2_debug", {}) if isinstance(observation.analysis, Mapping) else {}
            raw = debug.get("raw_detections", ()) if isinstance(debug, Mapping) else ()
            for item in raw if isinstance(raw, list) else ():
                bbox = item.get("bbox") if isinstance(item, Mapping) else None
                if not isinstance(bbox, list) or len(bbox) != 4:
                    continue
                x1, y1, x2, y2 = (int(round(float(value))) for value in bbox)
                cv2.rectangle(rendered, (x1, y1), (x2, y2), (255, 255, 0), 1)
                cv2.putText(rendered, f"{item.get('source_class_name', 'part')} {float(item.get('confidence', 0)) * 100:.1f}%", (max(0, x1), max(13, y1 - 3)), cv2.FONT_HERSHEY_SIMPLEX, .38, (255, 255, 0), 1, cv2.LINE_AA)
            model2_size = int(getattr(self.quality_model, "image_size", 640))
            tensor_preview, letterbox = self._letterbox_preview(crop, model2_size, cv2)
            cv2.imwrite(str(directory / f"{token}_original.jpg"), frame)
            cv2.imwrite(str(directory / f"{token}_model1_box.jpg"), original)
            cv2.imwrite(str(directory / f"{token}_roi.jpg"), crop)
            cv2.imwrite(str(directory / f"{token}_model2_input_preview.jpg"), tensor_preview)
            cv2.imwrite(str(directory / f"{token}_detections.jpg"), rendered)
            metadata = {
                "fish_id": int(detection.track_id),
                "frame_number": self._frame_index,
                "model1_box": list(detection.bbox),
                "padded_roi_box": [bounds.x1, bounds.y1, bounds.x2, bounds.y2],
                "roi_original_dimensions": {"width": bounds.width, "height": bounds.height},
                "model2_input_dimensions": {"width": model2_size, "height": model2_size},
                "model2_confidence_threshold": getattr(self.quality_model, "confidence_threshold", None),
                "letterbox": letterbox,
                "raw_detections": raw,
                "selected_detections": debug.get("selected_detections", ()) if isinstance(debug, Mapping) else (),
                "note": "This is a debug-only, bounded artifact. It is not inspection history and cannot alter a prediction.",
            }
            (directory / f"{token}_metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
            self._debug_capture_count += 1
        except Exception as exc:  # Debug I/O must never stop the conveyor.
            LOGGER.warning("[DEBUG] Could not save Model 2 artifact: %s", exc)

    def _save_hard_negative_candidate(self, frame: Any, detection: Any, *, model2_compatible: bool) -> None:
        """Retain an operator-labelable Model 1 crop for future research only."""

        if not self.debug_enabled or self._debug_capture_count >= self.debug_capture_limit:
            return
        if detection.track_id is None:
            return
        try:
            import cv2

            crop, bounds = crop_fish(frame, detection.bbox, padding=0)
            confidence = f"{float(detection.confidence):.3f}"
            capture_id = f"frame_{self._frame_index:06d}_track_{int(detection.track_id)}_conf_{confidence}"
            self._hard_negative_root.mkdir(parents=True, exist_ok=True)
            image_path = self._hard_negative_root / f"{capture_id}.jpg"
            metadata_path = self._hard_negative_root / f"{capture_id}.json"
            metadata = {
                "capture_id": capture_id,
                "frame_number": self._frame_index,
                "track_id": int(detection.track_id),
                "confidence": float(detection.confidence),
                "bbox": list(detection.bbox),
                "width": bounds.width,
                "height": bounds.height,
                "aspect_ratio": round(bounds.width / bounds.height, 6) if bounds.height else None,
                "area": bounds.width * bounds.height,
                "model2_compatible_part_evidence": bool(model2_compatible),
                "operator_label": None,
                "image_path": str(image_path),
                "metadata_path": str(metadata_path),
                "research_only": True,
                "note": "Set operator_label to NOT_FISH only after review. This record never feeds live inference.",
            }
            cv2.imwrite(str(image_path), crop)
            metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
            self._hard_negative_records[capture_id] = metadata
            self._debug_capture_count += 1
        except Exception as exc:
            LOGGER.warning("[DEBUG] Could not save hard-negative candidate: %s", exc)

    def has_live_worker(self) -> bool:
        """Treat a worker as busy until its exit cleanup has completed."""
        with self._lifecycle_lock:
            return self._thread is not None

    def start(self) -> bool:
        with self._lifecycle_lock:
            if self._thread is not None:
                return False
            if not self._models_prepared and not self._prepare_models_locked():
                return False
            self._models_prepared = False
            self._reset_model_tracker()
            if self.quality_model is not None and hasattr(self.quality_model, "reset_tracks"):
                self.quality_model.reset_tracks()
            self._frame_index = 0
            self._model2_failure_count = 0
            self._model2_retry_after = 0.0
            self._last_segmented_frame.clear()
            self._track_grades.clear()
            self._latest_part_overlays.clear()
            self._latest_frames.clear()
            if not self.state.begin_start():
                return False
            self._stop_event.clear()
            self._finalized.clear()
            self._thread = Thread(target=self._run, name="camera-inference", daemon=True)
            try:
                self._thread.start()
            except Exception as exc:
                self._thread = None
                self._finalized.set()
                self.state.mark_error(f"Could not start inspection worker: {exc}")
                raise
            return True

    def prepare_models(self) -> bool:
        """Resolve the real tracker before the durable startup snapshot."""
        with self._lifecycle_lock:
            self._models_prepared = self._thread is None and self._prepare_models_locked()
            return self._models_prepared

    def _prepare_models_locked(self) -> bool:
        if self.model.model is None:
            if not self.model.load():
                self.state.mark_error(self.model.error or "Model is unavailable.")
                return False
            self.state.set_model("ready", self.model.name, str(self.model.weights_path), f"Model ready on {self.model.device}.")
        if self.quality_model is not None and self.quality_model.model is None:
            if self.quality_model.load():
                self.state.set_segmenter("ready", self.quality_model.name, str(self.quality_model.weights_path), f"Quality Model ready on {self.quality_model.device}.")
            else:
                self.state.set_segmenter("unavailable", None, str(self.quality_model.weights_path) if self.quality_model.weights_path else None, self.quality_model.error or "Quality Model is unavailable.")
        strict_integrity = os.getenv("FISH_STRICT_MODEL_INTEGRITY", "0").strip().lower() in {"1", "true", "yes", "on"}
        if strict_integrity and getattr(self.model, "checkpoint_integrity", None) != "verified":
            self.state.mark_error("Strict model integrity requires a verified Model 1 checkpoint before inspection.")
            return False
        if strict_integrity and (self.quality_model is None or self.quality_model.model is None or getattr(self.quality_model, "checkpoint_integrity", None) != "verified"):
            self.state.mark_error("Strict model integrity requires a verified Model 2 checkpoint before inspection.")
            return False
        return True

    def stop(self, timeout: float | None = 3.0) -> bool:
        """Request stop; ``None`` waits for durable finalization during shutdown."""

        deadline = None if timeout is None else monotonic() + max(0.0, timeout)
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                self.state.mark_stopped()
                return False
            self._stop_event.set()
            self.state.mark_stopping()
        thread.join(timeout=None if deadline is None else max(0.0, deadline - monotonic()))
        self._schedule_finalizer(thread)
        return self._finalized.wait(None if deadline is None else max(0.0, deadline - monotonic()))

    def request_stop_after_current_frame(self, reason: str) -> None:
        """Safely stop a worker when a non-frame subsystem becomes unhealthy.

        This is deliberately non-blocking so callbacks invoked under the frame
        processing lock can request shutdown without attempting to join their
        own camera thread.
        """

        self.state.mark_error(str(reason))
        self._stop_event.set()

    def _schedule_finalizer(self, thread: Thread) -> None:
        """At most one daemon waits for a worker; API requests never wait on it."""
        with self._lifecycle_lock:
            if self._thread is not thread or self._finalizer_for is thread:
                return
            self._finalizer_for = thread
            FinalizerThread(target=self._wait_for_worker, args=(thread,), name="camera-finalizer", daemon=True).start()

    def _wait_for_worker(self, thread: Thread) -> None:
        thread.join()
        self._finalize_worker(thread)

    def _finalize_worker(self, thread: Thread) -> None:
        try:
            self._clear_transient_state()
            if callable(self.on_worker_exit):
                self.on_worker_exit()
            if self.state.snapshot()["inspection_status"] != "errored":
                self.state.mark_stopped()
        except Exception as exc:
            LOGGER.exception("Could not finalize the inspection after worker exit")
            self.state.mark_error(f"Inspection cleanup failed: {exc}")
        finally:
            with self._lifecycle_lock:
                if self._thread is thread:
                    self._thread = None
                    self._finalizer_for = None
                    self._finalized.set()

    def _clear_transient_state(self) -> None:
        """Reset live-only state after Stop without clearing production totals."""

        with self._processing_lock:
            self._reset_model_tracker()
            self._frame_index = 0
            self._model2_failure_count = 0
            self._model2_retry_after = 0.0
            self._last_segmented_frame.clear()
            self._track_grades.clear()
            self._latest_part_overlays.clear()
            self._latest_damage_evidence.clear()
            self._latest_frames.clear()
            if self.quality_model is not None and hasattr(self.quality_model, "reset_tracks"):
                self.quality_model.reset_tracks()
            self.state.clear_transient_tracking()

    def reset_session(self) -> None:
        """Atomically reset tracker identities and all session event data."""

        with self._processing_lock:
            # A deliberate session reset clears history and starts Fish #1
            # again. Stop/calibration retain their collision-free ID range.
            self._highest_track_id = None
            self._track_id_epoch_offset = 0
            self._reset_model_tracker()
            self._frame_index = 0
            self._model2_failure_count = 0
            self._model2_retry_after = 0.0
            self._last_segmented_frame.clear()
            self._track_grades.clear()
            self._latest_part_overlays.clear()
            self._latest_damage_evidence.clear()
            self._latest_frames.clear()
            if self.quality_model is not None and hasattr(self.quality_model, "reset_tracks"):
                self.quality_model.reset_tracks()
            self.state.reset_session()

    def _annotate(self, frame, detections, cv2):
        """Draw persistent IDs, live classifications, and the inspection line."""

        annotated = frame.copy()
        display = self.state.current_display_settings()
        height, width = annotated.shape[:2]
        config = self.state.tracking.config
        line_color = (0, 183, 235)
        if config.line_orientation == "vertical":
            coordinate = int(width * config.line_position)
            cv2.line(annotated, (coordinate, 0), (coordinate, height), line_color, 3)
            arrow = ">>" if config.conveyor_direction == "left_to_right" else "<<"
            label_position = (max(8, min(coordinate + 8, width - 190)), 25)
        else:
            coordinate = int(height * config.line_position)
            cv2.line(annotated, (0, coordinate), (width, coordinate), line_color, 3)
            arrow = "vv" if config.conveyor_direction == "top_to_bottom" else "^^"
            label_position = (8, max(22, coordinate - 9))
        cv2.putText(
            annotated,
            f"INSPECTION LINE {arrow}",
            label_position,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            line_color,
            2,
            cv2.LINE_AA,
        )

        active = {track["track_id"]: track for track in self.state.tracking.active_tracks()}
        for detection in detections:
            left, top, right, bottom = (int(value) for value in detection.bbox)
            damage_crop, damage_bounds = crop_fish(frame, detection.bbox, padding=0)
            damage_mask, damage_mask_metadata = generate_runtime_fish_mask(damage_crop)
            damage = analyze_surface_damage(
                cv2.cvtColor(damage_crop, cv2.COLOR_BGR2RGB),
                damage_mask if damage_mask is not None else np.zeros(damage_crop.shape[:2], dtype=bool),
                mask_source=str(damage_mask_metadata.get("source", "runtime_mask_unavailable")),
            )
            damage["mask_metadata"] = damage_mask_metadata
            if detection.track_id is not None:
                self._latest_damage_evidence[int(detection.track_id)] = {
                    key: value for key, value in damage.items() if key != "overlay_mask"
                }
            if display.get("damage_overlays") and damage.get("status") == "suspected":
                damage_overlay = damage.get("overlay_mask")
                if isinstance(damage_overlay, np.ndarray):
                    target = annotated[damage_bounds.y1:damage_bounds.y2, damage_bounds.x1:damage_bounds.x2]
                    red = np.zeros_like(target)
                    red[:, :, 2] = 220
                    region = damage_overlay[:target.shape[0], :target.shape[1]] > 0
                    target[region] = (0.65 * target[region] + 0.35 * red[region]).astype(np.uint8)
            track = active.get(detection.track_id)
            counted = bool(track and track["counted"])
            color = (43, 145, 87)
            if display["outlines"]:
                cv2.rectangle(annotated, (left, top), (right, bottom), color, 2)
            identity = f"Fish #{detection.track_id}" if detection.track_id is not None else "Acquiring ID"
            suffix = " | COUNTED" if counted else ""
            quality = track.get("quality") if track else None
            label_parts: list[str] = []
            if display["fish_ids"]:
                label_parts.append(f"{identity}{suffix}")
            if display["grades"] and quality:
                label_parts.append(str(quality))
            if display["confidence"]:
                quality_confidence = track.get("quality_confidence") if track else None
                quality_text = f" | Q {float(quality_confidence) * 100:.1f}%" if quality_confidence is not None else ""
                label_parts.append(f"D {detection.confidence * 100:.1f}%{quality_text}")
            if display["features"] and track and track.get("parts"):
                regions = sorted({str(part.get("region", "")) for part in track["parts"] if isinstance(part, dict) and part.get("region")})
                if regions:
                    label_parts.append("/".join(regions))
            label = " | ".join(label_parts)
            if not label:
                continue
            _draw_readable_label(annotated, label, left, top, color, cv2)
        return annotated

    def _annotate_debug_parts(self, annotated: Any, items: object, crop_bounds: CropBounds, color: tuple[int, int, int], prefix: str, cv2: Any) -> None:
        """Draw a debug-only Model 2 layer from serialized crop-local boxes."""

        if not isinstance(items, list):
            return
        height, width = annotated.shape[:2]
        for item in items:
            if not isinstance(item, Mapping):
                continue
            bbox = item.get("bbox")
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue
            translated = translate_bbox_to_frame(tuple(float(value) for value in bbox), crop_bounds, width, height)
            if translated is None:
                continue
            left, top, right, bottom = (int(round(value)) for value in translated)
            cv2.rectangle(annotated, (left, top), (right, bottom), color, 2)
            if self.state.current_display_settings().get("model2_labels", False):
                label = f"{prefix}: {item.get('region', '?')} {item.get('grade', '')} {float(item.get('confidence', 0.0)) * 100:.1f}%"
                cv2.putText(annotated, label, (max(0, left), max(14, top - 4)), cv2.FONT_HERSHEY_SIMPLEX, .38, color, 1, cv2.LINE_AA)

    def _annotate_quality(self, annotated: Any, results: list[tuple[FishQualityObservation, CropBounds]], cv2: Any) -> Any:
        """Overlay Model 2 boxes and optional raw detector trace layers.

        The production ``part_overlays`` switch now includes a visible box
        boundary.  It is no longer silently dependent on the unrelated global
        ``outlines`` switch, which was why enabled part overlays could look as
        though they had disappeared in the live feed.
        """

        colors = {"Class A": (76, 175, 80), "Class B": (255, 152, 0), "Class C": (170, 90, 205), "Rejected": (45, 45, 225)}
        height, width = annotated.shape[:2]
        display = self.state.current_display_settings()
        for result, crop_bounds in results:
            if display.get("roi_boundary", False):
                cv2.rectangle(annotated, (crop_bounds.x1, crop_bounds.y1), (crop_bounds.x2, crop_bounds.y2), (255, 255, 0), 1)
                cv2.putText(annotated, "Model 2 ROI", (crop_bounds.x1, max(14, crop_bounds.y1 - 3)), cv2.FONT_HERSHEY_SIMPLEX, .38, (255, 255, 0), 1, cv2.LINE_AA)
            for part in result.parts:
                part_grade = getattr(part, "grade", getattr(part, "quality", ""))
                part_region = getattr(part, "region", getattr(part, "part", ""))
                color = colors.get(part_grade, (180, 180, 180))
                translated = translate_bbox_to_frame(part.bbox, crop_bounds, width, height)
                if translated is not None:
                    left, top, right, bottom = translated
                    if display["part_overlays"]:
                        # Model 2 supplies a detection box, not a segmentation
                        # mask. Tint only the measured box and make its border
                        # independently visible at live-video scale.
                        overlay = annotated.copy()
                        cv2.rectangle(overlay, (int(left), int(top)), (int(right), int(bottom)), color, -1)
                        cv2.addWeighted(overlay, 0.20, annotated, 0.80, 0, annotated)
                        cv2.rectangle(annotated, (int(left), int(top)), (int(right), int(bottom)), color, 2)
                    elif display["outlines"]:
                        cv2.rectangle(annotated, (int(left), int(top)), (int(right), int(bottom)), color, 1)
                    if display["features"]:
                        grade_label = str(part_grade).replace("Class ", "")
                        label = f"{part_region} {grade_label}" if not display["confidence"] else f"{part_region} {grade_label} {part.confidence * 100:.0f}%"
                        _draw_readable_label(annotated, label, int(left), int(top), color, cv2)
            debug = result.analysis.get("model2_debug") if isinstance(result.analysis, Mapping) else None
            if self.debug_enabled and isinstance(debug, Mapping):
                if display.get("model2_raw_boxes", False):
                    self._annotate_debug_parts(annotated, debug.get("raw_detections"), crop_bounds, (0, 255, 255), "Raw", cv2)
                if display.get("model2_associated_boxes", False):
                    self._annotate_debug_parts(annotated, debug.get("selected_detections"), crop_bounds, (255, 255, 0), "Associated", cv2)
                if display.get("model2_rejected_boxes", False):
                    self._annotate_debug_parts(annotated, debug.get("rejected_detections"), crop_bounds, (0, 0, 255), "Rejected", cv2)
                    self._annotate_debug_parts(annotated, debug.get("unassigned_detections"), crop_bounds, (0, 90, 255), "Unassigned", cv2)
        return annotated

    def _annotate_part_preview(self, frame: Any, detections: list[PartDetection], cv2: Any) -> Any:
        """Draw raw part masks and boxes without fish IDs or inspection lines."""

        import numpy as np

        annotated = frame.copy()
        height, width = annotated.shape[:2]
        for detection in detections:
            color = PART_GRADE_COLORS.get(detection.grade, (180, 180, 180))
            left, top, right, bottom = (int(round(value)) for value in detection.bbox)
            polygon = None
            try:
                if detection.mask and len(detection.mask) >= 3:
                    points = np.asarray(detection.mask, dtype=np.float32)
                    if points.shape == (len(detection.mask), 2) and np.isfinite(points).all():
                        points[:, 0] = np.clip(points[:, 0], 0, max(0, width - 1))
                        points[:, 1] = np.clip(points[:, 1], 0, max(0, height - 1))
                        polygon = np.rint(points).astype(np.int32).reshape((-1, 1, 2))
                        overlay = annotated.copy()
                        cv2.fillPoly(overlay, [polygon], color)
                        cv2.addWeighted(overlay, 0.22, annotated, 0.78, 0, annotated)
                        cv2.polylines(annotated, [polygon], True, color, 2, cv2.LINE_AA)
            except Exception:  # One malformed mask must fall back to its box without stopping the feed.
                polygon = None
            cv2.rectangle(annotated, (left, top), (right, bottom), color, 1 if polygon is not None else 2)
            label = f"{detection.source_class_name} {detection.confidence * 100:.1f}%"
            _draw_readable_label(annotated, label, left, top, color, cv2)
        cv2.rectangle(annotated, (0, 0), (min(width - 1, 430), 48), (25, 32, 42), -1)
        cv2.putText(annotated, "PART MODEL PREVIEW", (10, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(annotated, "Raw parts - fish counting disabled", (10, 39), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (210, 220, 230), 1, cv2.LINE_AA)
        return annotated

    def _update_image_statistics(self, frame: Any, detections: list[Any], cv2: Any) -> None:
        """Measure the untouched camera frame for calibration reference only.

        The numbers are deliberately not supplied to either model, HSV analysis,
        or the grading engine.  Bounding boxes are used only to exclude detected
        fish from the background estimate when they are available.
        """

        profile = self.camera_controls.profile()
        confirmed = profile.get("operator_confirmation") if isinstance(profile.get("operator_confirmation"), Mapping) else {}
        with self._camera_state_lock:
            monitor_conditions = self._calibration_mode or (
                self._camera_locked and bool(confirmed.get("confirmed"))
            )
        if not monitor_conditions:
            return
        try:
            import numpy as np

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            height, width = gray.shape[:2]
            fish_mask = np.zeros((height, width), dtype=bool)
            for detection in detections:
                bbox = getattr(detection, "bbox", None)
                if not bbox or len(bbox) != 4:
                    continue
                left, top, right, bottom = (int(round(value)) for value in bbox)
                left, right = max(0, min(width, left)), max(0, min(width, right))
                top, bottom = max(0, min(height, top)), max(0, min(height, bottom))
                if right > left and bottom > top:
                    fish_mask[top:bottom, left:right] = True
            frame_brightness = float(gray.mean())
            fish_brightness = float(gray[fish_mask].mean()) if fish_mask.any() else None
            background_mask = ~fish_mask
            background_brightness = float(gray[background_mask].mean()) if background_mask.any() else None
            contrast = abs(fish_brightness - background_brightness) if fish_brightness is not None and background_brightness is not None else None
            background_values = gray[background_mask]
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            hsv_means = hsv.reshape((-1, 3)).mean(axis=0)
            with self._camera_state_lock:
                self._image_statistics = {
                    "frame_brightness": round(frame_brightness, 1),
                    "fish_roi_brightness": round(fish_brightness, 1) if fish_brightness is not None else None,
                    "background_brightness": round(background_brightness, 1) if background_brightness is not None else None,
                    "background_mean_brightness": round(background_brightness, 1) if background_brightness is not None else None,
                    "background_median_brightness": round(float(np.median(background_values)), 1) if background_values.size else None,
                    "background_std_brightness": round(float(np.std(background_values)), 1) if background_values.size else None,
                    "fish_background_contrast": round(contrast, 1) if contrast is not None else None,
                    "frame_hsv_mean": {
                        "h": round(float(hsv_means[0]), 2),
                        "s": round(float(hsv_means[1]), 2),
                        "v": round(float(hsv_means[2]), 2),
                    },
                }
        except Exception as exc:
            LOGGER.debug("[CAMERA] Could not calculate calibration statistics: %s", exc)

    def _record_quality_observation(
        self,
        detection: Any,
        result: FishQualityObservation,
        crop_bounds: CropBounds,
        crop_shape: tuple[int, ...],
        fresh: list[tuple[FishQualityObservation, CropBounds]],
        *,
        frame: Any | None = None,
        crop: Any | None = None,
    ) -> None:
        """Attach Model 1 provenance without changing Model 2 grade evidence."""

        summary = result.summary()
        analysis = dict(summary.analysis)
        crop_height, crop_width = crop_shape[:2]
        analysis["model1_detection"] = {
            "confidence": detection.confidence,
            "source": "Model 1 whole-fish detector",
            "note": "Detection confidence is retained for traceability and does not modify Model 2 grade scores.",
        }
        model2_detections = [
            {
                "label": getattr(part, "source_class_name", getattr(part, "class_name", "unknown")),
                "region": getattr(part, "region", getattr(part, "part", "unknown")),
                "grade": getattr(part, "grade", getattr(part, "quality", "unknown")),
                "evidence_score": getattr(part, "confidence", None),
                "crop_bbox": list(getattr(part, "bbox", ())),
            }
            for part in result.parts
        ]
        inference = analysis.get("quality_inference") if isinstance(analysis.get("quality_inference"), dict) else {}
        inference = dict(inference)
        inference.setdefault("crop_bounds", [crop_bounds.x1, crop_bounds.y1, crop_bounds.x2, crop_bounds.y2])
        inference.setdefault(
            "padding_hit_frame_limits",
            crop_bounds.x1 == 0 or crop_bounds.y1 == 0 or crop_bounds.x2 == (self.state.frame_size or (0, 0))[0] or crop_bounds.y2 == (self.state.frame_size or (0, 0))[1],
        )
        analysis["quality_inference"] = inference
        analysis["inference_debug"] = {
            "model1_detection": {
                "fish_id": detection.track_id,
                "confidence": detection.confidence,
                "frame_bbox": list(detection.bbox),
            },
            "fish_crop_dimensions": {"width": crop_width, "height": crop_height},
            "model2_detections": model2_detections,
            "weighted_scores": dict(analysis.get("weighted_scores", {})),
            "final_decision": {
                "grade": analysis.get("final_grade", "Ungraded"),
                "support": analysis.get("final_score"),
                "best_evidence_grade": analysis.get("provisional_grade"),
                "best_evidence_support": analysis.get("provisional_score"),
                "status": analysis.get("verdict_status"),
                "reason_codes": analysis.get("reason_codes", analysis.get("verdict_reason_code")),
            },
        }
        if self.debug_inference:
            LOGGER.info(
                "[Model 2] Fish #%s detections=%s weighted_scores=%s final=%s (%s)",
                detection.track_id,
                model2_detections,
                analysis["inference_debug"]["weighted_scores"],
                analysis["inference_debug"]["final_decision"].get("grade"),
                analysis["inference_debug"]["final_decision"].get("status"),
            )
        traceability = analysis.get("traceability") if isinstance(analysis.get("traceability"), dict) else {}
        traceability = dict(traceability)
        traceability.update({
            "model1_checkpoint": self.model.weights_path.name if getattr(self.model, "weights_path", None) else None,
            "model1_checkpoint_sha256": getattr(self.model, "checkpoint_sha256", None),
            "model1_detector_threshold": getattr(self.model, "confidence_threshold", self.state.confidence_threshold),
            "detection_threshold": getattr(self.model, "confidence_threshold", self.state.confidence_threshold),
            "tracker_backend": getattr(self.model, "tracker_backend", "iou_fallback"),
            "model2_inference_interval_frames": self.quality_interval,
            "model2_inference_frame_id": self._frame_index,
            "model2_candidate_grading_frames": analysis.get("candidate_frame_count"),
            "model2_usable_grading_frames": analysis.get("observation_count"),
        })
        analysis["traceability"] = traceability
        quality_details = analysis.get("frame_quality")
        latest_quality = quality_details.get("latest") if isinstance(quality_details, dict) else None
        latest_quality = latest_quality if isinstance(latest_quality, dict) else {}
        analysis["inspection_source"] = {
            "type": "live_camera", "frame_id": self._frame_index,
            "frame_width_px": frame.shape[1] if frame is not None else latest_quality.get("frame_width"),
            "frame_height_px": frame.shape[0] if frame is not None else latest_quality.get("frame_height"),
        }
        analysis["observation_accounting"] = {
            "model2_inference_interval_frames": self.quality_interval,
            "model2_inference_frame_id": self._frame_index,
            "candidate_grading_frames": analysis.get("candidate_frame_count"),
            "usable_grading_frames": analysis.get("observation_count"),
            "note": "Candidate and usable grading-frame counts are keyed to the persistent Model 1 track ID.",
        }
        if crop is not None:
            import cv2

            runtime_mask, mask_metadata = generate_runtime_fish_mask(crop)
            damage = analyze_surface_damage(
                cv2.cvtColor(crop, cv2.COLOR_BGR2RGB),
                runtime_mask if runtime_mask is not None else np.zeros(crop.shape[:2], dtype=bool),
                mask_source=str(mask_metadata.get("source", "runtime_mask_unavailable")),
            )
            damage.pop("overlay_mask", None)
            damage["mask_metadata"] = mask_metadata
            analysis["surface_damage"] = damage
            self._latest_damage_evidence[int(detection.track_id)] = dict(damage)
        performance = analysis.get("performance") if isinstance(analysis.get("performance"), dict) else {}
        performance = dict(performance)
        detector_seconds = getattr(self.model, "last_inference_seconds", None)
        performance["model1_inference_ms"] = round(float(detector_seconds) * 1000, 3) if detector_seconds is not None else None
        analysis["performance"] = performance
        summarized = replace(summary, analysis=analysis)
        self._track_grades[detection.track_id] = summarized
        self._last_segmented_frame[detection.track_id] = self._frame_index
        overlay_observation = FishQualityObservation(
            summarized.track_id,
            summarized.quality,
            summarized.quality_confidence,
            tuple(result.parts),
            dict(summarized.quality_votes),
            dict(summarized.analysis),
        )
        self._latest_part_overlays[int(detection.track_id)] = (overlay_observation, crop_bounds, self._frame_index)
        fresh.append((overlay_observation, crop_bounds))
        diagnostics = analysis.get("model2_debug") if isinstance(analysis.get("model2_debug"), Mapping) else {}
        raw = diagnostics.get("raw_detections", ()) if isinstance(diagnostics, Mapping) else ()
        for item in raw if isinstance(raw, list) else ():
            if isinstance(item, Mapping):
                confidence = item.get("confidence")
                region = item.get("region")
                if isinstance(confidence, (float, int)) and isinstance(region, str):
                    self._runtime_metrics.record_confidence(region, float(confidence))
        # Full-frame inference grades several fish before returning; read each
        # observation's own timing rather than the model's last fish timing.
        for stage, key in (("grading_engine", "grading_engine_ms"), ("hsv", "hsv_processing_ms")):
            milliseconds = performance.get(key)
            if isinstance(milliseconds, (int, float)) and not isinstance(milliseconds, bool):
                self._runtime_metrics.record_latency(stage, milliseconds / 1000.0)
        self._runtime_metrics.record_call("model2_roi")
        if frame is not None and crop is not None:
            self._save_debug_artifacts(frame, crop, detection, crop_bounds, overlay_observation)

    def _prune_track_evidence(self, retained_ids: set[int]) -> None:
        """Keep Model 2 state only while the domain tracker retains its identity."""
        self._track_grades = {track_id: grade for track_id, grade in self._track_grades.items() if track_id in retained_ids}
        self._last_segmented_frame = {track_id: seen for track_id, seen in self._last_segmented_frame.items() if track_id in retained_ids}
        self._latest_part_overlays = {track_id: overlay for track_id, overlay in self._latest_part_overlays.items() if track_id in retained_ids}
        if self.quality_model is not None and hasattr(self.quality_model, "prune_tracks"):
            self.quality_model.prune_tracks(retained_ids)

    def _record_model2_failures(self, frame: Any, detections: list[Any], message: str) -> None:
        """Replace affected live results with explicit, non-fabricated abstentions."""
        ids = {int(item.track_id) for item in detections}
        if isinstance(self.quality_model, YoloQualityModel):
            self.quality_model.discard_tracks(ids)
        for detection in detections:
            track_id = int(detection.track_id)
            self._latest_part_overlays.pop(track_id, None)
            self._last_segmented_frame.pop(track_id, None)
            try:
                if not isinstance(self.quality_model, YoloQualityModel):
                    raise RuntimeError("Canonical Model 2 unavailable-observation adapter is unavailable")
                crop, bounds = crop_fish(frame, detection.bbox, padding=self.quality_roi_padding)
                result = self.quality_model.unavailable_observation(
                    crop, track_id, frame_id=self._frame_index,
                    detection_confidence=detection.confidence, parent_bbox=detection.bbox,
                    frame_shape=frame.shape, error=message,
                )
                self._record_quality_observation(detection, result, bounds, crop.shape, [])
                self._latest_part_overlays.pop(track_id, None)
                self._last_segmented_frame.pop(track_id, None)
            except Exception:
                LOGGER.exception("Could not build Model 2 abstention for Fish #%s; recording a minimal failure result.", track_id)
                if isinstance(self.quality_model, YoloQualityModel):
                    self.quality_model.discard_tracks({track_id})
                self._track_grades[track_id] = QualitySummary(track_id, None, None, analysis={
                    "final_grade": "Ungraded", "final_score": None,
                    "verdict_status": "NEEDS_REVIEW", "verdict_reason_code": "UG_MODEL2_UNAVAILABLE",
                    "reason_codes": ["UG_MODEL2_UNAVAILABLE"],
                    "verdict_reason_text": "Model 2 inference failed; no quality grade was issued.",
                    "model2_available": False, "model2_error": message,
                })

    def process_frame(self, frame: Any, cv2: Any) -> Any:
        """Run the active mode for one frame; exposed for webcam-free tests."""

        self.state.set_frame_size(frame.shape[1], frame.shape[0])
        if self.runtime_mode == PART_PREVIEW_MODE:
            detections = self.model.predict(frame)
            self._update_image_statistics(frame, detections, cv2)
            return self._annotate_part_preview(frame, detections, cv2)  # type: ignore[arg-type]
        processing_started = monotonic()
        detections = self._scope_tracker_ids(self.model.predict(frame))  # type: ignore[union-attr]
        self._runtime_metrics.record_call("model1")
        self._runtime_metrics.record_latency("model1_inference", getattr(self.model, "last_inference_seconds", None))
        self._runtime_metrics.record_latency("tracker", getattr(self.model, "last_tracking_seconds", None))
        self._update_image_statistics(frame, detections, cv2)
        if self.debug_enabled:
            rows: list[dict[str, object]] = []
            for detection in detections:
                left, top, right, bottom = (float(value) for value in detection.bbox)
                box_width, box_height = max(0.0, right - left), max(0.0, bottom - top)
                rows.append({
                    "track_id": detection.track_id,
                    "confidence": detection.confidence,
                    "bbox": list(detection.bbox),
                    "width": round(box_width, 3),
                    "height": round(box_height, 3),
                    "aspect_ratio": round(box_width / box_height, 6) if box_height else None,
                    "area": round(box_width * box_height, 3),
                    "frame_number": self._frame_index + 1,
                    "model2_compatible_part_evidence": False,
                })
            self._last_model1_debug = rows
        if self.calibration_mode():
            # Detection can stay visible while calibration is active, but no
            # model-2 evidence, tracker state, counters, history, exports, or
            # grading records are produced from calibration frames.
            return self._annotate(frame, detections, cv2)
        frame_size = (frame.shape[1], frame.shape[0])
        self._frame_index += 1
        fresh: list[tuple[FishQualityObservation, CropBounds]] = []
        eligible: list[Any] = []
        scheduled_track_ids: set[int] = set()
        # Use the same monotonic instant for expiry and the later domain
        # update. Clear expired identities before inference, including when a
        # detector immediately reuses an ID after a long gap.
        frame_timestamp = monotonic()
        existing_tracks = {
            int(item["track_id"]): item
            for item in self.state.tracking.active_tracks()
            if item.get("track_id") is not None
            and frame_timestamp - float(item.get("last_seen_monotonic", frame_timestamp)) <= self.state.tracking.config.track_timeout
        }
        self._prune_track_evidence(set(existing_tracks))
        for detection in detections:
            if detection.track_id is None:
                self._record_model2_skip("untracked_detection")
                continue
            track_id = int(detection.track_id)
            # The deployed local YOLO Model 2 finalizes a track's temporal
            # evidence at the count line. Retained legacy adapters permit a
            # documented late-grade compatibility path and are not the
            # production two-YOLO runtime.
            if (bool(existing_tracks.get(track_id, {}).get("counted")) or self.state.tracking.is_counted(track_id)) and isinstance(self.quality_model, YoloQualityModel):
                self._record_model2_skip("finalized_track")
                continue
            if track_id in scheduled_track_ids:
                self._record_model2_skip("duplicate_track_same_frame")
                continue
            if self._last_segmented_frame.get(track_id) is not None and self._frame_index - self._last_segmented_frame[track_id] < self.quality_interval:
                self._record_model2_skip("interval_not_due")
                continue
            scheduled_track_ids.add(track_id)
            eligible.append(detection)
        if self.quality_model is not None and eligible and frame_timestamp < self._model2_retry_after:
            affected = [item for item in eligible if not bool(existing_tracks.get(int(item.track_id), {}).get("counted"))]
            self._record_model2_failures(frame, affected, "Model 2 retry is temporarily delayed after an inference failure.")
        elif self.quality_model is not None and eligible:
            completed_ids: set[int] = set()
            try:
                if isinstance(self.quality_model, YoloQualityModel) and self.quality_model.model is None:
                    # Keep the counted fish explicit: a missing local Model 2
                    # checkpoint is an abstention with UG_MODEL2_UNAVAILABLE,
                    # never a blank quality or fabricated part result.
                    for detection in eligible:
                        roi_started = monotonic()
                        crop, bounds = crop_fish(frame, detection.bbox, padding=self.quality_roi_padding)
                        self._runtime_metrics.record_latency("roi_extraction", monotonic() - roi_started)
                        result = self.quality_model.unavailable_observation(
                            crop,
                            int(detection.track_id),
                            frame_id=self._frame_index,
                            detection_confidence=detection.confidence,
                            parent_bbox=detection.bbox,
                            frame_shape=frame.shape,
                        )
                        self._record_quality_observation(detection, result, bounds, crop.shape, fresh, frame=frame, crop=crop)
                        completed_ids.add(int(detection.track_id))
                elif self.quality_model.model is not None and isinstance(self.quality_model, YoloQualityModel) and self.quality_inference_mode == "full_frame":
                    # Ownership must consider every visible fish, even if it
                    # is finalized, not scheduled, or temporarily untracked.
                    # Untracked and duplicate-ID detections get frame-local IDs
                    # and compete for ownership without being graded twice.
                    tracked_ids = {int(item.track_id) for item in detections if item.track_id is not None}
                    parents = []
                    seen_ids: set[int] = set()
                    transient_id = -1
                    for item in detections:
                        if item.track_id is None or int(item.track_id) in seen_ids:
                            while transient_id in tracked_ids:
                                transient_id -= 1
                            parent_id = transient_id
                            transient_id -= 1
                        else:
                            parent_id = int(item.track_id)
                        seen_ids.add(parent_id)
                        parents.append(ParentAnchor(parent_id, item.bbox, item.confidence))
                    full_frame_results = self.quality_model.predict_full_frame(
                        frame, parents, frame_id=self._frame_index,
                        grade_track_ids={int(item.track_id) for item in eligible},
                        source_context={"source_id": f"camera:{self.camera_index}"},
                    )
                    self._runtime_metrics.record_call("model2")
                    self._runtime_metrics.record_latency("model2_inference", self.quality_model.last_inference_seconds)
                    self._runtime_metrics.record_latency("association", self.quality_model.last_association_seconds)
                    self._runtime_metrics.record_latency("roi_extraction", self.quality_model.last_full_frame_roi_seconds)
                    self._runtime_metrics.record_latency("part_assignment", self.quality_model.last_part_assignment_seconds)
                    for detection in eligible:
                        result, bounds = full_frame_results[int(detection.track_id)]
                        self._record_quality_observation(detection, result, bounds, (bounds.height, bounds.width, frame.shape[2]), fresh)
                        completed_ids.add(int(detection.track_id))
                elif self.quality_model.model is not None:
                    for detection in eligible:
                        roi_started = monotonic()
                        crop, bounds = crop_fish(frame, detection.bbox, padding=self.quality_roi_padding)
                        self._runtime_metrics.record_latency("roi_extraction", monotonic() - roi_started)
                        if self.debug_inference:
                            LOGGER.info(
                                "[Model 1] Fish #%s confidence=%.2f%% bbox=%s -> Model 2 %s=%sx%s",
                                detection.track_id,
                                detection.confidence * 100,
                                tuple(round(value, 1) for value in detection.bbox),
                                self.quality_inference_mode,
                                crop.shape[1],
                                crop.shape[0],
                            )
                        if isinstance(self.quality_model, YoloQualityModel):
                            fish_mask, mask_metadata = generate_runtime_fish_mask(crop)
                            result = self.quality_model.predict(
                                crop,
                                int(detection.track_id),
                                frame_id=self._frame_index,
                                detection_confidence=detection.confidence,
                                parent_bbox=detection.bbox,
                                frame_shape=frame.shape,
                                frame_quality={"width_context": {
                                    "crop_bounds": [bounds.x1, bounds.y1, bounds.x2, bounds.y2],
                                    "overlapping": any(other is not detection and boxes_overlap(detection.bbox, other.bbox) for other in detections),
                                    "source_context": {"source_id": f"camera:{self.camera_index}"},
                                }},
                                fish_mask=fish_mask,
                                fish_mask_metadata=mask_metadata,
                                measurement_frame=frame,
                            )
                            result = replace(
                                result,
                                analysis={
                                    **result.analysis,
                                    "fish_mask": mask_metadata,
                                },
                            )
                            self._runtime_metrics.record_call("model2")
                        else:
                            # Compatibility adapter path; production uses
                            # YoloQualityModel and the canonical policy.
                            result = self.quality_model.predict(crop, int(detection.track_id))
                            self._runtime_metrics.record_call("model2")
                        self._runtime_metrics.record_latency("model2_inference", getattr(self.quality_model, "last_inference_seconds", None))
                        self._record_quality_observation(detection, result, bounds, crop.shape, fresh, frame=frame, crop=crop)
                        completed_ids.add(int(detection.track_id))
                if self._model2_failure_count and self.quality_model.model is not None:
                    self._model2_failure_count = 0
                    self._model2_retry_after = 0.0
                    self.state.set_segmenter("ready", getattr(self.quality_model, "name", None), str(getattr(self.quality_model, "weights_path", None)), "Quality Model inference recovered.")
            except Exception as exc:
                LOGGER.exception("Model 2 %s processing failed.", self.quality_inference_mode)
                message = f"Quality Model inference failed: {exc}"
                self._model2_failure_count = min(self._model2_failure_count + 1, 6)
                self._model2_retry_after = monotonic() + min(5.0, .25 * (2 ** (self._model2_failure_count - 1)))
                self.state.set_segmenter("error", getattr(self.quality_model, "name", None), str(getattr(self.quality_model, "weights_path", None)), message)
                affected = [item for item in eligible if int(item.track_id) not in completed_ids and not bool(existing_tracks.get(int(item.track_id), {}).get("counted"))]
                self._record_model2_failures(frame, affected, message)
        for detection in detections:
            overlay = self._latest_part_overlays.get(int(detection.track_id)) if detection.track_id is not None else None
            compatible = bool(overlay and overlay[0].parts)
            self._save_hard_negative_candidate(frame, detection, model2_compatible=compatible)
            for row in self._last_model1_debug:
                if row.get("track_id") == detection.track_id:
                    row["model2_compatible_part_evidence"] = compatible
        processing_time_ms = (monotonic() - processing_started) * 1000
        # Attach the full per-frame pipeline time before history/event creation.
        self._track_grades = {
            track_id: replace(
                grade,
                analysis={
                    **grade.analysis,
                    "performance": {
                        **(grade.analysis.get("performance") if isinstance(grade.analysis.get("performance"), dict) else {}),
                        "total_processing_ms": round(processing_time_ms, 3),
                    },
                },
            )
            for track_id, grade in self._track_grades.items()
        }
        tracking_started = monotonic()
        events = self.state.process_detections(
            detections,
            frame_size,
            timestamp=frame_timestamp,
            grades={
                track_id: grade for track_id, grade in self._track_grades.items()
                if not (isinstance(self.quality_model, YoloQualityModel) and bool(existing_tracks.get(track_id, {}).get("counted")))
            },
            processing_time_ms=processing_time_ms,
        )
        tracking_ms = (monotonic() - tracking_started) * 1000
        self._runtime_metrics.record_latency("event_tracking", tracking_ms / 1000.0)
        for event in events:
            conveyor_timing = event.analysis.get("conveyor_timing") if isinstance(event.analysis, Mapping) else None
            if isinstance(conveyor_timing, Mapping):
                latency_ms = conveyor_timing.get("first_detection_to_decision_ms")
                if isinstance(latency_ms, (int, float)):
                    self._runtime_metrics.record_latency("first_detection_to_decision", float(latency_ms) / 1000.0)
                deadline_status = conveyor_timing.get("deadline_status")
                if deadline_status in {"met", "missed"}:
                    self._runtime_metrics.increment(f"decision_deadline_{deadline_status}")
            event_performance = event.analysis.get("performance") if isinstance(event.analysis.get("performance"), dict) else {}
            self.state.tracking.update_event_analysis(
                event.track_id,
                {"performance": {**event_performance, "tracking_ms": round(tracking_ms, 3)}},
            )
        if self.quality_model is not None and hasattr(self.quality_model, "finalize_track"):
            for event in events:
                try:
                    best_frame = self.quality_model.finalize_track(event.track_id)
                    if best_frame:
                        self.state.tracking.update_event_analysis(event.track_id, {"best_frame": best_frame})
                except Exception as exc:
                    # Representative crop saving is optional; never lose a
                    # count or AI result because it failed after finalization.
                    self.state.set_segmenter("error", self.quality_model.name, str(self.quality_model.weights_path), f"Best-frame finalization failed: {exc}")
        overlay_started = monotonic()
        # Preserve the last real Model 2 boxes for each still-active track
        # between scheduled Model 2 frames. Previously ``fresh`` made boxes
        # vanish for the interval gap even when the UI control was enabled.
        visible_ids = {int(item.track_id) for item in detections if item.track_id is not None}
        overlays = [(observation, bounds) for track_id, (observation, bounds, _frame_id) in self._latest_part_overlays.items() if track_id in visible_ids]
        annotated = self._annotate_quality(self._annotate(frame, detections, cv2), overlays, cv2)
        self._runtime_metrics.record_latency("overlay_rendering", monotonic() - overlay_started)
        self._runtime_metrics.record_latency("total_processing", monotonic() - processing_started)
        return annotated

    def _open_capture(self, cv2: Any) -> tuple[Any | None, str]:
        """Open one capture, honoring a known saved backend before safe fallbacks."""

        candidates = self._capture_backend_candidates(cv2)
        preferred = self._requested_capture_backend() or self._saved_preferred_backend()
        if preferred is not None:
            candidates.sort(key=lambda candidate: 0 if candidate[2] == preferred else 1)
        with self._camera_state_lock:
            self._camera_open_attempts = []
        for label, backend, _candidate_key in candidates:
            try:
                capture = cv2.VideoCapture(self.camera_index, backend) if backend is not None else cv2.VideoCapture(self.camera_index)
            except Exception as exc:
                self._record_camera_open_attempt(label, "exception", detail=str(exc))
                LOGGER.warning("[CAMERA] %s open attempt failed: %s", label, exc)
                continue
            try:
                opened = bool(capture.isOpened())
            except Exception as exc:
                self._record_camera_open_attempt(label, "exception", detail=f"isOpened failed: {exc}")
                LOGGER.warning("[CAMERA] %s open-state check failed: %s", label, exc)
                try:
                    capture.release()
                except Exception:
                    pass
                continue
            if opened:
                try:
                    reported = capture.getBackendName()
                except Exception:
                    reported = label
                self._record_camera_open_attempt(label, "opened", reported_backend=str(reported or label))
                return capture, str(reported or label)
            try:
                capture.release()
            except Exception:
                pass
            self._record_camera_open_attempt(label, "not_opened")
            LOGGER.warning("[CAMERA] %s could not open camera index %s", label, self.camera_index)
        return None, "Unavailable"

    @staticmethod
    def _capture_backend_candidates(cv2: Any) -> list[tuple[str, int | None, str]]:
        """Return the application's fixed, portable fallback order."""

        candidates: list[tuple[str, int | None, str]] = []
        if os.name == "nt" and hasattr(cv2, "CAP_DSHOW"):
            candidates.append(("DSHOW", cv2.CAP_DSHOW, "dshow"))
        if os.name == "nt" and hasattr(cv2, "CAP_MSMF"):
            candidates.append(("MSMF", cv2.CAP_MSMF, "msmf"))
        candidates.append(("OpenCV default", None, "default"))
        return candidates

    @staticmethod
    def _requested_capture_backend() -> str | None:
        value = os.getenv("LEMURU_CAMERA_BACKEND", "").strip().casefold()
        return {
            "dshow": "dshow",
            "directshow": "dshow",
            "msmf": "msmf",
            "media foundation": "msmf",
            "default": "default",
            "opencv default": "default",
        }.get(value)

    def _saved_preferred_backend(self) -> str | None:
        """Map only known persisted backend names to safe candidate keys."""

        value = self.camera_controls.profile().get("preferred_backend")
        if not isinstance(value, str):
            return None
        normalized = " ".join(value.strip().casefold().split())
        aliases = {
            "dshow": "dshow",
            "directshow": "dshow",
            "msmf": "msmf",
            "media foundation": "msmf",
            "opencv default": "default",
            "default": "default",
        }
        return aliases.get(normalized)

    @staticmethod
    def _camera_attempt_detail(value: object) -> str:
        """Keep driver exception text useful but bounded and single-line."""

        return " ".join(str(value).split())[:240]

    def _record_camera_open_attempt(
        self,
        backend: str,
        status: str,
        *,
        detail: object | None = None,
        reported_backend: str | None = None,
    ) -> None:
        record: dict[str, object] = {"backend": backend, "status": status}
        if detail:
            record["detail"] = self._camera_attempt_detail(detail)
        if reported_backend:
            record["reported_backend"] = self._camera_attempt_detail(reported_backend)
        with self._camera_state_lock:
            self._camera_open_attempts.append(record)
            self._camera_open_attempts = self._camera_open_attempts[-8:]

    def _camera_open_attempts_snapshot(self) -> list[dict[str, object]]:
        with self._camera_state_lock:
            return [dict(item) for item in self._camera_open_attempts]

    def _camera_open_failure_message(self) -> str:
        """Give the operator bounded, actionable context without guessing cause."""

        attempts = self._camera_open_attempts_snapshot()
        if not attempts:
            return f"Camera {self.camera_index} could not be opened. Check its connection, permission, and configured index."
        summary = ", ".join(
            f"{item.get('backend', 'unknown')} ({item.get('status', 'failed')})"
            for item in attempts
        )
        return (
            f"Camera {self.camera_index} could not be opened after: {summary}. "
            "Check the connection, another application using the device, permissions, or the configured camera index."
        )

    def _capture_frames(self, capture: Any) -> None:
        """Keep reading the sole camera so inference never creates a backlog."""

        while not self._stop_event.is_set():
            capture_started = monotonic()
            try:
                with self.camera_controls.lock:
                    ok, frame = capture.read()
            except Exception as exc:
                if not self._stop_event.is_set():
                    LOGGER.exception("Camera %s frame acquisition failed", self.camera_index)
                    self.state.mark_error(f"Camera {self.camera_index} frame acquisition failed: {exc}")
                    self._stop_event.set()
                return
            self._runtime_metrics.record_latency("camera_capture", monotonic() - capture_started)
            if self._stop_event.is_set():
                return
            if not ok or frame is None:
                self.state.mark_error(f"Camera {self.camera_index} stopped returning frames.")
                self._stop_event.set()
                return
            captured_at = monotonic()
            # An opened device alone does not prove that usable frames arrive.
            self.state.mark_running()
            try:
                self.raw_preview.offer(frame, captured_at)
            except Exception:
                LOGGER.exception("Raw preview frame could not be copied")
            self._latest_frames.offer(frame, captured_at=captured_at)
            self._runtime_metrics.record_call("camera_capture")

    def _run(self) -> None:
        """Own setup/teardown while capture and inference exchange one frame."""

        capture = None
        try:
            import cv2

            capture, backend = self._open_capture(cv2)
            if capture is None:
                self.state.mark_error(self._camera_open_failure_message())
                return
            self.camera_controls.attach(capture, cv2, backend)
            try:
                profile_result = self.camera_controls.initialize_camera_settings()
                profile = profile_result.get("profile")
                if isinstance(profile, dict):
                    with self._camera_state_lock:
                        self._camera_locked = bool(profile.get("locked", False))
                if not profile_result.get("success"):
                    LOGGER.warning("[CAMERA] Inspection profile loaded with rejected settings: %s", profile_result.get("results"))
            except CameraControlError as exc:
                # A missing profile is normal on a new installation. A profile
                # error must never block raw acquisition or grading.
                LOGGER.info("[CAMERA] Inspection profile was not applied: %s", exc)
            if self._stop_event.is_set():
                return
            self.raw_preview.start(self._stop_event, cv2)
            self._capture_thread = Thread(target=self._capture_frames, args=(capture,), name="camera-capture", daemon=True)
            self._capture_thread.start()
            previous_time = monotonic()
            smoothed_fps = 0.0
            consecutive_processing_errors = 0

            while not self._stop_event.is_set():
                frame_generation = self.state.frame_generation()
                packet = self._latest_frames.take(timeout=.1)
                if packet is None:
                    continue
                if self.debug_paused:
                    self._runtime_metrics.increment("paused_frames")
                    continue
                self._runtime_metrics.record_latency("capture_to_process", monotonic() - packet.captured_at)
                try:
                    with self._processing_lock:
                        if frame_generation != self.state.frame_generation():
                            continue
                        annotated = self.process_frame(packet.frame, cv2)
                    consecutive_processing_errors = 0
                except Exception as exc:
                    consecutive_processing_errors += 1
                    if self.runtime_mode == WHOLE_FISH_MODE:
                        self.state.report_tracker_error(f"Fish detection/tracking frame failed: {exc}")
                    if consecutive_processing_errors >= 5:
                        activity = "Part-preview inference" if self.runtime_mode == PART_PREVIEW_MODE else "Fish detection/tracking"
                        self.state.mark_error(f"{activity} failed on five consecutive frames. Inspection stopped. Last error: {exc}")
                        self._stop_event.set()
                        return
                    annotated = packet.frame
                encode_started = monotonic()
                # Keep the operator-facing camera feed raw. Inference still
                # runs above for tracking, grading, and session totals.
                encoded, buffer = cv2.imencode(".jpg", packet.frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
                self._runtime_metrics.record_latency("jpeg_encoding", monotonic() - encode_started)
                if not encoded:
                    self._runtime_metrics.increment("jpeg_encode_failures")
                    continue
                now = monotonic()
                instant_fps = 1.0 / max(now - previous_time, 1e-6)
                smoothed_fps = instant_fps if smoothed_fps == 0 else (0.85 * smoothed_fps + 0.15 * instant_fps)
                previous_time = now
                self._runtime_metrics.record_call("processed_frame", when=now)
                jpeg = buffer.tobytes()
                self.state.publish_frame(jpeg, smoothed_fps, generation=frame_generation)
                self._runtime_metrics.record_latency("capture_to_publish", monotonic() - packet.captured_at)
        except Exception as exc:
            self.state.mark_error(f"Inspection failed: {exc}")
        finally:
            self._stop_event.set()
            self.raw_preview.finish()
            capture_thread = self._capture_thread
            if capture_thread is not None:
                capture_thread.join(timeout=.5)
            self._capture_thread = None
            if capture is not None:
                self.camera_controls.detach(capture)
                with self.camera_controls.lock:
                    capture.release()
            # A separate, bounded-count daemon joins this worker before closing
            # the durable session or permitting a new worker.
            self._schedule_finalizer(current_thread())
