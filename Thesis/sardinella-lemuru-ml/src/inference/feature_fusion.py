"""Reviewed structural support after the unchanged anatomical/width stages.

Image-processing candidates never establish severity or a grading rule. This
module consumes explicitly reviewed, source-bound evidence and a separately
reviewed policy. The shipped policy has no calibration and changes no grade.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import math
from pathlib import Path
from typing import Mapping

from src.inference.grading_policy import FishPolicyVerdict, GRADE_NAMES, GradingPolicy


@dataclass(frozen=True)
class StructuralFusionConfig:
    enabled: bool = False
    calibration_validated: bool = False
    policy_id: str | None = None
    reference_set_id: str | None = None
    validation_sample_count: int = 0
    policy_review_provenance: Mapping[str, object] = field(default_factory=dict)
    major_class_a_restriction_enabled: bool = True
    severity_metric: str = "skeleton_length_to_body_length"
    minor_upper_ratio: float | None = None
    moderate_upper_ratio: float | None = None
    maximum_structural_contribution: float = 0.0
    # Reviewed per-severity transfer rules, e.g. {"moderate": {"target":
    # "Class B", "fraction": ...}}. Defaults intentionally contain no rule.
    severity_support: Mapping[str, Mapping[str, object]] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("enabled", "calibration_validated", "major_class_a_restriction_enabled"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")
        if isinstance(self.validation_sample_count, bool) or not isinstance(self.validation_sample_count, int) or self.validation_sample_count < 0:
            raise ValueError("validation_sample_count must be a nonnegative integer")
        cap = self.maximum_structural_contribution
        if isinstance(cap, bool) or not isinstance(cap, (int, float)) or not math.isfinite(cap) or not 0 <= cap <= 1:
            raise ValueError("maximum_structural_contribution must be between zero and one")
        boundaries = (self.minor_upper_ratio, self.moderate_upper_ratio)
        if any(v is not None for v in boundaries):
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in boundaries):
                raise ValueError("Both reviewed severity boundaries must be positive finite ratios")
            if boundaries[0] >= boundaries[1]:
                raise ValueError("Reviewed minor boundary must be below the moderate boundary")
        if self.severity_metric != "skeleton_length_to_body_length":
            raise ValueError("Unsupported structural severity metric")
        if not isinstance(self.policy_review_provenance, Mapping) or not isinstance(self.severity_support, Mapping):
            raise ValueError("Structural policy provenance and support rules must be mappings")
        for severity, rule in self.severity_support.items():
            if severity not in {"minor", "moderate", "major"} or not isinstance(rule, Mapping):
                raise ValueError("Unknown reviewed structural severity support rule")
            fraction = rule.get("fraction")
            if (rule.get("target") not in {"Class B", "Class C"} or isinstance(fraction, bool)
                    or not isinstance(fraction, (int, float)) or not math.isfinite(fraction)
                    or not 0 <= fraction <= cap):
                raise ValueError("Structural support must target B/C within the configured cap")
        if self.calibration_validated and not self.has_reviewed_policy:
            raise ValueError("Validated structural calibration requires policy, reference set, sample count and reviewer provenance")

    @property
    def has_reviewed_policy(self):
        return (isinstance(self.policy_id, str) and bool(self.policy_id.strip())
                and isinstance(self.reference_set_id, str) and bool(self.reference_set_id.strip())
                and self.validation_sample_count > 0
                and _review_provenance(self.policy_review_provenance)
                and self.policy_review_provenance.get("reference_set_id") == self.reference_set_id)

    def to_dict(self):
        return asdict(self)


def _review_provenance(value):
    return isinstance(value, Mapping) and all(isinstance(value.get(key), str) and bool(value[key].strip())
                                              for key in ("review_id", "reviewer", "reference_set_id"))


def load_structural_fusion_config(path=None):
    import yaml
    target = Path(path) if path is not None else Path(__file__).resolve().parents[2] / "configs/structural_features.yaml"
    if not target.exists():
        return StructuralFusionConfig()
    value = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("Structural feature configuration must be a mapping")
    unknown = set(value) - set(StructuralFusionConfig.__dataclass_fields__)
    if unknown:
        raise ValueError("Unknown structural configuration keys: " + ", ".join(sorted(unknown)))
    return StructuralFusionConfig(**value)


def _finite_positive(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value > 0)


def assess_structural_evidence(evidence, config, *, fish_id, frame_id, source_context=None):
    """Check the separate reviewed-evidence contract, never a SAM score."""
    context = source_context if isinstance(source_context, Mapping) else {}
    record = evidence if isinstance(evidence, Mapping) else {}
    report = {"status": "unavailable", "severity": "unassessed", "severity_validated": False,
              "calibration_status": "Calibrated" if config.calibration_validated else "Not calibrated",
              "used_for_grading": False, "score_shift": 0.0, "contribution_reason": "not_calibrated",
              "validation_provenance": {}, "reasons": [], "policy_id": config.policy_id,
              "source_bound": False, "candidate_severity": record.get("severity"),
              "severity_metric": config.severity_metric, "parent_track_id": fish_id,
              "fish_id": fish_id, "frame_id": frame_id, "review_source_frame_id": record.get("frame_id"),
              "source_id": context.get("source_id"), "frame_pixels_sha256": context.get("frame_pixels_sha256"),
              "image_sha256": context.get("image_sha256"), "coordinate_space": record.get("coordinate_space"),
              "frame_width_px": context.get("frame_width_px"), "frame_height_px": context.get("frame_height_px")}
    reasons = report["reasons"]
    if not config.calibration_validated or not config.has_reviewed_policy:
        reasons.append("No independently reviewed crack-severity/grading calibration is configured.")
        return report
    if not config.enabled:
        report["contribution_reason"] = "structural_policy_disabled"
        reasons.append("The reviewed structural feature policy is disabled.")
        return report
    owner = record.get("parent_track_id", record.get("fish_id"))
    if isinstance(owner, bool) or owner != fish_id or frame_id is None or record.get("frame_id") != frame_id:
        reasons.append("Reviewed structural evidence does not match the fish and source frame.")
    digest_key = next((key for key in ("frame_pixels_sha256", "image_sha256") if isinstance(context.get(key), str)), None)
    digest = context.get(digest_key) if digest_key else None
    valid_digest = isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest.lower())
    if (not isinstance(context.get("source_id"), str) or not context["source_id"].strip()
            or record.get("source_id") != context.get("source_id") or not valid_digest
            or record.get(digest_key) != digest):
        reasons.append("Reviewed structural evidence has no matching acquisition ID and original-image digest.")
    for flag in ("reviewed", "ownership_validated", "body_mask_validated", "measurement_validated"):
        if record.get(flag) is not True:
            reasons.append(f"Required reviewed structural evidence flag is unavailable: {flag}.")
    if record.get("status") != "confirmed" or record.get("region") != "Body":
        reasons.append("Only confirmed Body structural evidence is eligible.")
    if any(record.get(flag) is not False for flag in ("clipped", "overlapping", "ownership_ambiguous", "partial_silhouette")):
        reasons.append("Clipping, overlap or uncertain Body ownership withholds structural grading.")
    provenance = record.get("validation_provenance")
    if (not _review_provenance(provenance)
            or provenance.get("reference_set_id") != config.reference_set_id):
        reasons.append("Structural evidence review does not match the policy's reviewed reference set.")
    locations = record.get("locations")
    valid_locations = []
    frame_width, frame_height = context.get("frame_width_px"), context.get("frame_height_px")
    if isinstance(locations, list) and record.get("coordinate_space") == "original_frame":
        for location in locations:
            if not isinstance(location, Mapping):
                continue
            x, y, width, height = (location.get(key) for key in ("x", "y", "width", "height"))
            if (_finite_positive(width) and _finite_positive(height) and isinstance(x, (int, float))
                    and isinstance(y, (int, float)) and not isinstance(x, bool) and not isinstance(y, bool)
                    and math.isfinite(x) and math.isfinite(y) and x >= 0 and y >= 0
                    and math.isfinite(x + width) and math.isfinite(y + height)
                    and (not _finite_positive(frame_width) or x + width <= frame_width)
                    and (not _finite_positive(frame_height) or y + height <= frame_height)):
                valid_locations.append(dict(location))
    if not valid_locations:
        reasons.append("Reviewed crack evidence has no localized original-frame support.")
    elif len(valid_locations) != len(locations):
        reasons.append("Reviewed crack localization contains malformed or out-of-frame regions.")
    severity = str(record.get("severity", "")).strip().lower()
    if severity in {"minor", "moderate", "major"} and record.get("severity_reviewed") is True:
        report["severity_source"] = "explicit_reviewed_severity"
    else:
        metrics = record.get("measurements") if isinstance(record.get("measurements"), Mapping) else {}
        ratio = metrics.get(config.severity_metric)
        if (_finite_positive(ratio) and config.minor_upper_ratio is not None
                and config.moderate_upper_ratio is not None):
            severity = "minor" if ratio <= config.minor_upper_ratio else "moderate" if ratio <= config.moderate_upper_ratio else "major"
            report.update(severity_source="reviewed_normalized_reference_boundaries", severity_ratio=ratio,
                          reference_boundaries={"minor_upper_ratio": config.minor_upper_ratio,
                                                "moderate_upper_ratio": config.moderate_upper_ratio})
        else:
            reasons.append("Neither reviewed severity nor reviewed normalized severity ranges are available.")
    if reasons:
        report["contribution_reason"] = "unreliable_or_unreviewed_structural_evidence"
        return report
    report.update(status="confirmed", severity=severity, severity_validated=True, source_bound=True,
                  validation_provenance=dict(provenance), locations=valid_locations,
                  contribution_reason="reviewed_evidence_available")
    return report


def integrate_structural_support(decision, evidence, config, policy, *, fish_id, frame_id, source_context=None):
    report = assess_structural_evidence(evidence, config, fish_id=fish_id, frame_id=frame_id, source_context=source_context)
    eligibility = {"class_a_eligible": True, "restricted_grades": [], "rule_applied": False,
                   "reason": "No validated major-crack eligibility restriction applies.", "policy_id": config.policy_id}
    original = decision
    if not report["severity_validated"]:
        return decision, report, eligibility
    severity = report["severity"]
    # Structural support cannot fill missing Head/Body, ownership, temporal or
    # confidence gates. Eligibility is recorded even if a fish is already UG.
    major = severity == "major" and config.major_class_a_restriction_enabled
    if major:
        eligibility.update(class_a_eligible=False, restricted_grades=["Class A"], rule_applied=True,
                           reason="A reliably confirmed major Body crack excludes Class A under the reviewed policy.")
    if decision.final_grade is None:
        report["contribution_reason"] = "baseline_ungraded_evidence_gates"
        return decision, report, eligibility
    scores = dict(decision.weighted_scores)
    rule = config.severity_support.get(severity, {})
    shift = 0.
    if rule and not decision.override and decision.final_grade != "Rejected":
        total = sum(scores.values())
        target = rule["target"]
        donors = ("Class A",) if target == "Class B" else ("Class A", "Class B")
        normalized = {grade: value / total for grade, value in scores.items()} if total > 0 else {}
        donor_total = sum(normalized.get(grade, 0.) for grade in donors)
        shift = min(float(rule["fraction"]), config.maximum_structural_contribution, donor_total)
        if shift > 0:
            candidate = dict(normalized)
            for grade in donors:
                candidate[grade] -= shift * normalized[grade] / donor_total
            candidate[target] += shift
            available = [grade for grade in GRADE_NAMES if not major or grade != "Class A"]
            ordered = sorted(available, key=lambda grade: (-candidate[grade], GRADE_NAMES.index(grade)))
            first, second = ordered[:2]
            if (candidate[first] >= policy.final_verdict_threshold and candidate[first] - candidate[second] >= policy.minimum_grade_margin
                    and first != "Rejected"):
                scores = candidate
                report.update(score_shift=shift, score_target=target, score_scale="normalized_combined_support")
            else:
                shift = 0.
    if decision.override or decision.final_grade == "Rejected":
        report["contribution_reason"] = "existing_rejected_safeguard_preserved"
        report["used_for_grading"] = major
        return decision, report, eligibility
    if not major and shift <= 0:
        report["contribution_reason"] = "no_reviewed_support_rule_for_severity"
        return decision, report, eligibility
    available = [grade for grade in GRADE_NAMES if grade not in eligibility["restricted_grades"]]
    ordered = sorted(available, key=lambda grade: (-scores[grade], GRADE_NAMES.index(grade)))
    first, second = ordered[:2]
    margin = scores[first] - scores[second]
    accepted = scores[first] > 0 and scores[first] >= policy.final_verdict_threshold and margin >= policy.minimum_grade_margin
    reason = ("GR_CONFIRMED_MAJOR_CRACK_A_EXCLUDED" if major else "GR_REVIEWED_STRUCTURAL_SUPPORT") if accepted else "UG_CONFIRMED_MAJOR_CRACK_NO_ELIGIBLE_GRADE"
    final = replace(decision, weighted_scores=scores, top_grade=first, top_support=scores[first],
                    second_grade=second, second_support=scores[second], grade_margin=margin,
                    final_grade=first if accepted else None, final_support=scores[first] if accepted else None,
                    reason_codes=(reason,), override=decision.override)
    report.update(used_for_grading=True, contribution_reason="confirmed_major_crack_class_a_excluded" if major else "reviewed_structural_support_applied",
                  original_grade=original.final_grade or "Ungraded", final_grade=final.final_grade or "Ungraded",
                  changed_classification=final.final_grade != original.final_grade)
    return final, report, eligibility


def feature_fusion_report(anatomical, geometric, structural, eligibility, final):
    return {"schema_version": "feature_fusion_v1",
            "primary_anatomical": {"grade": anatomical.final_grade or "Ungraded", "support": anatomical.final_support,
                                   "scores": dict(anatomical.weighted_scores), "effective_weights": dict(anatomical.effective_weights)},
            "geometric": dict(geometric), "structural": dict(structural), "eligibility": dict(eligibility),
            "original_grade": anatomical.final_grade or "Ungraded", "original_support": anatomical.final_support,
            "final_grade": final.final_grade or "Ungraded", "final_support": final.final_support,
            "final_scores": dict(final.weighted_scores),
            "structural_changed_classification": bool(structural.get("changed_classification", False)),
            "contributions_applied": (["geometric_width"] if geometric.get("contribution_applied") else [])
                                     + (["reviewed_structural_evidence"] if structural.get("used_for_grading") else [])}
