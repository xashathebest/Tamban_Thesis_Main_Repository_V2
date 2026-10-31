"""FastAPI application for the local inspection dashboard."""

from __future__ import annotations

import os
import asyncio
import json
import hashlib
import logging
import math
from collections import deque
from copy import deepcopy
from pathlib import Path
import subprocess
from contextlib import asynccontextmanager, nullcontext
from datetime import datetime
from time import monotonic
from threading import RLock

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src.api.camera import CameraInspectionService
from src.api import lan_security
from src.api.camera_controls import CAMERA_PROPERTIES, CameraControlError
from src.api.database import InspectionDatabase, InspectionSessionContext, grading_config_hash
from src.api.event_persistence import OrderedPersistenceDispatcher
from src.api.image_analysis import ImageUploadError, PartPreviewImageAnalyzer, StillImageAnalyzer, decode_uploaded_image
from src.api.domain import FEATURE_CAPABILITIES, QUALITY_COUNTER_NAMES, InspectionState, TrackingConfig
from src.api.export import DEFAULT_EXPORT_FIELDS, EXPORT_FIELDS, make_csv, make_xlsx
from src.api.expert_library import router as expert_library_router
from src.api.runtime import (
    PART_PREVIEW_MODE,
    resolve_part_weights_path,
    resolve_quality_inference_mode,
    resolve_runtime_mode,
)
from src.inference.yolo_fish_detector import YoloFishDetector, resolve_yolo_fish_detector_model_path
from src.inference.yolo_quality_model import YoloQualityModel, resolve_yolo_quality_model_path
from src.inference.model_registry import get_model_registry
from src.inference.structural_evidence import StructuralEvidence, summarize_structural_evidence
from src.inference.part_model import YoloPartModel
from src.inference.compute import resolve_compute
from src.preprocessing.dataset_utils import load_yaml_file, project_root


REPO_ROOT = project_root()
FRONTEND_DIR = REPO_ROOT / "frontend"
LOGGER = logging.getLogger(__name__)


def _optional_positive_float_setting(name: str) -> float | None:
    """Read an optional operator-supplied timing limit without inventing one."""

    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive number of seconds when set.") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number of seconds when set.")
    return value


def _positive_int_setting(name: str, default: int) -> int:
    """Read one bounded-queue capacity without accepting an unsafe zero value."""

    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer when set.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer when set.")
    return value
# Serialize inspection start with changes to the shared model or grading policy.
_model_change_lock = RLock()
PART_CONFIG = load_yaml_file(REPO_ROOT / "configs" / "yolov8.yaml")
FISH_DETECTION_CONFIDENCE = float(os.getenv("FISH_DETECTION_CONFIDENCE", "0.5"))
FISH_DETECTOR_DEVICE = os.getenv("FISH_DETECTOR_DEVICE", "auto")
FISH_DETECTOR_PATH = resolve_yolo_fish_detector_model_path(REPO_ROOT, os.getenv("FISH_DETECTOR_MODEL_PATH"))
_model_registry = get_model_registry()
# Keep Model 1 at the registered checkpoint's training resolution unless an
# operator deliberately overrides it.  A stale 640-pixel application default
# silently downscaled the active 768-pixel parent detector before it could
# locate fish or establish Model 2 parent ownership.
_active_model1_entry = _model_registry.get_model(_model_registry.get_default_model1_id())
_default_detector_image_size = _active_model1_entry.input_size if _active_model1_entry is not None else 640
FISH_DETECTOR_IMAGE_SIZE = int(os.getenv("FISH_DETECTOR_IMAGE_SIZE", str(_default_detector_image_size)))
FISH_QUALITY_CONFIDENCE = float(os.getenv("FISH_QUALITY_CONFIDENCE", os.getenv("FISH_SEGMENTATION_CONFIDENCE", "0.25")))
FISH_QUALITY_DEVICE = os.getenv("FISH_QUALITY_DEVICE", os.getenv("FISH_SEGMENTER_DEVICE", FISH_DETECTOR_DEVICE))
FISH_QUALITY_PATH = resolve_yolo_quality_model_path(REPO_ROOT, os.getenv("FISH_QUALITY_MODEL_PATH", os.getenv("FISH_SEGMENTER_MODEL_PATH")))
_active_model_entry = _model_registry.get_model(_model_registry.get_persisted_model2_id())
_default_quality_image_size = _active_model_entry.input_size if _active_model_entry is not None else 640
FISH_QUALITY_IMAGE_SIZE = int(os.getenv("FISH_QUALITY_IMAGE_SIZE", str(_default_quality_image_size)))
FISH_QUALITY_INTERVAL = int(os.getenv("FISH_QUALITY_INTERVAL", os.getenv("FISH_SEGMENTATION_INTERVAL", "3")))
FISH_QUALITY_ROI_PADDING = int(os.getenv("FISH_QUALITY_ROI_PADDING", os.getenv("FISH_SEGMENTATION_ROI_PADDING", "0")))
_REQUESTED_FISH_QUALITY_INFERENCE_MODE = os.getenv("FISH_QUALITY_INFERENCE_MODE", "full_frame").strip().lower()
FISH_UPLOAD_MAX_BYTES = int(os.getenv("FISH_UPLOAD_MAX_BYTES", str(10 * 1024 * 1024)))
FISH_UPLOAD_MAX_DIMENSION = int(os.getenv("FISH_UPLOAD_MAX_DIMENSION", "4096"))
FISH_UPLOAD_MAX_PIXELS = int(os.getenv("FISH_UPLOAD_MAX_PIXELS", str(16 * 1024 * 1024)))
PART_CONFIDENCE = float(os.getenv("LEMURU_PART_CONFIDENCE", os.getenv("LEMURU_CONFIDENCE", "0.25")))
PART_IMAGE_SIZE = int(PART_CONFIG.get("imgsz", 640))
CAMERA_INDEX = int(os.getenv("LEMURU_CAMERA_INDEX", "0"))
RUNTIME_MODE = resolve_runtime_mode(os.getenv("LEMURU_MODE"))
FISH_QUALITY_INFERENCE_MODE = resolve_quality_inference_mode(
    _REQUESTED_FISH_QUALITY_INFERENCE_MODE,
    RUNTIME_MODE,
)
if FISH_QUALITY_INFERENCE_MODE != _REQUESTED_FISH_QUALITY_INFERENCE_MODE:
    LOGGER.warning(
        "FISH_QUALITY_INFERENCE_MODE=%s is unsafe for whole-fish live grading; using full_frame association.",
        _REQUESTED_FISH_QUALITY_INFERENCE_MODE,
    )
PART_WEIGHTS_PATH = resolve_part_weights_path(REPO_ROOT, os.getenv("LEMURU_PART_WEIGHTS"))
UPLOAD_TEST_WEIGHTS_PATH = (REPO_ROOT / "models" / "yolo_parts" / "yolo26n_seg_exp4" / "weights" / "exp-4.pt").resolve()
UPLOAD_TEST_CONFIDENCE = float(os.getenv("LEMURU_UPLOAD_TEST_CONFIDENCE", str(PART_CONFIDENCE)))
TRACKING_CONFIG = TrackingConfig(
    tracker=os.getenv("LEMURU_TRACKER", "bytetrack.yaml"),
    line_orientation=os.getenv("LEMURU_LINE_ORIENTATION", "vertical").lower(),
    line_position=float(os.getenv("LEMURU_LINE_POSITION", "0.65")),
    conveyor_direction=os.getenv("LEMURU_CONVEYOR_DIRECTION", "left_to_right").lower(),
    track_timeout=float(os.getenv("LEMURU_TRACK_TIMEOUT", "1.5")),
    history_limit=int(os.getenv("LEMURU_HISTORY_LIMIT", "25")),
    decision_deadline_seconds=_optional_positive_float_setting("LEMURU_DECISION_DEADLINE_SECONDS"),
)
EVENT_PERSISTENCE_QUEUE_CAPACITY = _positive_int_setting("FISH_EVENT_PERSISTENCE_QUEUE_CAPACITY", 256)
EVENT_PERSISTENCE_DRAIN_TIMEOUT_SECONDS = 3.0

state = InspectionState(TRACKING_CONFIG, runtime_mode=RUNTIME_MODE)
quality_model: YoloQualityModel | None = None
if RUNTIME_MODE == PART_PREVIEW_MODE:
    state.confidence_threshold = PART_CONFIDENCE
    model = YoloPartModel(PART_WEIGHTS_PATH, confidence=PART_CONFIDENCE, imgsz=PART_IMAGE_SIZE)
else:
    state.confidence_threshold = FISH_DETECTION_CONFIDENCE
    state.set_quality_confidence_threshold(FISH_QUALITY_CONFIDENCE)
    model = YoloFishDetector(
        FISH_DETECTOR_PATH,
        confidence_threshold=FISH_DETECTION_CONFIDENCE,
        device=FISH_DETECTOR_DEVICE,
        image_size=FISH_DETECTOR_IMAGE_SIZE,
        tracker_config=TRACKING_CONFIG.tracker,
        require_bytetrack=os.getenv("FISH_REQUIRE_BYTETRACK", "0").strip().lower() in {"1", "true", "yes", "on"},
    )
    quality_model = YoloQualityModel(
        FISH_QUALITY_PATH,
        confidence_threshold=FISH_QUALITY_CONFIDENCE,
        device=FISH_QUALITY_DEVICE,
        image_size=FISH_QUALITY_IMAGE_SIZE,
        quality_inference_mode=FISH_QUALITY_INFERENCE_MODE,
        roi_padding=FISH_QUALITY_ROI_PADDING,
    )
    if quality_model.load():
        state.set_segmenter("ready", quality_model.name, str(quality_model.weights_path), f"Quality Model ready on {quality_model.device}.")
    else:
        state.set_segmenter("unavailable", None, str(quality_model.weights_path) if quality_model.weights_path else None, quality_model.error or "Quality Model is unavailable.")
service = CameraInspectionService(
    state, model, camera_index=CAMERA_INDEX, runtime_mode=RUNTIME_MODE,
    quality_model=quality_model, quality_interval=FISH_QUALITY_INTERVAL,
    quality_roi_padding=FISH_QUALITY_ROI_PADDING,
    quality_inference_mode=FISH_QUALITY_INFERENCE_MODE,
    camera_profile_path=REPO_ROOT / "configs" / "camera_settings.yaml",
)
image_analyzer = StillImageAnalyzer(model, quality_model, roi_padding=FISH_QUALITY_ROI_PADDING) if RUNTIME_MODE != PART_PREVIEW_MODE else None
upload_test_model = YoloPartModel(UPLOAD_TEST_WEIGHTS_PATH, confidence=UPLOAD_TEST_CONFIDENCE, imgsz=PART_IMAGE_SIZE) if RUNTIME_MODE == PART_PREVIEW_MODE else None
upload_test_analyzer = PartPreviewImageAnalyzer(upload_test_model) if upload_test_model is not None else None
_database_setting = os.getenv("FISH_INSPECTION_DB_PATH")
INSPECTION_DATABASE_PATH = (Path(_database_setting) if _database_setting else REPO_ROOT / "results" / "inspection_history.sqlite3").resolve()
inspection_database = InspectionDatabase(INSPECTION_DATABASE_PATH)
inspection_sessions = InspectionSessionContext(inspection_database)


