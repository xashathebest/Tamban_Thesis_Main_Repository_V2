"""Refine unresolved part ownership using measured, exclusive native SAM pixels.

This supplies the existing mask term of the canonical association score. It
does not certify candidate masks or detector rectangles as reviewed anatomy.
Existing assignments, score weights, thresholds, duplicate selection and
anatomical contradiction checks remain authoritative.
"""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Mapping, Sequence

import cv2
import numpy as np

from src.inference.association import (
    AssociationConfig, AssociationScore, ParentAnchor, PartAssociation,
    associate_parts_to_parents, score_part_parent,
)
from src.inference.mask_ownership import MaskOwnershipConfig, validate_candidate_masks
from src.inference.part_types import PartDetection


_ASSOCIATION_DEPENDENT_REASONS = {
    "required_head_evidence_unavailable", "required_body_evidence_unavailable",
    "required_anatomical_ownership_ambiguous",
}
_VISIBLE_FRAME_CONTACT_REASONS = {"mask_touches_frame_boundary", "parent_touches_frame_boundary"}


def _native_candidate(candidate, record, parent, shape, expected_frame_key):
    """Bind engineering evidence to this exact parent, prompt and source frame."""
    reasons = []
    if not isinstance(candidate, Mapping) or not isinstance(record, Mapping):
        return None, ["native_candidate_checks_unavailable"]
    recorded_reasons = set(record.get("reasons") or ())
    # Visible parts can still be associated on a frame-clipped fish. Native
    # clipping remains authoritative for anatomical rejection downstream.
    frame_contact_only = bool(recorded_reasons & _VISIBLE_FRAME_CONTACT_REASONS) and not (
        recorded_reasons - _ASSOCIATION_DEPENDENT_REASONS - _VISIBLE_FRAME_CONTACT_REASONS)
    if record.get("mask_geometry_checks_passed") is not True and not frame_contact_only:
        reasons.append("native_mask_geometry_checks_failed")
    if record.get("conflicting_parent_ids"):
        reasons.append("native_mask_ownership_conflict")
    reasons.extend(sorted(recorded_reasons - _ASSOCIATION_DEPENDENT_REASONS - _VISIBLE_FRAME_CONTACT_REASONS))
    if (record.get("parent_id") != parent.track_id or record.get("coordinate_space") != "original_frame"
            or record.get("frame_shape") != list(shape)):
        reasons.append("native_ownership_context_mismatch")
    provenance = candidate.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    if not (provenance.get("backend") == "mobilesam_experimental"
            or provenance.get("source") == "mobilesam_box_prompt_candidate"):
        reasons.append("native_mobilesam_provenance_unavailable")
    if (expected_frame_key is None or provenance.get("frame_key") != expected_frame_key
            or provenance.get("coordinate_space") != "original_frame"
            or provenance.get("mask_shape") != list(shape)):
        reasons.append("native_candidate_frame_mismatch")
    if (candidate.get("parent_id") != parent.track_id
            or provenance.get("parent_id") != parent.track_id):
        reasons.append("native_candidate_parent_mismatch")
    try:
        original = np.asarray(provenance.get("original_bbox_global"), dtype=float)
        prompt = np.asarray(provenance.get("prompt_bbox_global"), dtype=float)
        expected_prompt = np.clip(parent.bbox, [0, 0, 0, 0], [shape[1], shape[0], shape[1], shape[0]])
        if (original.shape != (4,) or prompt.shape != (4,)
                or not np.allclose(original, parent.bbox, rtol=0, atol=.001)
                or not np.allclose(prompt, expected_prompt, rtol=0, atol=.001)):
            reasons.append("native_candidate_prompt_mismatch")
    except (TypeError, ValueError):
        reasons.append("native_candidate_prompt_mismatch")
    mask = candidate.get("mask")
    if (not isinstance(mask, np.ndarray) or mask.shape != shape or mask.dtype.kind not in "buif"
            or (mask.dtype.kind == "f" and not np.isfinite(mask).all())):
        reasons.append("invalid_native_mask")
        binary = None
    else:
        binary = mask >= .5 if mask.dtype.kind == "f" else mask > 0
        if not binary.any():
            reasons.append("empty_native_mask")
        if (record.get("metrics") or {}).get("foreground_pixels") != int(binary.sum()):
            reasons.append("native_mask_record_pixel_mismatch")
    return (binary if not reasons else None), sorted(set(reasons))


