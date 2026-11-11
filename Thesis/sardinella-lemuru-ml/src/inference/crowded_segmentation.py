"""Conservative MobileSAM retries from estimated crowded-scene evidence.

Point prompts guide the existing model; they never validate anatomical pixels.
Candidate selection reruns the unchanged native-mask ownership checks over the
whole frame. No candidate is cut, blended, relabeled or scored by headlessness.
"""
from __future__ import annotations

from collections.abc import Mapping

import cv2
import numpy as np

from src.inference.association import associate_parts_to_parents
from src.inference.mask_ownership import (
    MaskOwnershipConfig, head_integrity_mask_eligibility, validate_candidate_masks,
)


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)


def _native_mask(candidate, shape):
    value = _field(candidate, "mask")
    if (isinstance(value, np.ndarray) and value.ndim == 2 and value.shape == shape
            and (value.dtype == np.bool_ or
                 np.issubdtype(value.dtype, np.integer) and np.isin(value, (0, 1, 255)).all())):
        return np.asarray(value != 0)
    return None


def _shape(candidates, frame_shape):
    if frame_shape is not None:
        return tuple(frame_shape[:2])
    for candidate in candidates.values():
        mask = _field(candidate, "mask")
        if isinstance(mask, np.ndarray) and mask.ndim == 2:
            return mask.shape
    return None


def _bounds(box, shape):
    try:
        values = np.asarray(box, dtype=float)
    except (TypeError, ValueError):
        return None
    if values.shape != (4,) or not np.isfinite(values).all() or values[2] <= values[0] or values[3] <= values[1]:
        return None
    x1, y1, x2, y2 = values
    return (max(0, min(shape[1], int(np.floor(x1)))), max(0, min(shape[0], int(np.floor(y1)))),
            max(0, min(shape[1], int(np.ceil(x2)))), max(0, min(shape[0], int(np.ceil(y2)))))


def _paint_box(canvas, box, value):
    bounds = _bounds(box, canvas.shape)
    if bounds is not None:
        x1, y1, x2, y2 = bounds
        canvas[y1:y2, x1:x2] = value


def _interior_point(support):
    """Choose a pixel inside an eroded support, never a rectangle center."""
    eroded = cv2.erode(support.astype(np.uint8), np.ones((3, 3), np.uint8),
                       borderType=cv2.BORDER_CONSTANT, borderValue=0)
    if not eroded.any():
        return None
    distance = cv2.distanceTransform(eroded, cv2.DIST_L2, 5)
    y, x = np.unravel_index(int(np.argmax(distance)), distance.shape)
    return [int(x), int(y)]


def _overlap(first, second):
    return max(first[0], second[0]) < min(first[2], second[2]) and max(first[1], second[1]) < min(first[3], second[3])