def _close_worker_session() -> None:
    """Finalize the durable session only after its camera worker has exited."""

    # ``stop_inspection`` may still own the model-change lock while waiting for
    # this finalizer.  The worker is already gone; the frame barrier alone is
    # sufficient and avoids delaying the truthful final stop state.
    _close_durable_session("camera worker finalization", timeout=None, acquire_model_lock=False)


service.on_worker_exit = _close_worker_session


def _checkpoint_sha256(path: object, fallback: object = None) -> str | None:
    """Calculate a full checkpoint fingerprint once per session when possible."""

    try:
        checkpoint = Path(path) if path is not None else None
        if checkpoint is None or not checkpoint.is_file():
            return str(fallback) if fallback else None
        digest = hashlib.sha256()
        with checkpoint.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return str(fallback) if fallback else None


def _git_commit() -> str | None:
    """Best-effort source revision without requiring Git for ordinary startup."""

    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={REPO_ROOT}", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def _camera_settings_snapshot() -> dict[str, object]:
    """Capture accepted camera values only; unavailable hardware remains explicit."""

    try:
        status = service.camera_status()
    except Exception as exc:  # pragma: no cover - hardware boundary
        return {"available": False, "reason": f"Camera settings unavailable: {exc}"}
    return {
        "available": bool(status.get("available")),
        "actual": status.get("actual", {}),
        "camera": status.get("camera", {}),
        "locked": status.get("locked"),
        "profile": status.get("profile", {}),
    }


def _grading_snapshot() -> dict[str, object]:
    if quality_model is None:
        return {}
    try:
        diagnostics = quality_model.diagnostics()
    except Exception:
        return {}
    config = diagnostics.get("grading_config") if isinstance(diagnostics, dict) else None
    return dict(config) if isinstance(config, dict) else {}


def _device_report() -> dict[str, object]:
    """Report requested versus actually available compute without installing anything."""

    try:
        import torch

        model1_compute = getattr(model, "compute", resolve_compute(FISH_DETECTOR_DEVICE))
        model2_compute = getattr(quality_model, "compute", resolve_compute(FISH_QUALITY_DEVICE)) if quality_model is not None else None
        return {
            "pytorch_cuda_available": bool(torch.cuda.is_available()),
            "pytorch_cuda_version": torch.version.cuda,
            "cuda_device_count": int(torch.cuda.device_count()) if torch.cuda.is_available() else 0,
            "requested_model1_device": FISH_DETECTOR_DEVICE,
            "requested_model2_device": FISH_QUALITY_DEVICE,
            "model1_device": getattr(model, "device", "unresolved"),
            "model2_device": getattr(quality_model, "device", "unresolved"),
            "model1_compute": model1_compute.to_dict(),
            "model2_compute": model2_compute.to_dict() if model2_compute is not None else None,
        }
    except Exception as exc:
        return {
            "pytorch_cuda_available": False,
            "pytorch_cuda_version": None,
            "cuda_device_count": 0,
            "requested_model1_device": FISH_DETECTOR_DEVICE,
            "requested_model2_device": FISH_QUALITY_DEVICE,
            "model1_device": getattr(model, "device", "unresolved"),
            "model2_device": getattr(quality_model, "device", "unresolved"),
            "model1_compute": resolve_compute(FISH_DETECTOR_DEVICE).to_dict(),
            "model2_compute": resolve_compute(FISH_QUALITY_DEVICE).to_dict() if quality_model is not None else None,
            "device_probe_error": str(exc),
        }


def _session_metadata() -> dict[str, object]:
    """Create one JSON-safe reproducibility snapshot for a durable session."""

    model1_path = getattr(model, "weights_path", None)
    model2_path = getattr(quality_model, "weights_path", None) if quality_model is not None else None
    grading_config = _grading_snapshot()
    return {
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "model1_path": str(model1_path) if model1_path else None,
        "model1_sha256": getattr(model, "checkpoint_sha256_full", None) or _checkpoint_sha256(model1_path, getattr(model, "checkpoint_sha256", None)),
        "model2_path": str(model2_path) if model2_path else None,
        "model2_sha256": getattr(quality_model, "checkpoint_sha256_full", None) or _checkpoint_sha256(model2_path, getattr(quality_model, "checkpoint_sha256", None)),
        "model2_id": getattr(quality_model, "active_model_id", None),
        "model2_name": getattr(quality_model, "active_model_name", None),
        "tracker_backend": getattr(model, "tracker_backend", None),
        "grading_config": grading_config,
        "grading_config_hash": grading_config_hash(grading_config),
        "camera_settings": _camera_settings_snapshot(),
        "runtime_settings": {
            "runtime_mode": RUNTIME_MODE,
            "quality_inference_mode": (
                getattr(service, "quality_inference_mode", FISH_QUALITY_INFERENCE_MODE)
                if RUNTIME_MODE != PART_PREVIEW_MODE
                else "not_applicable"
            ),
            "camera_index": CAMERA_INDEX,
            "model1": {
                "image_size": getattr(model, "image_size", FISH_DETECTOR_IMAGE_SIZE),
                "checkpoint_integrity": getattr(model, "checkpoint_integrity", "unavailable"),
                "device": getattr(model, "device", FISH_DETECTOR_DEVICE),
                "detector_confidence_threshold": getattr(model, "confidence_threshold", state.confidence_threshold),
                "class_names": list(getattr(model, "class_names", ())),
            },
            "model2": {
                "model_id": getattr(quality_model, "active_model_id", None),
                "model_name": getattr(quality_model, "active_model_name", None),
                "checkpoint_integrity": getattr(quality_model, "checkpoint_integrity", "unavailable"),
                "image_size": getattr(quality_model, "image_size", FISH_QUALITY_IMAGE_SIZE) if quality_model is not None else None,
                "device": getattr(quality_model, "device", FISH_QUALITY_DEVICE) if quality_model is not None else None,
                "detector_confidence_threshold": getattr(quality_model, "confidence_threshold", None) if quality_model is not None else None,
                "class_names": list(getattr(quality_model, "class_names", {}).values()) if quality_model is not None else [],
                "quality_interval": service.quality_interval,
                "roi_padding": service.quality_roi_padding,
            },
            "tracking": state.tracking.config.to_dict(),
            "preprocessing": {"automatic_image_adjustments": False},
            "device_report": _device_report(),
        },
    }


def _persist_tracking_event(
    action: str,
    event: dict[str, object],
    *,
    session_id: str | None = None,
    raise_on_failure: bool = False,
) -> None:
    """Write one immutable event snapshot to its captured durable session.

    Direct callers retain the historical best-effort behavior. The background
    dispatcher asks for failures to be raised so the FIFO head is retained.
    """

    persistence_started = monotonic()
    try:
        persisted_session_id = (
            inspection_sessions.record_event_for(session_id, action, event)
            if session_id is not None
            else inspection_sessions.record_event(action, event)
        )
        if persisted_session_id is None:
            message = f"Ignoring {action} for Fish #{event.get('track_id')} without an eligible session"
            if raise_on_failure:
                raise RuntimeError(message)
            LOGGER.warning(message)
            return
        # Camera configuration is recorded at session start and close. Keeping
        # camera-control I/O out of this worker preserves the frame-path split.
    except Exception as exc:
        LOGGER.exception("Could not persist %s for Fish #%s: %s", action, event.get("track_id"), exc)
        if raise_on_failure:
            raise
    finally:
        try:
            service.record_event_persistence(max(0.0, monotonic() - persistence_started))
        except Exception:  # pragma: no cover - diagnostics must not affect persistence
            LOGGER.exception("Could not record event-persistence timing")


def _persist_queued_tracking_event(record: dict[str, object]) -> None:
    """Dispatcher callback; an exception keeps the current FIFO head visible."""

    session_id = record.get("session_id")
    action = record.get("action")
    event = record.get("event")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Queued event persistence requires a captured session ID.")
    if not isinstance(action, str) or not isinstance(event, dict):
        raise ValueError("Queued event persistence record is malformed.")
    _persist_tracking_event(action, event, session_id=session_id, raise_on_failure=True)


_event_persistence_dispatcher_lock = RLock()


def _new_event_persistence_dispatcher() -> OrderedPersistenceDispatcher[dict[str, object]]:
    return OrderedPersistenceDispatcher(
        _persist_queued_tracking_event,
        capacity=EVENT_PERSISTENCE_QUEUE_CAPACITY,
        thread_name="inspection-event-persistence",
    )


event_persistence_dispatcher = _new_event_persistence_dispatcher()


def _event_persistence_snapshot() -> dict[str, object]:
    with _event_persistence_dispatcher_lock:
        return dict(event_persistence_dispatcher.snapshot())


def _event_persistence_dispatcher_for_submit() -> OrderedPersistenceDispatcher[dict[str, object]]:
    """Recreate only a cleanly shut-down worker, never one with retained data."""

    global event_persistence_dispatcher
    with _event_persistence_dispatcher_lock:
        snapshot = event_persistence_dispatcher.snapshot()
        if snapshot["failed"] or (snapshot["worker_alive"] and snapshot["stopping"]):
            return event_persistence_dispatcher
        if snapshot["accepting"] and snapshot["worker_alive"]:
            return event_persistence_dispatcher
        if snapshot["pending"] or snapshot["in_flight"]:
            return event_persistence_dispatcher
        event_persistence_dispatcher = _new_event_persistence_dispatcher()
        return event_persistence_dispatcher


def _event_persistence_problem(context: str, snapshot: dict[str, object]) -> str:
    failure = snapshot.get("failure")
    if isinstance(failure, dict):
        detail = f"{failure.get('exception_type', 'Persistence error')}: {failure.get('message', 'unknown error')}"
        return f"Durable event persistence failed during {context}; the session remains open. {detail}"
    if snapshot.get("pending") or snapshot.get("in_flight"):
        return f"Durable event persistence is still flushing during {context}; the session remains open."
    return f"Durable event persistence is unavailable during {context}; the session remains open."


def _mark_event_persistence_failed(context: str, snapshot: dict[str, object]) -> None:
    """Expose an unrecoverable durable-write failure and stop future counting."""

    message = _event_persistence_problem(context, snapshot)
    LOGGER.error("%s queue=%s", message, snapshot)
    try:
        request_stop = getattr(service, "request_stop_after_current_frame", None)
        if callable(request_stop):
            request_stop(message)
        else:
            state.mark_error(message)
    except Exception:  # pragma: no cover - status handling cannot hide the stored failure
        LOGGER.exception("Could not mark durable event persistence failure")


def _drain_event_persistence(context: str, *, timeout: float | None) -> bool:
    """Flush FIFO work before a session identity or direct durable write changes."""

    with _event_persistence_dispatcher_lock:
        dispatcher = event_persistence_dispatcher
    if dispatcher.drain(timeout=timeout):
        return True
    snapshot = dict(dispatcher.snapshot())
    LOGGER.error("%s queue=%s", _event_persistence_problem(context, snapshot), snapshot)
    if snapshot.get("failed"):
        _mark_event_persistence_failed(context, snapshot)
    return False


def _require_drained_event_persistence(context: str) -> None:
    if _drain_event_persistence(context, timeout=EVENT_PERSISTENCE_DRAIN_TIMEOUT_SECONDS):
        return
    snapshot = _event_persistence_snapshot()
    status_code = 503 if snapshot.get("failed") else 409
    raise HTTPException(status_code=status_code, detail=_event_persistence_problem(context, snapshot))