def _part_region(part, shape):
    """Rasterize one observed part ROI locally; outside-frame area is retained."""
    try:
        box = tuple(float(value) for value in part.bbox)
    except (TypeError, ValueError):
        return None
    if len(box) != 4 or not all(math.isfinite(value) for value in box):
        return None
    left, top, right, bottom = math.floor(box[0]), math.floor(box[1]), math.ceil(box[2]), math.ceil(box[3])
    if right <= left or bottom <= top:
        return None
    x1, y1, x2, y2 = max(0, left), max(0, top), min(shape[1], right), min(shape[0], bottom)
    if x2 <= x1 or y2 <= y1:
        return None
    if not part.mask:
        return (x1, y1, x2, y2), None, (right - left) * (bottom - top), "detector_rectangle_overlap_only"
    try:
        polygon = np.asarray(part.mask, dtype=float)
    except (TypeError, ValueError):
        return None
    if (polygon.ndim != 2 or polygon.shape[1] != 2 or len(polygon) < 3 or not np.isfinite(polygon).all()
            or np.any(polygon < (x1, y1)) or np.any(polygon >= (x2, y2))):
        return None
    pixels = np.zeros((y2 - y1, x2 - x1), np.uint8)
    cv2.fillPoly(pixels, [np.rint(polygon - (x1, y1)).astype(np.int32)], 1)
    denominator = int(pixels.sum())
    return ((x1, y1, x2, y2), pixels != 0, denominator, "detector_polygon_overlap_only") if denominator else None


