"""Local annotation candidates from the existing detectors and pixel-mask service.

The manual part taxonomy is the reference; a detector box is only a prompt.
Candidates always require review. No grading rules or detector settings change.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from time import perf_counter
import uuid

import cv2
import numpy as np

from src.inference.association import ParentAnchor, associate_parts_to_parents
from src.inference.mask_ownership import validate_candidate_masks
from src.preprocessing.audit_v7_exports import SOURCE_CLASSES
from src.preprocessing.dataset_utils import project_root


@lru_cache(maxsize=4)
def manual_reference(root: str) -> dict:
    """Read, never rewrite, the manual taxonomy and geometric reference examples."""
    if Path(root).is_file():
        # The selected primary dataset publishes this descriptor once during
        # import. It includes training examples only, never held-out statistics.
        reference = json.loads(Path(root).read_bytes())
        valid = isinstance(reference, dict) and reference.get("annotation_unit") == "fish_part" and isinstance(reference.get("classes"), dict)
        if valid:
            valid = all(isinstance(rows, list) and all(isinstance(example, dict) and example.get("split") == "train"
                       for example in rows) for rows in reference["classes"].values())
        if not valid:
            raise ValueError("The selected manual reference descriptor is invalid or contains held-out examples.")
        return reference
    examples = defaultdict(list)
    sources = []
    # Held-out labels are for evaluation only, never prediction adaptation.
    for split in ("train",):
        path = Path(root) / split / "_annotations.coco.json"
        if not path.is_file():
            continue
        raw = path.read_bytes()
        data = json.loads(raw)
        images = {im["id"]: im for im in data.get("images", [])}
        names = {cat["id"]: cat["name"] for cat in data.get("categories", [])}
        sources.append({"split": split, "path": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
        for ann in data.get("annotations", []):
            image = images.get(ann.get("image_id"))
            name = names.get(ann.get("category_id"))
            if image and name in SOURCE_CLASSES.values():
                # A loose reference envelope flags unusual shapes. It never
                # changes a predicted class, boundary, confidence or approval.
                area = ann.get("area")
                if isinstance(area, (int, float)) and area > 0:
                    examples[name].append({"annotation_id": ann["id"], "split": split,
                                           "area_fraction": area / (image["width"] * image["height"])})
    return {"sources": sources, "classes": dict(examples), "annotation_unit": "fish_part",
            "whole_fish_ground_truth_available": False}


def _class_mapping(classes):
    mapping, whole = {}, None
    for item in classes:
        if item.get("active", True) is False:
            continue
        if item.get("kind") == "whole_fish":
            whole = item["id"] if whole is None else whole
        model_id = item.get("model_class_id")
        name = item.get("source_name", item.get("name"))
        if model_id is None:
            model_id = next((key for key, value in SOURCE_CLASSES.items() if value == name), None)
        if model_id in SOURCE_CLASSES:
            mapping[model_id] = item["id"]
    if whole is None:
        raise ValueError("The class registry needs an active Whole fish class before automation.")
    missing = set(SOURCE_CLASSES) - mapping.keys()
    if missing:
        raise ValueError(f"Restore model-linked part classes before automation: {sorted(missing)}")
    return mapping, whole


def _usable_mask(candidate, shape, *, frame_key, prompt_id):
    provenance = candidate.get("provenance", {})
    if (candidate.get("parent_id") != prompt_id or provenance.get("parent_id") != prompt_id
            or provenance.get("frame_key") != frame_key
            or provenance.get("coordinate_space") != "original_frame"
            or provenance.get("mask_shape") != list(shape)):
        return None
    mask = candidate.get("mask")
    if not isinstance(mask, np.ndarray) or mask.shape != shape or mask.dtype != np.bool_ or not mask.any():
        return None
    if _boxlike_mask(mask):
        return None
    return mask.copy()


def _boxlike_mask(mask):
    """A filled rectangular prediction supplies no foreground boundary evidence."""
    _, _, width, height = cv2.boundingRect(mask.astype(np.uint8))
    area = np.count_nonzero(mask)
    return area >= mask.size or area / max(1, width * height) >= .995


def _native_part_mask(part, shape):
    """Retain a selected segmentation model's real native-coordinate polygon."""
    if not part.mask:
        return None
    points = np.asarray(part.mask, dtype=float)
    if (points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all()
            or (points < 0).any() or (points[:, 0] >= shape[1]).any() or (points[:, 1] >= shape[0]).any()):
        return None
    mask = np.zeros(shape, np.uint8)
    cv2.fillPoly(mask, [np.rint(points).astype(np.int32)], 1)
    return mask.astype(bool) if mask.any() else None


def _mask_rle(mask):
    flat = mask.reshape(-1, order="F")
    changes = np.flatnonzero(flat[1:] != flat[:-1]) + 1
    counts = np.diff(np.r_[0, changes, flat.size]).tolist()
    if flat[0]:
        counts.insert(0, 0)
    return {"size": list(mask.shape), "counts": counts}


