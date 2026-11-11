"""Conservative Model 2 part-to-Model 1 fish association.

This module works with native-frame detector geometry and optional reliable
instance geometry. It never infers occlusion or physical anatomy loss. A part
needs independent ownership support before global one-to-one selection; an
occupied parent must never send a duplicate to a less-supported neighbor.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import hypot, isfinite
from typing import Callable, Iterable, Sequence

from src.inference.part_types import PartDetection


BBox = tuple[float, float, float, float]


def _area(box: BBox) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _intersection(first: BBox, second: BBox) -> float:
    return max(0.0, min(first[2], second[2]) - max(first[0], second[0])) * max(
        0.0, min(first[3], second[3]) - max(first[1], second[1])
    )


def _center(box: BBox) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def required_pair_geometry(
    head_bbox: BBox, body_bbox: BBox, *, reliable_axis: tuple[float, float] | None = None,
) -> dict[str, object]:
    """Report strong required-pair contradictions in either inference mode.

    Natural ROI overlap is allowed. Exact concentric evidence cannot establish
    two independent regions. Transverse order is checked only when a caller
    explicitly supplies a reliable axis; no direction is guessed from boxes.
    This helper never changes confidence, ownership scores or grading weights.
    """
    coincident = _center(head_bbox) == _center(body_bbox)
    transverse_overlap = None
    if reliable_axis is not None:
        axis_x, axis_y = reliable_axis
        length = hypot(axis_x, axis_y)
        if isfinite(length) and length > 1e-9:
            axis_x, axis_y = axis_x / length, axis_y / length

            def interval(box):
                x1, y1, x2, y2 = box
                values = [-axis_y * x + axis_x * y for x, y in ((x1, y1), (x1, y2), (x2, y1), (x2, y2))]
                return min(values), max(values)

            first, second = interval(head_bbox), interval(body_bbox)
            transverse_overlap = bool(max(first[0], second[0]) <= min(first[1], second[1]))
    return {
        "head_body_centers_coincident": coincident,
        "head_body_axis_overlap": transverse_overlap,
        "required_pair_inconsistent": coincident or transverse_overlap is False,
    }


def _polygon_contains(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> bool:
    """Return whether a point is inside a simple polygon."""

    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = current
        x2, y2 = previous
        crosses = (y1 > y) != (y2 > y)
        if crosses and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            inside = not inside
        previous = current
    return inside


def _parent_axis(parent: ParentAnchor) -> tuple[float, float]:
    if parent.orientation is not None:
        dx, dy = parent.orientation
        length = hypot(dx, dy)
        if isfinite(length) and length > 1e-9:
            return dx / length, dy / length
    width = parent.bbox[2] - parent.bbox[0]
    height = parent.bbox[3] - parent.bbox[1]
    return (1.0, 0.0) if width >= height else (0.0, 1.0)


def _reliable_axis(parent: ParentAnchor) -> bool:
    return bool(parent.orientation is not None and parent.orientation_reliable
                and all(isfinite(value) for value in parent.orientation)
                and hypot(*parent.orientation) > 1e-9)


def _thresholds(rules: AssociationConfig) -> tuple[tuple[str, float], ...]:
    return tuple((name, float(getattr(rules, name))) for name in (
        "minimum_part_inside_fraction", "minimum_association_score",
        "minimum_association_margin", "center_padding_fraction",
        "minimum_anatomical_alignment", "maximum_longitudinal_span",
    ))


def _longitudinal_position(part_bbox: BBox, parent: ParentAnchor) -> float:
    """Normalize a part center along a directionless parent axis.

    The value is directionless because a box alone cannot tell head from tail.
    It is still useful for rejecting a head/body/tail set that collapses into
    the same short region of a parent.
    """

    px, py = _center(part_bbox)
    cx, cy = _center(parent.bbox)
    axis_x, axis_y = _parent_axis(parent)
    half_length = max(
        1.0,
        abs(axis_x) * (parent.bbox[2] - parent.bbox[0]) / 2.0
        + abs(axis_y) * (parent.bbox[3] - parent.bbox[1]) / 2.0,
    )
    return (px - cx) * axis_x / half_length + (py - cy) * axis_y / half_length


@dataclass(frozen=True)
class AssociationConfig:
    """Configurable engineering settings for geometric ownership checks.

    These settings govern ownership only.  They never alter a Model 2 raw
    confidence or the fish-level grading policy.
    """

    minimum_part_inside_fraction: float = 0.80
    minimum_association_score: float = 0.70
    minimum_association_margin: float = 0.12
    center_padding_fraction: float = 0.05
    minimum_anatomical_alignment: float = 0.18
    maximum_longitudinal_span: float = 1.35

    def __post_init__(self) -> None:
        for name in (
            "minimum_part_inside_fraction",
            "minimum_association_score",
            "minimum_association_margin",
            "center_padding_fraction",
            "minimum_anatomical_alignment",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1.")
        if self.maximum_longitudinal_span <= 0.0:
            raise ValueError("maximum_longitudinal_span must be positive.")


@dataclass(frozen=True)
class ParentAnchor:
    """One tracked Model 1 fish geometry source."""

    track_id: int
    bbox: BBox
    confidence: float | None = None
    # Optional reliable instance geometry. The deployed detector currently
    # supplies boxes only, but callers with masks or a measured axis can use
    # the same ownership implementation without changing its API.
    mask: tuple[tuple[float, float], ...] | None = None
    orientation: tuple[float, float] | None = None
    # Callers must not label a SAM candidate axis as validated ownership.
    # An engineering-only axis can be exposed without enabling hard gates.
    orientation_reliable: bool = True
    orientation_source: str | None = None
    mask_provenance: str | None = None


@dataclass(frozen=True)
class AssociationScore:
    """Explainable geometric score for one potential ownership relationship."""

    track_id: int
    score: float
    part_inside_fraction: float
    center_inside: bool
    normalized_center_distance: float
    mask_support: float = 0.0
    longitudinal_position: float | None = None
    detector_confidence: float | None = None
    eligible: bool | None = None
    failed_checks: tuple[str, ...] = ()
    acceptance_thresholds: tuple[tuple[str, float], ...] = ()
    orientation_axis: tuple[float, float] | None = None
    orientation_source: str | None = None
    orientation_reliable: bool = False
    transverse_position: float | None = None
    mask_provided: bool = False
    mask_provenance: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "track_id": self.track_id,
            "score": round(self.score, 6),
            "part_inside_fraction": round(self.part_inside_fraction, 6),
            "center_inside": self.center_inside,
            "normalized_center_distance": round(self.normalized_center_distance, 6),
            "mask_support": round(self.mask_support, 6),
            "longitudinal_position": (
                round(self.longitudinal_position, 6)
                if self.longitudinal_position is not None else None
            ),
            "detector_confidence": (
                round(self.detector_confidence, 6)
                if self.detector_confidence is not None else None
            ),
            "eligible": self.eligible,
            "failed_checks": list(self.failed_checks),
            "acceptance_thresholds": dict(self.acceptance_thresholds),
            "orientation": {
                "axis": list(self.orientation_axis) if self.orientation_axis is not None else None,
                "source": self.orientation_source,
                "reliable": self.orientation_reliable,
                "longitudinal_position": self.longitudinal_position,
                "transverse_position": self.transverse_position,
                "head_tail_direction_known": False,
            },
            "mask": {
                "provided": self.mask_provided,
                "center_support": self.mask_support if self.mask_provided else None,
                "provenance": self.mask_provenance,
                "role": "supporting_geometry_only",
            },
        }


@dataclass(frozen=True)
class PartAssociation:
    """Association decision for exactly one Model 2 detection."""

    part: PartDetection
    status: str
    track_id: int | None
    confidence: float | None
    margin: float | None
    candidates: tuple[AssociationScore, ...]
    reason: str | None = None
    # Only parents within the configured margin of the strongest candidate
    # participate in an ambiguity. Other scored parents are diagnostic only.
    ambiguous_track_ids: tuple[int, ...] = ()
    acceptance_thresholds: tuple[tuple[str, float], ...] = ()
    anatomical_checks: tuple[tuple[str, object], ...] = ()

    @property
    def ambiguous(self) -> bool:
        return self.status == "AMBIGUOUS"

    def to_dict(self) -> dict[str, object]:
        return {
            "part": self.part.to_dict(),
            "status": self.status,
            "track_id": self.track_id,
            "association_confidence": round(self.confidence, 6) if self.confidence is not None else None,
            "association_margin": round(self.margin, 6) if self.margin is not None else None,
            "reason": self.reason,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "ambiguous_track_ids": list(self.ambiguous_track_ids),
            "candidate_parent_ids": [candidate.track_id for candidate in self.candidates],
            "acceptance_thresholds": dict(self.acceptance_thresholds),
            "anatomical_checks": dict(self.anatomical_checks),
        }


def score_part_parent(
    part_bbox: BBox,
    parent: ParentAnchor,
    config: AssociationConfig | None = None,
    part_confidence: float | None = None,
) -> AssociationScore:
    """Score a part against one parent without making anatomical assumptions."""

    rules = config or AssociationConfig()
    part_area = _area(part_bbox)
    parent_area = _area(parent.bbox)
    if (not all(isfinite(value) for value in (*part_bbox, *parent.bbox))
            or part_area <= 0.0 or parent_area <= 0.0):
        return AssociationScore(parent.track_id, 0.0, 0.0, False, 1.0,
                                eligible=False, failed_checks=("invalid_geometry",),
                                acceptance_thresholds=_thresholds(rules))
    inside_fraction = _intersection(part_bbox, parent.bbox) / part_area
    px, py = _center(part_bbox)
    x1, y1, x2, y2 = parent.bbox
    pad_x = (x2 - x1) * rules.center_padding_fraction
    pad_y = (y2 - y1) * rules.center_padding_fraction
    center_inside = x1 - pad_x <= px <= x2 + pad_x and y1 - pad_y <= py <= y2 + pad_y
    cx, cy = _center(parent.bbox)
    diagonal = hypot(x2 - x1, y2 - y1)
    distance = hypot(px - cx, py - cy) / diagonal if diagonal > 0.0 else 1.0
    normalized_distance = min(1.0, max(0.0, distance))
    mask_support = 0.0
    if parent.mask and len(parent.mask) >= 3:
        mask_support = 1.0 if _polygon_contains((px, py), parent.mask) else 0.0
    longitudinal_position = _longitudinal_position(part_bbox, parent)
    axis_x, axis_y = _parent_axis(parent)
    half_cross_extent = max(1.0, abs(axis_y) * (x2 - x1) / 2.0 + abs(axis_x) * (y2 - y1) / 2.0)
    transverse_position = (-(px - cx) * axis_y + (py - cy) * axis_x) / half_cross_extent
    # Containment only creates a candidate. The mask, center, and proximity
    # cues are deliberately bounded so a rectangle cannot establish ownership
    # by itself when neighboring fish compete for the same region.
    confidence_support = (
        min(1.0, max(0.0, float(part_confidence)))
        if part_confidence is not None else None
    )
    score = (
        0.48 * inside_fraction
        + 0.15 * float(center_inside)
        + 0.10 * (1.0 - normalized_distance)
        + 0.22 * mask_support
        + 0.05 * (confidence_support or 0.0)
    )
    failed_checks = tuple(reason for failed, reason in (
        (inside_fraction < rules.minimum_part_inside_fraction, "part_not_contained"),
        (not center_inside, "part_center_outside"),
        (score < rules.minimum_association_score, "association_score_below_threshold"),
    ) if failed)
    return AssociationScore(
        parent.track_id,
        min(1.0, max(0.0, score)),
        inside_fraction,
        center_inside,
        normalized_distance,
        mask_support,
        longitudinal_position,
        confidence_support,
        eligible=not failed_checks,
        failed_checks=failed_checks,
        acceptance_thresholds=_thresholds(rules),
        orientation_axis=(axis_x, axis_y),
        orientation_source=(parent.orientation_source or "caller_supplied_axis")
            if parent.orientation is not None else "bbox_major_axis_hint",
        orientation_reliable=_reliable_axis(parent),
        transverse_position=transverse_position,
        mask_provided=bool(parent.mask and len(parent.mask) >= 3),
        mask_provenance=(parent.mask_provenance or "caller_supplied_instance_geometry") if parent.mask else None,
    )


def associate_parts_to_parents(
    parts: Iterable[PartDetection],
    parents: Sequence[ParentAnchor],
    config: AssociationConfig | None = None,
    *,
    candidate_scorer: Callable[[PartDetection, ParentAnchor, AssociationConfig], AssociationScore] | None = None,
) -> tuple[PartAssociation, ...]:
    """Return conservative ownership decisions for full-frame Model 2 boxes.

    A result may be ``ASSIGNED``, ``AMBIGUOUS``, or ``UNASSIGNED``.  The
    caller should preserve ambiguity rather than silently treating it as an
    absence of anatomy.
    """

    rules = config or AssociationConfig()
    results: list[PartAssociation] = []
    for part in parts:
        candidates = tuple(sorted(
            ((candidate_scorer(part, parent, rules) if candidate_scorer is not None
              else score_part_parent(part.bbox, parent, rules, part.confidence)) for parent in parents),
            key=lambda value: (-value.score, value.track_id),
        ))
        results.append(PartAssociation(
            part=part,
            status="UNASSIGNED",
            track_id=None,
            confidence=None,
            margin=None,
            candidates=candidates,
            acceptance_thresholds=_thresholds(rules),
        ))

    # First establish independent ownership. Only eligible parents can claim
    # a part or veto it as a competing owner. Rejected scores are still kept
    # above so a reviewer can inspect every threshold failure.
    for index, item in enumerate(results):
        eligible = tuple(candidate for candidate in item.candidates if candidate.eligible)
        if not eligible:
            reason = (item.candidates[0].failed_checks[0]
                      if item.candidates and item.candidates[0].failed_checks else "no_visible_parent")
            results[index] = replace(item, reason=reason)
            continue
        top = eligible[0]
        margin = top.score - eligible[1].score if len(eligible) > 1 else top.score
        if len(eligible) > 1 and margin < rules.minimum_association_margin:
            results[index] = replace(
                item, status="AMBIGUOUS", margin=margin,
                ambiguous_track_ids=tuple(candidate.track_id for candidate in eligible
                    if top.score - candidate.score < rules.minimum_association_margin),
                reason="competing_parent_geometry",
            )
        else:
            results[index] = replace(item, status="ASSIGNED", track_id=top.track_id,
                                     confidence=top.score, margin=margin)

    # Global one-to-one selection is constrained to independently supported
    # ownership edges. Maximizing unconstrained total score used to send the
    # second Head for fish 1 to fish 2 despite both Heads favoring fish 1.
    # An ambiguous detection also must not reserve a parent from a clear one.
    # Head, Body, Tail priority is explicit and no optional region steals a
    # required region. Duplicates remain visible, never reassigned by vacancy.
    assigned_by_region: dict[tuple[int, str], list[int]] = {}
    for index, result in enumerate(results):
        if result.status == "ASSIGNED" and result.track_id is not None:
            assigned_by_region.setdefault((result.track_id, result.part.region), []).append(index)
    for key in sorted(assigned_by_region, key=lambda value: ({"Head": 0, "Body": 1, "Tail": 2}.get(value[1], 3), value[0])):
        indexes = assigned_by_region[key]
        if len(indexes) < 2:
            continue
        winner = min(
            indexes,
            key=lambda index: (
                -results[index].part.confidence,
                -(results[index].confidence or 0.0),
                results[index].part.source_class_id,
                results[index].part.bbox,
            ),
        )
        for index in indexes:
            if index == winner:
                continue
            results[index] = replace(
                results[index],
                status="UNASSIGNED",
                track_id=None,
                confidence=None,
                reason="duplicate_region_for_parent",
            )
    # Native 2-D separation remains meaningful when an AABB cannot determine
    # fish orientation. A guessed horizontal/vertical projection must not
    # invalidate a diagonal fish. A reliable supplied axis additionally checks
    # Body alignment and directionless Head–Body–Tail ordering.
    for parent in parents:
        track_id = parent.track_id
        assigned = [
            (index, item) for index, item in enumerate(results)
            if item.track_id == track_id and item.status == "ASSIGNED"
        ]
        by_region = {item.part.region: (index, item) for index, item in assigned}
        head = by_region.get("Head")
        tail = by_region.get("Tail")
        body = by_region.get("Body")
        reliable_axis = _reliable_axis(parent)
        diagonal = max(1.0, hypot(parent.bbox[2] - parent.bbox[0], parent.bbox[3] - parent.bbox[1]))

        def separation(first, second):
            return 2.0 * hypot(*(a - b for a, b in zip(first.part.center, second.part.center))) / diagonal

        def score(item):
            return next(candidate for candidate in item.candidates if candidate.track_id == track_id)

        head_body_distinct = bool(head and body and separation(head[1], body[1]) >= rules.minimum_anatomical_alignment)
        pair_checks = (required_pair_geometry(head[1].part.bbox, body[1].part.bbox,
                          reliable_axis=_parent_axis(parent) if reliable_axis else None)
                       if head and body else {})
        head_body_axis_overlap = pair_checks.get("head_body_axis_overlap")
        independent_head_body = head_body_distinct and head_body_axis_overlap is not False
        # A required Head and Body cannot be established by concentric
        # detections of the same image location. Likewise an explicitly
        # reliable axis cannot support anatomically disjoint transverse
        # intervals. These contradictions apply with or without a Tail.
        # Ordinary overlap and uncertain axes remain diagnostic only; no
        # additional distance, IoU or confidence threshold is introduced.
        head_body_centers_coincident = pair_checks.get("head_body_centers_coincident")
        required_pair_inconsistent = pair_checks.get("required_pair_inconsistent") is True
        checks = {
            "parent_axis_reliable": reliable_axis,
            "axis_source": (parent.orientation_source or "caller_supplied_axis")
                if parent.orientation is not None else "bbox_major_axis_hint",
            "head_body_distinct": head_body_distinct if head and body else None,
            "head_body_axis_overlap": head_body_axis_overlap,
            "head_body_centers_coincident": head_body_centers_coincident if head and body else None,
            "required_pair_inconsistent": required_pair_inconsistent if head and body else None,
            "head_tail_separation_2d": separation(head[1], tail[1]) if head and tail else None,
        }
        for index, item in assigned:
            results[index] = replace(item, anatomical_checks=tuple(checks.items()))
        if required_pair_inconsistent:
            for index, _ in (head, body):
                results[index] = replace(results[index], status="AMBIGUOUS", track_id=None,
                    confidence=None, reason="required_anatomical_group_inconsistent",
                    ambiguous_track_ids=(track_id,))
            continue
        if head is None or tail is None:
            continue
        head_position = score(head[1]).longitudinal_position
        tail_position = score(tail[1]).longitudinal_position
        body_position = score(body[1]).longitudinal_position if body else None
        collapsed_2d = separation(head[1], tail[1]) < rules.minimum_anatomical_alignment
        axis_inconsistent = False
        if reliable_axis and head_position is not None and tail_position is not None:
            axis_inconsistent = abs(head_position - tail_position) < rules.minimum_anatomical_alignment
            if body_position is not None:
                axis_inconsistent |= not min(head_position, tail_position) <= body_position <= max(head_position, tail_position)
                axis_inconsistent |= (head_position * tail_position > 0.0
                    and abs(head_position - tail_position) > rules.maximum_longitudinal_span)
        implausible_group = collapsed_2d or axis_inconsistent
        if implausible_group:
            # Tail is optional. It cannot invalidate an independently supported
            # required Head/Body pair. Without that support keep the true
            # Head/Tail conflict ambiguous rather than inventing an owner.
            conflicts = (tail,) if independent_head_body else (head, tail)
            for index, _ in conflicts:
                results[index] = replace(
                    results[index],
                    status="AMBIGUOUS",
                    track_id=None,
                    confidence=None,
                    reason="anatomical_group_inconsistent",
                    ambiguous_track_ids=(track_id,),
                )
    return tuple(results)


def association_summary(associations: Iterable[PartAssociation], track_id: int) -> dict[str, object]:
    """Return JSON-safe per-track association diagnostics."""

    def ambiguous_for(item: PartAssociation) -> bool:
        if item.status != "AMBIGUOUS":
            return False
        if item.ambiguous_track_ids:
            return track_id in item.ambiguous_track_ids
        # Legacy callers can construct PartAssociation directly, without the
        # new contender field. Retain their conservative all-candidate result.
        return any(candidate.track_id == track_id for candidate in item.candidates)

    relevant = [
        item for item in associations
        if (item.track_id == track_id or any(candidate.track_id == track_id for candidate in item.candidates))
        and (item.status != "AMBIGUOUS" or ambiguous_for(item))
    ]
    assigned = [item for item in relevant if item.track_id == track_id and item.status == "ASSIGNED"]
    ambiguous = [item for item in relevant if ambiguous_for(item)]
    status_counts = {
        status: sum(1 for item in relevant if item.status == status)
        for status in ("ASSIGNED", "AMBIGUOUS", "UNASSIGNED", "REJECTED")
    }
    return {
        "mode": "full_frame",
        "assigned_part_count": len(assigned),
        "ambiguous_part_count": len(ambiguous),
        "ambiguous": bool(ambiguous),
        "status": (
            "AMBIGUOUS" if ambiguous else
            "VALID" if assigned else
            "MISSING"
        ),
        "status_counts": status_counts,
        "reasons": sorted({
            item.reason for item in relevant
            if item.reason
        }),
        "parts": [item.to_dict() for item in relevant],
    }