def estimated_refinement_prompts(
    candidates, parents, parts=(), *, associations=None, frame_shape=None,
    ownership=None, config=None,
):
    """Plan estimated foreground/background seeds for crowded, withheld fish.

    Every point lies on native foreground and an eroded geometric support.
    An own-exclusive rectangle or uniquely assigned part ROI supports positive
    points; corresponding neighboring geometry supports negatives. These are
    inference hints, explicitly unreviewed and unsuitable as validated tissue.
    """
    rules = config or MaskOwnershipConfig()
    parents, parts = list(parents), list(parts)
    shape = _shape(candidates, frame_shape)
    if shape is None:
        return {}
    rows = list(associate_parts_to_parents(parts, parents) if associations is None else associations)
    assigned = []
    for row in rows:
        part = _field(row, "part")
        confidence = _field(part, "confidence", 0)
        if (_field(row, "status") == "ASSIGNED" and _field(part, "region") in {"Body", "Head", "Tail"}
                and isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
                and np.isfinite(confidence) and confidence >= rules.minimum_part_confidence):
            assigned.append((_field(row, "track_id"), part))
    plans = {}
    for parent in parents:
        identity = parent.track_id
        plan = {"status": "withheld", "point_coords": [], "point_labels": [], "point_evidence": [],
                "source": "estimated_native_mask_and_detector_geometry", "estimated": True,
                "ownership_validated": False, "measurement_validated": False,
                "anatomical_truth_inferred": False, "native_pixels_modified": False, "reasons": []}
        plans[identity] = plan
        neighbors = [item for item in parents if item.track_id != identity and _overlap(parent.bbox, item.bbox)]
        if not neighbors:
            plan.update(status="not_needed", reasons=["no_overlapping_parent_boxes"])
            continue
        if ownership is not None and head_integrity_mask_eligibility(ownership.get(identity))["eligible"]:
            plan.update(status="not_needed", reasons=["initial_candidate_already_eligible"])
            continue
        native = _native_mask(candidates.get(identity, {}), shape)
        if native is None or not native.any():
            plan["reasons"].append("initial_native_foreground_unavailable")
            continue
        own_box = np.zeros(shape, bool)
        _paint_box(own_box, parent.bbox, True)
        own_support = native & own_box
        exclusive = own_support.copy()
        for other in neighbors:
            _paint_box(exclusive, other.bbox, False)
        own_parts = [part for owner, part in assigned if owner == identity]
        foreign_parts = [(owner, part) for owner, part in assigned if owner != identity]

        def add(support, label, source, supporting_parent, region=None):
            if len(plan["point_coords"]) >= 16:
                return
            point = _interior_point(support)
            if point is None or point in plan["point_coords"]:
                return
            plan["point_coords"].append(point)
            plan["point_labels"].append(label)
            plan["point_evidence"].append({"point": point, "label": label, "source": source,
                "supporting_parent_id": supporting_parent, "region_roi": region,
                "estimated": True, "reviewed": False, "eroded_native_foreground_support": True})

        add(exclusive, 1, "own_exclusive_parent_foreground", identity)
        # Part boxes help place prompts, but are never promoted to pixel labels.
        for region in ("Body", "Head", "Tail"):
            regional = np.zeros(shape, bool)
            for part in own_parts:
                if _field(part, "region") == region:
                    _paint_box(regional, _field(part, "bbox"), True)
            regional &= own_support
            for _, part in foreign_parts:
                _paint_box(regional, _field(part, "bbox"), False)
            add(regional, 1, "uniquely_assigned_part_roi_foreground", identity, region)
        if not plan["point_coords"]:
            plan["reasons"].append("no_exclusive_or_uniquely_supported_positive_interior")
            continue
        for neighbor in neighbors:
            other_native = _native_mask(candidates.get(neighbor.track_id, {}), shape)
            if other_native is None:
                continue
            neighbor_box = np.zeros(shape, bool)
            _paint_box(neighbor_box, neighbor.bbox, True)
            other_support = other_native & neighbor_box
            exclusive_other = other_support.copy()
            _paint_box(exclusive_other, parent.bbox, False)
            for part in own_parts:
                _paint_box(exclusive_other, _field(part, "bbox"), False)
            add(exclusive_other, 0, "neighbor_exclusive_parent_foreground", neighbor.track_id)
            regional = np.zeros(shape, bool)
            for owner, part in foreign_parts:
                if owner == neighbor.track_id:
                    _paint_box(regional, _field(part, "bbox"), True)
            regional &= other_support
            for part in own_parts:
                _paint_box(regional, _field(part, "bbox"), False)
            # An own-exclusive foreground area cannot simultaneously be negative.
            regional &= ~exclusive
            add(regional, 0, "uniquely_assigned_neighbor_part_roi_foreground", neighbor.track_id)
        if 0 not in plan["point_labels"]:
            plan.update(point_coords=[], point_labels=[], point_evidence=[])
            plan["reasons"].append("no_independent_neighbor_negative_interior")
            continue
        plan.update(status="planned", reasons=["crowded_candidate_requires_fresh_model_inference"])
    return plans


def select_refined_candidates(
    initial_candidates, proposed_candidates, parents, parts=(), *, associations=None,
    frame_shape=None, expected_frame_key=None, config=None,
):
    """Select whole native masks using existing ownership gates, never anatomy.

    A simultaneous proposal can resolve mutual overlap conflicts. Individual
    fallbacks are also considered. Already eligible candidates are frozen, and
    no candidate batch may make any previously eligible fish ineligible.
    """
    parents, parts = list(parents), list(parts)
    options = dict(associations=associations, frame_shape=frame_shape,
                   expected_frame_key=expected_frame_key, config=config)

    def evaluate(batch):
        checked = validate_candidate_masks(batch, parents, parts, **options)
        eligible = {identity for identity, row in checked.items() if head_integrity_mask_eligibility(row)["eligible"]}
        geometric_failures = sum(not row.get("mask_geometry_checks_passed", False) for row in checked.values())
        blocking = sum(len(head_integrity_mask_eligibility(row)["blocking_reasons"]) for row in checked.values())
        return checked, eligible, (len(eligible), -geometric_failures, -blocking)

    selected = dict(initial_candidates)
    checked, protected, ranking = evaluate(selected)
    attempts = []
    proposed = {identity: value for identity, value in proposed_candidates.items()
                if identity in selected and identity not in protected}
    batches = [("joint_refinement", {**selected, **proposed})] if proposed else []
    batches.extend((f"individual_refinement_{identity}", {**selected, identity: candidate})
                   for identity, candidate in proposed.items())
    selected_variant = "initial"
    for name, batch in batches:
        candidate_checks, eligible, candidate_rank = evaluate(batch)
        preserves = protected.issubset(eligible)
        accept = preserves and candidate_rank > ranking
        attempts.append({"variant": name, "eligible_parent_ids": sorted(eligible),
                         "preserves_initial_eligible_fish": preserves, "selected_at_evaluation": accept,
                         "rank": list(candidate_rank)})
        if accept:
            selected, checked, ranking, selected_variant = batch, candidate_checks, candidate_rank, name
    return selected, checked, {
        "selected_variant": selected_variant, "attempts": attempts,
        "protected_initial_eligible_parent_ids": sorted(protected),
        "selected_eligible_parent_ids": sorted(identity for identity, row in checked.items()
            if head_integrity_mask_eligibility(row)["eligible"]),
        "replaced_parent_ids": sorted(identity for identity, value in selected.items()
            if value is not initial_candidates.get(identity)),
        "selection_basis": "unchanged_native_mask_ownership_checks",
        "headless_geometry_used_for_selection": False, "native_pixels_modified": False,
        "ownership_validated": False,
    }
