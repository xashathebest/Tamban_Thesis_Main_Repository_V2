"""Audit paired, independently reviewed fish outcomes for body-width research.

This offline command reports measurements and Class C errors. It does not train
a model, invent a widening threshold, certify labels, or enable runtime scoring.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Mapping
import hashlib
import json
import math
from pathlib import Path

from src.evaluation.fish_level_validation import load_fish_level_records, normalize_grade


def _mapping(value: object) -> dict:
    if isinstance(value, str) and value.strip():
        value = json.loads(value)
    return dict(value) if isinstance(value, Mapping) else {}


def _flag(value: object, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise ValueError(f"{field} must explicitly be true or false.")


def _text(record: Mapping, field: str) -> str:
    value = str(record.get(field) or "").strip()
    if value.casefold() in {"", "unknown", "none", "null", "n/a", "tbd"}:
        raise ValueError(f"{field} must be recorded for each physical fish.")
    return value


def _proxy(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("relative_width_proxy must be a finite fraction or null.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("relative_width_proxy must be a finite fraction or null.") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError("relative_width_proxy must be a finite positive ratio.")
    return number


def _class_c_metrics(pairs: list[tuple[str | None, str | None]]) -> dict:
    counts = Counter((truth == "Class C", prediction == "Class C") for truth, prediction in pairs)
    tp, fn, fp, tn = (counts[key] for key in ((True, True), (True, False), (False, True), (False, False)))
    return {"true_positive": tp, "false_negative": fn, "false_positive": fp, "true_negative": tn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "false_positive_rate": fp / (fp + tn) if fp + tn else None,
            "ungraded_count": sum(prediction is None for _, prediction in pairs)}


def evaluate_body_width_records(records: Iterable[Mapping], *, dataset_split: str = "validation") -> dict:
    """Compare one paired outcome per physical specimen with explicit review.

    Required review declarations are assertions; callers must verify their
    authenticity. Missing width evidence is retained in the denominator. An
    Ungraded prediction is not a Class C prediction and is reported separately.
    Reference ranges use manual width labels, never the predicted/true grade.
    """
    if dataset_split not in {"validation", "test"}:
        raise ValueError("dataset_split must be validation or test.")
    rows = list(records)
    if not rows:
        raise ValueError("At least one independently reviewed physical fish is required.")
    seen: dict[str, set[str]] = {"fish_id": set(), "specimen_id": set()}
    groups: dict[str, str] = {}
    evaluated, baselines, candidates = [], [], []
    normal, widened = [], []
    scenarios: Counter = Counter()
    reliabilities: Counter = Counter()
    configurations: dict[str, dict] = {}
    for record in rows:
        if not isinstance(record, Mapping):
            raise ValueError("Each record must be a fish mapping.")
        identity = {field: _text(record, field) for field in (
            "fish_id", "specimen_id", "capture_session", "split", "expert_reviewer", "review_reference")}
        for field in seen:
            if identity[field].casefold() in seen[field]:
                raise ValueError(f"Duplicate {field}; use one paired row per physical fish.")
            seen[field].add(identity[field].casefold())
        split = identity["split"]
        if split not in {"train", "validation", "test"}:
            raise ValueError("split must be train, validation or test.")
        group = identity["capture_session"].casefold()
        if group in groups and groups[group] != split:
            raise ValueError("A capture_session overlaps splits; keep related captures in one split.")
        groups[group] = split
        if not _flag(record.get("independent_grade_review"), "independent_grade_review"):
            raise ValueError("An independent expert grade review is required.")
        if not _flag(record.get("system_prediction_hidden"), "system_prediction_hidden"):
            raise ValueError("Truth must be reviewed with the system prediction hidden.")
        if not _flag(record.get("association_reviewed"), "association_reviewed"):
            raise ValueError("The Model 1 to Model 2 association must be manually reviewed.")
        association_correct = _flag(record.get("association_correct"), "association_correct")
        truth = normalize_grade(record.get("true_grade"), allow_ungraded=False)
        if "baseline_grade" not in record or "candidate_grade" not in record:
            raise ValueError("Both baseline_grade and candidate_grade are required.")
        baseline = normalize_grade(record["baseline_grade"])
        candidate = normalize_grade(record["candidate_grade"])
        analysis = _mapping(record.get("analysis"))
        width = _mapping(analysis.get("body_width", record.get("body_width", record.get("body_width_analysis"))))
        value = _proxy(width.get("relative_width_proxy"))
        reliable = (width.get("reliable_for_scoring") is True if "reliable_for_scoring" in width else
                    width.get("reliability") == "Reliable proxy" and width.get("status") == "measured")
        contributed = _flag(width.get("score_contributed", False), "score_contributed")
        applied = _flag(width.get("score_applied", contributed), "score_applied")
        if contributed and not applied:
            raise ValueError("A final-grade contribution requires an applied score.")
        config = _mapping(width.get("threshold_configuration"))
        if config:
            encoded = json.dumps(config, sort_keys=True, allow_nan=False)
            configurations[encoded] = config
        if reliable and (value is None or value > 1 or not association_correct):
            raise ValueError("Reliable width requires a measured proxy and a correct reviewed association.")
        if applied:
            points = width.get("class_c_supporting_points")
            if (not reliable or width.get("score_status") != "Calibrated" or
                not _flag(config.get("calibration_validated", False), "calibration_validated") or
                not _flag(config.get("scoring_enabled", False), "scoring_enabled") or
                isinstance(points, bool) or not isinstance(points, (int, float)) or not 0 < points <= 10):
                raise ValueError("A contribution requires reliable evidence, positive points and enabled validated calibration.")
        elif baseline != candidate:
            raise ValueError("The grade must be preserved when width does not contribute.")
        scenario = _text(record, "geometry_case").lower()
        if scenario not in {"horizontal", "vertical", "diagonal", "overlapping", "clipped"}:
            raise ValueError("geometry_case must be horizontal, vertical, diagonal, overlapping or clipped.")
        if reliable and scenario in {"diagonal", "overlapping", "clipped"}:
            raise ValueError("A diagonal, overlapping or clipped review case must not have a reliable bounding-box width proxy.")
        width_label = str(record.get("manual_width_label") or "unreviewed").lower()
        if width_label not in {"normal", "widened", "uncertain", "unreviewed"}:
            raise ValueError("manual_width_label must be normal, widened, uncertain or unreviewed.")
        if split != dataset_split:
            continue
        scenarios[scenario] += 1
        reliabilities["Reliable proxy" if reliable else "Unreliable" if value is not None else "Unavailable"] += 1
        baselines.append((truth, baseline))
        candidates.append((truth, candidate))
        if reliable and width_label == "normal":
            normal.append(value)
        if reliable and width_label == "widened":
            widened.append(value)
        evaluated.append({**identity, "true_grade": truth, "baseline_grade": baseline or "Ungraded",
                          "candidate_grade": candidate or "Ungraded", "relative_width_proxy": value,
                          "association_correct": association_correct, "score_applied": applied,
                          "score_contributed": contributed,
                          "reliable_for_scoring": reliable,
                          "measurement_status": width.get("measurement_status", "Measured" if reliable else "Unreliable" if value is not None else "Missing Detection"),
                          "calibration_status": width.get("calibration_status", "Calibrated" if config.get("calibration_validated") else "Not Calibrated"),
                          "geometry_case": scenario, "manual_width_label": width_label})
    if not evaluated:
        raise ValueError(f"No reviewed records belong to the {dataset_split} split.")
    if len(configurations) > 1:
        raise ValueError("Use one frozen width threshold configuration per paired comparison.")
    baseline_metrics, candidate_metrics = _class_c_metrics(baselines), _class_c_metrics(candidates)
    return {"scope": "paired_individual_fish_body_width", "dataset_split": dataset_split,
            "fish_count": len(evaluated), "baseline_class_c": baseline_metrics, "candidate_class_c": candidate_metrics,
            "delta_candidate_minus_baseline": {key: (candidate_metrics[key] - baseline_metrics[key]
                if candidate_metrics[key] is not None and baseline_metrics[key] is not None else None)
                for key in ("precision", "recall", "false_positive_rate")},
            "changed_grade_count": sum(a != b for (_, a), (_, b) in zip(baselines, candidates)),
            "geometry_cases": dict(scenarios), "reliability_counts": dict(reliabilities),
            "threshold_configuration": next(iter(configurations.values()), None),
            "reference_preparation": {"normal_count": len(normal), "normal_observed_range":
                [min(normal), max(normal)] if normal else None, "widened_count": len(widened),
                "widened_observed_range": [min(widened), max(widened)] if widened else None,
                "reliably_measured_true_grades": sorted({row["true_grade"] for row in evaluated if row["reliable_for_scoring"]}),
                "calibration_validated": False, "thresholds_selected": False,
                "guidance": "Observed ranges are descriptive only. Select thresholds on validation fish, record expert approval and provenance, freeze them, then compare on independent test fish."},
            "limitations": "Review metadata are declarations, not authenticated truth. This report does not establish scientific adequacy or enable scoring.",
            "records": evaluated}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-split", choices=("validation", "test"), default="validation")
    args = parser.parse_args(argv)
    try:
        report = evaluate_body_width_records(load_fish_level_records(args.records), dataset_split=args.dataset_split)
        report["source_sha256"] = hashlib.sha256(args.records.read_bytes()).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