def _processing_guard():
    """Use the real frame barrier, with a harmless fallback for narrow unit fakes."""

    lock = getattr(service, "_processing_lock", None)
    return lock if lock is not None else nullcontext()


def _close_durable_session_locked(context: str, *, timeout: float | None) -> bool:
    """Flush then close exactly one session without re-entering camera control."""

    if not _drain_event_persistence(context, timeout=timeout):
        return False
    if not inspection_sessions.active:
        return True
    try:
        # Session metadata is captured at start and whenever a camera policy
        # rotates the session. Do not query a possibly blocked camera-control
        # lock during finalization; durable events are already flushed above.
        inspection_sessions.close()
        return True
    except Exception as exc:
        LOGGER.exception("Could not close durable inspection session after %s: %s", context, exc)
        _mark_event_persistence_failed(context, {**_event_persistence_snapshot(), "failure": {
            "exception_type": type(exc).__name__, "message": str(exc),
        }})
        return False


def _close_durable_session(
    context: str,
    *,
    timeout: float | None,
    acquire_model_lock: bool = True,
) -> bool:
    """Close only after queued writes and frame callbacks can no longer race it."""

    model_guard = _model_change_lock if acquire_model_lock else nullcontext()
    with model_guard, _processing_guard():
        return _close_durable_session_locked(context, timeout=timeout)


def _enqueue_tracking_event(action: str, event: dict[str, object]) -> None:
    """Capture durable identity first, then hand an immutable copy to the worker."""

    try:
        session_id = inspection_sessions.capture_event_target(action, event)
    except Exception as exc:
        LOGGER.exception("Could not capture durable target for %s / Fish #%s: %s", action, event.get("track_id"), exc)
        _mark_event_persistence_failed("event target capture", {"failed": True, "failure": {
            "exception_type": type(exc).__name__, "message": str(exc),
        }})
        return
    if session_id is None:
        LOGGER.warning("Ignoring %s for Fish #%s without an eligible session", action, event.get("track_id"))
        return
    try:
        dispatcher = _event_persistence_dispatcher_for_submit()
        # Healthy submissions return immediately. Saturation applies FIFO
        # producer backpressure instead of an unsafe direct write around older
        # records.
        accepted = dispatcher.submit({"session_id": session_id, "action": action, "event": event})
        snapshot = dict(dispatcher.snapshot())
    except Exception as exc:
        LOGGER.exception("Could not enqueue durable event %s / Fish #%s: %s", action, event.get("track_id"), exc)
        _mark_event_persistence_failed("event enqueue", {"failed": True, "failure": {
            "exception_type": type(exc).__name__, "message": str(exc),
        }})
        return
    if accepted:
        return
    _mark_event_persistence_failed("event enqueue", snapshot)


def _rotate_durable_session_locked() -> str:
    _require_drained_event_persistence("durable session rotation")
    return inspection_sessions.rotate(_session_metadata())


def rotate_durable_session() -> str:
    """Start a new durable policy version only after the prior FIFO drains."""

    with _model_change_lock, _processing_guard():
        return _rotate_durable_session_locked()


def _durable_events(
    *,
    range_name: str = "current_session",
    start_date: str | None = None,
    end_date: str | None = None,
    session_id: str | None = None,
) -> list[dict[str, object]]:
    """Read the durable source, with a small legacy fallback before a session starts."""

    requested_session = session_id or (inspection_sessions.session_id if range_name == "current_session" else None)
    events = inspection_database.events(
        session_id=requested_session,
        range_name=range_name,
        start_date=start_date,
        end_date=end_date,
    )
    if not events and range_name == "current_session" and requested_session is None:
        # Unit callers and a stopped app before its first durable session retain
        # the historical in-memory behavior, but live completed events always
        # arrive here through the tracking listener below.
        return state.tracking.archive_history()
    return events


state.tracking.add_event_listener(_enqueue_tracking_event)


@asynccontextmanager
async def lifespan(_: FastAPI):
    inspection_database.initialize()
    if model.load():
        mode_message = "Raw part preview ready; fish counting is disabled. " if RUNTIME_MODE == PART_PREVIEW_MODE else ""
        state.set_model("ready", model.name, str(model.weights_path), f"{mode_message}Model ready on {model.device}.")
        state.mark_tracker_ready()
    else:
        state.set_model("unavailable", None, None, model.error or "Model is unavailable.")
    if quality_model is None:
        state.set_segmenter("disabled", None, None, "Part-preview mode does not run the Model 2 quality pipeline.")
    elif quality_model.load():
        state.set_segmenter("ready", quality_model.name, str(quality_model.weights_path), f"Quality Model ready on {quality_model.device}.")
    else:
        state.set_segmenter("unavailable", None, str(quality_model.weights_path) if quality_model.weights_path else None, quality_model.error or "Quality Model is unavailable.")
    if upload_test_model is not None:
        # This preview-only model never participates in the production pipeline.
        upload_test_model.load()
    LOGGER.info("[RUNTIME] device_report=%s", _device_report())
    try:
        yield
    finally:
        # API stop requests remain bounded; process shutdown waits for the
        # worker/finalizer so accepted durable writes cannot be abandoned.
        service.stop(timeout=None)
        if service.has_live_worker():
            LOGGER.error("Camera worker is still running at shutdown; its durable session remains open.")
        else:
            # Graceful shutdown never abandons an accepted FIFO record. A
            # blocked write keeps shutdown pending; a recorded worker failure
            # returns promptly and leaves the durable session open.
            closed = _close_durable_session("application shutdown", timeout=None)
            if closed:
                with _event_persistence_dispatcher_lock:
                    dispatcher = event_persistence_dispatcher
                if not dispatcher.shutdown(timeout=None):
                    LOGGER.critical("Event persistence dispatcher did not shut down cleanly: %s", dispatcher.snapshot())
            else:
                LOGGER.critical("Durable session remains open because event persistence did not flush before shutdown.")


