"""Local Model 1 adapter for ``model1_fish_parent_detector.pt``.

The supplied checkpoint is an Ultralytics YOLO detection model.  It is a
single-class whole-fish detector, so it deliberately owns location and
persistent IDs only; grading is delegated to ``YoloQualityModel``.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from importlib.util import find_spec
import logging
import os
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Any, Callable

import numpy as np

from src.api.domain import Detection
from src.inference.fish_detector import FISH_CLASS_ID, FISH_CLASS_NAME, _ByteTrackInput, _default_tracker_factory
from src.inference.track_identity import ConfirmedFishIdentities
from src.inference.model_traceability import full_sha256
from src.inference.preprocessing import clamp_bbox, validate_image
from src.inference.compute import resolve_compute, timed_elapsed, timed_start


SUPPORTED_CHECKPOINT_SUFFIXES = (".pt", ".pth", ".ckpt")
LOGGER = logging.getLogger(__name__)


def _lap_dependency_error() -> str | None:
    """Check the binary can be loaded before Ultralytics imports its tracker.

    Merely finding a module on disk does not prove that its native extension
    matches the active Python/NumPy installation. Ultralytics otherwise tries
    an automatic package installation when importing an unavailable ``lap``.
    """
    try:
        if find_spec("lap") is None:
            return "missing"
        module = import_module("lap")
        if not callable(getattr(module, "lapjv", None)):
            return "lap.lapjv is unavailable"
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


class YoloFishDetectorError(RuntimeError):
    """Base error for the supplied Model 1 checkpoint."""


class YoloFishDetectorLoadError(YoloFishDetectorError):
    """Raised when Model 1 cannot be loaded as a YOLO detector."""


class YoloFishDetectorInferenceError(YoloFishDetectorError):
    """Raised when Model 1 cannot inspect a valid camera frame."""


@dataclass(frozen=True)
class FishDetection:
    """Untracked Model 1 output in original-frame coordinates."""

    bbox: tuple[float, float, float, float]
    confidence: float


def _iou(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> float:
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = (first[2] - first[0]) * (first[3] - first[1]) + (second[2] - second[0]) * (second[3] - second[1]) - intersection
    return intersection / union if union > 0 else 0.0


@dataclass(frozen=True)
class _IoUTrack:
    bbox: tuple[float, float, float, float]
    missing: int = 0
    velocity: tuple[float, float] = (0.0, 0.0)
    observations: int = 1

    def predicted_bbox(self) -> tuple[float, float, float, float]:
        dx, dy = (value * (self.missing + 1) for value in self.velocity)
        left, top, right, bottom = self.bbox
        return left + dx, top + dy, right + dx, bottom + dy


def _pairwise_iou(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """Compute the small tracking matrix without a Python loop per box pair."""

    overlap = np.maximum(0.0, np.minimum(first[:, None, 2:], second[None, :, 2:])
                         - np.maximum(first[:, None, :2], second[None, :, :2]))
    intersection = overlap[..., 0] * overlap[..., 1]
    first_size = np.maximum(0.0, first[:, 2:] - first[:, :2])
    second_size = np.maximum(0.0, second[:, 2:] - second[:, :2])
    union = (first_size[:, 0] * first_size[:, 1])[:, None] + (second_size[:, 0] * second_size[:, 1])[None, :] - intersection
    return np.divide(intersection, union, out=np.zeros_like(intersection), where=union > 0)


class _IoUTracker:
    """Motion-aware fallback when the optional ByteTrack ``lap`` dependency is absent.

    Prediction is used only for association. Every emitted box is a detection
    from this update; missed tracks are retained internally without producing
    synthetic fish. Global matching avoids consuming another fish's sole valid
    match merely because the detector returned its rows in a different order.
    """

    def __init__(self, minimum_iou: float = 0.30, max_missing_frames: int = 30) -> None:
        self.minimum_iou = minimum_iou
        self.max_missing_frames = max_missing_frames
        self._next_id = 1
        self._tracks: dict[int, _IoUTrack] = {}

    def _match(self, boxes: np.ndarray, source_order: list[int]) -> dict[int, int]:
        if not self._tracks or not source_order:
            return {}
        track_ids = sorted(self._tracks)
        tracks = [self._tracks[track_id] for track_id in track_ids]
        candidates = boxes[source_order]
        predicted = np.asarray([track.predicted_bbox() for track in tracks], dtype=np.float64)
        predicted_iou = _pairwise_iou(predicted, candidates)
        scores = np.where(predicted_iou >= self.minimum_iou, predicted_iou, -1.0)
        # A newly stopped fish or a jittering box may overlap its last observed
        # location better than its velocity estimate. Permit that fallback only
        # for adjacent observations, not indefinitely across an occlusion.
        observed_iou = _pairwise_iou(np.asarray([track.bbox for track in tracks]), candidates)
        visible = np.asarray([track.missing == 0 for track in tracks])[:, None]
        scores = np.maximum(scores, np.where(visible & (observed_iou >= self.minimum_iou), observed_iou * 0.9, -1.0))
        valid = scores >= 0.0
        active_rows = np.flatnonzero(valid.any(axis=1))
        active_columns = np.flatnonzero(valid.any(axis=0))
        if not len(active_rows) or not len(active_columns):
            return {}

        # SciPy is already required by scikit-learn; import the solver only when
        # an actual association is needed. Zero-cost invalid edges allow a
        # rectangular assignment without allocating one dummy column per track.
        from scipy.optimize import linear_sum_assignment

        selected = scores[np.ix_(active_rows, active_columns)]
        cardinality_reward = min(selected.shape) + 1.0
        costs = np.where(selected >= 0.0, -(cardinality_reward + selected), 0.0)
        rows, columns = linear_sum_assignment(costs)
        return {
            source_order[int(active_columns[column])]: track_ids[int(active_rows[row])]
            for row, column in zip(rows, columns)
            if selected[row, column] >= 0.0
        }

    def update(self, detections: _ByteTrackInput, _frame: Any) -> np.ndarray:
        boxes = np.asarray(detections.xyxy, dtype=np.float64).reshape((-1, 4))
        # Canonical geometry order gives both assignment ties and newly created
        # IDs a stable meaning when the detector reorders otherwise equal rows.
        source_order = sorted(range(len(boxes)), key=lambda index: (*boxes[index], float(detections.conf[index]), index))
        assignments = self._match(boxes, source_order)
        for source_index in source_order:
            if source_index not in assignments:
                assignments[source_index] = self._next_id
                self._next_id += 1
        assigned_ids = set(assignments.values())
        updated = {
            track_id: _IoUTrack(track.bbox, track.missing + 1, track.velocity, track.observations)
            for track_id, track in self._tracks.items()
            if track_id not in assigned_ids and track.missing < self.max_missing_frames
        }
        for source_index, track_id in assignments.items():
            candidate = tuple(float(value) for value in boxes[source_index])
            previous = self._tracks.get(track_id)
            if previous is None:
                updated[track_id] = _IoUTrack(candidate)
                continue
            elapsed = previous.missing + 1
            measured = tuple(((candidate[axis] + candidate[axis + 2]) - (previous.bbox[axis] + previous.bbox[axis + 2])) / (2 * elapsed)
                             for axis in (0, 1))
            velocity = (measured if previous.observations == 1
                        else tuple(0.65 * fresh + 0.35 * old for fresh, old in zip(measured, previous.velocity)))
            updated[track_id] = _IoUTrack(candidate, velocity=velocity, observations=previous.observations + 1)
        self._tracks = updated
        return np.asarray(
            [[*detections.xyxy[index], assignments[index], detections.conf[index], 0.0, index] for index in range(len(boxes))],
            dtype=np.float32,
        ).reshape((-1, 8))

    def reset(self) -> None:
        self._next_id = 1
        self._tracks.clear()


def resolve_yolo_fish_detector_model_path(repo_root: Path, explicit_path: str | Path | None = None) -> Path | None:
    """Resolve Model 1 explicitly, or its documented local default.

    A sole checkpoint fallback is retained for an operator-managed weights
    directory, but a directory with multiple files is intentionally ambiguous.
    """

    if explicit_path:
        candidate = Path(explicit_path).expanduser()
        return (candidate if candidate.is_absolute() else repo_root / candidate).resolve()
    weights = repo_root / "models" / "fish_detector" / "weights"
    preferred = weights / "model1_fish_parent_detector.pt"
    if preferred.is_file():
        return preferred.resolve()
    if not weights.is_dir():
        return None
    candidates = sorted(path.resolve() for path in weights.iterdir() if path.is_file() and path.suffix.casefold() in SUPPORTED_CHECKPOINT_SUFFIXES)
    return candidates[0] if len(candidates) == 1 else None


def _ordered_names(class_names: dict[int, str] | list[str] | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(class_names, dict):
        try:
            return tuple(str(class_names[index]) for index in range(len(class_names)))
        except KeyError as exc:
            raise ValueError("Model 1 class IDs must be contiguous and 0-based.") from exc
    return tuple(str(value) for value in class_names)


def validate_yolo_fish_detector_class_mapping(class_names: dict[int, str] | list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Validate the real single-class checkpoint mapping without relabelling it.

    The supplied model stores ``item`` as its class name, while its supplied
    training-pool YAML identifies the one semantic class as ``Fish``.  The
    runtime records the checkpoint label and exposes the semantic Fish contract
    to tracking; it never treats Model 1's label as a quality grade.
    """

    labels = _ordered_names(class_names)
    if len(labels) != 1 or not labels[0].strip():
        raise ValueError(f"Model 1 must expose exactly one non-empty whole-fish class, got {list(labels)!r}.")
    return labels


