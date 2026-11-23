"""Fit, validate and compare decision fusion using verified physical specimens.

No pseudo-labels, fabricated references, or automatic approval of annotations.
Calibration fits distributions, validation selects temperatures and checks the
frozen decision policy, and test is used only by the separate evaluate command.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import numpy as np

from src.inference.decision_fusion import (
    EXTRACTOR_VERSION, FAMILIES, FEATURE_KEYS, GRADE_NAMES, DecisionFusionConfig,
    digest_valid, fingerprint, fuse_decision, load_decision_fusion_config,
    measurement_issues, model_probabilities, normalize_scores, reference_support,
    source_matches, validate_calibration,
)
from src.inference.grading_policy import FishPolicyVerdict

SPLITS = ("calibration", "validation", "test")
UNKNOWN = {"", "unknown", "none", "n/a", "null"}


def baseline_from_record(row):
    values = deepcopy(row["ai_baseline"])
    values["final_grade"] = None if values.get("final_grade") == "Ungraded" else values.get("final_grade")
    for key in ("observed_regions", "reason_codes"):
        values[key] = tuple(values[key])
    values.pop("verdict_status", None)
    values.pop("original_weight_coverage", None)
    return FishPolicyVerdict(**values)


def validate_records(records):
    if not isinstance(records, list) or not records:
        raise ValueError("No annotator-verified, specimen-identified records were supplied.")
    identities, contexts, specimens = {}, set(), set()
    groups = {split: set() for split in SPLITS}
    for row in records:
        if not isinstance(row, dict) or row.get("split") not in SPLITS:
            raise ValueError("Every record needs a calibration/validation/test partition.")
        if row.get("annotator_verified") is not True or row.get("human_grade") not in GRADE_NAMES:
            raise ValueError("Every label must be an explicitly annotator-verified human grade.")
        for key in ("annotator_id", "review_id", "specimen_id", "capture_group_id", "duplicate_group_id"):
            if not isinstance(row.get(key), str) or row[key].strip().lower() in UNKNOWN:
                raise ValueError(f"A known {key} is required; image/track IDs cannot stand in for specimens.")
        if row["specimen_id"] in specimens:
            raise ValueError("Use one representative record per physical specimen; repeated views cannot inflate calibration counts.")
        specimens.add(row["specimen_id"])
        if not digest_valid(row.get("image_sha256")):
            raise ValueError("Each original image requires its SHA-256 fingerprint.")
        measures = row.get("measurements", {})
        source = row.get("source", {})
        if (measures.get("extractor_version") != EXTRACTOR_VERSION
                or not source_matches(measures, fish_id=row.get("fish_id"), frame_id=row.get("frame_id"), source=source)):
            raise ValueError("Measurements must match the original source, fish, frame and extractor.")
        if not digest_valid(source.get("frame_pixels_sha256")):
            raise ValueError("Original native-pixel fingerprints are required.")
        # Capture groups and declared augmentation/near-duplicate families join
        # the specimen and exact-image checks. Renamed images cannot evade them.
        keys = [(key, row[key]) for key in ("specimen_id", "capture_group_id", "duplicate_group_id", "image_sha256")]
        keys.append(("frame_pixels_sha256", source["frame_pixels_sha256"]))
        for kind, identity in keys:
            key = f"{kind}:{identity}"
            if key in identities and identities[key] != row["split"]:
                raise ValueError(f"Partition leakage through {kind}: {identity}")
            identities[key] = row["split"]
            groups[row["split"]].add(key)
        context = row.get("model_context", {})
        if not isinstance(context, dict) or not all(digest_valid(context.get(k)) for k in ("checkpoint_sha256", "anatomical_policy_sha256")):
            raise ValueError("Records must identify the exact checkpoint and anatomical policy.")
        contexts.add(fingerprint(context))
        if not isinstance(row.get("anatomical_policy"), dict) or fingerprint(row["anatomical_policy"]) != context["anatomical_policy_sha256"]:
            raise ValueError("The original anatomical policy must match its recorded fingerprint.")
        baseline = baseline_from_record(row)
        if normalize_scores(baseline.weighted_scores) is None or any(not 0 <= value <= 1 for value in baseline.weighted_scores.values()):
            raise ValueError("Original Model 2 support must be finite and within [0,1].")
        if baseline.final_grade not in (*GRADE_NAMES, None):
            raise ValueError("Original AI prediction has an invalid grade.")
        if not measures.get("capture_profile_id"):
            raise ValueError("A known camera/lighting capture profile is required.")
    if len(contexts) != 1:
        raise ValueError("Calibrate each checkpoint/anatomical policy separately.")
    if any(not groups[split] for split in SPLITS):
        raise ValueError("Reserve nonempty calibration, validation and untouched test specimens.")
    return {split: sorted(values) for split, values in groups.items()}


def _probability_metrics(truth, predictions):
    y = np.array([GRADE_NAMES.index(grade) for grade in truth])
    p = np.asarray(predictions)
    onehot = np.eye(len(GRADE_NAMES))[y]
    labels = p.argmax(axis=1)
    recalls = {grade: float(np.mean(labels[y == i] == i)) if np.any(y == i) else None for i, grade in enumerate(GRADE_NAMES)}
    confidence = p.max(axis=1)
    ece = 0.
    for index in range(10):
        selected = (confidence >= index / 10) & ((confidence <= 1.) if index == 9 else (confidence < (index + 1) / 10))
        if selected.any():
            ece += selected.mean() * abs(float((labels[selected] == y[selected]).mean() - confidence[selected].mean()))
    return {"brier_score": float(np.mean(np.sum((p - onehot) ** 2, axis=1))),
            "negative_log_likelihood": float(-np.log(np.maximum(p[np.arange(len(y)), y], 1e-12)).mean()),
            "balanced_accuracy": float(np.mean([v for v in recalls.values() if v is not None])),
            "per_class_recall": recalls, "expected_calibration_error_10_bins": float(ece), "specimen_count": len(y)}


def _temperature(truth, predictor):
    # A single scalar, chosen on validation only; class order/part weights stay
    # unchanged. The untouched test set is never used in fitting this scalar.
    grid = sorted({1., *np.geomspace(.25, 4., 41).tolist()})
    scores = [(float(_probability_metrics(truth, predictor(value))["negative_log_likelihood"]), value) for value in grid]
    return min(scores, key=lambda item: (item[0], abs(item[1] - 1)))[1]


def fit_calibration(records, config=None):
    config = config or DecisionFusionConfig()
    split_groups = validate_records(records)
    fit = [r for r in records if r["split"] == "calibration"]
    validation = [r for r in records if r["split"] == "validation"]
    for split, rows in (("calibration", fit), ("validation", validation)):
        counts = Counter(r["human_grade"] for r in rows)
        if any(counts[grade] < 5 for grade in GRADE_NAMES):
            raise ValueError(f"{split} requires at least five independent verified specimens per class; available {dict(counts)}.")
    truth = [r["human_grade"] for r in validation]
    score_rows = [r["ai_baseline"]["weighted_scores"] for r in validation]
    temperature = _temperature(truth, lambda t: [model_probabilities(scores, {"temperature": t}) for scores in score_rows])
    model_metrics = _probability_metrics(truth, [model_probabilities(scores, {"temperature": temperature}) for scores in score_rows])
    original_metrics = _probability_metrics(truth, [normalize_scores(scores) for scores in score_rows])
    model_validated = model_metrics["brier_score"] <= original_metrics["brier_score"] + 1e-12
    artifact = {"schema_version": "decision_fusion_calibration_v1", "extractor_version": EXTRACTOR_VERSION,
                "classes": list(GRADE_NAMES), "fusion_policy_id": config.policy_id(),
                "model_context": deepcopy(records[0]["model_context"]),
                "anatomical_policy": deepcopy(records[0]["anatomical_policy"]),
                "model2": {"validated": bool(model_validated), "temperature": temperature,
                           "validation_metrics": model_metrics, "uncalibrated_normalized_support_metrics": original_metrics},
                "provenance": {"manifest_sha256": fingerprint(records), "split_groups": split_groups,
                               "annotators": sorted({r["annotator_id"] for r in records}),
                               "review_ids": sorted({r["review_id"] for r in records}),
                               "fit_split": "calibration", "temperature_selection_split": "validation", "test_labels_used_for_fitting": False},
                "features": {}, "validation": {"passed": False}}
    for family in FAMILIES:
        eligible = lambda rows: [r for r in rows if not measurement_issues(family, r["measurements"].get("features", {}).get(family))]
        family_fit, family_val = eligible(fit), eligible(validation)
        counts = {split: dict(Counter(r["human_grade"] for r in rows)) for split, rows in (("calibration", family_fit), ("validation", family_val))}
        if any(counts[split].get(grade, 0) < 5 for split in counts for grade in GRADE_NAMES):
            artifact["features"][family] = {"validated": False, "reason": "insufficient_verified_feature_specimens_per_class", "class_counts": counts}
            continue
        keys = FEATURE_KEYS[family]
        vector = lambda row: [row["measurements"]["features"][family]["values"][key] for key in keys]
        array = np.array([vector(row) for row in family_fit], dtype=float)
        global_variance = np.var(array, axis=0)
        floor = np.maximum(np.sqrt(global_variance) * .05, 1e-6)
        entry = {"validated": True, "keys": list(keys), "class_counts": counts, "distributions": {},
                 "capture_profiles": sorted({r["measurements"]["capture_profile_id"] for r in family_fit}),
                 "temperature": 1., "distance_limit": 1., "reliability": 0.}
        if any(row["measurements"]["capture_profile_id"] not in entry["capture_profiles"] for row in family_val):
            entry.update(validated=False, reason="validation_capture_profile_not_represented_in_calibration")
            artifact["features"][family] = entry
            continue
        distances = []
        for grade in GRADE_NAMES:
            x = np.array([vector(row) for row in family_fit if row["human_grade"] == grade])
            mean = x.mean(axis=0)
            scale = np.maximum(np.sqrt(.8 * x.var(axis=0) + .2 * global_variance), floor)
            entry["distributions"][grade] = {"mean": mean.tolist(), "scale": scale.tolist(), "prior": len(x) / len(array)}
            distances.extend(np.sqrt(np.mean(((x - mean) / scale) ** 2, axis=1)).tolist())
        entry["distance_limit"] = max(1., float(np.quantile(distances, .995)))
        val_truth = [row["human_grade"] for row in family_val]
        def predict(t):
            candidate = {**entry, "temperature": t}
            return [reference_support(row["measurements"]["features"][family]["values"], candidate)[0] for row in family_val]
        entry["temperature"] = _temperature(val_truth, predict)
        metrics = _probability_metrics(val_truth, predict(entry["temperature"]))
        priors = np.array([entry["distributions"][grade]["prior"] for grade in GRADE_NAMES])
        prior_metrics = _probability_metrics(val_truth, [priors] * len(family_val))
        skill = max(0., 1 - metrics["brier_score"] / max(prior_metrics["brier_score"], 1e-12))
        entry["reliability"] = float(metrics["balanced_accuracy"] * np.sqrt(skill))
        entry["per_class_reliability"] = metrics["per_class_recall"]
        entry["validation_metrics"] = {**metrics, "brier_skill_over_prior": skill,
            "within_reference_fraction": sum(reference_support(r["measurements"]["features"][family]["values"], entry)[1] <= entry["distance_limit"] for r in family_val) / len(family_val)}
        entry["validated"] = bool(entry["reliability"] >= config.minimum_reliability and skill > 0)
        artifact["features"][family] = entry
    artifact["calibration_id"] = "fusion-" + fingerprint(artifact)[:20]
    if not model_validated:
        artifact["validation"] = {"passed": False, "reason": "model2_probability_calibration_worsened_brier_score"}
        return artifact
    comparison = evaluate_calibration(records, artifact, config, split="validation", candidate=True)
    passed = (comparison["candidate"]["macro_f1"] + 1e-12 >= comparison["model2_only"]["macro_f1"]
              and comparison["candidate"]["false_rejected_rate"] <= comparison["model2_only"]["false_rejected_rate"] + 1e-12
              and comparison["candidate"]["automatic_count"] > 0
              and any(entry.get("validated") for entry in artifact["features"].values()))
    artifact["validation"] = {"passed": bool(passed), "comparison": comparison,
                              "rule": "paired four-class macro F1 must not decline, false Rejected rate must not increase, eligible features and automatic decisions must exist"}
    return artifact


def evaluate_calibration(records, artifact, config=None, *, split="test", candidate=False):
    config = config or DecisionFusionConfig()
    groups = validate_records(records)
    if groups != artifact.get("provenance", {}).get("split_groups") or fingerprint(records) != artifact["provenance"]["manifest_sha256"]:
        raise ValueError("Evaluate the frozen manifest used to reserve these specimens; changed labels or partitions require a new calibration.")
    validate_calibration(artifact, config, candidate=candidate)
    if split not in {"validation", "test"}:
        raise ValueError("Evaluation uses validation or untouched test only.")
    rows = [r for r in records if r["split"] == split]
    outcomes = []
    for row in rows:
        baseline = baseline_from_record(row)
        decision, report = fuse_decision(baseline, row["measurements"], config, artifact,
            fish_id=row["fish_id"], frame_id=row["frame_id"], source=row["source"],
            model_context=row["model_context"], head_evidence=row.get("head_integrity_evidence"), candidate=candidate)
        outcomes.append({"specimen_id": row["specimen_id"], "capture_group_id": row["capture_group_id"],
                         "human_grade": row["human_grade"], "model2_only": baseline.final_grade or "Ungraded",
                         "candidate": decision.final_grade or "Ungraded", "decision_state": report["decision_state"],
                         "review_required": report["review_required"], "mode": report["mode"],
                         "disagreement_reasons": report["disagreement_reasons"]})
    def metrics(name):
        matrix = np.zeros((4, 5), dtype=int)
        for row in outcomes:
            matrix[GRADE_NAMES.index(row["human_grade"]), (*GRADE_NAMES, "Ungraded").index(row[name])] += 1
        recalls, precisions, f1 = {}, {}, []
        for i, grade in enumerate(GRADE_NAMES):
            tp, actual, predicted = matrix[i, i], matrix[i].sum(), matrix[:, i].sum()
            recalls[grade] = float(tp / actual) if actual else 0.
            precisions[grade] = float(tp / predicted) if predicted else 0.
            f1.append(float(2 * tp / (actual + predicted)) if actual + predicted else 0.)
        negative_count = int(matrix[:3].sum())
        automatic = int(matrix[:, :4].sum())
        correct = int(np.trace(matrix[:, :4]))
        return {"accuracy_including_review_abstentions": correct / len(rows), "macro_f1": sum(f1) / 4,
                "automatic_accuracy": correct / automatic if automatic else None,
                "automatic_count": automatic, "review_count": len(rows) - automatic,
                "automatic_coverage": automatic / len(rows), "per_class_recall": recalls,
                "per_class_precision": precisions, "confusion_matrix": matrix.tolist(),
                "confusion_columns": [*GRADE_NAMES, "Ungraded"],
                "false_rejected_count": int(matrix[:3, 3].sum()), "non_rejected_truth_count": negative_count,
                "false_rejected_rate": float(matrix[:3, 3].sum() / negative_count) if negative_count else 0.}
    baseline_metrics, candidate_metrics = metrics("model2_only"), metrics("candidate")
    # Paired capture-group bootstrap. This interval is uncertainty, not approval.
    capture_ids = sorted({row["capture_group_id"] for row in outcomes})
    intervals = []
    if len(capture_ids) >= 2:
        rng = np.random.default_rng(42)
        by_group = {key: [r for r in outcomes if r["capture_group_id"] == key] for key in capture_ids}
        for _ in range(500):
            sample = [r for key in rng.choice(capture_ids, len(capture_ids), replace=True) for r in by_group[key]]
            intervals.append(sum((r["candidate"] == r["human_grade"]) - (r["model2_only"] == r["human_grade"]) for r in sample) / len(sample))
    return {"split": split, "specimen_count": len(rows), "capture_group_count": len(capture_ids),
            "model2_only": baseline_metrics, "candidate": candidate_metrics,
            "paired_accuracy_delta_group_bootstrap_95_interval": np.quantile(intervals, [.025, .975]).tolist() if intervals else None,
            "bootstrap_seed": 42, "bootstrap_repetitions": len(intervals),
            "paired_outcomes": outcomes, "truth_counts": dict(Counter(r["human_grade"] for r in rows)),
            "interpretation": "Ungraded remains in the denominator. Validation selects calibration; test is an independent performance estimate, not a guarantee of improvement."}


def export_review_records(database, identities):
    """Read Review & Teach corrections without overwriting original AI evidence.

    A human-supplied identity map links session/track IDs to real specimens and
    acquisition/duplicate groups. Unknown identities are withheld, never guessed.
    """
    records, withheld = [], []
    identity_map = {(r["session_id"], r["track_id"]): r for r in identities}
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        for session, track, raw in connection.execute("SELECT session_id, track_id, event_json FROM fish_inspections"):
            event = json.loads(raw)
            if not event.get("manual_override"):
                continue
            identity = identity_map.get((session, track))
            audit = connection.execute("SELECT manual_grade, reviewer, audit_id FROM inspection_review_audit WHERE session_id=? AND track_id=? ORDER BY audit_id DESC LIMIT 1", (session, track)).fetchone()
            analysis = event.get("analysis", {})
            fusion = analysis.get("feature_fusion", {}).get("decision_fusion", {})
            latest = analysis.get("frame_quality", {}).get("latest", {})
            if not identity or not audit or not audit[1] or not fusion.get("model_only_verdict") or not latest.get("fusion_measurements"):
                withheld.append({"session_id": session, "track_id": track, "reason": "missing_specimen_identity_verified_review_or_original_fusion_measurements"})
                continue
            grade = audit[0] if audit[0] in GRADE_NAMES else f"Class {audit[0]}"
            records.append({**identity, "fish_id": track, "frame_id": latest["fusion_measurements"]["frame_id"],
                "annotator_verified": True, "annotator_id": audit[1], "review_id": f"review-audit:{session}:{audit[2]}",
                "human_grade": grade, "original_ai_prediction": fusion["model_only_prediction"],
                "ai_baseline": fusion["model_only_verdict"], "measurements": latest["fusion_measurements"],
                "model_context": fusion["model_context"], "anatomical_policy": fusion["anatomical_policy"], "source": latest.get("source_context", {})})
    return {"schema_version": "decision_fusion_records_v1", "records": records, "withheld": withheld}


def audit_existing(root):
    root = Path(root)
    report = {"calibration_ready": False, "inspection_count": 0, "human_review_count": 0,
              "source_bound_feature_records": 0, "datasets": [], "limitations": []}
    database = root / "results/inspection_history.sqlite3"
    if database.exists():
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            report["inspection_count"] = connection.execute("SELECT count(*) FROM fish_inspections").fetchone()[0]
            report["human_review_count"] = connection.execute("SELECT count(*) FROM inspection_review_audit").fetchone()[0]
            for raw, in connection.execute("SELECT event_json FROM fish_inspections"):
                event = json.loads(raw)
                bundle = event.get("analysis", {}).get("frame_quality", {}).get("latest", {}).get("fusion_measurements", {})
                report["source_bound_feature_records"] += int(bool(bundle.get("source_review_valid")))
    for path in root.glob("*/**/_annotations.coco.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        images = data.get("images", [])
        report["datasets"].append({"path": path.relative_to(root).as_posix(), "images": len(images),
            "annotations": len(data.get("annotations", [])), "categories": [c.get("name") for c in data.get("categories", [])],
            "specimen_ids_present": all(bool(image.get("specimen_id")) for image in images) if images else False,
            "whole_fish_feature_reference_records": 0})
    report["limitations"] = ["Part annotations are not verified whole-fish feature-to-grade reference distributions.",
        "Known physical specimen, capture and duplicate-family IDs are required before partitioning.",
        "Calibrated size endpoints/widths, crack nuisance negatives, lighting-aware color and texture validation are required.",
        "No calibration or accuracy improvement is inferred from saved AI predictions."]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit")
    audit.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    audit.add_argument("--output", type=Path, required=True)
    template = commands.add_parser("template")
    template.add_argument("--output", type=Path, required=True)
    export = commands.add_parser("export-reviews")
    export.add_argument("--database", type=Path, required=True)
    export.add_argument("--identities", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    for name in ("fit", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        if name == "evaluate":
            command.add_argument("--artifact", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "audit":
        result = audit_existing(args.root)
    elif args.command == "template":
        result = {"schema_version": "decision_fusion_records_v1", "records": [],
                  "required_record_fields": ["specimen_id", "capture_group_id", "duplicate_group_id", "image_sha256", "split", "annotator_verified", "annotator_id", "review_id", "human_grade", "original_ai_prediction", "ai_baseline", "measurements", "model_context", "anatomical_policy", "source", "fish_id", "frame_id"],
                  "notes": ["No example labels or measurements are approved.", "Use original runtime fusion measurements and separate verified human labels; never use AI grades as truth.", "Assign one representative per physical specimen; reserve independent capture/duplicate families for calibration, validation and test."]}
    elif args.command == "export-reviews":
        result = export_review_records(args.database, json.loads(args.identities.read_text(encoding="utf-8"))["identities"])
    else:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != "decision_fusion_records_v1":
            raise ValueError("Expected decision_fusion_records_v1 manifest.")
        records = manifest["records"]
        config = load_decision_fusion_config()
        result = fit_calibration(records, config) if args.command == "fit" else evaluate_calibration(records, json.loads(args.artifact.read_text(encoding="utf-8")), config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"{args.command}: {args.output}")
    if args.command == "fit":
        print("Validation passed; runtime-eligible artifact." if result["validation"]["passed"] else "Validation did not pass; runtime will withhold this artifact.")


if __name__ == "__main__":
    main()
