"""Bounding-box body-width diagnostics, calibration, and legacy Body replay.

No biological thresholds are supplied. Geometry tolerances only decide whether
an axis-aligned bounding-box proxy is usable; they do not diagnose abnormality.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from src.inference.part_types import PartDetection


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _box(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    values = tuple(_number(item) for item in value)
    if any(item is None for item in values):
        return None
    x1, y1, x2, y2 = values
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _intersection(first: Sequence[float], second: Sequence[float]) -> float:
    return max(0.0, min(first[2], second[2]) - max(first[0], second[0])) * max(
        0.0, min(first[3], second[3]) - max(first[1], second[1])
    )


def boxes_overlap(first: object, second: object) -> bool:
    """Flag any positive box intersection, including conservative false alarms."""
    first_box, second_box = _box(first), _box(second)
    return bool(first_box and second_box and _intersection(first_box, second_box) > 0)


@dataclass(frozen=True)
class BodyWidthConfig:
    """Explicit calibration provenance and bounded, default-off contribution."""

    scoring_enabled: bool = False
    calibration_validated: bool = False
    calibration_id: str | None = None
    validation_sample_count: int = 0
    normal_reference_min: float | None = None
    normal_reference_max: float | None = None
    extreme_reference: float | None = None
    scoring_method: str = "post_weighted_v2"
    maximum_geometric_contribution: float = 0.10
    maximum_body_score_shift: float = 0.10
    minimum_class_c_evidence: float = 0.25
    geometry_max_axis_deviation_degrees: float = 15.0
    geometry_min_elongation: float = 4.0
    minimum_detection_confidence: float = 0.25
    minimum_part_inside_fraction: float = 0.95

    def __post_init__(self) -> None:
        for name in ("scoring_enabled", "calibration_validated"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean.")
        if not isinstance(self.scoring_method, str) or self.scoring_method not in {"post_weighted_v2", "body_component_v1"}:
            raise ValueError("scoring_method must be post_weighted_v2 or body_component_v1.")
        if isinstance(self.validation_sample_count, bool) or not isinstance(self.validation_sample_count, int) or self.validation_sample_count < 0:
            raise ValueError("validation_sample_count must be a non-negative integer.")
        if self.calibration_id is not None and (not isinstance(self.calibration_id, str) or not self.calibration_id.strip()):
            raise ValueError("calibration_id must be null or a nonempty provenance identifier.")
        for name in ("minimum_class_c_evidence", "minimum_detection_confidence", "minimum_part_inside_fraction"):
            number = _number(getattr(self, name))
            if number is None or not 0 < number <= 1:
                raise ValueError(f"{name} must be positive and at most 1.")
            object.__setattr__(self, name, number)
        shift = _number(self.maximum_body_score_shift)
        if shift is None or not 0 <= shift <= 0.10:
            raise ValueError("maximum_body_score_shift must be between 0 and the hard cap of 0.10.")
        object.__setattr__(self, "maximum_body_score_shift", shift)
        contribution = _number(self.maximum_geometric_contribution)
        if contribution is None or not 0 <= contribution <= 0.10:
            raise ValueError("maximum_geometric_contribution must be between 0 and the hard cap of 0.10.")
        object.__setattr__(self, "maximum_geometric_contribution", contribution)
        angle = _number(self.geometry_max_axis_deviation_degrees)
        elongation = _number(self.geometry_min_elongation)
        if angle is None or not 0 < angle <= 15:
            raise ValueError("geometry_max_axis_deviation_degrees must be positive and at most 15.")
        if elongation is None or elongation < 1 / math.tan(math.radians(angle)):
            raise ValueError("geometry_min_elongation must conservatively bound the configured axis angle.")
        object.__setattr__(self, "geometry_max_axis_deviation_degrees", angle)
        object.__setattr__(self, "geometry_min_elongation", elongation)
        thresholds = (self.normal_reference_min, self.normal_reference_max, self.extreme_reference)
        if any(value is not None for value in thresholds):
            numbers = tuple(_number(value) for value in thresholds)
            if any(value is None for value in numbers) or not 0 <= numbers[0] <= numbers[1] < numbers[2] <= 1:
                raise ValueError("Calibration requires 0 <= normal min <= normal max < extreme <= 1.")
            for name, value in zip(("normal_reference_min", "normal_reference_max", "extreme_reference"), numbers):
                object.__setattr__(self, name, value)
        if self.calibration_validated and (any(value is None for value in thresholds) or not self.calibration_id or self.validation_sample_count < 1):
            raise ValueError("Validated calibration requires thresholds, provenance and reviewed labeled measurements.")

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "BodyWidthConfig":
        if not isinstance(values, Mapping):
            raise ValueError("Body-width configuration must be a mapping.")
        unknown = set(values) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"Unknown body-width configuration key(s): {', '.join(sorted(unknown))}.")
        return cls(**dict(values))

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def load_body_width_config(path: str | Path | None = None) -> BodyWidthConfig:
    import yaml

    location = Path(path) if path is not None else Path(__file__).resolve().parents[2] / "configs" / "body_width.yaml"
    if not location.exists():
        return BodyWidthConfig()
    with location.open(encoding="utf-8") as source:
        values = yaml.safe_load(source)
    return BodyWidthConfig.from_mapping(values or {})


def analyze_body_width(
    whole_bbox: object,
    parts: Iterable[PartDetection],
    *,
    config: BodyWidthConfig | None = None,
    detection_confidence: float | None = None,
    parent_usable: bool = True,
    association_reliable: bool = True,
    association_status: str | None = None,
    frame_shape: Sequence[int] | None = None,
    clipped: bool = False,
    overlapping: bool = False,
    minimum_part_confidence: float = 0.25,
) -> dict[str, object]:
    """Reuse original boxes, requiring one shared coordinate space for all boxes.

    Raw dimensions and their initial ratio remain visible when geometry is
    uncertain. Head/Tail centers or strong elongation validate a near-axis
    proxy for scoring. Diagonal evidence is never rectified into fabricated
    anatomical measurements, and reliability is independent of calibration.
    """
    rules = config or BodyWidthConfig()
    parts = tuple(parts)
    whole = _box(whole_bbox)
    candidates = [part for part in parts if part.region == "Body" and _box(part.bbox) is not None]
    selected = max(candidates, key=lambda part: part.confidence, default=None)
    body = _box(selected.bbox) if selected is not None else None
    whole_width, whole_height = (whole[2] - whole[0], whole[3] - whole[1]) if whole else (None, None)
    body_width, body_height = (body[2] - body[0], body[3] - body[1]) if body else (None, None)
    result: dict[str, object] = {
        "algorithm_version": "relative_body_width_bbox_v2",
        "status": "unavailable", "whole_fish_bbox": list(whole) if whole else None,
        "measurement_status": "Missing Detection", "measurement_available": False,
        "calibration_status": "Calibrated" if rules.calibration_validated else "Not Calibrated",
        "reliable_for_scoring": False,
        "whole_fish_width_px": whole_width, "whole_fish_height_px": whole_height,
        "body_bbox": list(body) if body else None, "body_width_px": body_width, "body_height_px": body_height,
        "relative_width_proxy": None, "initial_relative_width_proxy": None,
        "measurement_method": "axis_aligned_bounding_box_proxy", "orientation": "unknown",
        "reliability": "Unavailable", "reliability_reasons": [],
        "normal_reference_range": [rules.normal_reference_min, rules.normal_reference_max] if rules.calibration_validated else None,
        "width_abnormality": "Unavailable", "class_c_supporting_points": None,
        "score_status": "Not calibrated" if not rules.calibration_validated else "Unavailable",
        "scoring_enabled": rules.scoring_enabled, "score_contributed": False, "applied_body_score_shift": 0.0,
        "contribution_reason": "not_calibrated" if not rules.calibration_validated else "measurement_unavailable",
        "threshold_configuration": rules.to_dict(), "calibration_id": rules.calibration_id,
        "note": "Bounding-box proxy, not anatomical width or body weight. Orientation and ownership limitations apply.",
    }
    reasons: list[str] = []
    if not whole:
        reasons.append("whole_fish_geometry_unavailable")
    if not body or selected is None:
        reasons.append("body_evidence_unavailable")
    elif _number(selected.confidence) is None or selected.confidence < minimum_part_confidence:
        reasons.append("body_evidence_low_confidence")
    if body and selected is not None:
        # Multiple grade hypotheses over one spatial region are normal. Two
        # spatially separate confident Body regions cannot justify one width.
        selected_area = (body[2] - body[0]) * (body[3] - body[1])
        for candidate in candidates:
            if candidate is selected or candidate.confidence < minimum_part_confidence:
                continue
            candidate_area = (candidate.bbox[2] - candidate.bbox[0]) * (candidate.bbox[3] - candidate.bbox[1])
            if _intersection(body, candidate.bbox) < .50 * min(selected_area, candidate_area):
                reasons.append("ambiguous_body_geometry")
                break
    if not parent_usable:
        reasons.append("parent_evidence_unreliable")
    if detection_confidence is not None and (_number(detection_confidence) is None or detection_confidence < rules.minimum_detection_confidence):
        reasons.append("parent_evidence_low_confidence")
    if not association_reliable or str(association_status or "").lower() in {"ambiguous", "association_ambiguous", "unassigned", "unreliable"}:
        reasons.append("association_unreliable")
    if overlapping:
        reasons.append("overlapping_fish")
    if whole and frame_shape is not None and len(frame_shape) >= 2:
        clipped = clipped or whole[0] <= 0 or whole[1] <= 0 or whole[2] >= frame_shape[1] or whole[3] >= frame_shape[0]
    if clipped:
        reasons.append("clipped_fish")
    if whole and body:
        if _intersection(whole, body) / (body_width * body_height) < rules.minimum_part_inside_fraction:
            reasons.append("body_outside_parent")
        if min(body_width, body_height) >= max(whole_width, whole_height):
            reasons.append("body_geometry_inconsistent")
        parts_by_region: dict[str, PartDetection] = {}
        for part in parts:
            if part.region in {"Head", "Tail"} and _box(part.bbox) and part.confidence >= minimum_part_confidence:
                prior = parts_by_region.get(part.region)
                if prior is None or part.confidence > prior.confidence:
                    parts_by_region[part.region] = part
        if "Head" in parts_by_region and "Tail" in parts_by_region:
            head, tail = parts_by_region["Head"], parts_by_region["Tail"]
            dx, dy = abs(head.center[0] - tail.center[0]), abs(head.center[1] - tail.center[1])
            angle = math.degrees(math.atan2(dy, dx)) if dx or dy else 45.0
            axis_deviation = min(angle, 90.0 - angle)
            orientation = "horizontal" if angle <= 45 else "vertical"
            if axis_deviation > rules.geometry_max_axis_deviation_degrees:
                orientation = "diagonal"
                reasons.append("diagonal_orientation")
            elif (whole_width >= whole_height) != (orientation == "horizontal"):
                reasons.append("orientation_geometry_conflict")
            result["measurement_method"] = "axis_aligned_bounding_box_proxy_head_tail_checked"
            result["axis_deviation_degrees"] = axis_deviation
            # Parts must remain inside the same parent, and Body should lie
            # between the Head/Tail centers along the asserted longitudinal axis.
            if any(_intersection(whole, part.bbox) / ((part.bbox[2] - part.bbox[0]) * (part.bbox[3] - part.bbox[1])) < rules.minimum_part_inside_fraction for part in (head, tail)):
                reasons.append("orientation_parts_outside_parent")
            coordinate = 0 if orientation == "horizontal" else 1
            # Near-coincident part centers do not establish a fish axis. This
            # is a geometry safeguard, independent of widening calibration.
            if max(dx, dy) < .50 * max(whole_width, whole_height):
                reasons.append("orientation_evidence_too_close")
            body_center = ((body[0] + body[2]) / 2, (body[1] + body[3]) / 2)
            if not min(head.center[coordinate], tail.center[coordinate]) < body_center[coordinate] < max(head.center[coordinate], tail.center[coordinate]):
                reasons.append("body_not_between_head_tail")
        elif max(whole_width, whole_height) / min(whole_width, whole_height) >= rules.geometry_min_elongation:
            orientation = "horizontal" if whole_width >= whole_height else "vertical"
        else:
            orientation = "unknown"
            reasons.append("orientation_unconfirmed")
        result["orientation"] = orientation
    result["reliability_reasons"] = list(dict.fromkeys(reasons))
    if not whole or not body:
        result["contribution_reason"] = "missing_detection"
        return result
    proxy = min(body_width, body_height) / max(whole_width, whole_height)
    result.update(status="measured", relative_width_proxy=proxy, initial_relative_width_proxy=proxy,
                  measurement_available=True)
    if reasons:
        result.update(measurement_status="Unreliable", reliability="Unreliable",
                      width_abnormality="Unreliable", contribution_reason="measurement_unreliable")
        return result
    result.update(measurement_status="Measured", reliability="Reliable proxy", reliable_for_scoring=True,
                  width_abnormality="Not calibrated")
    if not rules.calibration_validated:
        return result
    points = min(10.0, max(0.0, 10.0 * (proxy - rules.normal_reference_max) / (rules.extreme_reference - rules.normal_reference_max)))
    # Bins describe a continuous score; there are no discontinuities in points.
    abnormality = "Normal" if points == 0 else "Slight abnormality" if points <= 3 else "Moderate abnormality" if points <= 6 else "Significant abnormality" if points < 10 else "Extreme abnormality"
    result.update(class_c_supporting_points=points, score_status="Calibrated", width_abnormality=abnormality,
                  contribution_reason="scoring_disabled" if not rules.scoring_enabled else "pending_grade_evidence")
    return result


def supplement_body_scores(
    part_scores: Mapping[str, Mapping[str, float]],
    analysis: Mapping[str, object],
    config: BodyWidthConfig | None = None,
) -> tuple[dict[str, dict[str, float]], dict[str, object]]:
    """Replay legacy bounded Body A/B support redistribution exactly once.

    Raw detector scores need not sum to one. Donor fractions are normalized,
    retaining their original total support and leaving Rejected unchanged.
    Independent confident Body C evidence is mandatory; width cannot invent C.
    """
    rules = config or BodyWidthConfig()
    scores = {region: dict(values) for region, values in part_scores.items()}
    result = dict(analysis)
    if result.get("score_contributed"):
        return scores, result
    result.update(score_contributed=False, applied_body_score_shift=0.0)
    if not rules.calibration_validated:
        result["contribution_reason"] = "not_calibrated"
        return scores, result
    if not rules.scoring_enabled:
        result["contribution_reason"] = "scoring_disabled"
        return scores, result
    if result.get("reliable_for_scoring") is False or result.get("measurement_status") == "Unreliable":
        result["contribution_reason"] = "measurement_unreliable"
        return scores, result
    if result.get("status") != "measured" or result.get("score_status") != "Calibrated":
        result["contribution_reason"] = "measurement_unavailable"
        return scores, result
    body = scores.get("Body", {})
    points = _number(result.get("class_c_supporting_points"))
    c_support = _number(body.get("Class C", 0))
    if c_support is None or c_support < rules.minimum_class_c_evidence:
        result["contribution_reason"] = "independent_class_c_evidence_required"
        return scores, result
    donors = {grade: max(0.0, _number(body.get(grade, 0)) or 0.0) for grade in ("Class A", "Class B")}
    donor_total = sum(donors.values())
    shift = min(rules.maximum_body_score_shift * min(10, max(0, points or 0)) / 10, donor_total, max(0.0, 1.0 - c_support))
    if shift <= 0:
        result["contribution_reason"] = "no_support_shift"
        return scores, result
    body["Class C"] = c_support + shift
    for grade, donor in donors.items():
        body[grade] = donor - shift * donor / donor_total
    result.update(score_contributed=True, applied_body_score_shift=shift, contribution_reason="applied_within_body_component")
    return scores, result
