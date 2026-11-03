"""Check a reviewed feature catalog without inventing labels or activating it.

Create an empty template:
  python -m src.evaluation.review_structural_features --template review.json
Audit supplied reference artifacts:
  python -m src.evaluation.review_structural_features --validate review.json --report qa.json
Original photographs, annotations, and reference masks are read-only inputs.
Passing these artifact checks is not independent scientific validation.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np


def reference_template():
    return {"schema_version": "reviewed_feature_records_v1", "reference_set_id": None,
            "independent_validation_description": None,
            "instructions": ["Add reviewed records with source_id, fish_id and SHA-256 of native BGR frame bytes.",
                "Use original_image_path plus full-original-frame binary whole_mask_path/body_mask_path PNGs.",
                "Record reviewer, review_id, reference_set_id; separate calibration/validation source photographs.",
                "Structural evidence needs reviewed localized Body cracks and reviewed severity or reviewed normalized ranges.",
                "Do not copy software fixture labels or thresholds into calibration. This tool never enables grading."],
            "record_example_not_approved": {"source_id": None, "frame_pixels_sha256": None, "fish_id": None,
                "original_image_path": None, "whole_mask_path": None, "body_mask_path": None,
                "validation_provenance": {"reviewer": None, "review_id": None, "reference_set_id": None},
                "split": None, "structural_evidence": {"status": "unconfirmed", "reviewed": False,
                    "severity": "unassessed", "severity_reviewed": False, "region": "Body",
                    "ownership_validated": False, "body_mask_validated": False, "measurement_validated": False,
                    "parent_track_id": None, "frame_id": None, "source_id": None, "frame_pixels_sha256": None,
                    "clipped": None, "overlapping": None, "ownership_ambiguous": None, "partial_silhouette": None,
                    "validation_provenance": {"reviewer": None, "review_id": None, "reference_set_id": None},
                    "coordinate_space": "original_frame", "locations": [], "measurements": {}}}, "records": []}


def validate_reference_package(package, *, base_dir):
    issues, reviewed, splits, source_sets = [], [], Counter(), {}
    if not isinstance(package, dict) or package.get("schema_version") != "reviewed_feature_records_v1":
        return {"artifact_checks_passed": False, "issues": ["Expected reviewed_feature_records_v1 catalog."],
                "automatic_activation_performed": False, "scientific_accuracy_validated": False}
    records = package.get("records")
    if not isinstance(records, list) or not records:
        issues.append("No reviewed reference records supplied.")
        records = []
    reference_id = package.get("reference_set_id")
    if not isinstance(reference_id, str) or not reference_id.strip():
        issues.append("A reviewed reference_set_id is required.")
    def resolve(value):
        if not isinstance(value, str) or not value.strip():
            return None
        path = Path(value)
        return path if path.is_absolute() else Path(base_dir) / path
    for index, record in enumerate(records):
        row_issues = []
        if not isinstance(record, dict):
            issues.append(f"Record {index}: object required.")
            continue
        owner = record.get("fish_id")
        if isinstance(owner, bool) or not isinstance(owner, int):
            row_issues.append("fish_id must be the recorded Model 1 integer ID")
        if not isinstance(record.get("source_id"), str) or not record["source_id"].strip():
            row_issues.append("source_id is missing")
        paths = {name: resolve(record.get(name)) for name in ("original_image_path", "whole_mask_path", "body_mask_path")}
        arrays = {}
        for name, path in paths.items():
            if path is None or not path.is_file():
                row_issues.append(f"{name} file is unavailable")
                continue
            array = cv2.imread(str(path), cv2.IMREAD_COLOR if name == "original_image_path" else cv2.IMREAD_GRAYSCALE)
            if array is None:
                row_issues.append(f"{name} is not a decodable image")
            elif name != "original_image_path" and (not np.isin(array, (0,1,255)).all() or not array.any()):
                row_issues.append(f"{name} must be a nonempty binary native-frame mask")
            else:
                arrays[name] = array
        image = arrays.get("original_image_path")
        digest = None
        if image is not None:
            digest = hashlib.sha256(np.ascontiguousarray(image).tobytes()).hexdigest()
            if digest != record.get("frame_pixels_sha256"):
                row_issues.append("original native BGR frame digest does not match")
            for name in ("whole_mask_path", "body_mask_path"):
                if name in arrays and arrays[name].shape != image.shape[:2]:
                    row_issues.append(f"{name} dimensions differ from original native frame")
        whole, body = arrays.get("whole_mask_path"), arrays.get("body_mask_path")
        if whole is not None and body is not None and whole.shape == body.shape and np.any((body != 0) & (whole == 0)):
            row_issues.append("reviewed Body pixels extend outside the reviewed whole-fish mask")
        provenance = record.get("validation_provenance")
        if not isinstance(provenance, dict) or any(not isinstance(provenance.get(key), str) or not provenance[key].strip()
                                                  for key in ("reviewer", "review_id", "reference_set_id")):
            row_issues.append("explicit reviewer/reference provenance is missing")
        elif provenance["reference_set_id"] != reference_id:
            row_issues.append("record and catalog reference sets differ")
        split = record.get("split")
        if split not in {"calibration", "validation"}:
            row_issues.append("split must explicitly be calibration or validation")
        else:
            splits[split] += 1
            if digest:
                source_sets.setdefault(digest, set()).add(split)
        evidence = record.get("structural_evidence")
        if evidence is not None:
            if not isinstance(evidence, dict):
                row_issues.append("structural_evidence must be an explicit reviewed record")
            else:
                for key in ("source_id", "frame_pixels_sha256"):
                    if evidence.get(key) != record.get(key):
                        row_issues.append(f"structural evidence {key} differs from its source record")
                if evidence.get("parent_track_id", evidence.get("fish_id")) != owner:
                    row_issues.append("structural evidence belongs to another fish")
                if evidence.get("status") != "confirmed" or evidence.get("reviewed") is not True:
                    row_issues.append("crack confirmation is absent; candidate evidence cannot calibrate severity")
                if evidence.get("severity") not in {"minor", "moderate", "major", "none"} or evidence.get("severity_reviewed") is not True:
                    row_issues.append("expert severity label is absent")
                for flag in ("ownership_validated", "body_mask_validated", "measurement_validated"):
                    if evidence.get(flag) is not True:
                        row_issues.append(f"reviewed crack flag {flag} is absent")
                if evidence.get("coordinate_space") != "original_frame" or not isinstance(evidence.get("locations"), list):
                    row_issues.append("localized original-frame crack evidence is absent")
                severity = evidence.get("severity")
                if severity != "none" and not evidence.get("locations"):
                    row_issues.append("positive crack labels require localized original-frame evidence")
                approval = evidence.get("validation_provenance")
                if (not isinstance(approval, dict) or any(not isinstance(approval.get(key), str) or not approval[key].strip()
                    for key in ("reviewer", "review_id", "reference_set_id"))
                        or approval.get("reference_set_id") != reference_id):
                    row_issues.append("structural severity review provenance differs from the reference catalog")
                for location in evidence.get("locations", []) if isinstance(evidence.get("locations"), list) else []:
                    values = [location.get(key) for key in ("x", "y", "width", "height")] if isinstance(location, dict) else []
                    if (len(values) != 4 or any(isinstance(v, bool) or not isinstance(v, (int,float)) or not math.isfinite(v) for v in values)
                            or values[0] < 0 or values[1] < 0 or values[2] <= 0 or values[3] <= 0):
                        row_issues.append("structural localization contains a malformed rectangle")
                        continue
                    x, y, width, height = values
                    if image is not None and (x+width > image.shape[1] or y+height > image.shape[0]):
                        row_issues.append("structural localization is outside the original frame")
                    elif body is not None and not body[int(y):int(np.ceil(y+height)),int(x):int(np.ceil(x+width))].any():
                        row_issues.append("structural localization has no reviewed Body pixel support")
        reviewed.append({"record_index": index, "fish_id": owner, "source_id": record.get("source_id"),
                         "frame_pixels_sha256": digest, "artifact_checks_passed": not row_issues, "issues": row_issues})
        issues.extend(f"Record {index}: {message}." for message in row_issues)
    if any(len(split_set) > 1 for split_set in source_sets.values()):
        issues.append("The same source pixels occur in calibration and validation splits.")
    if not splits.get("calibration") or not splits.get("validation"):
        issues.append("Separate source photographs for calibration and held-out validation are still needed.")
    return {"schema_version": "structural_reference_audit_v1", "reference_set_id": reference_id,
            "artifact_checks_passed": not issues, "issues": issues, "record_count": len(records),
            "split_counts": dict(splits), "records": reviewed, "automatic_activation_performed": False,
            "scientific_accuracy_validated": False,
            "next_steps": ["An expert must review masks, crack causes, severity and normalized measurements.",
                "Evaluate held-out crack precision/recall, scale/shadow false positives and grade-eligibility outcomes.",
                "Record the applicable quality standard and policy approval before enabling structural_features.yaml.",
                "Artifact integrity checks and synthetic tests do not establish feature accuracy."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--template", type=Path)
    mode.add_argument("--validate", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.template:
        if args.template.exists():
            parser.error("Refusing to overwrite an existing reference catalog")
        args.template.parent.mkdir(parents=True, exist_ok=True)
        args.template.write_text(json.dumps(reference_template(), indent=2)+"\n", encoding="utf-8")
        print(json.dumps({"template": str(args.template), "approved_records": 0, "grading_enabled": False}))
        return
    result = validate_reference_package(json.loads(args.validate.read_text(encoding="utf-8")), base_dir=args.validate.parent)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
