"""Conservative Model 2 part-to-Model 1 fish association.

This module deliberately works only with geometry exposed by the two deployed
detectors.  It does not infer occlusion, physical anatomy loss, or a fish
orientation.  A part is assigned only when one parent has enough geometric
support and is clearly better than every alternative; otherwise it is kept
unassigned for an explicit Ungraded decision upstream.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import hypot
from typing import Iterable, Sequence

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
        if length > 1e-9:
            return dx / length, dy / length
    width = parent.bbox[2] - parent.bbox[0]
    height = parent.bbox[3] - parent.bbox[1]
    return (1.0, 0.0) if width >= height else (0.0, 1.0)


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
    """Validated, non-scientific geometric acceptance settings.

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
    if part_area <= 0.0 or parent_area <= 0.0:
        return AssociationScore(parent.track_id, 0.0, 0.0, False, 1.0)
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
    return AssociationScore(
        parent.track_id,
        min(1.0, max(0.0, score)),
        inside_fraction,
        center_inside,
        normalized_distance,
        mask_support,
        longitudinal_position,
        confidence_support,
    )


def associate_parts_to_parents(
    parts: Iterable[PartDetection],
    parents: Sequence[ParentAnchor],
    config: AssociationConfig | None = None,
) -> tuple[PartAssociation, ...]:
    """Return conservative ownership decisions for full-frame Model 2 boxes.

    A result may be ``ASSIGNED``, ``AMBIGUOUS``, or ``UNASSIGNED``.  The
    caller should preserve ambiguity rather than silently treating it as an
    absence of anatomy.
    """

    rules = config or AssociationConfig()
    results: list[PartAssociation] = []
    candidate_scores: list[tuple[AssociationScore, ...]] = []
    for part in parts:
        candidates = tuple(sorted(
            (score_part_parent(part.bbox, parent, rules, part.confidence) for parent in parents),
            key=lambda value: (-value.score, value.track_id),
        ))
        candidate_scores.append(candidates)
        results.append(PartAssociation(
            part=part,
            status="UNASSIGNED",
            track_id=None,
            confidence=None,
            margin=None,
            candidates=candidates,
        ))

    def eligible(score: AssociationScore) -> bool:
        return (
            score.part_inside_fraction >= rules.minimum_part_inside_fraction
            and score.center_inside
            and score.score >= rules.minimum_association_score
        )

    # Solve each region as a small maximum-weight matching. The skip option
    # preserves safe abstention, while the parent set prevents two physical
    # detections of one region from being assigned to one fish.
    by_region: dict[str, list[int]] = {}
    for index, item in enumerate(results):
        by_region.setdefault(item.part.region, []).append(index)
    for region_indexes in by_region.values():
        memo: dict[tuple[int, tuple[int, ...]], tuple[float, tuple[int | None, ...]]] = {}

        def solve(position: int, used: tuple[int, ...]) -> tuple[float, tuple[int | None, ...]]:
            key = (position, used)
            if key in memo:
                return memo[key]
            if position >= len(region_indexes):
                return 0.0, ()
            index = region_indexes[position]
            best_score, remainder = solve(position + 1, used)
            best_assignment = (None,) + remainder
            for candidate in candidate_scores[index]:
                if not eligible(candidate) or candidate.track_id in used:
                    continue
                next_score, next_assignment = solve(
                    position + 1,
                    tuple(sorted((*used, candidate.track_id))),
                )
                total = candidate.score + next_score
                if total > best_score:
                    best_score = total
                    best_assignment = (candidate.track_id,) + next_assignment
            memo[key] = best_score, best_assignment
            return memo[key]

        _, assignment = solve(0, ())
        for position, index in enumerate(region_indexes):
            candidates = candidate_scores[index]
            top = candidates[0] if candidates else None
            second = candidates[1] if len(candidates) > 1 else None
            margin = (
                top.score - second.score
                if top is not None and second is not None
                else (top.score if top is not None else None)
            )
            assigned_id = assignment[position] if position < len(assignment) else None
            if assigned_id is None or top is None or not eligible(top):
                continue
            close_candidates = tuple(
                candidate.track_id
                for candidate in candidates
                if top.score - candidate.score < rules.minimum_association_margin
            )
            if second is not None and margin is not None and margin < rules.minimum_association_margin:
                results[index] = replace(
                    results[index],
                    status="AMBIGUOUS",
                    margin=margin,
                    ambiguous_track_ids=close_candidates,
                    reason="competing_parent_geometry",
                )
                continue
            selected = next(
                (candidate for candidate in candidates if candidate.track_id == assigned_id),
                None,
            )
            if selected is not None:
                results[index] = replace(
                    results[index],
                    status="ASSIGNED",
                    track_id=assigned_id,
                    confidence=selected.score,
                    margin=margin,
                )
    # A Model 2 full-frame detection can be geometrically plausible for a
    # parent while still duplicate another Head/Body/Tail candidate for that
    # same parent.  The canonical per-fish input intentionally has one
    # selected anatomical region per frame.  Choose the strongest raw Model 2
    # detector evidence (then association support) and leave all other same-
    # region candidates explicitly unassigned; never merge them as independent
    # anatomical evidence or fabricate an ambiguity claim.
    assigned_by_region: dict[tuple[int, str], list[int]] = {}
    for index, result in enumerate(results):
        if result.status == "ASSIGNED" and result.track_id is not None:
            assigned_by_region.setdefault((result.track_id, result.part.region), []).append(index)
    for indexes in assigned_by_region.values():
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
    # Matching may leave a lower-confidence duplicate unassigned before the
    # legacy duplicate pass above sees it. Keep the explicit reason for
    # diagnostics and for callers that distinguish duplicate evidence from a
    # missing anatomical region.
    selected_by_region = {
        (item.track_id, item.part.region): index
        for index, item in enumerate(results)
        if item.status == "ASSIGNED" and item.track_id is not None
    }
    for index, item in enumerate(results):
        if item.status != "UNASSIGNED" or item.reason is not None:
            continue
        for candidate in item.candidates:
            key = (candidate.track_id, item.part.region)
            if key in selected_by_region and eligible(candidate):
                results[index] = replace(item, reason="duplicate_region_for_parent")
                break

    # A rectangle can still produce a superficially valid Head/Body/Tail set
    # when a neighboring part is inside it. Reject only the conflicting
    # anatomical evidence; isolated valid regions remain usable. Direction is
    # intentionally symmetric because a box alone cannot identify head versus
    # tail for rotated or opposite-facing fish.
    for track_id in {parent.track_id for parent in parents}:
        assigned = [
            (index, item) for index, item in enumerate(results)
            if item.track_id == track_id and item.status == "ASSIGNED"
        ]
        by_region = {item.part.region: (index, item) for index, item in assigned}
        head = by_region.get("Head")
        tail = by_region.get("Tail")
        if head is None or tail is None:
            continue
        head_score = next(
            (candidate for candidate in head[1].candidates if candidate.track_id == track_id), None
        )
        tail_score = next(
            (candidate for candidate in tail[1].candidates if candidate.track_id == track_id), None
        )
        body = by_region.get("Body")
        body_score = (
            next(
                (candidate for candidate in body[1].candidates if candidate.track_id == track_id),
                None,
            )
            if body is not None else None
        )
        if head_score is None or tail_score is None:
            continue
        head_position = head_score.longitudinal_position
        tail_position = tail_score.longitudinal_position
        body_position = body_score.longitudinal_position if body_score is not None else 0.0
        if head_position is None or tail_position is None or body_position is None:
            continue
        # Both regions collapsing into the same short longitudinal segment is
        # a common signature of a neighboring part crossing the parent ROI.
        separated = abs(head_position - tail_position) >= rules.minimum_anatomical_alignment
        opposite_sides = head_position * tail_position <= 0.0
        body_between = min(head_position, tail_position) <= body_position <= max(head_position, tail_position)
        implausible_group = (
            not separated
            or (body_score is not None and not body_between)
            or (body_score is not None and not opposite_sides
                and abs(head_position - tail_position) > rules.maximum_longitudinal_span)
        )
        if implausible_group:
            for index, item in (head, tail):
                results[index] = replace(
                    item,
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
