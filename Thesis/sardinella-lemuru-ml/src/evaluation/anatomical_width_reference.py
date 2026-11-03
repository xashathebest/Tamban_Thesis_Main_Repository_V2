"""Prepare reviewed anatomical references without selecting or enabling rules.

``template --output review.json`` writes an empty review worksheet.
``evaluate --input review.json --output report.json`` checks reviewed records
and explicit expert-selected limits. It never edits runtime configuration,
source annotations, model weights, or approves its own measured masks.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median

from src.inference.body_width import BodyWidthConfig


METRIC = "body_width_to_fish_length_ratio"


def review_template():
    return {"schema_version": "anatomical_width_reference_v1", "metric": METRIC,
        "instructions": "Add independently reviewed specimen records, reference/validation split and review-selected limits. No measurements or limits are supplied by this template.",
        "required_record_fields": ["specimen_id", "image_sha256", "capture_session", "source_id", "split",
            "reviewer", "review_reference", "measurement_validated", "ownership_validated", "body_region_validated",
            "fish_length_px", "max_body_width_px", "manual_width_label"],
        "records": [], "calibration_review": {"approved": False, "calibration_id": None,
            "source_id": None, "reviewer": None, "review_reference": None, "held_out_grade_report": None,
            "normal_reference_min": None, "normal_reference_max": None, "extreme_reference": None}}


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() not in {"unknown", "todo", "n/a"}


def _positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def evaluate_reference(payload):
    if not isinstance(payload, dict) or payload.get("metric") != METRIC or not isinstance(payload.get("records"), list):
        raise ValueError("Provide a reviewed anatomical-width reference worksheet with the declared metric.")
    normalized, identities, images, sessions = [], set(), set(), {}
    for index, record in enumerate(payload["records"]):
        if not isinstance(record, dict):
            raise ValueError(f"Record {index} must be a reviewed object.")
        for key in ("specimen_id", "image_sha256", "capture_session", "source_id", "reviewer", "review_reference"):
            if not _text(record.get(key)):
                raise ValueError(f"Record {index} requires {key}.")
        if record["specimen_id"] in identities or record["image_sha256"] in images:
            raise ValueError("Duplicate specimens or repeated source images cannot count as independent references.")
        digest = record["image_sha256"]
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest.lower()):
            raise ValueError("image_sha256 must be an actual 64-character SHA-256 digest.")
        if record.get("split") not in {"reference", "validation"} or record.get("manual_width_label") not in {"normal", "widened"}:
            raise ValueError("Each record requires reference/validation split and a reviewed normal/widened label.")
        for flag in ("measurement_validated", "ownership_validated", "body_region_validated"):
            if record.get(flag) is not True:
                raise ValueError(f"Record {index} has no reviewed {flag} approval.")
        if not _positive(record.get("fish_length_px")) or not _positive(record.get("max_body_width_px")):
            raise ValueError("Reference lengths and widths must be finite, positive native-pixel measurements.")
        ratio = record["max_body_width_px"] / record["fish_length_px"]
        if not 0 < ratio < 1:
            raise ValueError("Reference Body width must be smaller than longitudinal fish length.")
        previous = sessions.setdefault(record["capture_session"], record["split"])
        if previous != record["split"]:
            raise ValueError("A capture session must not cross reference and held-out validation splits.")
        identities.add(record["specimen_id"]); images.add(digest)
        normalized.append({**record, "ratio": ratio})
    review = payload.get("calibration_review", {})
    if not isinstance(review, dict):
        raise ValueError("calibration_review must be an explicit review object.")
    sources = {row["source_id"] for row in normalized}
    if len(sources) > 1:
        raise ValueError("Separate reference worksheets are required for different cameras, perspective or acquisition contexts.")
    reference = [row for row in normalized if row["split"] == "reference"]
    normal = [row for row in reference if row["manual_width_label"] == "normal"]
    wide = [row for row in reference if row["manual_width_label"] == "widened"]
    validation = [row for row in normalized if row["split"] == "validation"]
    needed = []
    if not normal: needed.append("Reviewed normal-width native measurements")
    if not wide: needed.append("Reviewed widened-Body native measurements")
    if not validation: needed.append("Independent held-out capture-session measurements and grade comparison")
    if review.get("approved") is not True: needed.append("Explicit expert approval of reference limits")
    for key in ("calibration_id", "source_id", "reviewer", "review_reference", "held_out_grade_report"):
        if not _text(review.get(key)): needed.append(f"Recorded {key}")
    limits = [review.get(key) for key in ("normal_reference_min", "normal_reference_max", "extreme_reference")]
    if (any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in limits)
            or not 0 <= limits[0] <= limits[1] < limits[2] <= 1):
        needed.append("Explicit expert-selected normal and extreme reference limits")
    if normalized and review.get("source_id") != normalized[0]["source_id"]:
        needed.append("Calibration capture context matching reviewed measurements")
    configuration = None
    if not needed:
        configuration = BodyWidthConfig(scoring_enabled=False, calibration_validated=True,
            calibration_id=review["calibration_id"], validation_sample_count=len(normalized),
            normal_reference_min=review.get("normal_reference_min"), normal_reference_max=review.get("normal_reference_max"),
            extreme_reference=review.get("extreme_reference"), reference_metric=METRIC,
            reference_source_id=review["source_id"],
            reference_review_provenance=f"{review['reviewer']}: {review['review_reference']}; held-out comparison: {review['held_out_grade_report']}",
            reference_distribution=tuple(row["ratio"] for row in normal),
            reference_sample_ids=tuple(row["specimen_id"] for row in normal)).to_dict()
    def distribution(rows):
        values = [row["ratio"] for row in rows]
        return {"count": len(values), "values": values, "min": min(values) if values else None,
                "max": max(values) if values else None, "median": median(values) if values else None}
    return {"metric": METRIC, "record_count": len(normalized), "normal_reference": distribution(normal),
            "widened_reference": distribution(wide), "held_out_count": len(validation),
            "data_still_needed": needed, "calibration_validated": configuration is not None,
            "thresholds_selected_by_program": False, "automatic_grading_enabled": False,
            "reviewed_configuration_proposal": configuration,
            "note": "Review flags and selected limits are external evidence, not scientific validation performed by this program. Runtime activation requires a separate reviewed configuration change."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    template = subparsers.add_parser("template"); template.add_argument("--output", required=True, type=Path)
    evaluate = subparsers.add_parser("evaluate"); evaluate.add_argument("--input", required=True, type=Path); evaluate.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "template": result = review_template()
    else:
        if args.input.resolve() == args.output.resolve(): parser.error("Output must not overwrite the reviewed input worksheet.")
        result = evaluate_reference(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    main()