def refine_instance_associations(
    candidates: Mapping, ownership: Mapping, parents: Sequence[ParentAnchor], parts: Sequence[PartDetection],
    associations: Sequence[PartAssociation], frame_shape, expected_frame_key,
    *, config: AssociationConfig | None = None, protected_parent_ids=(),
) -> tuple[tuple[PartAssociation, ...], dict]:
    """Supply measured instance support for unresolved canonical associations.

    Already assigned parts are retained. Reviewed parent IDs are protected from
    new assignments. Shared candidate pixels contribute to neither fish's score.
    Every refinement is rechecked against native ownership; invalid supporting
    masks are removed and association is recomputed before returning.
    """
    rules, mask_rules = config or AssociationConfig(), MaskOwnershipConfig()
    baseline = tuple(associations)
    shape = tuple(int(value) for value in frame_shape[:2])
    protected = set(protected_parent_ids)
    locked = {row.part: row for row in baseline if row.status == "ASSIGNED" and row.track_id is not None}
    occupied = {(row.track_id, row.part.region) for row in locked.values()}
    native, excluded = {}, {}
    for parent in parents:
        mask, reasons = _native_candidate(candidates.get(parent.track_id), ownership.get(parent.track_id), parent, shape, expected_frame_key)
        if parent.track_id in protected:
            reasons = sorted(set(reasons + ["independently_reviewed_parent_protected"]))
            mask = None
        if mask is None:
            excluded[parent.track_id] = reasons
        else:
            native[parent.track_id] = mask
    diagnostics = {
        "algorithm_version": "native_instance_association_v1",
        "applied": False, "ownership_validated": False, "anatomical_mask_validated": False,
        "mask_support_definition": "Exclusive native instance foreground intersecting the observed part ROI divided by that ROI's pixel area; shared pixels withheld.",
        "score_weights": {"part_inside_fraction": .48, "center_inside": .15, "center_proximity": .10,
                          "native_mask_support": .22, "detector_confidence": .05},
        "minimum_association_score": rules.minimum_association_score,
        "minimum_association_margin": rules.minimum_association_margin,
        "minimum_part_inside_fraction": rules.minimum_part_inside_fraction,
        "excluded_parent_masks": excluded, "protected_parent_ids": sorted(protected),
        "retained_existing_assignments": len(locked), "refinement_iterations": 0, "parts": [],
    }
    if not native:
        diagnostics["status"] = "no_reliable_native_instance_support"
        return baseline, diagnostics
    # All native masks, including a neighbor rejected for geometry, can expose
    # shared pixels. Such pixels cannot establish either candidate's ownership.
    coverage = np.zeros(shape, dtype=np.uint32)
    for candidate in candidates.values():
        other = candidate.get("mask") if isinstance(candidate, Mapping) else None
        if isinstance(other, np.ndarray) and other.shape == shape and other.dtype.kind in "buif":
            coverage += other >= .5 if other.dtype.kind == "f" else other > 0
    unique = coverage == 1
    exclusive = {identity: mask & unique for identity, mask in native.items()}
    regions = {part: _part_region(part, shape) for part in parts}
    active = set(native)
    final = baseline
    support_rows = {}
    for iteration in range(len(active) + 1):
        support_rows = {}

        def scorer(part, parent, settings):
            initial = score_part_parent(part.bbox, parent, settings, part.confidence)
            fixed = locked.get(part)
            if fixed is not None:
                if fixed.track_id != parent.track_id:
                    return replace(initial, eligible=False, failed_checks=("existing_part_assignment_retained",))
                return next((score for score in fixed.candidates if score.track_id == parent.track_id), initial)
            region = regions[part]
            if (parent.track_id not in active or region is None or parent.mask
                    or part.confidence < mask_rules.minimum_part_confidence):
                return initial
            (x1, y1, x2, y2), part_pixels, denominator, basis = region
            observed = exclusive[parent.track_id][y1:y2, x1:x2]
            intersection = int(np.count_nonzero(observed if part_pixels is None else observed & part_pixels))
            support = intersection / max(1, denominator)
            usable_support = support if support >= mask_rules.minimum_detected_part_coverage else 0.0
            score = min(1.0, max(0.0, initial.score - .22 * initial.mask_support + .22 * usable_support))
            failures = tuple(reason for reason in initial.failed_checks if reason != "association_score_below_threshold")
            if score < settings.minimum_association_score:
                failures += ("association_score_below_threshold",)
            support_rows.setdefault(part, {})[parent.track_id] = {
                "exclusive_intersection_pixels": intersection, "part_roi_pixels": denominator,
                "measured_mask_support": support, "applied_mask_support": usable_support,
                "minimum_detected_part_coverage": mask_rules.minimum_detected_part_coverage,
                "overlap_basis": basis, "score_before_mask_support": initial.score, "score_with_mask_support": score,
                "ownership_validated": False,
            }
            return replace(initial, score=score, mask_support=usable_support, eligible=not failures,
                           failed_checks=failures, mask_provided=True,
                           mask_provenance="mobilesam_native_exclusive_part_roi_fraction_unreviewed")

        proposed = associate_parts_to_parents(parts, parents, rules, candidate_scorer=scorer)
        # A newly introduced anatomical contradiction must not erase a prior
        # accepted part. The unresolved new part remains withheld by canonical
        # checks; preserving the old row cannot create a new duplicate region.
        proposed = tuple(
            locked[row.part] if row.part in locked else
            replace(row, status="UNASSIGNED", track_id=None, confidence=None,
                    reason="existing_region_assignment_retained")
            if row.status == "ASSIGNED" and (row.track_id in protected or (row.track_id, row.part.region) in occupied)
            else row
            for row in proposed
        )
        relied = {row.track_id for row in proposed if row.status == "ASSIGNED" and row.part not in locked
                  and row.track_id in active and row.candidates
                  and any(score.track_id == row.track_id and score.mask_support > 0 for score in row.candidates)}
        checked = validate_candidate_masks(candidates, parents, parts, associations=proposed,
                                           frame_shape=shape, expected_frame_key=expected_frame_key)
        invalid = set()
        for parent in parents:
            if parent.track_id not in relied:
                continue
            _, reasons = _native_candidate(candidates.get(parent.track_id), checked.get(parent.track_id), parent, shape, expected_frame_key)
            if reasons:
                invalid.add(parent.track_id)
                excluded[parent.track_id] = ["post_association_native_recheck_failed", *reasons]
        diagnostics["refinement_iterations"] = iteration + 1
        if not invalid:
            final = proposed
            break
        active -= invalid
    before = {row.part: row for row in baseline}
    for row in final:
        previous = before.get(row.part)
        changed = previous is not None and (previous.status, previous.track_id) != (row.status, row.track_id)
        diagnostics["parts"].append({
            "part": row.part.to_dict(), "status_before": previous.status if previous else None,
            "parent_id_before": previous.track_id if previous else None,
            "status_after": row.status, "parent_id_after": row.track_id, "changed": changed,
            "native_mask_support": support_rows.get(row.part, {}),
        })
    diagnostics.update(applied=any(row["changed"] for row in diagnostics["parts"]),
                       status="refined_with_native_instance_support", usable_parent_ids=sorted(active))
    return final, diagnostics
