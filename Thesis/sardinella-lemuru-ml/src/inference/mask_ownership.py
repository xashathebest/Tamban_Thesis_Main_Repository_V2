"""Conservative engineering checks for experimental native-frame fish masks.

Successful model inference, a high mask score, and box containment are not
ownership validation. These checks never approve masks for grading. Shadow
part proposals are diagnostic and do not replace the canonical association.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Mapping, Sequence

import cv2
import numpy as np

from src.inference.association import (
    AssociationConfig, ParentAnchor, associate_parts_to_parents, score_part_parent,
)


@dataclass(frozen=True)
class MaskOwnershipConfig:
    """Engineering rejection gates, not calibrated anatomical thresholds."""
    minimum_mask_pixels: int = 128
    minimum_parent_mask_fraction: float = .80
    minimum_box_occupancy: float = .05
    maximum_secondary_component_fraction: float = .02
    maximum_hole_fraction: float = .03
    minimum_axis_ratio: float = 2.0
    maximum_neighbor_exclusive_fraction: float = .05
    maximum_pair_overlap_fraction: float = .10
    minimum_detected_part_coverage: float = .05
    maximum_neighbor_part_coverage: float = .50
    minimum_part_confidence: float = .25
    minimum_shadow_part_coverage: float = .10
    minimum_shadow_mask_margin: float = .15

    def __post_init__(self):
        if not isinstance(self.minimum_mask_pixels, int) or isinstance(self.minimum_mask_pixels, bool) or self.minimum_mask_pixels < 1:
            raise ValueError("minimum_mask_pixels must be a positive integer")
        for name, value in asdict(self).items():
            if name in ("minimum_mask_pixels", "minimum_axis_ratio"):
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be finite and in [0, 1]")
        if not math.isfinite(self.minimum_axis_ratio) or self.minimum_axis_ratio <= 1:
            raise ValueError("minimum_axis_ratio must exceed one")


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)


def _confidence(part):
    value = _field(part, "confidence", 0)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1 else 0.0


def _recorded_provenance(value):
    return bool(value.strip()) if isinstance(value, str) else isinstance(value, (Mapping, list)) and bool(value)


def _box(value):
    try:
        if len(value) != 4 or any(isinstance(item, bool) for item in value):
            return None
        values = tuple(float(item) for item in value)
        return values if all(map(math.isfinite, values)) and values[2] > values[0] and values[3] > values[1] else None
    except (TypeError, ValueError, OverflowError):
        return None


def _bounds(box, shape):
    height, width = shape
    return (max(0, min(width, int(math.floor(box[0])))), max(0, min(height, int(math.floor(box[1])))),
            max(0, min(width, int(math.ceil(box[2])))), max(0, min(height, int(math.ceil(box[3])))))


def _count(mask, box):
    x1, y1, x2, y2 = _bounds(box, mask.shape)
    return int(np.count_nonzero(mask[y1:y2, x1:x2]))


def _box_pixels(box, shape):
    x1, y1, x2, y2 = _bounds(box, shape)
    return (x2 - x1) * (y2 - y1)


def _candidate_mask(candidate, shape):
    mask = _field(candidate, "mask")
    if not isinstance(mask, np.ndarray) or mask.ndim != 2 or tuple(mask.shape) != tuple(shape):
        return None
    if mask.dtype == np.bool_:
        return mask
    if np.issubdtype(mask.dtype, np.integer) and np.isin(mask, (0, 1, 255)).all():
        return mask != 0
    return None


def _part_coverage(mask, part):
    box = _box(_field(part, "bbox"))
    pixels = _box_pixels(box, mask.shape) if box else 0
    return _count(mask, box) / pixels if pixels else 0.0


def _association_rows(parts, parents, associations):
    return tuple(associate_parts_to_parents(parts, parents) if associations is None else associations)


def validate_candidate_masks(
    candidates: Mapping, parents: Sequence[ParentAnchor], parts=(), *, associations=None,
    frame_shape=None, expected_frame_key=None, config: MaskOwnershipConfig | None = None,
) -> dict[int, dict]:
    """Evaluate a whole batch so two prompts cannot silently claim one fish.

    ``mask`` inputs are binary full-original-frame arrays. No component is
    removed or reassigned. Ordinary part boxes provide consistency evidence
    only; they are never promoted to validated anatomical pixel labels.
    """
    rules = config or MaskOwnershipConfig()
    ids = [parent.track_id for parent in parents]
    if len(set(ids)) != len(ids) or any(not isinstance(value, (int, np.integer)) or isinstance(value, bool) for value in ids):
        raise ValueError("Parent Fish IDs must be unique integers within a frame")
    if not parents:
        return {}
    shape = tuple(frame_shape[:2]) if frame_shape is not None else None
    if shape is None:
        sample = next((_field(item, "mask") for item in candidates.values()
                       if isinstance(_field(item, "mask"), np.ndarray)), None)
        shape = sample.shape if sample is not None else None
    if shape is None or len(shape) != 2 or any(not isinstance(v, (int, np.integer)) or isinstance(v, bool) or v <= 0 for v in shape):
        raise ValueError("Mask ownership requires a positive native frame shape")
    rows = _association_rows(parts, parents, associations)
    results, masks, geometry_reasons = {}, {}, {}
    for parent in parents:
        candidate = candidates.get(parent.track_id, {})
        score = _field(candidate, "score")
        score = float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score) else None
        result = {"parent_id": parent.track_id, "status": "unavailable", "reasons": [], "metrics": {},
                  "engineering_checks_passed": False, "mask_geometry_checks_passed": False,
                  "ownership_validated": False, "approved_for_grading": False,
                  "measurement_validated": False, "mask_validated_for_cracks": False,
                  "coordinate_space": "original_frame", "frame_shape": list(shape),
                  "model_mask_score": score, "score_interpretation": "Model-predicted mask quality; not fish ownership probability",
                  "conflicting_parent_ids": [], "required_parts": ["Body", "Head"],
                  "body_support": {"source": "unavailable", "validated": False,
                                   "reason": "No explicitly validated Body pixel support was supplied."},
                  "checks_configuration": asdict(rules),
                  "validation_status": "Not validated against expert ownership labels"}
        results[parent.track_id] = result
        geometry_reasons[parent.track_id] = []
        if _field(candidate, "status") == "unavailable" or _field(candidate, "available") is False:
            result["reasons"].append("candidate_unavailable")
            result["backend_reason"] = str(_field(candidate, "reason", "Candidate mask unavailable"))
            continue
        mask = _candidate_mask(candidate, shape)
        box = _box(parent.bbox)
        if mask is None or box is None:
            result["reasons"].append("invalid_native_mask_or_parent_box")
            continue
        area = int(np.count_nonzero(mask))
        result["metrics"]["foreground_pixels"] = area
        if area == 0:
            result["reasons"].append("empty_mask")
            continue
        masks[parent.track_id] = mask
        fail = geometry_reasons[parent.track_id]
        candidate_owner = _field(candidate, "parent_id")
        if candidate_owner is not None and (isinstance(candidate_owner, bool) or candidate_owner != parent.track_id):
            fail.append("candidate_parent_identity_mismatch")
        prompt_box = _field(candidate, "bbox_global")
        if prompt_box is not None and (_box(prompt_box) is None or not np.allclose(_box(prompt_box), box, rtol=0, atol=.001)):
            fail.append("candidate_prompt_box_mismatch")
        if expected_frame_key is not None:
            provenance = _field(candidate, "provenance", {})
            recorded_frame_key = provenance.get("frame_key") if isinstance(provenance, Mapping) else None
            if recorded_frame_key != expected_frame_key:
                fail.append("candidate_frame_identity_mismatch")
        if area < rules.minimum_mask_pixels:
            fail.append("insufficient_foreground_pixels")
        inside = _count(mask, box)
        fraction = inside / area
        occupancy = inside / max(1, _box_pixels(box, shape))
        result["metrics"].update(mask_inside_intended_box_fraction=fraction, intended_box_occupancy=occupancy)
        if fraction < rules.minimum_parent_mask_fraction:
            fail.append("foreground_extends_beyond_intended_parent")
        if occupancy < rules.minimum_box_occupancy:
            fail.append("insufficient_visible_parent_support")
        x, y, width, height = cv2.boundingRect(mask.view(np.uint8))
        local = mask[y:y + height, x:x + width].view(np.uint8)
        components, _, stats, _ = cv2.connectedComponentsWithStats(local, 8)
        areas = sorted((int(v) for v in stats[1:, cv2.CC_STAT_AREA]), reverse=True)
        secondary = (sum(areas[1:]) / area) if areas else 1.0
        result["metrics"].update(component_count=components - 1, secondary_component_fraction=secondary,
                                  foreground_bbox=[x, y, x + width, y + height])
        if secondary > rules.maximum_secondary_component_fraction:
            fail.append("fragmented_or_merged_foreground_components")
        filled = np.pad(local, 1).copy()
        cv2.floodFill(filled, None, (0, 0), 1)
        holes = int(np.count_nonzero(filled == 0))
        result["metrics"]["hole_fraction"] = holes / max(1, area + holes)
        if result["metrics"]["hole_fraction"] > rules.maximum_hole_fraction:
            fail.append("implausible_silhouette_holes")
        moments = cv2.moments(local, binaryImage=True)
        covariance = np.array([[moments["mu20"], moments["mu11"]], [moments["mu11"], moments["mu02"]]]) / max(1, moments["m00"])
        values = np.linalg.eigvalsh(covariance)
        ratio = math.sqrt(max(0.0, values[1]) / max(1e-9, values[0]))
        result["metrics"]["principal_axis_ratio"] = ratio
        if ratio < rules.minimum_axis_ratio:
            fail.append("implausible_or_orientation_uncertain_silhouette")
        if mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any():
            fail.append("mask_touches_frame_boundary")
        if box[0] <= 0 or box[1] <= 0 or box[2] >= shape[1] or box[3] >= shape[0]:
            fail.append("parent_touches_frame_boundary")
        for neighbor in parents:
            if neighbor.track_id == parent.track_id:
                continue
            other_box = _box(neighbor.bbox)
            if other_box is None:
                continue
            other_inside = _count(mask, other_box)
            intersection = (max(box[0], other_box[0]), max(box[1], other_box[1]),
                            min(box[2], other_box[2]), min(box[3], other_box[3]))
            shared_box_count = _count(mask, intersection) if intersection[2] > intersection[0] and intersection[3] > intersection[1] else 0
            exclusive = max(0, other_inside - shared_box_count) / area
            if exclusive > rules.maximum_neighbor_exclusive_fraction:
                fail.append("foreground_in_neighbor_exclusive_region")
                result["conflicting_parent_ids"].append(neighbor.track_id)
        own = [row for row in rows if _field(row, "status") == "ASSIGNED" and _field(row, "track_id") == parent.track_id
               and _confidence(_field(row, "part")) >= rules.minimum_part_confidence]
        coverage = {}
        for row in own:
            part = _field(row, "part")
            region = _field(part, "region")
            coverage[region] = max(coverage.get(region, 0.0), _part_coverage(mask, part))
        result["metrics"]["detected_part_box_coverage"] = coverage
        result["part_support_interpretation"] = "Detector-ROI consistency only; bounding-box pixels do not establish anatomical ownership"
        for region in ("Body", "Head"):
            if region not in coverage:
                result["reasons"].append(f"required_{region.lower()}_evidence_unavailable")
            elif coverage[region] < rules.minimum_detected_part_coverage:
                result["reasons"].append(f"candidate_omits_detected_{region.lower()}_region")
        for row in rows:
            if _field(row, "status") == "AMBIGUOUS":
                contenders = _field(row, "ambiguous_track_ids", ()) or tuple(_field(c, "track_id") for c in _field(row, "candidates", ()))
                if parent.track_id in contenders and _field(_field(row, "part"), "region") in ("Head", "Body"):
                    result["reasons"].append("required_anatomical_ownership_ambiguous")
            if _field(row, "status") == "ASSIGNED" and _field(row, "track_id") not in (None, parent.track_id):
                part = _field(row, "part")
                if _field(part, "region") in ("Head", "Body") and _part_coverage(mask, part) >= rules.maximum_neighbor_part_coverage:
                    result["reasons"].append("candidate_contains_neighbor_anatomical_evidence")
                    geometry_reasons[parent.track_id].append("candidate_contains_neighbor_anatomical_evidence")
                    result["conflicting_parent_ids"].append(_field(row, "track_id"))
        result["reasons"].extend(fail)
    for index, first in enumerate(parents):
        for second in parents[index + 1:]:
            a, b = masks.get(first.track_id), masks.get(second.track_id)
            if a is None or b is None:
                continue
            area = int(np.count_nonzero(a & b))
            fraction = area / max(1, min(results[first.track_id]["metrics"]["foreground_pixels"], results[second.track_id]["metrics"]["foreground_pixels"]))
            for owner, other in ((first, second), (second, first)):
                results[owner.track_id]["metrics"].setdefault("pair_overlap_fraction", {})[str(other.track_id)] = fraction
                if fraction > rules.maximum_pair_overlap_fraction:
                    results[owner.track_id]["reasons"].append("overlapping_mask_ownership_conflict")
                    geometry_reasons[owner.track_id].append("overlapping_mask_ownership_conflict")
                    results[owner.track_id]["conflicting_parent_ids"].append(other.track_id)
    for owner, result in results.items():
        result["reasons"] = sorted(set(result["reasons"]))
        result["conflicting_parent_ids"] = sorted(set(result["conflicting_parent_ids"]))
        if owner not in masks:
            continue
        result["mask_geometry_checks_passed"] = not geometry_reasons[owner]
        result["engineering_checks_passed"] = not result["reasons"]
        result["status"] = ("checks_passed_unvalidated" if result["engineering_checks_passed"] else
                            "rejected" if geometry_reasons[owner] else "ambiguous")
    return results


def _trusted_part_mask(evidence, parent_id, shape):
    if (not isinstance(evidence, Mapping) or evidence.get("parent_track_id") != parent_id
            or evidence.get("ownership_validated") is not True or evidence.get("mask_validated") is not True
            or evidence.get("coordinate_space") != "original_frame" or not _recorded_provenance(evidence.get("validation_provenance"))):
        return None
    mask = evidence.get("mask")
    if isinstance(mask, np.ndarray) and mask.dtype == np.bool_ and mask.shape == shape:
        return mask
    polygon = evidence.get("polygon")
    try:
        vertices = np.asarray(polygon, dtype=float)
        if vertices.ndim == 2 and vertices.shape[0] >= 3 and vertices.shape[1] == 2 and np.isfinite(vertices).all():
            if (vertices[:, 0] < 0).any() or (vertices[:, 0] >= shape[1]).any() or (vertices[:, 1] < 0).any() or (vertices[:, 1] >= shape[0]).any():
                return None
            mask = np.zeros(shape, np.uint8)
            cv2.fillPoly(mask, [np.rint(vertices).astype(np.int32)], 1)
            return mask.astype(bool)
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def trusted_prompt_points(parent_id, trusted_parts, frame_shape, *, maximum_positive=2, maximum_negative=2):
    """Only explicit reviewed anatomical pixels can become point prompts."""
    shape = tuple(frame_shape[:2])
    points, labels, provenance = [], [], []
    reviewed = []
    for evidence in trusted_parts:
        owner = _field(evidence, "parent_track_id")
        if _field(evidence, "orientation_reliable") is not True:
            continue
        mask = _trusted_part_mask(evidence, owner, shape)
        if mask is not None and mask.any():
            reviewed.append((owner, evidence, mask))
    for positive in (True, False):
        maximum = maximum_positive if positive else maximum_negative
        accepted = 0
        for owner, evidence, mask in reviewed:
            if accepted >= maximum:
                break
            if (owner == parent_id) != positive:
                continue
            exclusive = mask.copy()
            for other_owner, _, other_mask in reviewed:
                if other_owner != owner:
                    exclusive &= ~other_mask
            if not exclusive.any():
                continue
            padded = np.pad(exclusive.astype(np.uint8), 1)
            distance = cv2.distanceTransform(padded, cv2.DIST_L2, 5)[1:-1, 1:-1]
            y, x = np.unravel_index(int(np.argmax(distance)), shape)
            if [int(x), int(y)] in points:
                continue
            points.append([int(x), int(y)])
            labels.append(1 if positive else 0)
            provenance.append({"parent_id": owner, "region": _field(evidence, "region"),
                               "source": "reviewed_anatomical_pixel_support", "validation_provenance": evidence["validation_provenance"]})
            accepted += 1
    return {"point_coords": points, "point_labels": labels, "provenance": provenance,
            "status": "reviewed_pixels_only" if points else "unavailable_no_validated_anatomical_points",
            "coordinate_space": "original_frame", "invented_from_boxes": False}


def body_support_mask(parent_id, candidate, ownership, trusted_parts, frame_shape):
    """Return reviewed Body pixels only; never turn a Body box into anatomy."""
    shape = tuple(frame_shape[:2])
    unavailable = {"source": "unavailable", "validated": False,
                   "reason": "No independently reviewed Body pixel support for this parent."}
    mask = _candidate_mask(candidate, shape)
    if mask is None or not ownership.get("engineering_checks_passed"):
        return None, {**unavailable, "reason": "Candidate fish ownership checks did not pass."}
    for evidence in trusted_parts:
        if _field(evidence, "region") != "Body":
            continue
        body = _trusted_part_mask(evidence, parent_id, shape)
        if body is None or not body.any():
            continue
        retained = body & mask
        fraction = int(retained.sum()) / int(body.sum())
        if fraction < .95:
            return None, {**unavailable, "reason": "Candidate omits reviewed Body pixels.", "retained_fraction": fraction}
        retained.flags.writeable = False
        return retained, {"source": "reviewed_body_mask_intersection", "validated": True,
                          "coordinate_space": "original_frame", "retained_fraction": fraction,
                          "validation_provenance": evidence["validation_provenance"],
                          "scope": "Reviewed Body pixels retained by candidate; does not validate the entire fish mask."}
    return None, unavailable


def shadow_mask_associations(candidates, ownership, parents, parts, *, config=None):
    """Propose ownership from native pixels without changing real associations."""
    rules, association_rules = config or MaskOwnershipConfig(), AssociationConfig()
    proposed = []
    for index, part in enumerate(parts):
        support = []
        for parent in parents:
            result = ownership.get(parent.track_id, {})
            if not result.get("mask_geometry_checks_passed"):
                continue
            shape = tuple(result["frame_shape"])
            mask = _candidate_mask(candidates.get(parent.track_id, {}), shape)
            if mask is None:
                continue
            geometry = score_part_parent(part.bbox, parent, association_rules, part.confidence)
            if (geometry.part_inside_fraction < association_rules.minimum_part_inside_fraction or not geometry.center_inside
                    or geometry.score < association_rules.minimum_association_score or _confidence(part) < rules.minimum_part_confidence):
                continue
            fraction = _part_coverage(mask, part)
            if fraction >= rules.minimum_shadow_part_coverage:
                support.append((fraction, parent.track_id))
        support.sort(key=lambda row: (-row[0], row[1]))
        row = {"part_index": index, "region": part.region, "raw_confidence": part.confidence,
               "status": "UNASSIGNED", "proposed_track_id": None,
               "supports": [{"parent_id": owner, "mask_box_coverage": fraction} for fraction, owner in support],
               "applied_to_grading": False, "ownership_validated": False}
        if support:
            margin = support[0][0] - support[1][0] if len(support) > 1 else support[0][0]
            row["mask_support_margin"] = margin
            if len(support) > 1 and margin < rules.minimum_shadow_mask_margin:
                row.update(status="AMBIGUOUS", reason="competing_candidate_mask_support")
            else:
                row.update(status="PROPOSED", proposed_track_id=support[0][1], reason="experimental_native_pixel_support_only")
        proposed.append(row)
    groups = {}
    for row in proposed:
        if row["status"] == "PROPOSED":
            groups.setdefault((row["proposed_track_id"], row["region"]), []).append(row)
    for rows in groups.values():
        rows.sort(key=lambda row: (-row["raw_confidence"], -row["supports"][0]["mask_box_coverage"], row["part_index"]))
        for duplicate in rows[1:]:
            duplicate.update(status="UNASSIGNED", proposed_track_id=None, reason="duplicate_region_for_parent")
    summaries = {}
    for parent in parents:
        regions = {row["region"] for row in proposed if row["status"] == "PROPOSED" and row["proposed_track_id"] == parent.track_id}
        required = {"Head", "Body"}.issubset(regions)
        summaries[parent.track_id] = {"required_regions_available": required, "optional_tail_available": "Tail" in regions,
                                     "evidence_status": "CANDIDATE_EVIDENCE_ONLY" if required else "Ungraded",
                                     "effective_weights_if_validated": ({"Body": .5, "Head": .3, "Tail": .2} if "Tail" in regions else {"Body": .625, "Head": .375}) if required else {},
                                     "applied_to_grading": False}
    return {"mode": "experimental_shadow_only", "parts": proposed, "parents": summaries,
            "applied_to_grading": False, "ownership_validated": False,
            "note": "Candidate mask support is not expert ownership validation; active grades and confidence are unchanged."}