class YoloFishDetector:
    """Persistent YOLO Model 1 detector coupled to the existing ByteTrack ID layer."""

    supports_masks = False

    def __init__(
        self,
        model_path: Path | None,
        *,
        confidence_threshold: float = 0.50,
        device: str = "auto",
        image_size: int = 640,
        tracker_config: str = "bytetrack.yaml",
        require_bytetrack: bool = False,
        model_factory: Callable[[str], Any] | None = None,
        tracker_factory: Callable[[str], Any] | None = None,
        track_confirmation_frames: int = 2,
    ) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("FISH_DETECTION_CONFIDENCE must be between 0 and 1.")
        if image_size <= 0:
            raise ValueError("FISH_DETECTOR_IMAGE_SIZE must be positive.")
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.requested_device = device
        self.compute = resolve_compute(device, os.getenv("FISH_INFERENCE_FP16", "auto"))
        self.image_size = image_size
        self.tracker_config = tracker_config
        self.require_bytetrack = require_bytetrack
        self._model_factory = model_factory
        self._tracker_factory = tracker_factory or _default_tracker_factory
        self.model: Any | None = None
        self._tracker: Any | None = None
        self._fish_identities = ConfirmedFishIdentities(track_confirmation_frames)
        self.device: str | int = self.compute.device
        self.fp16 = self.compute.fp16_enabled
        self.error: str | None = None
        self.class_names: tuple[str, ...] = ()
        self.tracker_backend = "unresolved"
        self.tracker_warning: str | None = None
        self.last_inference_seconds: float | None = None
        self.last_tracking_seconds: float | None = None
        self.checkpoint_sha256: str | None = None
        self.checkpoint_sha256_full: str | None = None
        self.checkpoint_integrity = "unresolved"
        self._lock = RLock()

    @property
    def name(self) -> str:
        checkpoint = self.model_path.name if self.model_path else "checkpoint unresolved"
        return f"YOLO whole-fish detector ({checkpoint})"

    @property
    def weights_path(self) -> Path | None:
        return self.model_path

    def _resolve_device(self) -> str | int:
        requested = self.requested_device.strip().lower()
        if requested in {"", "auto"}:
            return self.compute.device
        if requested == "cpu":
            return "cpu"
        if requested.startswith("cuda"):
            try:
                return self.compute.device
            except Exception:
                return "cpu"
        if requested.isdigit():
            return self.compute.device if self.compute.device.startswith("cuda") else "cpu"
        raise YoloFishDetectorLoadError("FISH_DETECTOR_DEVICE must be 'auto', 'cpu', a CUDA device, or a numeric GPU index.")

    def load(self) -> bool:
        if self.model is not None:
            return True
        if self.model_path is None:
            self.error = "Model 1 checkpoint is unresolved. Place model1_fish_parent_detector.pt in models/fish_detector/weights/ or set FISH_DETECTOR_MODEL_PATH."
            return False
        if not self.model_path.is_file():
            self.error = f"Model 1 checkpoint was not found: {self.model_path}. Set FISH_DETECTOR_MODEL_PATH to an existing local checkpoint."
            return False
        try:
            checksum = full_sha256(self.model_path)
            if checksum is None:
                raise YoloFishDetectorLoadError("Cannot hash Model 1 checkpoint.")
            strict_integrity = os.getenv("FISH_STRICT_MODEL_INTEGRITY", "0").strip().lower() in {"1", "true", "yes", "on"}
            integrity = "not_checked"
            if strict_integrity:
                from src.inference.model_registry import get_model_registry
                registry = get_model_registry()
                entry = registry.get_model(registry.get_default_model1_id())
                if entry is None or registry.resolve_checkpoint_path(entry) != self.model_path.resolve():
                    raise YoloFishDetectorLoadError("Strict model integrity requires the registered Model 1 checkpoint path.")
                expected = getattr(entry, "sha256", None)
                if not isinstance(expected, str) or len(expected.strip()) != 64 or checksum != expected.strip().lower():
                    raise YoloFishDetectorLoadError("Model 1 SHA-256 mismatch or missing registry hash.")
                integrity = "verified"
            factory = self._model_factory
            if factory is None:
                from ultralytics import YOLO

                factory = YOLO
            self.device = self._resolve_device()
            model = factory(str(self.model_path))
            if getattr(model, "task", None) != "detect":
                raise YoloFishDetectorLoadError(f"Model 1 must be a YOLO detection checkpoint, got task={getattr(model, 'task', None)!r}.")
            labels = validate_yolo_fish_detector_class_mapping(getattr(model, "names", {}))
            model_to = getattr(model, "to", None)
            if callable(model_to):
                model_to(self.device)
            if self._tracker_factory is not _default_tracker_factory:
                if self.require_bytetrack:
                    raise YoloFishDetectorLoadError("Strict ByteTrack mode does not permit a custom tracker.")
                tracker = self._tracker_factory(self.tracker_config)
                tracker_backend = "custom tracker"
                tracker_warning = "A custom tracker is active; ByteTrack has not been verified."
            elif (lap_error := _lap_dependency_error()) is not None:
                if self.require_bytetrack:
                    raise YoloFishDetectorLoadError(f"ByteTrack is required, but the lap dependency is unavailable ({lap_error}). Install the optional ByteTrack requirements for this Python environment.")
                tracker = _IoUTracker()
                if lap_error == "missing":
                    tracker_backend = "IoU fallback (optional ByteTrack lap dependency unavailable)"
                    tracker_warning = "ByteTrack is unavailable because lap is missing. IoU fallback is active; tracking results may differ."
                else:
                    tracker_backend = "IoU fallback (ByteTrack lap dependency failed to load)"
                    tracker_warning = f"ByteTrack is unavailable because lap could not be loaded ({lap_error}). IoU fallback is active; tracking results may differ."
            else:
                tracker = self._tracker_factory(self.tracker_config)
                tracker_backend = "ByteTrack"
                tracker_warning = None
        except YoloFishDetectorLoadError as exc:
            self.error = str(exc)
            return False
        except Exception as exc:
            self.error = f"Unable to load Model 1 as a local YOLO detector. Verify the checkpoint and Ultralytics/PyTorch installation. Details: {exc}"
            return False
        self.model, self._tracker, self.class_names, self.tracker_backend, self.error = model, tracker, labels, tracker_backend, None
        self.tracker_warning = tracker_warning
        if tracker_warning:
            LOGGER.warning("[TRACKER] %s", tracker_warning)
        # Calculated once at successful startup, never once per camera frame.
        self.checkpoint_sha256_full = checksum
        self.checkpoint_sha256 = checksum[:12]
        self.checkpoint_integrity = integrity
        LOGGER.info(
            "[MODEL 1] requested_device=%s resolved_device=%s class_mapping=%s tracker=%s",
            self.requested_device,
            self.device,
            {index: name for index, name in enumerate(self.class_names)},
            self.tracker_backend,
        )
        return True

    @staticmethod
    def _raw_detections(result: Any, width: int, height: int, threshold: float) -> list[FishDetection]:
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return []
        values: list[FishDetection] = []
        for box in boxes:
            try:
                class_id = float(box.cls.item())
                confidence = float(box.conf.item())
                if class_id != FISH_CLASS_ID or not np.isfinite(confidence) or not 0.0 <= confidence <= 1.0 or confidence < threshold:
                    continue
                xyxy = np.asarray(box.xyxy[0].tolist(), dtype=float).reshape(-1)
                if xyxy.size != 4:
                    continue
                bounded = clamp_bbox(tuple(float(value) for value in xyxy), width, height)
            except (AttributeError, IndexError, TypeError, ValueError, OverflowError):
                continue
            if bounded is not None:
                values.append(FishDetection(bounded, confidence))
        return values

    def detect(self, frame_bgr: Any) -> list[FishDetection]:
        """Run Model 1 without mutating ByteTrack or live counters."""

        return self._detect(frame_bgr, self.confidence_threshold)

    def _detect(self, frame_bgr: Any, threshold: float) -> list[FishDetection]:
        """Collect safe detections at the threshold needed by the caller."""

        if self.model is None:
            raise YoloFishDetectorInferenceError(self.error or "Model 1 is not loaded.")
        try:
            frame = validate_image(frame_bgr, name="Camera frame")
            height, width = frame.shape[:2]
            with self._lock:
                started = timed_start(str(self.device))
                options = {"source": frame, "conf": threshold, "imgsz": self.image_size, "device": self.device, "verbose": False}
                if self.fp16:
                    options["half"] = True
                results = self.model.predict(**options)
                self.last_inference_seconds = timed_elapsed(started, str(self.device))
            return self._raw_detections(results[0], width, height, threshold) if results else []
        except YoloFishDetectorInferenceError:
            raise
        except Exception as exc:
            raise YoloFishDetectorInferenceError(f"Model 1 YOLO inference failed: {exc}") from exc

    def predict(self, frame_bgr: Any) -> list[Detection]:
        if self._tracker is None:
            raise YoloFishDetectorInferenceError(self.error or "Model 1 tracker is not initialized.")
        if self.tracker_backend == "ByteTrack":
            # ByteTrack's second association stage needs weak observations to
            # maintain an existing identity. They remain internal evidence:
            # only detections meeting the operator's threshold leave here.
            try:
                low_threshold = float(getattr(getattr(self._tracker, "args", None), "track_low_thresh", 0.1))
            except (TypeError, ValueError, OverflowError):
                low_threshold = 0.1
            if not np.isfinite(low_threshold) or not 0.0 <= low_threshold <= 1.0:
                low_threshold = 0.1
            raw = self._detect(frame_bgr, min(self.confidence_threshold, low_threshold))
        else:
            raw = self.detect(frame_bgr)
        current_track_ids: set[int] | None = None
        observed_rows: list[Any] | None = None
        try:
            with self._lock:
                missing_limit = getattr(self._tracker, "max_frames_lost",
                                        getattr(self._tracker, "max_time_lost",
                                                getattr(self._tracker, "max_missing_frames", 30)))
                if isinstance(missing_limit, int) and not isinstance(missing_limit, bool) and missing_limit >= 0:
                    self._fish_identities.max_missing_frames = missing_limit
                if self.tracker_backend == "ByteTrack":
                    tracker_args = getattr(self._tracker, "args", None)
                    if tracker_args is not None:
                        # Weak detections may recover an existing track, but
                        # may not start new native candidates below the
                        # operator's threshold. Retain the configured floor so
                        # lowering the live threshold can lower it again.
                        original_floor = getattr(self._tracker, "_lemuru_new_track_floor", None)
                        if original_floor is None:
                            try:
                                original_floor = float(getattr(tracker_args, "new_track_thresh", 0.25))
                            except (TypeError, ValueError, OverflowError):
                                original_floor = 0.25
                            if not np.isfinite(original_floor) or not 0.0 <= original_floor <= 1.0:
                                original_floor = 0.25
                            self._tracker._lemuru_new_track_floor = original_floor
                        tracker_args.new_track_thresh = max(original_floor, self.confidence_threshold)
                started = perf_counter()
                tracks = self._tracker.update(_ByteTrackInput(raw), frame_bgr)
                self.last_tracking_seconds = perf_counter() - started
                # Native ByteTrack exposes the last actual observation frame.
                # A predicted/lost track must never borrow a current raw box
                # through its retained detection index.
                tracker_frame = getattr(self._tracker, "frame_id", None)
                active_tracks = getattr(self._tracker, "tracked_stracks", None)
                if self.tracker_backend == "ByteTrack" and tracker_frame is not None and active_tracks is not None:
                    current_observations = [
                        track for track in active_tracks
                        if track.frame_id == tracker_frame and track.state == 1
                    ]
                    current_track_ids = {
                        int(track.track_id) for track in current_observations if track.is_activated
                    }
                    observed_rows = [getattr(track, "result", None) for track in current_observations]
        except Exception as exc:
            raise YoloFishDetectorInferenceError(f"Model 1 {self.tracker_backend} update failed: {exc}") from exc
        # ByteTrack only emits confirmed tracks. Keep each unmatched raw fish
        # box as untracked so it can compete for Model 2 part ownership while
        # remaining ineligible for grading and line-crossing counts.
        def assignments(values: Any, allowed_ids: set[int] | None = None) -> dict[int, int]:
            matched: dict[int, int] = {}
            ambiguous_sources: set[int] = set()
            sources_by_track: dict[int, set[int]] = {}
            try:
                rows = np.asarray(values, dtype=np.float64)
            except (TypeError, ValueError, OverflowError):
                rows = np.empty((0, 8), dtype=np.float64)
            if rows.ndim == 1 and rows.size == 8:
                rows = rows.reshape((1, 8))
            if rows.ndim != 2 or rows.shape[1] != 8:
                rows = np.empty((0, 8), dtype=np.float64)
            for track in rows:
                if not np.isfinite(track).all() or not track[4].is_integer() or not track[7].is_integer():
                    continue
                source_index = int(track[7])
                if not 0 <= source_index < len(raw):
                    continue
                track_id = int(track[4])
                if track_id < 0 or track[6] != FISH_CLASS_ID or not 0.0 <= track[5] <= 1.0:
                    continue
                if allowed_ids is not None and track_id not in allowed_ids:
                    continue
                if track[2] <= track[0] or track[3] <= track[1]:
                    continue
                # Allow Kalman smoothing while rejecting a stale index that
                # now points at a different fish elsewhere in the frame.
                if _iou(tuple(track[:4]), raw[source_index].bbox) < 0.1:
                    continue
                if source_index in matched and matched[source_index] != track_id:
                    ambiguous_sources.add(source_index)
                else:
                    matched[source_index] = track_id
                sources_by_track.setdefault(track_id, set()).add(source_index)
            for source_indices in sources_by_track.values():
                if len(source_indices) > 1:
                    ambiguous_sources.update(source_indices)
            return {index: track_id for index, track_id in matched.items() if index not in ambiguous_sources}

        matched = assignments(tracks, current_track_ids)
        detections = [
            Detection(FISH_CLASS_ID, FISH_CLASS_NAME, source.confidence, source.bbox,
                      matched.get(index))
            for index, source in enumerate(raw)
            if source.confidence >= self.confidence_threshold
        ]
        observed_tracks = None
        if observed_rows is not None:
            # Actual unconfirmed observations seed the first strong frame;
            # weak observations only retain an already confirmed identity.
            # Neither is published as a tracked fish by this separate seam.
            observed_tracks = [
                Detection(FISH_CLASS_ID, FISH_CLASS_NAME, raw[index].confidence, raw[index].bbox, track_id)
                for index, track_id in assignments(observed_rows).items()
            ]
        with self._lock:
            return self._fish_identities.update(
                detections, minimum_confidence=self.confidence_threshold, observed_tracks=observed_tracks,
            )

    def reset_tracker(self) -> None:
        if self._tracker is not None:
            with self._lock:
                self._tracker.reset()
                self._fish_identities.reset()

    def diagnostics(self) -> dict[str, float | str | int | None]:
        return {
            "device": self.device,
            "backend": self.compute.backend,
            "fp16_enabled": self.fp16,
            "compute": self.compute.to_dict(),
            "tracker": self.tracker_backend,
            "tracker_warning": self.tracker_warning,
            "bytetrack_required": self.require_bytetrack,
            "fish_identity": self._fish_identities.diagnostics(),
            "last_inference_ms": round(self.last_inference_seconds * 1000, 2) if self.last_inference_seconds is not None else None,
            "last_tracking_ms": round(self.last_tracking_seconds * 1000, 2) if self.last_tracking_seconds is not None else None,
            "checkpoint_name": self.model_path.name if self.model_path else None,
            "checkpoint_sha256": self.checkpoint_sha256,
            "requested_device": self.requested_device,
            "class_mapping": {index: name for index, name in enumerate(self.class_names)},
        }
