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
from src.inference.fish_geometry import measure_fish_geometry
from src.inference.part_types import PartDetection
from src.inference.preprocessing import measurement_crop_bounds


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


def _source_bound(record, frame, frame_id, parent_id):
    return (isinstance(record, dict) and record.get("frame_id") == frame_id
            and str(record.get("source_parent_id", record.get("parent_track_id"))) == str(parent_id)
            and (record.get("frame_width_px") is None or record["frame_width_px"] == frame.shape[1])
            and (record.get("frame_height_px") is None or record["frame_height_px"] == frame.shape[0]))


def _preview_analysis(frame, item, provider, report):
    """Supply native display evidence without a detector, regrade, or inference.

    An on-demand snapshot intentionally has no saved analysis. Its already
    generated native candidate can still supply estimated diagnostic axes.
    Saved crack locations are reusable only for this exact frame and parent.
    """
    parent_id, frame_id = item["id"], provider.frame_id
    original = item.get("analysis") if isinstance(item.get("analysis"), dict) else {}
    analysis = {key: deepcopy(original[key]) for key in
                ("quality_inference", "model2_debug", "model1_detection") if key in original}
    saved = original.get("fish_geometry", {})
    saved = saved if isinstance(saved, dict) else {}
    visual = saved.get("visualization") or saved.get("candidate_visualization") or {}
    # Still-photo frame labels repeat across uploads; a matching label alone
    # cannot authorize borrowing coordinates from different original pixels.
    saved_segmentation = original.get("segmentation", {})
    saved_segmentation = saved_segmentation if isinstance(saved_segmentation, dict) else {}
    mask_metadata = saved.get("mask_metadata", {})
    source_keys = [saved_segmentation.get("provenance", {}).get("frame_key"),
                   mask_metadata.get("candidate_provenance", {}).get("frame_key")]
    source_matches = (getattr(provider, "frame_key", None) is not None
                      and provider.frame_key in source_keys)
    reuse_geometry = (report.get("engineering_checks_passed") is True
                      and source_matches and _source_bound(saved, frame, frame_id, parent_id)
                      and _source_bound(visual, frame, frame_id, parent_id)
                      and visual.get("coordinate_space") == "original_frame"
                      and visual.get("frame_width_px") == frame.shape[1]
                      and visual.get("frame_height_px") == frame.shape[0]
                      and bool(visual.get("length_path") or visual.get("principal_axis")))
    if reuse_geometry:
        geometry = deepcopy(saved)
        for key in ("body_width", "feature_fusion"):
            if isinstance(original.get(key), dict):
                analysis[key] = deepcopy(original[key])
    else:
        try:
            bounds = measurement_crop_bounds(frame, item["bbox"])
            get_mask = getattr(provider, "get", None)
            mask, metadata = get_mask(parent_id, bounds) if callable(get_mask) else (None, {})
            metadata = {**metadata, "expected_parent_id": parent_id, "frame_id": frame_id,
                        "parent_track_id": parent_id}
            if report.get("engineering_checks_passed") is not True:
                metadata["context_reliability_reasons"] = ["mask_ownership_unreliable"]
            parts = []
            for part in item.get("parts", []):
                try:
                    owner = part.get("source_parent_id", part.get("parent_track_id"))
                    if (owner is not None and str(owner) != str(parent_id)
                            or part.get("coordinate_space", "original_frame") != "original_frame"
                            or part.get("frame_id", frame_id) != frame_id
                            or part.get("association_status", "ASSIGNED") != "ASSIGNED"
                            or part.get("association", {}).get("status", "ASSIGNED") != "ASSIGNED"):
                        continue
                    box = part["bbox"]
                    if (len(box) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                            or not math.isfinite(v) for v in box)):
                        continue
                    local = (box[0] - bounds.x1, box[1] - bounds.y1,
                             box[2] - bounds.x1, box[3] - bounds.y1)
                    polygon = part.get("mask")
                    polygon = ([(x - bounds.x1, y - bounds.y1) for x, y in polygon]
                               if polygon is not None and part.get("mask_coordinate_space", "original_frame") == "original_frame"
                               else None)
                    parts.append(PartDetection.from_source_class(part["source_class_id"], part["confidence"], local, polygon))
                except (KeyError, TypeError, ValueError):
                    continue
            get_body = getattr(provider, "body_mask", None)
            body_mask, body_metadata = get_body(parent_id, bounds) if callable(get_body) else (None, {})
            box = item["bbox"]
            overlapping = any(other.track_id != parent_id
                and min(box[2], other.bbox[2]) > max(box[0], other.bbox[0])
                and min(box[3], other.bbox[3]) > max(box[1], other.bbox[1])
                for other in getattr(provider, "parents", []))
            geometry = measure_fish_geometry(
                mask, parts, parent_bbox=box, crop_bounds=bounds, frame_shape=frame.shape,
                overlapping=overlapping, association_reliable=report.get("engineering_checks_passed") is True,
                mask_metadata=metadata, body_mask=body_mask, body_mask_metadata=body_metadata,
            )
            geometry.update(mask_metadata=metadata, mask_crop_bounds=[bounds.x1, bounds.y1, bounds.x2, bounds.y2])
        except Exception as error:
            geometry = measure_fish_geometry(None)
            geometry["reasons"].append("preview_geometry_processing_failed")
            geometry["measurement_error_type"] = type(error).__name__
        geometry.update(frame_id=frame_id, parent_track_id=parent_id, frame_width_px=frame.shape[1],
                        frame_height_px=frame.shape[0], display_only=True, used_for_grading=False,
                        display_geometry_source="Already generated native candidate mask; no models or grading rerun.")
        analysis["body_width"] = {
            "status": "unavailable", "width_abnormality": "Unavailable: no reviewed anatomical width reference",
            "candidate_anatomical_ratio": geometry.get("candidate_measurements", {}).get("relative_width_ratio"),
            "reason": "Preview geometry is display evidence only; Body ownership and a normal-width reference remain unvalidated.",
            "score_contributed": False, "used_for_grading": False,
        }
    analysis["fish_geometry"] = geometry
    damage = original.get("surface_damage", {})
    if source_matches and _source_bound(damage, frame, frame_id, parent_id):
        analysis["surface_damage"] = deepcopy(damage)
    else:
        analysis["surface_damage"] = {
            "status": "unavailable", "validation_status": "unvalidated", "locations": [],
            "severity": "unassessed", "mask_validated_for_cracks": False, "used_for_grading": False,
            "frame_id": frame_id, "parent_track_id": parent_id, "coordinate_space": "original_frame",
            "frame_width_px": frame.shape[1], "frame_height_px": frame.shape[0],
            "reason": "No source-matched crack candidates were recorded for this preview. A reviewed, correctly owned Body pixel mask is required; MobileSAM candidate masks do not establish Body anatomy or absence of cracks.",
        }
    analysis["inspection_source"] = {"type": "mask_preview", "frame_id": frame_id,
                                     "frame_width_px": frame.shape[1], "frame_height_px": frame.shape[0]}
    return analysis


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
                        "segmentation": report, "analysis": _preview_analysis(frame, item, provider, report)})
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
