"""One-click verified review and background learning over canonical revisions."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import math
import os
from pathlib import Path
from threading import Event, RLock, Thread
from urllib.parse import unquote

import cv2

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from src.annotation.store import AnnotationError, get_annotation_store
from src.api.annotation_store import AnnotationStore, annotation_view
from src.preprocessing.dataset_utils import project_root


LOGGER = logging.getLogger(__name__)
_services = {}
_lock = RLock()
_maintenance_stop = Event()
_maintenance_thread = None
_candidate_models = {}


def get_learning_service(canonical=None):
    canonical = canonical or get_annotation_store()
    key = str(canonical.root)
    with _lock:
        if key not in _services:
            from src.annotation_learning import LearningService
            checkpoint = Path(os.getenv("FISH_ANNOTATION_LEARNING_CHECKPOINT") or project_root() / "models" / "yolo_parts" / "yolo26n_seg_exp4" / "weights" / "exp-4.pt")
            _services[key] = LearningService(AnnotationStore(canonical), canonical.root / "learning",
                baseline_root=canonical.manual_source, base_checkpoint=checkpoint if checkpoint.is_file() else None)
        return _services[key]


def _classes(store):
    return {c["id"]: c for c in store.classes()["classes"]}


def review_item(store, document, *, include_learning=True):
    classes = _classes(store)
    service = get_learning_service(store) if include_learning else None
    row = service.store.get(document["id"]) if service else None
    automation = document.get("automation") or {}
    warnings = list(automation.get("errors") or []) + list(automation.get("learning_warnings") or [])
    for annotation in document["annotations"]:
        warnings.extend(str(f).replace("_", " ") for f in annotation.get("flags", []))
    if row and row["quarantined"]:
        warnings.append("Excluded from learning: " + row.get("quarantine_reason", "Needs review."))
    return {"image_id": document["id"], "filename": document["filename"], "width": document["width"], "height": document["height"],
        "status": document["status"], "revision": document["revision"], "source": "manual" if document.get("baseline") else "ai",
        "split": document.get("split"), "dataset_id": row.get("dataset_id") if row else None,
        "annotations": [annotation_view(a, classes, document["width"], document["height"]) for a in document["annotations"] if a.get("status") != "rejected"],
        "predictions": row.get("predictions", []) if row else [], "corrections": row.get("corrections") if row else None,
        "model_version": automation.get("learning_model_version", "existing-detectors"),
        "warnings": list(dict.fromkeys(warnings)), "references": automation.get("learning_references", [])}


def _pending(store):
    documents = [d for d in store.list()["images"] if d["status"] in {"unreviewed", "corrected"}]
    documents.sort(key=lambda d: (d.get("created_at", ""), d["id"]))
    return [{"image_id": d["id"], "filename": d["filename"], "status": d["status"], "width": d["width"], "height": d["height"], "annotation_count": d["annotation_count"]} for d in documents]


def verify_review(store, image_id, payload):
    """Save a complete decision and audit in one canonical SQLite transaction."""
    action = payload.get("action")
    if action not in {"approve", "edit", "decline"}:
        raise AnnotationError("Choose approve, edit, or decline.")
    reason = payload.get("reason")
    if reason is not None and (not isinstance(reason, str) or len(reason) > 500):
        raise AnnotationError("Decline reason must contain at most 500 characters.")
    duration = payload.get("review_time_ms")
    if duration is not None and (isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0 or duration > 86_400_000):
        raise AnnotationError("Review time must be a finite duration of at most one day.")
    with store._db(True) as db:
        original = store._get(db, image_id)
        store._check_revision(original, payload.get("revision"))
        document = deepcopy(original)
        if action == "edit":
            raw = payload.get("annotations")
            if not isinstance(raw, list) or len(raw) > 2000:
                raise AnnotationError("Provide the complete corrected annotation set.")
            classes = _classes(store)
            old = {a["id"]: a for a in original["annotations"]}
            canonical = []
            for annotation in raw:
                if not isinstance(annotation, dict):
                    raise AnnotationError("Every annotation must be an object.")
                item = deepcopy(old.get(annotation.get("id"), {}))
                item.update(id=annotation.get("id"), class_id=annotation.get("class_id"))
                category = classes.get(item["class_id"], {})
                item["parent_id"] = None if category.get("kind") == "whole_fish" else annotation.get("fish_id") or None
                # Unchanged contours retain the lossless canonical segmentation.
                if annotation.get("mask_changed") or not item.get("segmentation"):
                    points = annotation.get("mask")
                    if not isinstance(points, list) or len(points) < 3 or any(not isinstance(p, list) or len(p) != 2 for p in points):
                        raise AnnotationError("Draw a valid polygon before verifying an edited mask.")
                    item["segmentation"] = [[v for point in points for v in point]]
                item["status"] = "corrected"
                canonical.append(item)
            document["annotations"] = store._normal_annotations(canonical, original, original["annotations"])
        if action == "decline":
            document["status"] = "rejected"
        else:
            if original["status"] == "rejected" and action == "approve":
                raise AnnotationError("Edit the declined image before verifying it.")
            if not document["annotations"] or not any(a.get("status") != "rejected" for a in document["annotations"]):
                raise AnnotationError("An empty annotation set cannot be approved; draw missing parts or decline the image.")
            validation = store._validate_document(document)
            if validation["errors"]:
                raise AnnotationError("Cannot approve: " + "; ".join(e["message"] for e in validation["errors"][:6]))
            for annotation in document["annotations"]:
                if annotation["status"] not in {"rejected", "manual_verified"}:
                    annotation["status"] = "approved"
            document["status"] = "approved"
        metadata = deepcopy(document.get("metadata") or {})
        metadata["human_review"] = {"action": action, "entire_annotation_set": action != "decline", "reason": reason,
            "review_time_ms": duration, "reviewed_at": datetime.now(timezone.utc).isoformat(), "previous_revision": original["revision"]}
        document["metadata"] = metadata
        document["revision"] += 1
        saved = store._persist(db, document)
        # No label copies: this small metadata index only supports progress stats.
        db.execute("CREATE TABLE IF NOT EXISTS annotation_feedback_metadata (key TEXT PRIMARY KEY,value_json TEXT NOT NULL)")
        db.execute("INSERT INTO annotation_feedback_metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                   ("review:" + image_id, json.dumps(metadata["human_review"])))
    return saved


def apply_learning_context(store, document, output):
    """Context is evidence only. It never approves or copies reference masks."""
    service = get_learning_service(store)
    classes = _classes(store)
    labels = [view for a in output["annotations"] if (view := annotation_view(a, classes, document["width"], document["height"], model_ids=True)) is not None]
    adapted = service.adapt(store.pixels_path(document["id"]), labels, exclude_image_id=document["id"])
    by_id = {a["id"]: a for a in adapted["annotations"]}
    for annotation in output["annotations"]:
        evidence = by_id.get(annotation["id"], {}).get("adaptive_evidence")
        if evidence:
            annotation.setdefault("metadata", {})["adaptive_evidence"] = evidence
        if by_id.get(annotation["id"], {}).get("needs_review"):
            annotation["flags"] = list(dict.fromkeys([*annotation.get("flags", []), "insufficient_verified_reference_evidence"]))
    metadata = output.setdefault("automation", {})
    metadata.update(learning_references=adapted["references"], learning_warnings=adapted["warnings"],
                    learning_model_version=metadata.get("prediction_model_version", service.deployed_version()))
    return output


def annotation_quality_model(store=None):
    """A promoted part model plugs into the existing annotation engine."""
    store = store or get_annotation_store()
    service = get_learning_service(store)
    version = service.deployed_version()
    if not version.startswith(("annotation-", "original-")):
        return None
    checkpoint = service.deployed_checkpoint()
    if checkpoint is None:
        LOGGER.error("Promoted annotation checkpoint is unavailable; falling back to existing detectors.")
        return None
    with _lock:
        if version not in _candidate_models:
            from src.annotation_learning import UltralyticsAnnotationTrainer
            _candidate_models.clear()
            class PromotedPartModel:
                def __init__(self):
                    self.model = UltralyticsAnnotationTrainer._load(Path(checkpoint))
                    self.weights_path = Path(checkpoint)
                    self.confidence_threshold = .25
                    configured_size = getattr(self.model, "overrides", {}).get("imgsz", 640)
                    self.image_size = configured_size if isinstance(configured_size, int) else max(configured_size) if isinstance(configured_size, (list, tuple)) and configured_size else 640
                    self.version = version
                def infer_crop(self, frame):
                    from src.inference.part_model import part_detections_from_result
                    with _lock:
                        result = self.model.predict(source=frame, device="cpu", verbose=False,
                            conf=self.confidence_threshold, imgsz=self.image_size, half=False)[0]
                    return part_detections_from_result(result)
            _candidate_models[version] = PromotedPartModel()
        return _candidate_models[version]


def bootstrap_manual_baseline(learning):
    """Index the existing dataset once; keep its source files immutable."""
    store = learning.store
    canonical = store.canonical
    profile = store.baseline_profile()
    if profile:
        result = _profile_indexing_status(profile)
        if store.metadata("baseline_bootstrap") != result:
            store.set_metadata("baseline_bootstrap", result)
        return result
    files = [canonical.manual_source / split / "_annotations.coco.json" for split in ("train", "valid", "test")]
    existing = [path for path in files if path.is_file()]
    if not existing:
        result = {"state": "unavailable", "errors": ["Original manual dataset is unavailable; no baseline was invented."]}
        store.set_metadata("baseline_bootstrap", result)
        return result
    fingerprint = sha256("".join(sha256(p.read_bytes()).hexdigest() for p in existing).encode()).hexdigest()
    previous = store.metadata("baseline_bootstrap", {})
    if previous.get("fingerprint") == fingerprint and previous.get("state") == "ready":
        return previous
    if previous.get("fingerprint") and previous["fingerprint"] != fingerprint:
        result = {"state": "source_changed", "fingerprint": previous["fingerprint"], "errors": ["Original manual source changed. The established baseline remains preserved; inspect the dataset protocol before importing replacements."]}
        store.set_metadata("baseline_bootstrap", result)
        return result
    store.set_metadata("baseline_bootstrap", {"state": "indexing", "fingerprint": fingerprint, "errors": []})
    report = canonical.import_manual([p.parent.name for p in existing])
    result = {"state": "errors" if report["errors"] else "ready", "fingerprint": fingerprint,
        "imported": report["imported"], "already_indexed": report["skipped"], "errors": report["errors"]}
    store.set_metadata("baseline_bootstrap", result)
    return result


def _profile_indexing_status(profile):
    raw_status = profile.get("status", "ready")
    state = {"importing": "indexing", "error": "errors", "failed": "errors", "needs_review": "errors"}.get(raw_status, raw_status)
    if state not in {"ready", "indexing", "errors"}:
        state = "errors"
    errors = list(profile.get("errors") or [])
    if profile.get("error"):
        errors.append(str(profile["error"]))
    return {"state": state, "dataset_id": profile["dataset_id"], "name": profile.get("name", profile["dataset_id"]),
            "errors": errors, "source_status": profile.get("status", "ready")}


def start_learning_maintenance():
    global _maintenance_thread
    with _lock:
        if _maintenance_thread and _maintenance_thread.is_alive():
            return
        _maintenance_stop.clear()
        def maintain():
            indexed_baseline = None
            while not _maintenance_stop.is_set():
                try:
                    learning = get_learning_service()
                    baseline = bootstrap_manual_baseline(learning)
                    baseline_key = (baseline.get("dataset_id"), baseline.get("fingerprint"))
                    if baseline["state"] == "ready" and indexed_baseline != baseline_key:
                        learning.prepare_references()
                        indexed_baseline = baseline_key
                    if baseline["state"] == "ready":
                        learning.maybe_schedule()
                except Exception:
                    # A competing importer can temporarily own the writer.
                    # Retry the complete setup next cycle without blocking app
                    # startup or trying the same failed initialization twice.
                    LOGGER.exception("Annotation learning maintenance deferred; will retry. Verified annotations remain saved.")
                _maintenance_stop.wait(60)
        _maintenance_thread = Thread(target=maintain, name="annotation-learning-maintenance", daemon=True)
        _maintenance_thread.start()


def stop_learning_maintenance():
    _maintenance_stop.set()


def create_review_router(store=None, learning=None, automation=None):
    router = APIRouter(prefix="/api/annotations", tags=["Verified annotation review"])
    def workspace():
        return store or get_annotation_store()
    def learner():
        return learning or get_learning_service(workspace())
    def translate(error):
        raise HTTPException(getattr(error, "status_code", 422), str(error)) from error

    @router.get("/pending")
    def pending():
        items = _pending(workspace())
        return {"items": items[:200], "total": len(items), "next_image_id": items[0]["image_id"] if items else None}

    @router.get("/learning/status")
    def status():
        result = learner().status()
        classes = _classes(workspace())
        profile = result.get("primary_baseline")
        return dict(result, current_model_version=result.get("deployed_model_version"), pending_training=result.get("pending_training_examples", 0),
            baseline_indexing=_profile_indexing_status(profile) if profile else learner().store.metadata("baseline_bootstrap", {"state": "not_started"}),
            class_names={k: c["name"] for k, c in classes.items() if c["active"]}, class_kinds={k: c["kind"] for k, c in classes.items() if c["active"]})

    @router.post("/learning/rollback")
    def rollback(payload: dict):
        try:
            return learner().rollback(payload.get("version"))
        except (AnnotationError, ValueError) as error:
            translate(error)

    @router.post("/upload")
    async def upload(request: Request):
        filename = unquote(request.headers.get("x-filename", "image.png"))
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 40 * 1024 * 1024:
                raise HTTPException(413, "Image exceeds the 40 MiB limit.")
        def process():
            item = workspace().upload(bytes(body), filename)
            if not item["annotations"] and item["status"] == "unreviewed":
                from src.api.annotation_workspace import _automation
                callback = automation or _automation
                if callback:
                    try:
                        item = workspace().auto(item["id"], item["revision"], callback)
                    except (AnnotationError, RuntimeError, HTTPException) as error:
                        LOGGER.warning("Annotation prediction unavailable; image saved for editing: %s", error)
            return review_item(workspace(), item)
        try:
            return await asyncio.to_thread(process)
        except AnnotationError as error:
            translate(error)

    @router.get("/{image_id}/image")
    def image(image_id: str):
        try:
            return FileResponse(workspace().pixels_path(image_id), media_type="image/png", headers={"Cache-Control": "no-store"})
        except AnnotationError as error:
            translate(error)

    @router.get("/{image_id}")
    def item(image_id: str):
        try:
            return review_item(workspace(), workspace().get(image_id))
        except AnnotationError as error:
            translate(error)

    @router.post("/{image_id}/review")
    def review(image_id: str, payload: dict):
        try:
            saved = verify_review(workspace(), image_id, payload)
            try:
                learner().maybe_schedule()
            except Exception:
                LOGGER.exception("Verified review was saved; learning scheduling failed.")
            pending_images = _pending(workspace())
            return {"item": review_item(workspace(), saved), "next_image_id": pending_images[0]["image_id"] if pending_images else None}
        except AnnotationError as error:
            translate(error)
    return router


router = create_review_router()
