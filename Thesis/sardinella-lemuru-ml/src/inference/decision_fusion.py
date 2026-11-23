"""Calibrated, source-bound decision fusion; detector scores are not probabilities.

The anatomical policy remains authoritative for ownership, required regions and
temporal acceptance. Only a frozen, specimen-separated calibration can supply
the supporting 30%. Agreement measures consistency, never correctness.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
from typing import Mapping

import numpy as np

from src.inference.grading_policy import GRADE_NAMES

WEIGHTS = {"model2": .70, "size": .15, "cracks": .05, "color": .05, "texture": .05}
FAMILIES = tuple(name for name in WEIGHTS if name != "model2")
EXTRACTOR_VERSION = "owned_fish_fusion_v1"
FEATURE_KEYS = {
    "size": ("relative_width_ratio", "body_width_to_length_ratio", "body_width_profile_cv"),
    "cracks": ("crack_area_fraction", "crack_length_to_fish_length"),
    "color": ("mean_value", "median_value", "mean_saturation", "yellow_ratio_proxy", "brown_ratio_proxy"),
    "texture": ("glcm_contrast", "glcm_homogeneity", "glcm_entropy", "lbp_entropy",
                "lbp_nonuniform_ratio", "mean_gradient_proxy"),
}
REQUIRED_CHECKS = {
    "size": ("complete_mask", "ownership", "measurement", "anatomical_endpoints", "perpendicular_widths", "proportions"),
    "cracks": ("complete_mask", "ownership", "measurement", "structural_discrimination"),
    "color": ("complete_mask", "ownership", "measurement", "lighting_calibrated"),
    "texture": ("complete_mask", "ownership", "measurement", "glcm_valid", "lbp_valid", "surface_valid"),
}


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def digest_valid(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def serializable_evidence(value):
    """Unavailable numeric values remain null, so one bad feature cannot break JSON."""
    if isinstance(value, Mapping):
        return {str(key): serializable_evidence(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable_evidence(item) for item in value]
    if isinstance(value, np.ndarray):
        return serializable_evidence(value.tolist())
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


@dataclass(frozen=True)
class DecisionFusionConfig:
    enabled: bool = True
    minimum_reliability: float = .50
    strong_conflict_reliability: float = .65
    strong_conflict_margin: float = .35
    minimum_decision_confidence: float = .55
    minimum_fused_margin: float = .08
    disagreement_penalty: float = .25
    major_conflict_penalty: float = .50
    artifact_path: str = "configs/decision_fusion_calibration.json"

    def __post_init__(self):
        if not isinstance(self.enabled, bool) or not isinstance(self.artifact_path, str):
            raise ValueError("Fusion enablement and artifact path have invalid types.")
        for name, value in asdict(self).items():
            if name not in {"enabled", "artifact_path"} and (finite(value) is None or not 0 <= value <= 1):
                raise ValueError(f"{name} must be a finite fraction.")
        if self.minimum_reliability <= 0 or self.strong_conflict_reliability < self.minimum_reliability:
            raise ValueError("Reliable conflict evidence must meet the feature reliability gate.")

    def to_dict(self):
        return {**asdict(self), "configured_weights": dict(WEIGHTS)}

    def policy_id(self):
        values = self.to_dict()
        for key in ("enabled", "artifact_path"):
            values.pop(key)
        return fingerprint(values)


def load_decision_fusion_config(path=None):
    import yaml
    target = Path(path) if path else Path(__file__).resolve().parents[2] / "configs/decision_fusion.yaml"
    if not target.exists():
        return DecisionFusionConfig()
    values = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(values, dict):
        raise ValueError("Decision fusion configuration must be a mapping.")
    weights = values.pop("weights", WEIGHTS)
    if weights != WEIGHTS:
        raise ValueError("Decision fusion preserves Model 2/size/cracks/color/texture at 70/15/5/5/5 percent.")
    return DecisionFusionConfig(**values)


def load_calibration(config):
    path = Path(config.artifact_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    if not path.exists():
        return None, "No annotator-verified feature calibration is installed."
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        validate_calibration(artifact, config)
        return artifact, None
    except (OSError, ValueError, TypeError, KeyError, OverflowError, AttributeError) as error:
        return None, f"Calibration withheld: {error}"


def validate_calibration(artifact, config, *, candidate=False):
    if (not isinstance(artifact, Mapping) or artifact.get("schema_version") != "decision_fusion_calibration_v1"
            or artifact.get("extractor_version") != EXTRACTOR_VERSION
            or artifact.get("classes") != list(GRADE_NAMES)
            or artifact.get("fusion_policy_id") != config.policy_id()):
        raise ValueError("Calibration schema, extractor, classes or decision policy does not match.")
    if not isinstance(artifact.get("calibration_id"), str) or not artifact["calibration_id"].strip():
        raise ValueError("A frozen calibration ID is required.")
    context = artifact.get("model_context", {})
    if not isinstance(context, Mapping) or not all(digest_valid(context.get(k)) for k in ("checkpoint_sha256", "anatomical_policy_sha256")):
        raise ValueError("Calibration must identify the exact Model 2 checkpoint and anatomical policy.")
    anatomical_policy = artifact.get("anatomical_policy")
    if not isinstance(anatomical_policy, Mapping) or fingerprint(anatomical_policy) != context["anatomical_policy_sha256"]:
        raise ValueError("Anatomical acceptance rules do not match the calibrated policy fingerprint.")
    for key in ("final_verdict_threshold", "minimum_grade_margin"):
        if finite(anatomical_policy.get(key)) is None or not 0 <= anatomical_policy[key] <= 1:
            raise ValueError("Anatomical support/margin acceptance rules must be finite fractions.")
    provenance = artifact.get("provenance", {})
    if not isinstance(provenance, Mapping) or not digest_valid(provenance.get("manifest_sha256")):
        raise ValueError("Calibration has no verified-record manifest fingerprint.")
    groups = provenance.get("split_groups", {})
    if not isinstance(groups, Mapping) or set(groups) != {"calibration", "validation", "test"}:
        raise ValueError("Calibration requires three independently separated specimen/capture partitions.")
    partitions = []
    for split in groups:
        values = groups[split]
        if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v for v in values):
            raise ValueError("Partition identities must be known and nonempty.")
        partitions.append(set(values))
    if any(partitions[i] & partitions[j] for i in range(3) for j in range(i)):
        raise ValueError("Calibration contains specimen, capture-group or duplicate-image leakage.")
    if not isinstance(artifact.get("validation"), Mapping) or (not candidate and artifact["validation"].get("passed") is not True):
        raise ValueError("Fusion did not pass its held-out validation comparison.")
    model = artifact.get("model2", {})
    temperature = finite(model.get("temperature"))
    if model.get("validated") is not True or temperature is None or not .25 <= temperature <= 4.:
        raise ValueError("Model 2 probabilities require a validated temperature calibration.")
    families = artifact.get("features")
    if not isinstance(families, Mapping) or set(families) - set(FAMILIES):
        raise ValueError("Unknown or malformed calibrated feature families.")
    for family, entry in families.items():
        if not isinstance(entry, Mapping) or entry.get("validated") is not True:
            continue
        reliability, temperature = finite(entry.get("reliability")), finite(entry.get("temperature"))
        limit = finite(entry.get("distance_limit"))
        if (entry.get("keys") != list(FEATURE_KEYS[family]) or reliability is None or not 0 < reliability <= 1
                or temperature is None or not .25 <= temperature <= 4. or limit is None or limit <= 0
                or not isinstance(entry.get("capture_profiles"), list) or not entry["capture_profiles"]):
            raise ValueError(f"Invalid {family} calibration or capture profiles.")
        for grade in GRADE_NAMES:
            distribution = entry.get("distributions", {}).get(grade, {})
            vectors = [distribution.get(key) for key in ("mean", "scale")]
            if any(not isinstance(v, list) or len(v) != len(FEATURE_KEYS[family]) or any(finite(x) is None for x in v) for v in vectors):
                raise ValueError(f"Missing {family}/{grade} reference distribution.")
            prior = finite(distribution.get("prior"))
            if any(s < 1e-6 for s in vectors[1]) or prior is None or not 0 < prior <= 1:
                raise ValueError("Reference scales and priors must be positive.")
            class_reliability = finite(entry.get("per_class_reliability", {}).get(grade))
            if class_reliability is None or not 0 <= class_reliability <= 1:
                raise ValueError("Per-class reliability must come from validation examples.")
            for split in ("calibration", "validation"):
                count = entry.get("class_counts", {}).get(split, {}).get(grade)
                if isinstance(count, bool) or not isinstance(count, int) or count < 5:
                    raise ValueError("Each calibrated family needs at least five independent specimens per class per fit/validation partition.")
    return artifact


def normalize_scores(scores):
    values = np.array([finite(scores.get(grade)) if isinstance(scores, Mapping) else None for grade in GRADE_NAMES], dtype=float)
    if not np.isfinite(values).all() or (values < 0).any() or values.max() <= 0:
        return None
    values /= values.max()
    return values / values.sum()


def softmax(values, temperature=1.):
    logits = np.asarray(values, dtype=float) / temperature
    logits -= logits.max()
    result = np.exp(logits)
    return result / result.sum()


def model_probabilities(scores, model):
    normalized = normalize_scores(scores)
    return None if normalized is None else softmax(np.log(np.maximum(normalized, 1e-12)), model["temperature"])


def reference_support(values, calibration):
    """Class-conditional likelihoods followed by held-out temperature scaling."""
    sample = np.asarray([values[key] for key in calibration["keys"]], dtype=float)
    likelihoods, distances = [], []
    for grade in GRADE_NAMES:
        distribution = calibration["distributions"][grade]
        scale = np.asarray(distribution["scale"])
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            z = np.clip((sample - np.asarray(distribution["mean"])) / scale, -1e6, 1e6)
        distances.append(float(np.sqrt(np.mean(z * z))))
        likelihoods.append(float(-.5 * np.sum(z * z) - np.log(scale).sum() + math.log(distribution["prior"])))
    return softmax(likelihoods, calibration["temperature"]), min(distances)


def source_matches(record, *, fish_id, frame_id, source):
    if (not isinstance(record, Mapping) or not isinstance(source, Mapping) or fish_id is None
            or isinstance(fish_id, bool) or not isinstance(frame_id, (int, str)) or isinstance(frame_id, bool)):
        return False
    digest = source.get("frame_pixels_sha256")
    return (record.get("fish_id") == fish_id and not isinstance(record.get("fish_id"), bool)
            and record.get("frame_id") == frame_id and isinstance(source.get("source_id"), str)
            and bool(source["source_id"].strip()) and record.get("source_id") == source["source_id"]
            and digest_valid(digest) and record.get("frame_pixels_sha256") == digest)


def head_integrity_check(record, *, fish_id, frame_id, source):
    confirmed = (source_matches(record, fish_id=fish_id, frame_id=frame_id, source=source)
                 and record.get("state") == "confirmed_absent" and record.get("reviewed") is True
                 and record.get("ownership_validated") is True and record.get("visibility_validated") is True
                 and all(isinstance(record.get(key), str) and record[key].strip() for key in ("reviewer", "review_id")))
    return {"state": "confirmed_absent" if confirmed else "unverified",
            "independent_pathway": True, "confirmed_missing_head": confirmed,
            "reason": "Source-bound, visible Head absence confirmed by review." if confirmed
            else "Head non-detection alone does not establish physical absence.",
            "evidence": serializable_evidence(record) if isinstance(record, Mapping) else {}}


def measurement_issues(family, entry):
    if not isinstance(entry, Mapping):
        return ["measurement_unavailable"]
    checks = entry.get("checks", {})
    checks = checks if isinstance(checks, Mapping) else {}
    issues = [f"validation_failed:{check}" for check in REQUIRED_CHECKS[family] if checks.get(check) is not True]
    values = entry.get("values", {})
    if not isinstance(values, Mapping) or any(finite(values.get(key)) is None for key in FEATURE_KEYS[family]):
        issues.append("measurements_missing_or_nonfinite")
    reliability = finite(entry.get("measurement_reliability"))
    if reliability is None or not 0 < reliability <= 1:
        issues.append("measurement_reliability_unavailable")
    return issues


def fuse_decision(baseline, measurements, config, artifact, *, fish_id, frame_id, source=None,
                  model_context=None, head_evidence=None, restricted_grades=(), fallback=None,
                  calibration_error=None, candidate=False):
    """Return a real verdict plus an auditable comparison to the untouched AI.

    ``candidate`` is used only by offline validation before artifact promotion.
    Missing evidence has zero weight; it is never encoded as a low-quality fish.
    """
    fallback = baseline if fallback is None else fallback
    measures = measurements if isinstance(measurements, Mapping) else {}
    report = {"schema_version": "decision_fusion_v1", "configured_weights": dict(WEIGHTS),
              "effective_weights": {"model2": .70, **dict.fromkeys(FAMILIES, 0.)},
              "unallocated_supporting_weight": .30, "mode": "model2_only",
              "model_only_prediction": baseline.final_grade or "Ungraded", "model_only_scores": dict(baseline.weighted_scores),
              "model_only_verdict": baseline.to_dict(), "model_context": deepcopy(model_context),
              "model2_class_probabilities": None, "feature_only_prediction": None,
              "feature_only_class_support": None, "features": {}, "per_feature_reliability": {},
              "per_class_combined_support": dict(fallback.weighted_scores), "evidence_agreement_score": None,
              "model_to_feature_disagreement": None, "decision_state": "AGREEMENT", "agreement_validated": False,
              "disagreement_reasons": [], "validation_reasons": [], "calibration_id": None,
              "score_interpretation": "Model 2-only detector support; no supporting 30% evidence is available.",
              "head_integrity": head_integrity_check(head_evidence, fish_id=fish_id, frame_id=frame_id, source=source)}
    valid_artifact = artifact
    try:
        if not config.enabled:
            raise ValueError("Decision fusion is disabled.")
        validate_calibration(artifact, config, candidate=candidate)
        if artifact["model_context"] != model_context:
            raise ValueError("Model 2 checkpoint or anatomical policy differs from calibration.")
        report["calibration_id"] = artifact["calibration_id"]
        report["anatomical_policy"] = deepcopy(artifact["anatomical_policy"])
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError) as error:
        valid_artifact = None
        report["validation_reasons"].append(calibration_error or str(error))
    model_p = model_probabilities(baseline.weighted_scores, valid_artifact["model2"]) if valid_artifact else None
    report["model2_class_probabilities"] = dict(zip(GRADE_NAMES, model_p.tolist())) if model_p is not None else None
    eligible = {}
    bundle_bound = (measures.get("extractor_version") == EXTRACTOR_VERSION
                    and source_matches(measures, fish_id=fish_id, frame_id=frame_id, source=source))
    for family in FAMILIES:
        entries = measures.get("features", {})
        entry = entries.get(family, {}) if isinstance(entries, Mapping) else {}
        entry = entry if isinstance(entry, Mapping) else {}
        issues = measurement_issues(family, entry)
        if not bundle_bound:
            issues.append("measurement_source_or_extractor_mismatch")
        calibration = valid_artifact.get("features", {}).get(family, {}) if valid_artifact else {}
        calibration = calibration if isinstance(calibration, Mapping) else {}
        if calibration.get("validated") is not True:
            issues.append("annotator_verified_reference_unavailable")
        if calibration and measures.get("capture_profile_id") not in calibration.get("capture_profiles", []):
            issues.append("capture_or_lighting_profile_outside_calibration")
        support, distance, reliability = None, None, 0.
        if not issues and model_p is not None:
            support, distance = reference_support(entry["values"], calibration)
            class_reliability = calibration["per_class_reliability"][GRADE_NAMES[int(np.argmax(support))]]
            reliability = min(calibration["reliability"], class_reliability) * entry["measurement_reliability"]
            if distance > calibration["distance_limit"]:
                issues.append("outside_calibrated_reference_distribution")
            if reliability < config.minimum_reliability:
                issues.append("reliability_below_acceptance_threshold")
        if model_p is None:
            issues.append("calibrated_model2_probabilities_unavailable")
        info = {"eligible": not issues, "used_for_grading": False, "reliability": reliability,
                "measurement_reliability": entry.get("measurement_reliability"),
                "calibration_reliability": calibration.get("reliability"), "reasons": issues,
                "measurements": serializable_evidence(entry.get("values", {})), "checks": deepcopy(entry.get("checks", {})),
                "class_support": dict(zip(GRADE_NAMES, support.tolist())) if support is not None else None,
                "reference_distance": distance, "assessment": GRADE_NAMES[int(np.argmax(support))] if support is not None else "Unavailable",
                "validation_metrics": deepcopy(calibration.get("validation_metrics", {}))}
        report["features"][family] = info
        report["per_feature_reliability"][family] = reliability
        if not issues:
            eligible[family] = (support, reliability)
    decision = fallback
    confidence = fallback.final_support or 0.
    if fallback != baseline:
        report.update(mode="legacy_reviewed_rules", score_interpretation="Existing reviewed anatomical/geometry rules; no calibrated 30% fusion evidence.")
    if eligible:
        report["mode"] = "calibrated_fusion"
        report["score_interpretation"] = "70% calibrated Model 2 plus 30% eligible class support; decision confidence is a conflict-penalized support score, not measured accuracy."
        denominator = sum(WEIGHTS[f] * r for f, (_, r) in eligible.items())
        feature_p, adjusted_feature_p = np.zeros(len(GRADE_NAMES)), np.zeros(len(GRADE_NAMES))
        mean_distance, severity_distance, strong, contrary = 0., 0., [], []
        model_index = int(np.argmax(model_p))
        for family, (support, reliability) in eligible.items():
            weight = .30 * WEIGHTS[family] * reliability / denominator
            report["effective_weights"][family] = weight
            # Reliability also attenuates a sole feature, even when it owns all
            # available supporting weight. The residual preserves model evidence.
            adjusted = reliability * support + (1 - reliability) * model_p
            feature_p += weight / .30 * support
            adjusted_feature_p += weight / .30 * adjusted
            distance = float(.5 * np.abs(model_p - support).sum())
            mean_distance += weight / .30 * distance
            info = report["features"][family]
            info.update(used_for_grading=True, model_disagreement=distance, effective_weight=weight,
                        reliability_adjusted_support=dict(zip(GRADE_NAMES, adjusted.tolist())))
            if int(np.argmax(support)) != model_index:
                contrary.append(family)
                margin = float(support.max() - support[model_index])
                severity = abs(int(np.argmax(support)) - model_index) / (len(GRADE_NAMES) - 1)
                severity_distance += weight / .30 * distance * severity
                info.update(conflict_margin=margin, conflict_severity=severity)
                report["disagreement_reasons"].append(f"{family}: supports {info['assessment']} over {GRADE_NAMES[model_index]} by {margin:.4f}; reliability {reliability:.4f}; distribution distance {distance:.4f}.")
                if reliability >= config.strong_conflict_reliability and margin >= config.strong_conflict_margin:
                    strong.append(family)
        combined = .70 * model_p + .30 * adjusted_feature_p
        report.update(unallocated_supporting_weight=0., agreement_validated=True,
                      evidence_agreement_score=1 - mean_distance,
                      model_to_feature_disagreement=float(.5 * np.abs(model_p - feature_p).sum()),
                      feature_only_prediction=GRADE_NAMES[int(np.argmax(feature_p))],
                      feature_only_class_support=dict(zip(GRADE_NAMES, feature_p.tolist())),
                      per_class_combined_support=dict(zip(GRADE_NAMES, combined.tolist())),
                      decision_state="MAJOR_DISAGREEMENT" if len(strong) >= 2 else "MINOR_DISAGREEMENT" if contrary else "AGREEMENT")
        order = sorted(range(len(GRADE_NAMES)), key=lambda i: (-combined[i], i))
        first, second = order[:2]
        report["severity_weighted_disagreement"] = severity_distance
        confidence = float(combined[first]) * (1 - config.disagreement_penalty * (mean_distance + severity_distance) / 2)
        reasons = []
        if len(strong) >= 2:
            confidence *= config.major_conflict_penalty
            reasons.append("UG_FUSION_MAJOR_DISAGREEMENT")
        if len(contrary) == 1 and WEIGHTS[contrary[0]] <= .05 and first != model_index:
            reasons.append("UG_FUSION_SINGLE_LOW_WEIGHT_FEATURE_CHANGED_GRADE")
        if baseline.final_grade is None:
            reasons.extend(baseline.reason_codes)
        confidence_threshold = max(config.minimum_decision_confidence, artifact["anatomical_policy"]["final_verdict_threshold"])
        margin_threshold = max(config.minimum_fused_margin, artifact["anatomical_policy"]["minimum_grade_margin"])
        report["acceptance_thresholds"] = {"decision_confidence": confidence_threshold, "class_margin": margin_threshold}
        if confidence < confidence_threshold:
            reasons.append("UG_FUSION_LOW_DECISION_CONFIDENCE")
        if combined[first] - combined[second] < margin_threshold:
            reasons.append("UG_FUSION_LOW_MARGIN")
        if GRADE_NAMES[first] in restricted_grades:
            reasons.append("UG_FUSION_REVIEWED_ELIGIBILITY_RESTRICTION")
        if baseline.override or baseline.final_grade == "Rejected":
            if GRADE_NAMES[first] != "Rejected":
                reasons.append("UG_FUSION_REJECTED_SAFEGUARD")
        report["fused_candidate_prediction"] = GRADE_NAMES[first]
        decision = replace(baseline, weighted_scores=report["per_class_combined_support"],
                           top_grade=GRADE_NAMES[first], top_support=float(combined[first]),
                           second_grade=GRADE_NAMES[second], second_support=float(combined[second]),
                           grade_margin=float(combined[first] - combined[second]),
                           final_grade=None if reasons else GRADE_NAMES[first], final_support=float(combined[first]),
                           reason_codes=tuple(dict.fromkeys(reasons)) if reasons else ("GR_CALIBRATED_FEATURE_FUSION",))
    if report["head_integrity"]["confirmed_missing_head"]:
        report["decision_state"] = "CRITICAL_ANATOMICAL_DISAGREEMENT"
        report["disagreement_reasons"].append("Confirmed missing Head independently blocks automatic grading, regardless of weighted quality support.")
        decision = replace(decision, final_grade=None, reason_codes=("UG_CONFIRMED_MISSING_HEAD",))
        confidence = 0.
    report.update(final_fused_prediction=decision.final_grade or "Ungraded", decision_confidence=confidence,
                  confidence_kind="conflict_penalized_support_not_accuracy" if eligible else "model2_support_not_probability",
                  review_required=decision.final_grade is None,
                  automatic_status="HUMAN_REVIEW" if decision.final_grade is None else "AUTOMATIC",
                  review_reasons=list(decision.reason_codes) if decision.final_grade is None else [],
                  changed_prediction=decision.final_grade != baseline.final_grade,
                  evidence_note="Consistency of calibrated evidence is not proof of correctness; no majority vote is used.")
    return decision, serializable_evidence(report)
