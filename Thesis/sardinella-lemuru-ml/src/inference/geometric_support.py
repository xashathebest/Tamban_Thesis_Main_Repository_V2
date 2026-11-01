"""Optional validated geometry after the unchanged weighted grading policy.

Combined scores are normalized support shares, not calibrated probabilities.
Only A/B support can be redistributed; Rejected support and baseline evidence
gates are preserved. Runtime and offline replay call this same pure function.
"""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Mapping

from src.inference.body_width import BodyWidthConfig
from src.inference.grading_policy import FishPolicyVerdict, GRADE_NAMES, GradingPolicy


def integrate_geometric_support(
    decision: FishPolicyVerdict,
    width: Mapping[str, object],
    config: BodyWidthConfig,
    policy: GradingPolicy,
    *,
    part_scores: Mapping[str, Mapping[str, float]],
) -> tuple[FishPolicyVerdict, dict[str, object], dict[str, object]]:
    """Apply one bounded support transfer only to an already eligible fish.

    No-op paths preserve the original confidence scale and exact verdict. An
    active contribution normalizes the competing weighted scores to a unit
    total, then transfers at most the configured share from A/B to Class C.
    The recorded original verdict makes that scale change explicit.
    """
    result = dict(width)
    original_scores = dict(decision.weighted_scores)
    total = sum(original_scores.values())
    normalized = {grade: value / total for grade, value in original_scores.items()} if total > 0 else {}
    geometry: dict[str, object] = {
        "scoring_method": "post_weighted_v2",
        "original_grade": decision.final_grade or "Ungraded",
        "original_support": decision.final_support,
        "original_scores": original_scores,
        "original_provisional_grade": decision.top_grade,
        "original_provisional_support": decision.top_support,
        "normalized_original_scores": normalized,
        "final_grade": decision.final_grade or "Ungraded",
        "final_support": decision.final_support,
        "final_scores": dict(original_scores),
        "width_changed_classification": False,
        "contribution_applied": False,
        "contribution_reason": "not_calibrated",
        "class_c_points": result.get("class_c_supporting_points"),
        "applied_score_shift": 0.0,
        "score_scale": "original_weighted_support",
    }

    def unchanged(reason: str):
        result.update(score_applied=False, score_contributed=False,
                      applied_body_score_shift=0.0, applied_geometric_score_shift=0.0,
                      width_changed_classification=False, contribution_reason=reason,
                      scoring_method="post_weighted_v2")
        geometry["contribution_reason"] = reason
        return decision, result, geometry

    if result.get("score_applied") and result.get("scoring_method") == "post_weighted_v2":
        # A final-stage result cannot be supplemented a second time. Normal
        # engine evaluations always start from fresh raw weighted evidence.
        saved = result.get("grading_contribution")
        return decision, result, dict(saved) if isinstance(saved, Mapping) else geometry
    if not config.calibration_validated:
        return unchanged("not_calibrated")
    if not config.scoring_enabled:
        return unchanged("scoring_disabled")
    if not bool(result.get("reliable_for_scoring", result.get("reliability") == "Reliable proxy")):
        return unchanged("unreliable_measurement" if result.get("measurement_available") else "missing_measurement")
    if result.get("score_status") != "Calibrated":
        return unchanged("not_calibrated")
    if decision.final_grade is None:
        return unchanged("baseline_ungraded_evidence_gates")
    if decision.final_grade == "Rejected" or decision.override:
        return unchanged("rejected_safeguard")
    if "Body" not in decision.observed_regions:
        return unchanged("missing_required_body_evidence")
    points = result.get("class_c_supporting_points")
    if isinstance(points, bool) or not isinstance(points, (int, float)) or not math.isfinite(points):
        return unchanged("missing_calibrated_points")
    if points <= 0:
        return unchanged("normal_width")
    c_evidence = part_scores.get("Body", {}).get("Class C", 0.0)
    if not math.isfinite(c_evidence) or c_evidence < config.minimum_class_c_evidence:
        return unchanged("independent_class_c_evidence_required")
    if not normalized:
        return unchanged("missing_weighted_evidence")
    donors = normalized["Class A"] + normalized["Class B"]
    shift = min(config.maximum_geometric_contribution * min(points, 10.0) / 10.0, donors)
    if shift <= 0:
        return unchanged("no_support_shift")
    combined = dict(normalized)
    for grade in ("Class A", "Class B"):
        combined[grade] -= shift * normalized[grade] / donors
    combined["Class C"] += shift
    # The Rejected share is identical to its normalized baseline share. The
    # unchanged anatomy contributions are retained separately in the verdict.
    ordered = sorted(GRADE_NAMES, key=lambda grade: (-combined[grade], GRADE_NAMES.index(grade)))
    first, second = ordered[:2]
    margin = combined[first] - combined[second]
    if combined[first] < policy.final_verdict_threshold or margin < policy.minimum_grade_margin:
        geometry["candidate_scores"] = combined
        return unchanged("combined_support_below_acceptance_gates")
    # Geometry supports C only; it cannot establish a new Rejected decision.
    if first == "Rejected":
        return unchanged("rejected_safeguard")
    final = replace(decision, weighted_scores=combined, top_grade=first,
                    top_support=combined[first], second_grade=second,
                    second_support=combined[second], grade_margin=margin,
                    final_grade=first, final_support=combined[first])
    changed = first != decision.final_grade
    reason = "validated_width_changed_classification" if changed else "validated_width_support_applied"
    geometry.update(final_grade=first, final_support=combined[first], final_scores=combined,
                    width_changed_classification=changed, contribution_applied=True,
                    contribution_reason=reason, applied_score_shift=shift,
                    score_scale="normalized_combined_support")
    result.update(score_applied=True, score_contributed=True, applied_body_score_shift=0.0,
                  applied_geometric_score_shift=shift, width_changed_classification=changed,
                  contribution_reason=reason, scoring_method="post_weighted_v2",
                  grading_contribution=dict(geometry))
    return final, result, geometry