def _bbox(mask, fallback):
    if mask is not None:
        return list(cv2.boundingRect(mask.astype(np.uint8)))
    left, top, right, bottom = fallback
    return [left, top, right - left, bottom - top]


def generate_annotations(document, frame, classes, *, detector, quality_model, sam_service=None,
                         reference_root=None):
    """One detector pass each and one SAM embedding for all fish and parts."""
    started = perf_counter()
    if getattr(detector, "model", None) is None:
        raise RuntimeError("Whole-fish detection is unavailable. Load the existing Model 1 checkpoint.")
    mapping, whole_class = _class_mapping(classes)
    reference = manual_reference(str(reference_root or project_root() / "Dried Fish Quality Grading.v7i.coco-segmentation"))
    detections = list(detector.detect(frame))
    parents = [ParentAnchor(index, tuple(d.bbox), d.confidence) for index, d in enumerate(detections, 1)]
    errors = []
    parts = []
    if quality_model is not None and getattr(quality_model, "model", None) is not None:
        parts = list(quality_model.infer_crop(frame))
    else:
        errors.append("Part detector unavailable; anatomy remains undetected, not physically absent.")
    associations = associate_parts_to_parents(parts, parents)
    frame_key = "annotations:" + str(document["id"]) + ":" + uuid.uuid4().hex
    if sam_service is None:
        from src.inference.mobilesam_backend import get_mobilesam_service
        sam_service = get_mobilesam_service()
    candidates, part_candidates, native_fallbacks, diagnostics = {}, {}, {}, {}
    if parents or parts:
        with sam_service.open_frame(frame, frame_key) as session:
            for parent in parents:
                candidates[parent.track_id] = session.predict(parent.track_id, parent.bbox)
            for index, part in enumerate(parts):
                native = _native_part_mask(part, frame.shape[:2]) if part.mask else None
                if part.mask and (native is None or _boxlike_mask(native)):
                    # Preserve the model output, but ask the existing foreground
                    # segmenter for actual boundaries rather than certifying a
                    # box-shaped native prediction as useful segmentation.
                    native_fallbacks[index] = {
                        "reason": "boxlike" if native is not None else "invalid",
                        "segmentation": _mask_rle(native) if native is not None else None}
                if not part.mask or index in native_fallbacks:
                    part_candidates[index] = session.predict("part-" + str(index), part.bbox)
            diagnostics = session.diagnostics()
    ownership = validate_candidate_masks(candidates, parents, parts, associations=associations,
                                         frame_shape=frame.shape, expected_frame_key=frame_key) if parents else {}
    annotations, masks = [], {}
    parent_ids = {p.track_id: "fish-" + str(p.track_id) for p in parents}
    whole_masks = {p.track_id: _usable_mask(candidates.get(p.track_id, {}), frame.shape[:2],
                                          frame_key=frame_key, prompt_id=p.track_id) for p in parents}
    for parent in parents:
        mask = whole_masks[parent.track_id]
        assigned = [a.part.region for a in associations if a.track_id == parent.track_id and a.status == "ASSIGNED"]
        flags = [region.lower() + "_undetected_not_confirmed_absent" for region in ("Head", "Body", "Tail") if region not in assigned]
        flags.extend(ownership.get(parent.track_id, {}).get("reasons", []))
        if not ownership.get(parent.track_id, {}).get("engineering_checks_passed"):
            flags.append("fish_mask_ownership_requires_review")
        candidate = candidates.get(parent.track_id, {})
        if mask is None:
            flags.append("missing_segmentation")
            errors.append(f"Fish {parent.track_id}: " + str(candidate.get("reason") or "No usable nonrectangular pixel mask."))
        if parent.confidence is not None and parent.confidence < .7:
            flags.append("low_confidence_review")
        if parent.bbox[0] <= 0 or parent.bbox[1] <= 0 or parent.bbox[2] >= frame.shape[1] or parent.bbox[3] >= frame.shape[0]:
            flags.append("partially_visible_or_frame_boundary")
        ann = {"id": parent_ids[parent.track_id], "class_id": whole_class, "parent_id": None,
               "segmentation": _mask_rle(mask) if mask is not None else None, "bbox": _bbox(mask, parent.bbox),
               "confidence": parent.confidence, "status": "unreviewed", "source": "automated", "flags": flags,
               "metadata": {"detector_bbox_xyxy": list(parent.bbox), "mask_score": candidate.get("score"),
                            "mask_provenance": candidate.get("provenance", {}), "ownership": ownership.get(parent.track_id, {})}}
        annotations.append(ann)
        if mask is not None:
            masks[ann["id"]] = mask
    for index, association in enumerate(associations):
        part = association.part
        # Associations are returned in the same order as the original parts.
        candidate = part_candidates.get(index, {})
        uses_native = bool(part.mask) and index not in native_fallbacks
        mask = (_native_part_mask(part, frame.shape[:2]) if uses_native else
                _usable_mask(candidate, frame.shape[:2], frame_key=frame_key, prompt_id="part-" + str(index)))
        original_part_segmentation = _mask_rle(mask) if mask is not None else None
        parent_id = association.track_id if association.status == "ASSIGNED" else None
        flags = []
        if index in native_fallbacks:
            flags.append("native_part_mask_" + native_fallbacks[index]["reason"] + "_requires_review")
        if (not uses_native and candidate.get("mask") is not None and mask is None
                and (candidate.get("parent_id") != "part-" + str(index)
                     or candidate.get("provenance", {}).get("parent_id") != "part-" + str(index)
                     or candidate.get("provenance", {}).get("frame_key") != frame_key
                     or candidate.get("provenance", {}).get("coordinate_space") != "original_frame"
                     or candidate.get("provenance", {}).get("mask_shape") != list(frame.shape[:2]))):
            flags.append("mask_provenance_mismatch_requires_regeneration")
        if parent_id is None:
            flags.append("ownership_" + association.status.lower())
        elif mask is not None and whole_masks.get(parent_id) is not None:
            parent_mask = whole_masks[parent_id]
            outside = int(np.count_nonzero(mask & ~parent_mask))
            if outside:
                if uses_native:
                    flags.append("native_part_mask_outside_candidate_parent_requires_review")
                else:
                    flags.append("part_mask_clipped_to_candidate_parent_requires_review")
                    mask &= parent_mask
            if not mask.any():
                mask = None
        if mask is None:
            flags.append("missing_segmentation")
        if part.confidence < .7:
            flags.append("low_confidence_review")
        examples = reference["classes"].get(SOURCE_CLASSES[part.source_class_id], [])
        if mask is not None and len(examples) >= 4:
            areas = [example["area_fraction"] for example in examples]
            fraction = np.count_nonzero(mask) / mask.size
            if fraction < min(areas) / 2 or fraction > max(areas) * 2:
                flags.append("mask_area_outside_manual_reference_envelope")
        ann = {"id": "part-" + str(index + 1), "class_id": mapping[part.source_class_id],
               "parent_id": parent_ids.get(parent_id), "segmentation": _mask_rle(mask) if mask is not None else None,
               "bbox": _bbox(mask, part.bbox), "confidence": part.confidence, "status": "unreviewed", "source": "automated",
               "flags": flags, "metadata": {"model_class_id": part.source_class_id, "region": part.region,
                   "grade": part.grade, "detector_bbox_xyxy": list(part.bbox), "association": association.to_dict(),
                   "mask_score": candidate.get("score"), "mask_provenance": (candidate.get("provenance", {}) if not uses_native else
                       {"source": "existing_model2_instance_segmentation", "coordinate_space": "original_frame", "frame_key": frame_key}),
                   "original_predicted_segmentation": original_part_segmentation,
                   **({"original_native_predicted_segmentation": native_fallbacks[index]["segmentation"],
                       "native_mask_fallback_reason": native_fallbacks[index]["reason"]} if index in native_fallbacks else {}),
                   "reference_example_ids": [e["annotation_id"] for e in examples[:3]]}}
        annotations.append(ann)
        if mask is not None:
            masks[ann["id"]] = mask
    # Keep uncertain instances available for editing; never resolve a merged
    # candidate by arbitrarily assigning shared pixels to a different fish.
    for index, first in enumerate(annotations):
        for second in annotations[index + 1:]:
            if first["id"] not in masks or second["id"] not in masks:
                continue
            if second.get("parent_id") == first["id"] or first.get("parent_id") == second["id"]:
                continue
            overlap = int(np.count_nonzero(masks[first["id"]] & masks[second["id"]]))
            if not overlap:
                continue
            minimum = min(np.count_nonzero(masks[first["id"]]), np.count_nonzero(masks[second["id"]]))
            flag = "possible_duplicate_mask" if overlap / max(1, minimum) >= .9 else "overlapping_or_ambiguous_masks"
            for ann in (first, second):
                if flag not in ann["flags"]:
                    ann["flags"].append(flag)
    return {"annotations": annotations, "automation": {
        "status": "predictions_require_review" if annotations else "no_detections_requires_review",
        "model1_detections": len(detections), "model2_detections": len(parts),
        "pixel_masks": len(masks), "errors": errors, "performance": diagnostics,
        "elapsed_ms": round((perf_counter() - started) * 1000, 3),
        "manual_reference": {key: value for key, value in reference.items() if key != "classes"},
        "review_policy": "All predictions are unreviewed. Undetected anatomy does not establish physical absence.",
        "models": {"model1": str(getattr(detector, "weights_path", "")),
                   "model2": str(getattr(quality_model, "weights_path", "")),
                   "model1_confidence": getattr(detector, "confidence_threshold", None),
                   "model2_confidence": getattr(quality_model, "confidence_threshold", None)}}}
