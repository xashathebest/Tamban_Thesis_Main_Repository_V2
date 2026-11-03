"""Explicit mask previews reuse detector evidence without regrading a fish."""
from __future__ import annotations

import base64
from collections import OrderedDict
from copy import deepcopy
import math
from threading import RLock
from time import monotonic, perf_counter
import uuid

import cv2
import numpy as np

from src.inference.association import ParentAnchor
from src.inference.experimental_segmentation import ExperimentalFrameSegmentation
from src.inference.part_types import PartDetection


class PreviewSnapshotError(ValueError):
    pass


def detector_signature(detector):
    return (id(detector), id(getattr(detector, "model", None)),
            str(getattr(detector, "weights_path", "")),
            getattr(detector, "confidence_threshold", None), getattr(detector, "image_size", None),
            getattr(detector, "iou_threshold", None), getattr(detector, "max_detections", None))


class PreviewSnapshotCache:
    """Bounded metadata only; no uploaded pixels, grades or model state stored."""
    def __init__(self, capacity=32, ttl_seconds=300, *, clock=monotonic):
        self.capacity, self.ttl_seconds, self.clock = capacity, ttl_seconds, clock
        self._entries = OrderedDict()
        self._lock = RLock()

    def _prune(self):
        now = self.clock()
        for token in list(self._entries):
            if now - self._entries[token][0] >= self.ttl_seconds:
                del self._entries[token]

    def remember(self, image_sha256, frame_shape, fish, detector):
        records = []
        for item in fish:
            if not isinstance(item, dict) or isinstance(item.get("id"), bool) or not isinstance(item.get("id"), int):
                return None
            analysis = item.get("analysis") if isinstance(item.get("analysis"), dict) else {}
            native = analysis.get("model1_detection", {})
            bbox = native.get("bbox", item.get("bbox")) if isinstance(native, dict) else item.get("bbox")
            if not isinstance(bbox, (tuple, list)) or len(bbox) != 4:
                return None
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in bbox):
                return None
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                return None
            records.append({"id": item["id"], "bbox": list(bbox),
                            "detector_confidence": item.get("detector_confidence"),
                            "parts": deepcopy(item.get("parts", []))})
        token = uuid.uuid4().hex
        snapshot = {"image_sha256": image_sha256, "frame_shape": tuple(frame_shape),
                    "fish": records, "detector_signature": detector_signature(detector)}
        with self._lock:
            self._prune()
            self._entries[token] = (self.clock(), snapshot)
            while len(self._entries) > self.capacity:
                self._entries.popitem(last=False)
        return token

    def resolve(self, token, image_sha256, frame_shape, detector):
        with self._lock:
            self._prune()
            record = self._entries.get(token)
            if record is None:
                raise PreviewSnapshotError("The image-analysis snapshot expired or is unavailable. Run analysis again or select the image again.")
            snapshot = record[1]
            if snapshot["image_sha256"] != image_sha256 or snapshot["frame_shape"] != tuple(frame_shape):
                raise PreviewSnapshotError("The mask request does not match the analyzed image. Select the image and run analysis again.")
            if snapshot["detector_signature"] != detector_signature(detector):
                raise PreviewSnapshotError("Model 1 or its settings changed after analysis. Run analysis again before inspecting its masks.")
            return deepcopy(snapshot["fish"])


def _part_evidence(fish):
    selected, seen = [], set()
    for record in fish:
        for part in record.get("parts", []):
            try:
                key = (part["source_class_id"], part["confidence"], tuple(part["bbox"]))
                if key not in seen:
                    selected.append(PartDetection.from_source_class(*key))
                    seen.add(key)
            except (KeyError, ValueError, TypeError):
                # Only already assigned, schema-compatible Model 2 evidence is
                # eligible for checks. Missing evidence stays unavailable.
                continue
    return selected