app = FastAPI(title="Sardinella Lemuru Fish Detection API", version="3.0.0", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")
app.include_router(expert_library_router)
app.include_router(lan_security.router)


@app.middleware("http")
async def protect_lan_requests(request: Request, call_next):
    denied = await lan_security.guard(request)
    if denied is not None:
        return denied
    context = lan_security.request_role.set(getattr(request.state, "lan_role", None))
    try:
        response = await call_next(request)
    finally:
        lan_security.request_role.reset(context)
    if lan_security.enabled() and request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def _feature_counters(events: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    """Count fish with real final Model 2 regional evidence, never fake defects."""

    observed_regions: dict[str, int] = {name: 0 for name in FEATURE_CAPABILITIES}
    for event in events:
        analysis = event.get("analysis")
        part_results = analysis.get("part_results") if isinstance(analysis, dict) and isinstance(analysis.get("part_results"), dict) else {}
        for region in observed_regions:
            result = part_results.get(region) if isinstance(part_results, dict) else None
            if isinstance(result, dict) and result.get("present") is True:
                observed_regions[region] += 1
    counters: dict[str, dict[str, object]] = {}
    for name, capability in FEATURE_CAPABILITIES.items():
        counters[name] = {
            "count": observed_regions[name],
            "available": bool(capability["available"]),
            "source": capability["source"],
        }
    return counters


class _RunningValues:
    """Keep the sum and count used by dashboard averages without retaining samples."""
    def __init__(self) -> None:
        self.total = 0.0
        self.count = 0

    def append(self, value: float) -> None:
        self.total += value
        self.count += 1

    def __len__(self) -> int:
        return self.count

    def __iter__(self):
        yield self.total


_ANALYTICS_TREND_LIMIT = 500
_analytics_cache_lock = RLock()
_analytics_cache: dict[str, object] = {}


def _analytics(events, snapshot: dict[str, object], *, chronological_input: bool = False,
               previous: dict[str, object] | None = None, return_state: bool = False):
    """Build dashboard analytics from current or historical durable events."""

    quality_counters = {name: 0 for name in QUALITY_COUNTER_NAMES}
    chronological = events if chronological_input else reversed(events)
    throughput = deque(maxlen=_ANALYTICS_TREND_LIMIT)
    confidence_over_time = deque(maxlen=_ANALYTICS_TREND_LIMIT)
    grade_confidences = _RunningValues()
    detection_confidences = _RunningValues()
    processing_times = _RunningValues()
    decision_latency_values = _RunningValues()
    deadline_status_counts = {"not_configured": 0, "met": 0, "missed": 0}
    part_quality = {"Head": _RunningValues(), "Body": _RunningValues(), "Tail": _RunningValues()}
    color_trend = deque(maxlen=_ANALYTICS_TREND_LIMIT)
    hue_values = _RunningValues()
    coverage_values = _RunningValues()
    observed_region_counts = _RunningValues()
    model2_observation_counts = _RunningValues()
    feature_counts = _feature_counters([])
    ungraded_reasons: dict[str, int] = {}
    event_count = 0
    automatic_count = 0
    needs_review_count = 0
    manual_review_count = 0
    review_queue_count = 0
    body_only_count = 0
    two_region_count = 0
    complete_region_count = 0
    final_supports = _RunningValues()
    best_supports = _RunningValues()
    performance_values = {key: _RunningValues() for key in (
        "model1_inference_ms", "model2_inference_ms", "grading_engine_ms",
        "hsv_processing_ms", "tracking_ms", "total_processing_ms",
    )}
    if previous is not None:
        saved = deepcopy(previous)
        quality_counters = saved["quality_counters"]
        throughput, confidence_over_time = saved["throughput"], saved["confidence_over_time"]
        grade_confidences, detection_confidences, processing_times = saved["grade_confidences"], saved["detection_confidences"], saved["processing_times"]
        decision_latency_values = saved.get("decision_latency_values", decision_latency_values)
        deadline_status_counts = saved.get("deadline_status_counts", deadline_status_counts)
        part_quality, color_trend, hue_values = saved["part_quality"], saved["color_trend"], saved["hue_values"]
        coverage_values, observed_region_counts, model2_observation_counts = saved["coverage_values"], saved["observed_region_counts"], saved["model2_observation_counts"]
        feature_counts, event_count = saved["feature_counts"], saved["event_count"]
        ungraded_reasons = saved["ungraded_reasons"]
        automatic_count, needs_review_count, manual_review_count = saved["automatic_count"], saved["needs_review_count"], saved["manual_review_count"]
        review_queue_count = saved["review_queue_count"]
        body_only_count, two_region_count, complete_region_count = saved["body_only_count"], saved["two_region_count"], saved["complete_region_count"]
        final_supports, best_supports, performance_values = saved["final_supports"], saved["best_supports"], saved["performance_values"]
    for event in chronological:
        event_count += 1
        quality = event.get("quality")
        if quality not in quality_counters:
            event_analysis = event.get("analysis")
            quality = event_analysis.get("final_grade") if isinstance(event_analysis, dict) else None
        quality_bucket = quality if quality in quality_counters else "Ungraded"
        quality_counters[quality_bucket] += 1
        throughput.append({"timestamp": event.get("timestamp"), "total": event_count})
        if event.get("quality_confidence") is not None:
            confidence = float(event["quality_confidence"]) * 100
            grade_confidences.append(confidence)
            confidence_over_time.append({"timestamp": event.get("timestamp"), "confidence": round(confidence, 1)})
        if event.get("final_confidence") is not None:
            detection_confidences.append(float(event["final_confidence"]) * 100)
        if event.get("processing_time_ms") is not None:
            processing_times.append(float(event["processing_time_ms"]))
        analysis = event.get("analysis")
        conveyor_timing = analysis.get("conveyor_timing") if isinstance(analysis, dict) and isinstance(analysis.get("conveyor_timing"), dict) else {}
        latency_ms = conveyor_timing.get("first_detection_to_decision_ms") if isinstance(conveyor_timing, dict) else None
        if latency_ms is not None:
            try:
                parsed_latency = float(latency_ms)
                if math.isfinite(parsed_latency) and parsed_latency >= 0:
                    decision_latency_values.append(parsed_latency)
            except (TypeError, ValueError):
                pass
        deadline_status = conveyor_timing.get("deadline_status") if isinstance(conveyor_timing, dict) else None
        if deadline_status in deadline_status_counts:
            deadline_status_counts[str(deadline_status)] += 1
        if quality_bucket == "Ungraded":
            reasons = analysis.get("reason_codes") if isinstance(analysis, dict) else None
            codes = {code for code in reasons if isinstance(code, str) and code.strip()} if isinstance(reasons, (list, tuple)) else set()
            if not codes and isinstance(analysis, dict):
                reason = analysis.get("verdict_reason_code")
                if isinstance(reason, str) and reason.strip():
                    codes.add(reason)
            for code in codes or {"Not recorded"}:
                ungraded_reasons[code] = ungraded_reasons.get(code, 0) + 1
        part_results = analysis.get("part_results") if isinstance(analysis, dict) and isinstance(analysis.get("part_results"), dict) else {}
        for region, counter in feature_counts.items():
            result = part_results.get(region)
            if isinstance(result, dict) and result.get("present") is True:
                counter["count"] += 1
        colors = analysis.get("color") if isinstance(analysis, dict) and isinstance(analysis.get("color"), dict) else {}
        if isinstance(analysis, dict):
            status = analysis.get("verdict_status")
            automatic_count += int(status == "AUTO_GRADED")
            needs_review_count += int(status == "NEEDS_REVIEW")
            review_queue_count += int(status == "NEEDS_REVIEW" and not event.get("manual_override"))
            coverage = analysis.get("original_weight_coverage")
            if coverage is not None:
                try:
                    coverage_values.append(float(coverage) * 100)
                except (TypeError, ValueError):
                    pass
            regions = analysis.get("observed_regions")
            if not isinstance(regions, list):
                regions = [region for region in ("Body", "Head", "Tail")
                           if isinstance(part_results.get(region), dict) and part_results[region].get("present") is True]
            region_count = len(regions)
            observed_region_counts.append(region_count)
            body_only_count += int(region_count == 1 and "Body" in regions)
            two_region_count += int(region_count == 2)
            complete_region_count += int(region_count == 3)
            observations = analysis.get("observation_count")
            if observations is not None:
                try:
                    model2_observation_counts.append(int(observations))
                except (TypeError, ValueError):
                    pass
            final_score = analysis.get("final_score")
            if final_score is not None:
                try:
                    final_supports.append(float(final_score) * 100)
                except (TypeError, ValueError):
                    pass
            best_score = analysis.get("provisional_score", analysis.get("best_evidence_score"))
            if best_score is not None:
                try:
                    best_supports.append(float(best_score) * 100)
                except (TypeError, ValueError):
                    pass
            performance = analysis.get("performance")
            if isinstance(performance, dict):
                for key, values in performance_values.items():
                    value = performance.get(key)
                    if value is not None:
                        try:
                            values.append(float(value))
                        except (TypeError, ValueError):
                            pass
        manual_review_count += int(bool(event.get("manual_override")))
        for region in part_quality:
            result = part_results.get(region) if isinstance(part_results, dict) else None
            confidence = result.get("grade_confidence") if isinstance(result, dict) else None
            if confidence is not None:
                part_quality[region].append(float(confidence) * 100)
        whole = colors.get("Whole Fish") if isinstance(colors, dict) else None
        if isinstance(whole, dict) and whole.get("mean_hue_deg") is not None:
            hue_values.append(round(float(whole["mean_hue_deg"]), 2))
            color_trend.append({
                "timestamp": event.get("timestamp"),
                "mean_hue_deg": round(float(whole["mean_hue_deg"]), 2),
                "yellow_ratio_proxy": round(float(whole.get("yellow_ratio_proxy") or 0) * 100, 2),
            })
    result = {
        "has_data": bool(event_count),
        "grade_distribution": {name: int(value) for name, value in quality_counters.items()},
        "grade_distribution_basis": "original_ai_verdict",
        "ungraded_reasons": ungraded_reasons,
        "accuracy_available": False,
        "manual_reviewed_basis": "operator_reviewed_outcomes",
        "feature_counts": feature_counts,
        "throughput": list(throughput),
        "confidence_over_time": list(confidence_over_time),
        "trend_points_limit": _ANALYTICS_TREND_LIMIT,
        "trend_events_total": event_count,
        "average_grade_confidence": round(sum(grade_confidences) / len(grade_confidences), 1) if grade_confidences else None,
        "average_detection_confidence": round(sum(detection_confidences) / len(detection_confidences), 1) if detection_confidences else None,
        "average_processing_time_ms": round(sum(processing_times) / len(processing_times), 1) if processing_times else None,
        "average_first_detection_to_decision_ms": round(sum(decision_latency_values) / len(decision_latency_values), 1) if decision_latency_values else None,
        "decision_deadline_status_counts": dict(deadline_status_counts),
        "decision_timing_scope": "Elapsed time from first persistent Model 1 detection to virtual count-line decision; not physical entry or actuator confirmation.",
        "average_part_quality_scores": {
            region: round(sum(values) / len(values), 1) if values else None
            for region, values in part_quality.items()
        },
        "color_trend": list(color_trend),
        "average_whole_fish_hue": round(sum(hue_values) / len(hue_values), 2) if hue_values else None,
        "automatically_graded": automatic_count,
        "needs_review": needs_review_count,
        "manual_reviewed": manual_review_count,
        "review_queue_count": review_queue_count,
        "body_only_count": body_only_count,
        "two_region_count": two_region_count,
        "complete_region_count": complete_region_count,
        "average_evidence_coverage": round(sum(coverage_values) / len(coverage_values), 1) if coverage_values else None,
        "average_observed_regions": round(sum(observed_region_counts) / len(observed_region_counts), 2) if observed_region_counts else None,
        "average_model2_observations": round(sum(model2_observation_counts) / len(model2_observation_counts), 2) if model2_observation_counts else None,
        "average_final_support": round(sum(final_supports) / len(final_supports), 1) if final_supports else None,
        "average_best_evidence_support": round(sum(best_supports) / len(best_supports), 1) if best_supports else None,
        "performance": {
            key: round(sum(values) / len(values), 2) if values else None
            for key, values in performance_values.items()
        },
    }
    if not return_state:
        return result
    saved = {name: value for name, value in locals().items() if name in {
        "quality_counters", "throughput", "confidence_over_time", "grade_confidences", "detection_confidences",
        "processing_times", "decision_latency_values", "deadline_status_counts", "part_quality", "color_trend", "hue_values", "coverage_values", "observed_region_counts",
        "model2_observation_counts", "feature_counts", "ungraded_reasons", "event_count", "automatic_count", "needs_review_count",
        "manual_review_count", "review_queue_count", "body_only_count", "two_region_count", "complete_region_count", "final_supports",
        "best_supports", "performance_values",
    }}
    return result, saved


def _durable_analytics(range_name: str, session_id: str | None, start_date: str | None,
                       end_date: str | None, snapshot: dict[str, object]) -> tuple[dict[str, object], int | None]:
    """Cache a current-session summary until its transactional revision changes."""
    if range_name == "current_session" and session_id is None:
        return _analytics(state.tracking.archive_history(), snapshot), None
    with _analytics_cache_lock:
        revision = inspection_database.event_revision(session_id) if range_name == "current_session" else None
        key = (inspection_database, session_id, revision)
        if range_name == "current_session" and _analytics_cache.get("key") == key:
            return deepcopy(_analytics_cache["value"]), revision
        previous = None
        events = None
        reviews = None
        old_key = _analytics_cache.get("key")
        if range_name == "current_session" and old_key and old_key[:2] == key[:2] and revision > old_key[2]:
            delta = inspection_database.analytics_insertions_since(session_id, _analytics_cache["marker"], _analytics_cache["last_key"])
            if delta is not None and len(delta) == revision - old_key[2]:
                events = delta
                previous = _analytics_cache["state"]
            else:
                changes = inspection_database.analytics_reviews_since(session_id, _analytics_cache["marker"])
                if changes is not None and len(changes) == revision - old_key[2]:
                    reviews = changes
        if reviews is not None:
            result = deepcopy(_analytics_cache["value"])
            summary_state = deepcopy(_analytics_cache["state"])
            summary_state["manual_review_count"] += sum(int(new) - int(old) for old, new, _ in reviews)
            summary_state["review_queue_count"] += sum(
                int(needs_review) * (int(old) - int(new)) for old, new, needs_review in reviews
            )
            result["manual_reviewed"] = summary_state["manual_review_count"]
            result["review_queue_count"] = summary_state["review_queue_count"]
        else:
            if events is None:
                events = inspection_database.iter_events_chronological(
                    session_id=session_id, range_name=range_name, start_date=start_date, end_date=end_date,
                )
            result, summary_state = _analytics(events, snapshot, chronological_input=True, previous=previous, return_state=True)
        if range_name == "current_session" and inspection_database.event_revision(session_id) == revision:
            marker, last_key = inspection_database.analytics_change_marker(session_id)
            if inspection_database.event_revision(session_id) != revision:
                return result, revision
            _analytics_cache.clear()
            _analytics_cache.update(key=key, value=deepcopy(result), state=summary_state, marker=marker, last_key=last_key)
        return result, revision


def _runtime_diagnostics_payload() -> dict[str, object]:
    """Combine camera metrics with bounded, non-sensitive queue health."""

    diagnostics = service.runtime_diagnostics()
    persistence_queue = _event_persistence_snapshot()
    diagnostics["event_persistence_queue"] = persistence_queue
    diagnostics["event_persistence_drained"] = not bool(
        persistence_queue.get("pending") or persistence_queue.get("in_flight") or persistence_queue.get("failed")
    )
    return diagnostics


def _status_payload(*, include_analytics: bool = True) -> dict[str, object]:
    snapshot = state.snapshot()
    snapshot["raw_preview_available"] = bool(getattr(getattr(service, "raw_preview", None), "enabled", False))
    snapshot["tracker_backend"] = getattr(model, "tracker_backend", None)
    snapshot["tracker_warning"] = getattr(model, "tracker_warning", None)
    detector_threshold = getattr(model, "confidence_threshold", getattr(model, "confidence", state.confidence_threshold))
    snapshot["detection_confidence_threshold"] = state.confidence_threshold
    snapshot["default_confidence_threshold"] = PART_CONFIDENCE if RUNTIME_MODE == PART_PREVIEW_MODE else FISH_DETECTION_CONFIDENCE
    snapshot["default_quality_confidence_threshold"] = FISH_QUALITY_CONFIDENCE
    if include_analytics:
        current_analytics, _ = _durable_analytics("current_session", inspection_sessions.session_id, None, None, snapshot)
        snapshot["feature_counters"] = current_analytics["feature_counts"]
    snapshot["upload_analysis_available"] = bool((image_analyzer is not None and model.model is not None) or (upload_test_model is not None and upload_test_model.model is not None))
    snapshot["upload_analysis_mode"] = "whole_fish" if image_analyzer is not None and model.model is not None else "part_preview"
    snapshot["upload_analysis_label"] = (
        "Whole-fish image analysis" if image_analyzer is not None and model.model is not None else "Raw part-segmentation test"
    )
    snapshot["model_info"] = {
        "detector": {
            "name": state.model_name or "Fish detector",
            "status": state.model_status,
            "checkpoint_resolved": bool(getattr(model, "weights_path", None)),
            "device": getattr(model, "device", "unresolved"),
            "image_size": getattr(model, "image_size", None),
            "confidence_threshold": detector_threshold,
        },
        "quality": {
            "name": state.segmenter_name or "Quality Model",
            "status": state.segmenter_status,
            "checkpoint_resolved": bool(getattr(quality_model, "weights_path", None)),
            "device": getattr(quality_model, "device", "unresolved"),
            "image_size": getattr(quality_model, "image_size", None),
            "confidence_threshold": getattr(quality_model, "confidence_threshold", None),
            "class_names": list(getattr(quality_model, "class_names", {}).values()),
            "supports_masks": bool(getattr(quality_model, "supports_masks", False)),
            "diagnostics": quality_model.diagnostics() if quality_model is not None else {},
        },
    }
    snapshot["model_info"]["detector"].update({
        "class_names": list(getattr(model, "class_names", ())),
        "supports_masks": bool(getattr(model, "supports_masks", False)),
        "diagnostics": model.diagnostics() if hasattr(model, "diagnostics") else {},
    })
    snapshot["model_info"]["quality"].update({
        "quality_interval": service.quality_interval,
        "roi_padding": service.quality_roi_padding,
        "quality_inference_mode": service.quality_inference_mode,
    })
    if include_analytics:
        snapshot["device_report"] = _device_report()
    if lan_security.diagnostics_allowed():
        snapshot["runtime_diagnostics"] = _runtime_diagnostics_payload()
    else:
        snapshot["runtime_diagnostics"] = {"enabled": False}
    # Retain the old response member for clients on a prior dashboard build.
    snapshot["model_info"]["segmenter"] = snapshot["model_info"]["quality"]
    quality_diagnostics = snapshot["model_info"]["quality"].get("diagnostics", {})
    snapshot["grading_rules"] = quality_diagnostics.get("grading_config", {}) if isinstance(quality_diagnostics, dict) else {}
    from src.inference.model_registry import get_model_registry
    registry = get_model_registry()
    active_m2_id = getattr(quality_model, "active_model_id", None) or registry.get_persisted_model2_id()
    active_m2_entry = registry.get_model(active_m2_id)
    snapshot["active_model2_id"] = active_m2_id
    snapshot["active_model2_name"] = getattr(quality_model, "active_model_name", None) or (active_m2_entry.display_name if active_m2_entry else None)
    if include_analytics:
        snapshot["available_models"] = [m.to_dict() for m in registry.list_model2_candidates()]
    snapshot["model_info"]["quality"]["model_id"] = active_m2_id
    snapshot["model_info"]["quality"]["model_name"] = snapshot["active_model2_name"]
    snapshot["model_info"]["quality"]["is_loaded"] = bool(
        (getattr(quality_model, "adapter", None) and quality_model.adapter.is_loaded)
        or getattr(quality_model, "model", None) is not None
    )
    snapshot["model_info"]["quality"]["model_error"] = getattr(quality_model, "error", None)
    if include_analytics:
        snapshot["analytics"] = current_analytics
    persistence_queue = _event_persistence_snapshot()
    snapshot["durable_session"] = {
        "session_id": inspection_sessions.session_id,
        "active": inspection_sessions.active,
        "database_ready": True,
        "event_persistence_drained": not bool(
            persistence_queue.get("pending") or persistence_queue.get("in_flight") or persistence_queue.get("failed")
        ),
        "event_persistence_failed": bool(persistence_queue.get("failed")),
    }
    if not include_analytics:
        snapshot["event_revision"] = inspection_database.event_revision(snapshot["durable_session"]["session_id"])
    return snapshot


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/status")
def get_status() -> dict[str, object]:
    return _status_payload()


@app.get("/api/status/live")
def get_live_status() -> dict[str, object]:
    """Small polling response; durable analytics is fetched separately."""
    return _status_payload(include_analytics=False)


@app.get("/api/models")
def list_available_models() -> dict[str, object]:
    """Return all models in the central registry with their verified tasks and availability."""
    from src.inference.model_registry import get_model_registry

    registry = get_model_registry()
    active_m2_id = getattr(quality_model, "active_model_id", None) or registry.get_persisted_model2_id()
    models_list = []
    allowed_model2_ids = {entry.id for entry in registry.list_model2_candidates()}
    for entry in registry.list_models():
        if entry.role == "model2_part_quality" and entry.id not in allowed_model2_ids:
            continue
        if entry.role == "part_preview":
            continue
        item = entry.to_dict()
        item["is_active"] = bool(
            (entry.role == "model1_fish_detector" and entry.id == registry.get_default_model1_id())
            or (entry.role in {"model2_part_quality", "part_preview"} and entry.id == active_m2_id)
        )
        item["is_loaded"] = bool(
            item["is_active"]
            and (
                (entry.role == "model1_fish_detector" and getattr(model, "model", None) is not None)
                or (
                    entry.role in {"model2_part_quality", "part_preview"}
                    and quality_model is not None
                    and (
                        (getattr(quality_model, "adapter", None) and quality_model.adapter.is_loaded)
                        or getattr(quality_model, "model", None) is not None
                    )
                )
            )
        )
        models_list.append(item)
    return {
        "models": models_list,
        "active_model1_id": registry.get_default_model1_id(),
        "active_model2_id": active_m2_id,
        "default_model2_id": registry.get_default_model2_id(),
    }


@app.post("/api/models/select")
async def select_model(request: Request) -> dict[str, object]:
    """Switch the active Model 2 to another validated compatible model checkpoint."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    model_id = body.get("model_id")
    if not model_id or not isinstance(model_id, str):
        raise HTTPException(status_code=400, detail="'model_id' string is required.")

    from src.inference.model_registry import get_model_registry

    registry = get_model_registry()
    entry = registry.get_model(model_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Model ID '{model_id}' was not found in the registry.")
    if not registry.is_allowed_model2(model_id):
        raise HTTPException(status_code=403, detail="Only the approved Model 2 checkpoints may be selected.")

    compatible, reason = registry.validate_compatibility(model_id, "model2_grading")
    if not compatible:
        raise HTTPException(
            status_code=400,
            detail=reason or f"Model '{model_id}' cannot be used for Model 2 quality inspection.",
        )

    if quality_model is None:
        raise HTTPException(status_code=500, detail="Model 2 quality model service is not initialized.")

    with _model_change_lock:
        _require_inspection_stopped_for_model_change()
        return _select_model_locked(model_id)


def _select_model_locked(model_id: str) -> dict[str, object]:
    if quality_model.active_model_id == model_id and quality_model.model is not None:
        return {
            "success": True,
            "active_model2_id": quality_model.active_model_id,
            "active_model2_name": quality_model.name,
            "checkpoint": str(quality_model.weights_path),
            **_status_payload(),
        }
    if inspection_sessions.active:
        raise HTTPException(status_code=409, detail="Stop and close the current session before changing the model.")
    try:
        quality_model.switch_model(model_id)
        state.set_segmenter(
            "ready",
            quality_model.name,
            str(quality_model.weights_path),
            f"Quality Model '{quality_model.name}' ready on {quality_model.device}.",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Model switch failed: {exc}") from exc

    return {
        "success": True,
        "active_model2_id": quality_model.active_model_id,
        "active_model2_name": quality_model.name,
        "checkpoint": str(quality_model.weights_path),
        **_status_payload(),
    }


def _require_inspection_stopped_for_model_change() -> None:
    if state.snapshot()["inspection_status"] in {"starting", "running", "stopping"} or service.has_live_worker():
        raise HTTPException(
            status_code=409,
            detail="Stop inspection before switching the active model; active fish must not mix models.",
        )


@app.post("/api/inspection/start")
def start_inspection() -> dict[str, object]:
    with _model_change_lock:
        if service.has_live_worker():
            return {"started": False, **_status_payload()}
        persistence = _event_persistence_dispatcher_for_submit().snapshot()
        if persistence["failed"]:
            raise HTTPException(status_code=503, detail=_event_persistence_problem("inspection start", dict(persistence)))
        if not persistence["accepting"] or not persistence["worker_alive"]:
            raise HTTPException(status_code=409, detail=_event_persistence_problem("inspection start", dict(persistence)))
        # A worker that exited unexpectedly can leave its session open.
        if inspection_sessions.active:
            if not _close_durable_session("inspection restart", timeout=EVENT_PERSISTENCE_DRAIN_TIMEOUT_SECONDS):
                raise HTTPException(
                    status_code=503,
                    detail=_event_persistence_problem("inspection restart", _event_persistence_snapshot()),
                )
        if not service.prepare_models():
            return {"started": False, **_status_payload()}
        inspection_sessions.start(_session_metadata())
        try:
            started = service.start()
        except Exception:
            if service.has_live_worker():
                try:
                    service.stop()
                except Exception:
                    LOGGER.exception("Could not stop worker after inspection startup failed")
            if not service.has_live_worker():
                _close_durable_session("failed inspection startup", timeout=EVENT_PERSISTENCE_DRAIN_TIMEOUT_SECONDS)
            raise
        if not started and not service.has_live_worker():
            _close_durable_session("cancelled inspection startup", timeout=EVENT_PERSISTENCE_DRAIN_TIMEOUT_SECONDS)
        return {"started": started, **_status_payload()}


@app.post("/api/inspection/stop")
def stop_inspection() -> dict[str, object]:
    with _model_change_lock:
        service.stop()
        if inspection_sessions.active and not service.has_live_worker():
            _close_durable_session("inspection stop", timeout=EVENT_PERSISTENCE_DRAIN_TIMEOUT_SECONDS)
        persistence = _event_persistence_snapshot()
        stopped = not service.has_live_worker() and not inspection_sessions.active and not bool(
            persistence.get("pending") or persistence.get("in_flight") or persistence.get("failed")
        )
        return {"stopped": stopped, **_status_payload()}


@app.get("/api/camera/settings")
def get_camera_settings() -> dict[str, object]:
    """Return physical-camera readbacks from the shared capture owner."""

    return service.camera_status()


@app.get("/api/camera/capabilities")
def get_camera_capabilities() -> dict[str, object]:
    status = service.camera_status()
    capabilities = status.get("capabilities")
    return capabilities if isinstance(capabilities, dict) else {"available": False, "reason": "Camera capabilities are unavailable.", "properties": {}}


async def _camera_payload(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Camera settings must be valid JSON.") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Camera settings must be a JSON object.")
    return payload


def _record_camera_policy_change(result: dict[str, object]) -> str | None:
    """Prevent one fish from spanning physical-camera acquisition settings."""

    entries = result.get("results")
    changed = bool(result["changed"]) if "changed" in result else bool(result.get("success")) or (
        isinstance(entries, dict)
        and any(isinstance(value, dict) and value.get("success") is True for value in entries.values())
    )
    if not changed:
        return None
    # One lock boundary prevents a just-finished frame from enqueueing an old
    # policy record between clearing transient evidence and rotating sessions.
    with _model_change_lock, _processing_guard():
        try:
            service.reset_active_policy_evidence()
            if not inspection_sessions.active:
                return None
            return _rotate_durable_session_locked()
        except Exception as exc:
            # The physical setting has already changed. Continuing to process
            # with the old session metadata would mix acquisition policies, so
            # stop safely and leave the durable session open for recovery.
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            message = f"Camera policy changed but durable session rotation did not complete: {detail}"
            LOGGER.error(message)
            request_stop = getattr(service, "request_stop_after_current_frame", None)
            if callable(request_stop):
                request_stop(message)
            else:
                state.mark_error(message)
            raise


@app.post("/api/camera/settings")
async def update_camera_settings(request: Request) -> dict[str, object]:
    """Apply only supported hardware settings and return their actual readback."""

    payload = await _camera_payload(request)
    try:
        allowed_keys = {item.key for item in CAMERA_PROPERTIES} | {"calibration_mode"}
        unknown_keys = sorted(str(key) for key in set(payload) - allowed_keys)
        if unknown_keys:
            raise HTTPException(status_code=422, detail=f"Unsupported camera setting(s): {', '.join(unknown_keys)}.")
        calibration_supplied = "calibration_mode" in payload
        calibration = payload.pop("calibration_mode", None)
        values = {item.key: payload[item.key] for item in CAMERA_PROPERTIES if item.key in payload}
        if calibration_supplied and not isinstance(calibration, bool):
            raise HTTPException(status_code=422, detail="calibration_mode must be true or false.")
        if calibration_supplied and values:
            raise HTTPException(status_code=422, detail="Change calibration mode separately from physical camera controls.")
        if calibration is not None:
            service.set_calibration_mode(calibration)
        if not values:
            status = service.camera_status()
            return {"success": True, "requested": {}, "actual": status.get("actual", {}), "camera": status}
        # Freeze frame callbacks across both the physical adjustment and its
        # durable policy boundary; no fish can straddle the two configurations.
        with _model_change_lock, _processing_guard():
            result = service.update_camera_settings(values)
            session_id = _record_camera_policy_change(result)
        return {**result, "policy_session_id": session_id, "camera": service.camera_status()}
    except CameraControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/api/camera/reset")
def reset_camera_settings() -> dict[str, object]:
    try:
        with _model_change_lock, _processing_guard():
            result = service.reset_camera_settings()
            session_id = _record_camera_policy_change(result)
        return {**result, "policy_session_id": session_id, "camera": service.camera_status()}
    except CameraControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/api/camera/profile/save")
def save_camera_profile() -> dict[str, object]:
    try:
        result = service.save_camera_profile()
        return {**result, "camera": service.camera_status()}
    except CameraControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/api/camera/reference")
async def record_camera_reference(request: Request) -> dict[str, object]:
    """Record calibration-only reference-scene statistics for a future study."""

    payload = await _camera_payload(request)
    unknown_keys = sorted(str(key) for key in set(payload) - {"scene_type", "note"})
    if unknown_keys:
        raise HTTPException(status_code=422, detail=f"Unsupported reference field(s): {', '.join(unknown_keys)}.")
    try:
        result = service.record_camera_reference(payload.get("scene_type"), payload.get("note"))
        return {**result, "camera": service.camera_status()}
    except CameraControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/api/camera/profile/confirm")
async def confirm_camera_profile(request: Request) -> dict[str, object]:
    """Persist operator confirmation and physical setup metadata explicitly."""

    payload = await _camera_payload(request)
    allowed = {"operator_confirmed", "operator_name", "installation"}
    unknown_keys = sorted(str(key) for key in set(payload) - allowed)
    if unknown_keys:
        raise HTTPException(status_code=422, detail=f"Unsupported profile-confirmation field(s): {', '.join(unknown_keys)}.")
    installation = payload.get("installation")
    if installation is not None and not isinstance(installation, dict):
        raise HTTPException(status_code=422, detail="installation must be a JSON object.")
    try:
        result = service.confirm_camera_profile(
            operator_confirmed=payload.get("operator_confirmed"),
            operator_name=payload.get("operator_name"),
            installation=installation,
        )
        return {**result, "camera": service.camera_status()}
    except CameraControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/api/camera/profile/load")
def load_camera_profile() -> dict[str, object]:
    try:
        with _model_change_lock, _processing_guard():
            result = service.load_camera_profile()
            session_id = _record_camera_policy_change(result)
        return {**result, "policy_session_id": session_id, "camera": service.camera_status()}
    except CameraControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/api/camera/lock")
async def lock_camera_settings(request: Request) -> dict[str, object]:
    payload = await _camera_payload(request)
    try:
        status = service.lock_camera_settings(payload.get("locked"))
        return {"success": True, "locked": status.get("locked"), "camera": status}
    except CameraControlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/api/session/reset")
def reset_session() -> dict[str, object]:
    # Block frame callbacks until both the durable identity and trackers change.
    with _model_change_lock, service._processing_lock:
        _rotate_durable_session_locked()
        service.reset_session()
    return {"reset": True, **_status_payload()}


@app.get("/api/history")
def get_history(
    page: int = 1,
    page_size: int = 25,
    range_name: str = "current_session",
    session_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    search: str | None = None,
    grade: str | None = None,
    feature: str | None = None,
    min_confidence: float | None = None,
) -> dict[str, object]:
    """Paginate durable inspection records, optionally scoped to one session."""

    if page < 1 or not 1 <= page_size <= 100:
        raise HTTPException(status_code=422, detail="page must be positive and page_size must be between 1 and 100.")
    if min_confidence is not None and not 0 <= min_confidence <= 100:
        raise HTTPException(status_code=422, detail="min_confidence must be between 0 and 100.")
    requested_session = session_id or (inspection_sessions.session_id if range_name == "current_session" else None)
    if range_name != "current_session" or requested_session is not None:
        try:
            items, total = inspection_database.events_page(
                session_id=requested_session, range_name=range_name, start_date=start_date, end_date=end_date,
                page=page, page_size=page_size, search=search, grade=grade, feature=feature,
                min_confidence=min_confidence,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        snapshot = state.snapshot()
        return {
            "items": items, "total": total, "page": page, "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "latest_event": snapshot["latest_event"], "recent_history": snapshot["recent_history"],
            "range": range_name, "session_id": requested_session, "sessions": inspection_database.sessions(),
        }
    try:
        events = _durable_events(
            range_name=range_name,
            session_id=session_id,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if search:
        needle = search.casefold().replace("fish", "").replace("#", "").strip()
        events = [event for event in events if needle in str(event.get("track_id", "")).casefold()]
    if grade and grade.casefold() not in {"all", ""}:
        events = [event for event in events if (event.get("quality") or "Ungraded").casefold() == grade.casefold()]
    if feature and feature.casefold() not in {"all", ""}:
        events = [
            event for event in events
            if any(isinstance(part, dict) and str(part.get("region", "")).casefold() == feature.casefold() for part in (event.get("parts") or []))
        ]
    if min_confidence is not None:
        if not 0 <= min_confidence <= 100:
            raise HTTPException(status_code=422, detail="min_confidence must be between 0 and 100.")
        def weighted_support(event: dict[str, object]) -> float:
            analysis = event.get("analysis")
            if isinstance(analysis, dict):
                for key in ("final_score", "provisional_score", "best_evidence_score"):
                    try:
                        value = analysis.get(key)
                        if value is not None:
                            return float(value)
                    except (TypeError, ValueError):
                        continue
            try:
                return float(event.get("quality_confidence") or 0)
            except (TypeError, ValueError):
                return 0.0
        events = [
            event
            for event in events
            if weighted_support(event) * 100 >= min_confidence
        ]
    total = len(events)
    start = (page - 1) * page_size
    snapshot = state.snapshot()
    return {
        "items": events[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "latest_event": snapshot["latest_event"],
        "recent_history": snapshot["recent_history"],
        "range": range_name,
        "session_id": session_id or (inspection_sessions.session_id if range_name == "current_session" else None),
        "sessions": inspection_database.sessions(),
    }


@app.get("/api/sessions")
def get_sessions(limit: int = 100) -> dict[str, object]:
    """Expose durable session snapshots for history and export selectors."""

    if not 1 <= limit <= 1000:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 1000.")
    return {
        "items": inspection_database.sessions(limit=limit),
        "current_session_id": inspection_sessions.session_id,
        "active": inspection_sessions.active,
    }


def _canonical_manual_grade(value: object) -> str | None:
    """Accept compact operator choices while persisting the canonical labels."""

    if value is None:
        return None
    text = str(value).strip()
    aliases = {
        "a": "Class A", "class a": "Class A",
        "b": "Class B", "class b": "Class B",
        "c": "Class C", "class c": "Class C",
        "rejected": "Rejected",
    }
    if text.casefold() not in aliases:
        raise ValueError("manual_grade must be A, B, C, Rejected, or null to clear the review.")
    return aliases[text.casefold()]


@app.get("/api/reviews")
def get_review_queue(include_reviewed: bool = False, session_id: str | None = None) -> dict[str, object]:
    """List durable AI results that remain Ungraded / Needs Review."""

    if session_id is not None and (not session_id.strip() or inspection_database.session(session_id) is None):
        raise HTTPException(status_code=404, detail="Inspection session not found.")
    items = []
    for event in _durable_events(session_id=session_id):
        analysis = event.get("analysis")
        needs_review = isinstance(analysis, dict) and analysis.get("verdict_status") == "NEEDS_REVIEW"
        if needs_review and (include_reviewed or not event.get("manual_override")):
            items.append(event)
    return {"items": items, "total": len(items), "include_reviewed": include_reviewed,
            "session_id": session_id or inspection_sessions.session_id}


@app.post("/api/reviews/{track_id}")
async def review_fish(track_id: int, request: Request) -> dict[str, object]:
    """Record a manual final grade while retaining the original AI evidence."""

    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Review settings must be valid JSON.") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Review settings must be a JSON object.")
    if "manual_grade" not in payload:
        raise HTTPException(status_code=422, detail="manual_grade is required; use null to clear a review.")
    requested_session = payload.get("session_id")
    if "session_id" in payload and (not isinstance(requested_session, str) or not requested_session.strip()):
        raise HTTPException(status_code=422, detail="session_id must be a non-empty string when supplied.")
    reviewer = payload.get("reviewer")
    if reviewer is not None and (not isinstance(reviewer, str) or len(reviewer.strip()) > 120):
        raise HTTPException(status_code=422, detail="reviewer must be a string of at most 120 characters.")
    reviewer = reviewer.strip() or None if isinstance(reviewer, str) else None
    try:
        manual_grade = _canonical_manual_grade(payload.get("manual_grade"))
        with _model_change_lock, service._processing_lock:
            _require_drained_event_persistence("manual review")
            current_session = inspection_sessions.session_id
            session_id = requested_session or current_session
            if session_id is not None:
                if inspection_database.session(session_id) is None:
                    raise HTTPException(status_code=404, detail="Inspection session not found.")
                item = inspection_database.apply_manual_review(session_id, track_id, manual_grade, reviewer=reviewer)
                if item is None:
                    raise KeyError(track_id)
                if session_id == current_session:
                    try:
                        state.tracking.apply_manual_review(track_id, manual_grade, reviewer=reviewer,
                                                           review_timestamp=item.get("review_timestamp"), notify=False)
                    except KeyError:
                        pass
            else:
                item = state.tracking.apply_manual_review(track_id, manual_grade, reviewer=reviewer)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Fish #{track_id} is not in the selected session.") from None
    review_queue_count = len(get_review_queue(session_id=session_id).get("items", []))
    return {"updated": True, "item": item, "review_queue_count": review_queue_count}


@app.get("/api/sessions/{session_id}/reviews/{track_id}/audit")
def get_review_audit(session_id: str, track_id: int) -> dict[str, object]:
    if inspection_database.session(session_id) is None or not inspection_database.event_exists(session_id, track_id):
        raise HTTPException(status_code=404, detail="Inspection session or fish not found.")
    items = inspection_database.review_audit(session_id, track_id)
    return {"session_id": session_id, "track_id": track_id, "items": items}


def _structural_review_event(track_id: int) -> dict[str, object]:
    for event in _durable_events():
        if event.get("track_id") == track_id:
            return event
    raise HTTPException(status_code=404, detail=f"Fish #{track_id} is not in the current durable session.")


@app.get("/api/reviews/{track_id}/structure")
def get_structural_review(track_id: int) -> dict[str, object]:
    event = _structural_review_event(track_id)
    analysis = event.get("analysis") if isinstance(event.get("analysis"), dict) else {}
    return {"track_id": track_id, "structural_evidence": analysis.get("structural_evidence", summarize_structural_evidence([]))}


@app.post("/api/reviews/{track_id}/structure")
async def add_structural_review(track_id: int, request: Request) -> dict[str, object]:
    """Append a reported observation without changing the AI or manual grade."""
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Structural review must be valid JSON.") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Structural review must be a JSON object.")
    try:
        source = payload.get("source", "unverified")
        if not isinstance(source, str) or source not in {"expert_review", "unverified"}:
            raise ValueError("Manual review cannot certify a verified-detector source.")
        value = dict(payload)
        if value.get("observed_at") is None:
            value["observed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        observation = StructuralEvidence.from_mapping(value)
        # Serialize the read-modify-write with live event persistence, manual
        # review and session rotation. Otherwise an old event snapshot can
        # overwrite a newer verdict or the structural record can disappear.
        with _model_change_lock, service._processing_lock:
            _require_drained_event_persistence("structural review")
            event = _structural_review_event(track_id)
            analysis = dict(event.get("analysis")) if isinstance(event.get("analysis"), dict) else {}
            existing = analysis.get("structural_evidence")
            old_records = existing.get("records", []) if isinstance(existing, dict) else []
            if not isinstance(old_records, list) or not all(isinstance(item, dict) for item in old_records):
                raise ValueError("Stored structural evidence is invalid; manual review is required.")
            records = [StructuralEvidence.from_mapping(item) for item in old_records]
            summary = summarize_structural_evidence([*records, observation])
            analysis["structural_evidence"] = summary
            updated = {**event, "analysis": analysis}
            session_id = inspection_sessions.session_id
            if session_id:
                inspection_database.upsert_event(session_id, updated)
            state.tracking.update_event_analysis(track_id, {"structural_evidence": summary})
        return {"updated": True, "track_id": track_id, "structural_evidence": summary}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/analytics")
def get_analytics(
    range_name: str = "current_session",
    session_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, object]:
    snapshot = state.snapshot()
    requested_session = session_id or (inspection_sessions.session_id if range_name == "current_session" else None)
    try:
        analytics, revision = _durable_analytics(range_name, requested_session, start_date, end_date, snapshot)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if range_name == "current_session" and session_id is None and inspection_sessions.session_id != requested_session:
        raise HTTPException(status_code=409, detail="Session changed while analytics was being collected; retry.")
    return {
        **analytics,
        "range": range_name,
        "session_id": requested_session,
        "event_revision": revision,
    }


@app.get("/api/settings")
def get_settings() -> dict[str, object]:
    return {
        "detection_confidence_threshold": state.confidence_threshold,
        "quality_confidence_threshold": state.quality_confidence_threshold,
        "display_settings": state.current_display_settings(),
        "policy_settings_locked": state.snapshot()["inspection_status"] in {"starting", "running", "stopping"},
        "policy_settings_lock_reason": "Stop inspection before changing a detector or grading policy setting.",
        "advanced_thresholds_supported": True,
    }


@app.get("/api/debug/runtime")
def get_runtime_diagnostics() -> dict[str, object]:
    """Developer-only bounded runtime telemetry and artifact locations."""

    return _runtime_diagnostics_payload()


@app.post("/api/debug/runtime")
async def update_runtime_diagnostics(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Runtime diagnostics must be valid JSON.") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Runtime diagnostics must be a JSON object.")
    try:
        service.set_runtime_diagnostics(payload)
    except CameraControlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"updated": True, **_status_payload()}


@app.post("/api/debug/frontend-metrics")
async def record_frontend_metrics(request: Request) -> dict[str, object]:
    """Receive a browser render duration; unavailable clients simply omit it."""

    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Frontend metrics must be valid JSON.") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Frontend metrics must be a JSON object.")
    try:
        milliseconds = float(payload.get("render_ms"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="render_ms must be a number.") from None
    service.record_frontend_render(milliseconds)
    return {"recorded": True}


@app.post("/api/debug/hard-negatives/{capture_id}/not-fish")
def mark_hard_negative_not_fish(capture_id: str) -> dict[str, object]:
    """Apply an operator research label; never feed it into live inference."""

    try:
        record = service.mark_hard_negative(capture_id)
    except CameraControlError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"updated": True, "record": record, "runtime_diagnostics": _runtime_diagnostics_payload()}


@app.post("/api/settings")
async def update_settings(request: Request) -> dict[str, object]:
    """Apply independent Model 1/Model 2 thresholds and live overlays."""

    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Settings must be valid JSON.") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Settings must be a JSON object.")
    with _model_change_lock:
        return _update_settings_locked(payload)


def _update_settings_locked(payload: dict) -> dict[str, object]:
    allowed = {"confidence_threshold", "detection_confidence_threshold", "quality_confidence_threshold", "display_settings", "model2_id", "selected_model2"}
    unknown = set(payload) - allowed
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unsupported setting(s): {', '.join(sorted(unknown))}.")
    if {"confidence_threshold", "detection_confidence_threshold"} <= payload.keys() or {"model2_id", "selected_model2"} <= payload.keys():
        raise HTTPException(status_code=422, detail="Use only one name for each setting.")

    detector_key = "detection_confidence_threshold" if "detection_confidence_threshold" in payload else "confidence_threshold"
    model_key = "model2_id" if "model2_id" in payload else "selected_model2"
    policy_requested = detector_key in payload or "quality_confidence_threshold" in payload
    model_requested = model_key in payload
    if model_requested:
        _require_inspection_stopped_for_model_change()
    if policy_requested and (state.snapshot()["inspection_status"] in {"starting", "running", "stopping"} or service.has_live_worker()):
        raise HTTPException(status_code=409, detail="Stop inspection before changing detector or grading-policy settings; active fish must not mix policies.")

    def threshold_for(key: str) -> float | None:
        if key not in payload:
            return None
        value = payload[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise HTTPException(status_code=422, detail=f"{key} must be a number between 0 and 1.")
        return float(value)

    detector_threshold = threshold_for(detector_key)
    quality_threshold = threshold_for("quality_confidence_threshold")
    display = None
    if "display_settings" in payload:
        if not isinstance(payload["display_settings"], dict):
            raise HTTPException(status_code=422, detail="display_settings must be an object.")
        try:
            display = state.validate_display_settings(payload["display_settings"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    model2_request = payload.get(model_key) if model_requested else None
    switching = False
    if model_requested:
        if not isinstance(model2_request, str) or not model2_request:
            raise HTTPException(status_code=422, detail="model2_id must be a non-empty string.")
        from src.inference.model_registry import get_model_registry
        registry = get_model_registry()
        entry = registry.get_model(model2_request)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Model ID '{model2_request}' was not found in the registry.")
        compatible, reason = registry.validate_compatibility(model2_request, "model2_grading")
        if not compatible:
            raise HTTPException(status_code=400, detail=reason or f"Model '{model2_request}' cannot be used for Model 2 quality inspection.")
        if quality_model is None:
            raise HTTPException(status_code=500, detail="Model 2 quality model service is not initialized.")
        switching = quality_model.active_model_id != model2_request or quality_model.model is None
        if switching:
            if inspection_sessions.active:
                raise HTTPException(status_code=409, detail="Stop and close the current session before changing the model.")
            checkpoint = registry.resolve_checkpoint_path(entry)
            if not checkpoint.is_file():
                raise HTTPException(status_code=422, detail=f"Model checkpoint not found: {checkpoint}")

    detector_attr = "confidence_threshold" if hasattr(model, "confidence_threshold") else "confidence" if hasattr(model, "confidence") else None
    previous_detector = getattr(model, detector_attr) if detector_attr else None
    previous_quality = getattr(quality_model, "confidence_threshold", None) if quality_model is not None else None
    previous_state = (state.confidence_threshold, state.quality_confidence_threshold, state.current_display_settings(),
                      state.segmenter_status, state.segmenter_name, state.segmenter_weights_path, state.segmenter_message)
    try:
        if detector_threshold is not None:
            state.set_confidence_threshold(detector_threshold)
            if detector_attr:
                setattr(model, detector_attr, detector_threshold)
        if quality_threshold is not None:
            state.set_quality_confidence_threshold(quality_threshold)
            if quality_model is not None:
                quality_model.confidence_threshold = quality_threshold
        if display is not None:
            state.set_display_settings(display)
        if switching:
            state.set_segmenter("ready", entry.display_name, str(checkpoint), f"Quality Model '{entry.display_name}' ready on {quality_model.device}.")
            # switch_model preserves the old loaded model and persisted selection on load/write failures.
            quality_model.switch_model(model2_request)
        elif policy_requested and inspection_sessions.active:
            rotate_durable_session()
    except HTTPException:
        with state._lock:
            (state.confidence_threshold, state.quality_confidence_threshold, state.display_settings,
             state.segmenter_status, state.segmenter_name, state.segmenter_weights_path, state.segmenter_message) = previous_state
        if detector_attr:
            setattr(model, detector_attr, previous_detector)
        if quality_model is not None:
            quality_model.confidence_threshold = previous_quality
        raise
    except Exception as exc:
        with state._lock:
            (state.confidence_threshold, state.quality_confidence_threshold, state.display_settings,
             state.segmenter_status, state.segmenter_name, state.segmenter_weights_path, state.segmenter_message) = previous_state
        if detector_attr:
            setattr(model, detector_attr, previous_detector)
        if quality_model is not None:
            quality_model.confidence_threshold = previous_quality
        raise HTTPException(status_code=500, detail=f"Settings could not be applied: {exc}") from exc
    try:
        status = _status_payload()
    except Exception:
        # The settings have committed. Do not report a failed update solely
        # because unrelated optional status details could not be assembled.
        LOGGER.exception("Settings applied, but full status could not be assembled")
        status = {
            "detection_confidence_threshold": state.confidence_threshold,
            "quality_confidence_threshold": state.quality_confidence_threshold,
            "display_settings": state.current_display_settings(),
            "active_model2_id": getattr(quality_model, "active_model_id", None),
            "status_detail": "Full status is temporarily unavailable.",
        }
    return {"updated": True, **status}


@app.post("/api/export")
async def export_history(request: Request) -> Response:
    """Generate a current-session CSV or XLSX file without a fake export flow."""

    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Export settings must be valid JSON.") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Export settings must be a JSON object.")
    export_format = str(payload.get("format", "csv")).lower()
    if export_format not in {"csv", "xlsx"}:
        raise HTTPException(status_code=422, detail="format must be csv or xlsx.")
    full_evidence = payload.get("complete_analysis", False)
    if not isinstance(full_evidence, bool):
        raise HTTPException(status_code=422, detail="complete_analysis must be true or false.")
    selected_fields = payload.get("fields", [])
    if not isinstance(selected_fields, list) or not all(isinstance(field, str) for field in selected_fields):
        raise HTTPException(status_code=422, detail="fields must be a list of field names.")
    if full_evidence:
        fields = DEFAULT_EXPORT_FIELDS
    else:
        if not selected_fields:
            raise HTTPException(status_code=422, detail="Choose at least one export field.")
        fields = tuple(selected_fields)
        if len(set(fields)) != len(fields):
            raise HTTPException(status_code=422, detail="Export fields must not contain duplicates.")
    if any(field not in EXPORT_FIELDS for field in fields):
        raise HTTPException(status_code=422, detail="One or more export fields are unsupported.")
    range_name = str(payload.get("range", "current_session"))
    requested_session = payload.get("session_id")
    if requested_session is not None and (not isinstance(requested_session, str) or not requested_session):
        raise HTTPException(status_code=422, detail="session_id must be a non-empty string when supplied.")
    try:
        # An export is a durable snapshot, unlike live polling. Freeze new
        # frame callbacks while accepted FIFO writes drain and rows are read.
        with _model_change_lock, _processing_guard():
            _require_drained_event_persistence("export")
            requested_metadata = inspection_database.session(requested_session) if requested_session is not None else None
            if requested_session is not None and requested_metadata is None:
                raise HTTPException(status_code=404, detail="Inspection session not found.")
            events = _durable_events(
                range_name=range_name,
                session_id=requested_session,
                start_date=payload.get("start_date"),
                end_date=payload.get("end_date"),
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session_ids = list(dict.fromkeys(event.get("session_id") for event in events))
    multiple_sessions = len(session_ids) > 1
    if export_format == "csv" and multiple_sessions:
        raise HTTPException(status_code=422, detail="Use Excel for a multi-session export so each session's grading rules can be included.")
    snapshot = state.snapshot()
    analytics = _analytics(events, snapshot)
    quality = analytics["grade_distribution"]
    assert isinstance(quality, dict)
    decision_deadline_counts = analytics["decision_deadline_status_counts"]
    assert isinstance(decision_deadline_counts, dict)
    summary = {
        "Total Fish": len(events),
        "Average Final Support": f"{analytics['average_grade_confidence']:.1f}%" if analytics["average_grade_confidence"] is not None else "",
        "Average Detection Confidence": f"{analytics['average_detection_confidence']:.1f}%" if analytics["average_detection_confidence"] is not None else "",
        "Automatically Graded": analytics["automatically_graded"],
        "Needs Review": analytics["needs_review"],
        "Manual Reviewed": analytics["manual_reviewed"],
        "Average Evidence Coverage": f"{analytics['average_evidence_coverage']:.1f}%" if analytics["average_evidence_coverage"] is not None else "",
        "Average Observed Regions": analytics["average_observed_regions"] if analytics["average_observed_regions"] is not None else "",
        "Average Model 2 Observations": analytics["average_model2_observations"] if analytics["average_model2_observations"] is not None else "",
        "Body-only Fish": analytics["body_only_count"],
        "Two-region Fish": analytics["two_region_count"],
        "Complete Three-region Fish": analytics["complete_region_count"],
        "Average Processing Time (ms)": analytics["average_processing_time_ms"] or "",
        "Average First Detection to Decision (ms)": (
            analytics["average_first_detection_to_decision_ms"]
            if analytics["average_first_detection_to_decision_ms"] is not None
            else ""
        ),
        "Decision Deadline Met": decision_deadline_counts.get("met", 0),
        "Decision Deadline Missed": decision_deadline_counts.get("missed", 0),
        "Decision Deadline Not Configured": decision_deadline_counts.get("not_configured", 0),
        "Decision Timing Scope": analytics["decision_timing_scope"],
        "Average Whole-Fish Hue (deg)": analytics["average_whole_fish_hue"] if analytics["average_whole_fish_hue"] is not None else "",
    }
    part_averages = analytics["average_part_quality_scores"]
    assert isinstance(part_averages, dict)
    summary.update({f"Average {region} Evidence": value if value is not None else "" for region, value in part_averages.items()})
    summary.update({f"AI {name} Count": value for name, value in quality.items()})
    summary.update({f"{name} Observed": detail["count"] for name, detail in _feature_counters(events).items()})
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if export_format == "csv":
        body = make_csv(events, fields)
        media_type, extension = "text/csv; charset=utf-8", "csv"
    else:
        try:
            session_metadata = requested_metadata
            if session_metadata is None and len(session_ids) == 1 and session_ids[0]:
                session_metadata = inspection_database.session(str(session_ids[0]))
            elif session_metadata is None and not session_ids and range_name == "current_session" and inspection_sessions.session_id:
                session_metadata = inspection_database.session(inspection_sessions.session_id)
            configurations = None
            if multiple_sessions:
                configurations = [
                    (inspection_database.session(str(identifier)) if identifier else None) or {"session_id": identifier}
                    for identifier in session_ids
                ]
                session_metadata = None
            rules = session_metadata.get("grading_config") if session_metadata is not None else None
            body = make_xlsx(
                events,
                fields,
                summary,
                rules if isinstance(rules, dict) else None,
                session_configuration=session_metadata,
                session_configurations=configurations,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        media_type, extension = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="sardinella_inspection_{timestamp}.{extension}"'},
    )


async def _read_bounded_upload(request: Request, max_bytes: int) -> bytes:
    """Stop consuming the ASGI stream as soon as the byte limit is exceeded."""
    body = bytearray()
    stream = request.stream()
    try:
        async for chunk in stream:
            if len(chunk) > max_bytes - len(body):
                raise HTTPException(status_code=413, detail=f"The uploaded image exceeds the {max_bytes} byte limit.")
            body.extend(chunk)
    finally:
        await stream.aclose()
    return bytes(body)


@app.post("/api/analyze-image")
async def analyze_image(request: Request) -> dict[str, object]:
    """Analyze one image using the active model without changing its selection."""

    filename = request.headers.get("x-filename", "")
    if not filename:
        raise HTTPException(status_code=400, detail="An uploaded image filename is required.")
    declared_length = request.headers.get("content-length")
    if declared_length and declared_length.isdigit() and int(declared_length) > FISH_UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"The uploaded image exceeds the {FISH_UPLOAD_MAX_BYTES} byte limit.")

    try:
        frame = decode_uploaded_image(
            await _read_bounded_upload(request, FISH_UPLOAD_MAX_BYTES),
            filename,
            max_bytes=FISH_UPLOAD_MAX_BYTES,
            max_dimension=FISH_UPLOAD_MAX_DIMENSION,
            max_pixels=FISH_UPLOAD_MAX_PIXELS,
        )
        model_override = request.headers.get("x-model-id") or request.query_params.get("model_id")
        with _model_change_lock:
            if model_override:
                if quality_model is None:
                    raise HTTPException(status_code=400, detail="A Model 2 override is unavailable in this analysis mode.")
                if getattr(quality_model, "active_model_id", None) != model_override:
                    from src.inference.model_registry import get_model_registry

                    registry = get_model_registry()
                    compatible, reason = registry.validate_compatibility(model_override, "model2_grading")
                    if not compatible:
                        raise HTTPException(status_code=400, detail=reason or f"Model '{model_override}' is not compatible for image analysis.")
                    raise HTTPException(status_code=409, detail="Upload analysis uses the active Model 2. Select another model explicitly before uploading.")

            # Do not interleave still-image inference with a live frame's
            # inference, grading, and per-frame diagnostic measurements.
            with service._processing_lock:
                strict_integrity = os.getenv("FISH_STRICT_MODEL_INTEGRITY", "0").strip().lower() in {"1", "true", "yes", "on"}
                if strict_integrity and image_analyzer is not None and (
                    getattr(model, "checkpoint_integrity", None) != "verified"
                    or getattr(quality_model, "checkpoint_integrity", None) != "verified"
                    or getattr(quality_model, "model", None) is None
                ):
                    raise HTTPException(status_code=503, detail="Strict model integrity requires both registered checkpoints to be verified before image analysis.")
                if image_analyzer is not None and model.model is not None:
                    return image_analyzer.analyze(frame)
                if upload_test_model is not None and upload_test_model.model is not None and upload_test_analyzer is not None:
                    return upload_test_analyzer.analyze(frame)
                detail = (upload_test_model.error if upload_test_model is not None else None) or model.error or "No local upload-analysis model is available."
                raise HTTPException(status_code=503, detail=detail)
    except ImageUploadError as exc:
        status = 413 if "byte limit" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def _mjpeg_frames(request: Request):
    last_version = -1
    while True:
        if not lan_security.stream_authorized(request):
            break
        frame, version = state.frame()
        if frame is not None and version != last_version:
            last_version = version
            dispatch_started = monotonic()
            yield b"--frame\r\nContent-Type: image/jpeg\r\nCache-Control: no-cache\r\n\r\n" + frame + b"\r\n"
            # This is stream-consumer pacing (the API uses MJPEG, not a
            # WebSocket), not a claim of end-to-end browser paint time.
            service.record_stream_dispatch(max(0.0, monotonic() - dispatch_started))
        # Waiting asynchronously lets a disconnected client or server shutdown
        # cancel the stream even when there are no new camera frames.
        await asyncio.sleep(0.025 if state.inspection_status == "running" else 0.2)


@app.get("/api/video-feed")
def video_feed(request: Request) -> StreamingResponse:
    return StreamingResponse(_mjpeg_frames(request), media_type="multipart/x-mixed-replace; boundary=frame")


async def _raw_mjpeg_frames(request: Request):
    preview = service.raw_preview
    preview.subscribe()
    try:
        last_version = -1
        while lan_security.stream_authorized(request):
            frame, version = preview.frame()
            if frame is not None and version != last_version:
                last_version = version
                yield b"--frame\r\nContent-Type: image/jpeg\r\nCache-Control: no-cache\r\n\r\n" + frame + b"\r\n"
            await asyncio.sleep(0.025 if state.inspection_status == "running" else 0.2)
    finally:
        preview.unsubscribe()


@app.get("/api/video-feed/raw")
def raw_video_feed(request: Request) -> StreamingResponse:
    if not service.raw_preview.enabled:
        raise HTTPException(status_code=404, detail="Raw preview is disabled.")
    return StreamingResponse(_raw_mjpeg_frames(request), media_type="multipart/x-mixed-replace; boundary=frame")