def generate_mask_preview(frame, fish, *, image_sha256, sam_service=None, model1_inference_ms=0., reused=False, mask_context=None):
    started = perf_counter()
    provider = getattr(mask_context, "_experimental", None) if mask_context is not None and mask_context.is_for_frame(frame) else None
    if provider is not None:
        sam_service = provider.service or sam_service
    if sam_service is None:
        from src.inference.mobilesam_backend import get_mobilesam_service
        sam_service = get_mobilesam_service()
    frame_id = provider.frame_id if provider is not None else "mask-preview:" + uuid.uuid4().hex
    if provider is None:
        parents = [ParentAnchor(item["id"], tuple(item["bbox"]), item.get("detector_confidence") or 0.) for item in fish]
        provider = ExperimentalFrameSegmentation(frame, frame_id, service=sam_service)
        provider.prepare(parents, _part_evidence(fish))
    records, errors = [], []
    generated = review_required = 0
    for item in fish:
        report = deepcopy(provider.report(item["id"]))
        candidate = provider.candidates.get(item["id"], {})
        mask = candidate.get("mask")
        meaningful = isinstance(mask, np.ndarray) and mask.shape == frame.shape[:2] and mask.any()
        pixels = int(np.count_nonzero(mask)) if meaningful else 0
        if meaningful:
            _, _, width, height = cv2.boundingRect(mask.astype(np.uint8))
            meaningful = pixels / max(1, width * height) < .995 and pixels < mask.size
        contours = report.get("mask_overlay", {}).get("contours", [])
        usable = bool(meaningful and contours)
        report.update(preview_usable=usable, foreground_pixels=pixels, used_for_grading=False,
                      measurement_validated=False, mask_validated_for_cracks=False)
        if pixels and not meaningful:
            report.setdefault("reasons", []).append("Nearly rectangular or full-image foreground; no meaningful silhouette established.")
        if not usable:
            detail = candidate.get("detail") or candidate.get("reason") or "; ".join(report.get("reasons", []))
            errors.append(f"Fish #{item['id']}: {detail}")
        else:
            generated += 1
        needs_review = report.get("ownership_status") != "checks_passed_unvalidated"
        review_required += int(usable and needs_review)
        records.append({"id": item["id"], "bbox": list(item["bbox"]), "parts": deepcopy(item.get("parts", [])),
                        "segmentation": report, **({"analysis": {key: deepcopy(item["analysis"].get(key, {}))
                            for key in ("surface_damage", "fish_geometry", "feature_fusion", "inspection_source",
                                        "quality_inference", "model2_debug", "model1_detection")}}
                            if isinstance(item.get("analysis"), dict) else {})})
    scale = min(1., 1280 / max(frame.shape[:2]))
    preview = frame if scale == 1 else cv2.resize(frame, (round(frame.shape[1] * scale), round(frame.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("The original image preview could not be encoded.")
    diagnostics = provider.diagnostics()
    status = "generated" if generated else "unavailable" if fish else "no_fish"
    message = (f"Generated {generated} candidate masks. {review_required} require review due to overlap, missing anatomy or unreliable isolation. All masks remain unvalidated."
               if generated else "No fish detected; no masks generated." if not fish else
               "Segmentation failed: " + ("; ".join(errors) or "No usable pixel masks returned."))
    return {"status": status, "message": message, "generated_masks": generated, "review_required_masks": review_required,
            "errors": errors, "used_for_grading": False, "detector_snapshot_reused": reused,
            "source": {"frame_id": frame_id, "frame_width_px": frame.shape[1], "frame_height_px": frame.shape[0],
                       "image_sha256": image_sha256},
            "preview_image": "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii"), "fish": records,
            "performance": {"segmentation_ms": diagnostics.get("segmentation_ms", 0.),
                            "embedding_ms": diagnostics.get("embedding_ms"), "prompt_ms": diagnostics.get("prompt_ms"),
                            "model1_inference_ms": model1_inference_ms,
                            "total_processing_ms": round((perf_counter() - started) * 1000 + model1_inference_ms, 3),
                            "gpu_memory": diagnostics.get("gpu_memory"), "diagnostics": diagnostics,
                            "timing_scope": "Model 1 if needed, segmentation, ownership checks and preview encoding; excludes request decode and network"},
            "backend_status": sam_service.status(),
            "setup_command": "python -m src.evaluation.download_mobilesam_checkpoint"}
