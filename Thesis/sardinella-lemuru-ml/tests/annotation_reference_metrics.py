"""Reproduce reference metrics from saved predictions, without model inference.

Run ``python tests/annotation_reference_metrics.py --verify-store`` from the
project root. Only ignored QA reports are written; source data and SQLite are
opened read only. These development-reference metrics are not independent
model accuracy or verified whole-fish ownership measurements.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.annotation.masks import coco_segmentation_to_mask, segmentation_to_mask
from src.annotation.store import AnnotationStore

OUTPUT = ROOT / "results/qa/annotation_workflow"
SOURCE = ROOT / "Dried Fish Quality Grading.v7i.coco-segmentation"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_report(name, report):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / name).write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")


def axis_aligned_rectangle(segmentation):
    """Recognize an open or closed four-corner ring, counting unique vertices.

    COCO exports commonly repeat the first point as the fifth point. That
    closing point must not cause an ordinary box to count as a real boundary.
    An axis-aligned bowtie has the same corners but is not a rectangle ring.
    """
    if not isinstance(segmentation, list) or len(segmentation) != 1:
        return False
    ring = segmentation[0]
    if not isinstance(ring, list) or len(ring) < 8 or len(ring) % 2:
        return False
    points = [tuple(ring[index:index + 2]) for index in range(0, len(ring), 2)]
    while len(points) > 1 and points[-1] == points[0]:
        points.pop()
    unique = set(points)
    if len(unique) != 4 or len({p[0] for p in unique}) != 2 or len({p[1] for p in unique}) != 2:
        return False
    area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2
    x_values, y_values = [p[0] for p in unique], [p[1] for p in unique]
    rectangle_area = (max(x_values) - min(x_values)) * (max(y_values) - min(y_values))
    return rectangle_area > 0 and math.isclose(area, rectangle_area, rel_tol=0, abs_tol=1e-8)


def self_tests():
    assert axis_aligned_rectangle([[0, 0, 5, 0, 5, 3, 0, 3]])
    assert axis_aligned_rectangle([[0, 0, 5, 0, 5, 3, 0, 3, 0, 0]])
    assert axis_aligned_rectangle([[0, 0, 0, 3, 5, 3, 5, 0, 0, 0]])
    assert not axis_aligned_rectangle([[0, 0, 5, 3, 5, 0, 0, 3, 0, 0]])
    assert not axis_aligned_rectangle([[0, 0, 5, 0, 4, 3, 0, 3, 0, 0]])
    assert not axis_aligned_rectangle([[0, 0, 5, 0, 0, 3, 0, 0]])
    matches = match_boxes([[0, 0, 10, 10]], [[0, 0, 10, 10], [0, 0, 10, 10]])
    assert matches == [(0, 0, 1.0)], "A GT instance cannot match two predictions."
    assert not match_boxes([[0, 0, 10, 10]], [[30, 30, 40, 40]])
    return {"passed": True, "assertions": 8}


def box_iou(first, second):
    x1, y1 = max(first[0], second[0]), max(first[1], second[1])
    x2, y2 = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0., x2 - x1) * max(0., y2 - y1)
    first_area = max(0., first[2] - first[0]) * max(0., first[3] - first[1])
    second_area = max(0., second[2] - second[0]) * max(0., second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.


def match_boxes(truth, predictions, threshold=.5):
    """Deterministic greedy highest-IoU, class-agnostic one-to-one matching."""
    candidates = [(box_iou(t, p), i, j) for i, t in enumerate(truth) for j, p in enumerate(predictions)]
    matched_truth, matched_predictions, matches = set(), set(), []
    for overlap, i, j in sorted(candidates, key=lambda item: (-item[0], item[1], item[2])):
        if overlap < threshold:
            break
        if i not in matched_truth and j not in matched_predictions:
            matched_truth.add(i)
            matched_predictions.add(j)
            matches.append((i, j, overlap))
    return matches


def reference_metrics():
    source_path = SOURCE / "test/_annotations.coco.json"
    source = json.loads(source_path.read_bytes())
    images = {image["file_name"]: image for image in source["images"]}
    annotations = {image["id"]: [] for image in source["images"]}
    for annotation in source["annotations"]:
        annotations[annotation["image_id"]].append(annotation)
    nonrectangular = [a for a in source["annotations"] if not axis_aligned_rectangle(a["segmentation"])]
    assert len(nonrectangular) == 6, "Source boundary coverage changed; inspect before interpreting metrics."
    result = {"schema_version": 2, "method": "test split only; greedy descending-IoU class-agnostic one-to-one detector boxes",
              "source_sha256": digest(source_path.read_bytes()), "manual_test_images": len(images),
              "manual_test_annotations": len(source["annotations"]),
              "manual_test_nonrectangular_annotations": len(nonrectangular),
              "nonrectangular_source_annotation_ids": [a["id"] for a in nonrectangular],
              "rectangle_filter": "one ring; remove repeated closing point; four unique axis-aligned corners and full rectangle area",
              "self_tests": self_tests()}
    for name in ("real_models", "real_annotation_incumbent"):
        directory = OUTPUT / name
        report = json.loads((directory / "report.json").read_bytes())
        assert report["source_before"] == report["source_after"], "Inference QA reported a modified manual source."
        assert report["source_before"]["test"] == result["source_sha256"], "Saved predictions reference different manual test labels."
        cases = [case for case in report["cases"] if case["source_split"] == "test"]
        assert len(cases) == len(images) and len({case["filename"] for case in cases}) == len(images)
        match_count, correct_count, predictions_count = 0, 0, 0
        nonrect_results, inputs, per_case = [], [], []
        for case in cases:
            path = directory / (case["case"] + ".json")
            saved = json.loads(path.read_bytes())
            image = images[case["filename"]]
            truth = annotations[image["id"]]
            parts = [ann for ann in saved["annotations"] if "model_class_id" in ann.get("metadata", {})]
            boxes = [[a["bbox"][0], a["bbox"][1], a["bbox"][0] + a["bbox"][2], a["bbox"][1] + a["bbox"][3]] for a in truth]
            matches = match_boxes(boxes, [a["metadata"]["detector_bbox_xyxy"] for a in parts])
            predictions_count += len(parts)
            by_truth = {i: (j, overlap) for i, j, overlap in matches}
            correct = sum(truth[i]["category_id"] == parts[j]["class_id"] for i, j, _ in matches)
            match_count += len(matches)
            correct_count += correct
            per_case.append({"case": case["case"], "matches": len(matches), "correct_classes": correct})
            inputs.append({"case": case["case"], "sha256": digest(path.read_bytes())})
            for i, actual in enumerate(truth):
                if axis_aligned_rectangle(actual["segmentation"]):
                    continue
                item = {"case": case["case"], "source_annotation_id": actual["id"], "matched": i in by_truth,
                        "class_correct": False, "mask_iou": None}
                if i in by_truth:
                    j, overlap = by_truth[i]
                    predicted = parts[j]
                    item.update({"prediction_id": predicted["id"], "box_iou": overlap,
                                 "class_correct": actual["category_id"] == predicted["class_id"]})
                    if item["class_correct"] and predicted.get("segmentation"):
                        expected = coco_segmentation_to_mask(actual["segmentation"], image["height"], image["width"]) != 0
                        mask = segmentation_to_mask(predicted["segmentation"], image["height"], image["width"]) != 0
                        intersection, union = np.count_nonzero(expected & mask), np.count_nonzero(expected | mask)
                        item["mask_iou"] = float(intersection / union) if union else None
                nonrect_results.append(item)
        values = [row["mask_iou"] for row in nonrect_results if row["mask_iou"] is not None]
        result[name] = {"report_sha256": digest((directory / "report.json").read_bytes()), "prediction_inputs": inputs,
                        "box_match_IoU_threshold": .5, "test_prediction_parts": predictions_count,
                        "class_agnostic_box_matches": match_count, "correct_classes": correct_count,
                        "matched_part_class_accuracy": correct_count / match_count if match_count else None,
                        "nonrectangular_GT_box_matches": sum(row["matched"] for row in nonrect_results),
                        "nonrectangular_GT_class_correct_matches": sum(row["class_correct"] for row in nonrect_results),
                        "nonrectangular_GT_class_correct_matched_masks": len(values),
                        "nonrectangular_GT_matched_mask_IoU_values": values,
                        "mean_matched_nonrectangular_mask_IoU": sum(values) / len(values) if values else None,
                        "nonrectangular_outcomes": nonrect_results, "per_case": per_case}
    result["limitations"] = [
        "Development-reference part metrics only: source has historical training overlap and is not independent accuracy evidence.",
        "Part class accuracy is conditional on class-agnostic one-to-one detector box IoU >= 0.5; unmatched parts are excluded.",
        "Only six test masks are nonrectangular. Mask IoU further excludes unmatched, incorrect-class, and missing-mask predictions; it is not dataset-wide mask accuracy.",
        "Nonrectangular manual polygons are reference shapes, not independently audited pixel-perfect anatomical boundaries.",
        "No independently verified whole-fish ownership/silhouette ground truth or measured human annotation correction rate.",
        "Predictions remain unreviewed QA artifacts and are never saved as verified training labels."]
    write_report("reference_part_metrics.json", result)
    return result


class ReadOnlyStore(AnnotationStore):
    @contextmanager
    def _db(self, write=False):
        if write:
            raise AssertionError("QA must never write the default annotation store.")
        database = sqlite3.connect((self.root / "annotations.sqlite3").as_uri() + "?mode=ro", uri=True)
        try:
            database.execute("PRAGMA query_only=ON")
            yield database
        finally:
            database.close()


def store_snapshot():
    store = ReadOnlyStore(ROOT / "dataset/annotation_workspace", SOURCE)
    with store._db() as database:
        documents = [json.loads(row[0]) for row in database.execute("SELECT document FROM images ORDER BY id")]
        revisions = database.execute("SELECT image_id,revision,document FROM revisions ORDER BY image_id,revision").fetchall()
        imports = dict(database.execute("SELECT import_key,image_id FROM imports"))
        sqlite_integrity = database.execute("PRAGMA integrity_check").fetchone()[0]
    snapshot = json.loads((OUTPUT / "source_integrity_before.json").read_bytes())
    source_changed = [entry["path"] for entry in snapshot["files"]
                      if not (ROOT / entry["path"]).is_file() or digest((ROOT / entry["path"]).read_bytes()) != entry["sha256"]]
    errors, masks_checked, pngs_checked, metadata_checked, import_keys = [], 0, 0, 0, set()
    sources, source_hashes = {}, {}
    def issue(image_id, message, annotation_id=None):
        errors.append({"image_id": image_id, "annotation_id": annotation_id, "message": message})
    for split in ("train", "valid", "test"):
        raw = (SOURCE / split / "_annotations.coco.json").read_bytes()
        data = json.loads(raw)
        source_hashes[split] = digest(raw)
        sources[split] = {"images": {image["id"]: image for image in data["images"]},
                          "annotations": {annotation["id"]: annotation for annotation in data["annotations"]},
                          "categories": {category["id"]: category for category in data["categories"]}}
    for document in documents:
        baseline = document.get("baseline")
        if not baseline:
            issue(document["id"], "Expected an immutable manual baseline.")
            continue
        source = sources[baseline["split"]]
        original_image = source["images"][baseline["source_image_id"]]
        if document.get("source_record") != original_image:
            issue(document["id"], "Original image metadata differs from source COCO.")
        key = f"{source_hashes[baseline['split']]}:{baseline['split']}:{baseline['source_image_id']}"
        import_keys.add(key)
        if imports.get(key) != document["id"]:
            issue(document["id"], "Import idempotence key does not resolve to this existing image.")
        source_path = SOURCE / baseline["split"] / original_image["file_name"]
        if digest(source_path.read_bytes()) != document["image_sha256"]:
            issue(document["id"], "Original source image bytes differ from preserved original digest.")
        if baseline["sha256"] != source_hashes[baseline["split"]]:
            issue(document["id"], "Baseline hash differs from original COCO.")
        for annotation in document["annotations"]:
            original = source["annotations"][annotation["source_annotation_id"]]
            if annotation["original_annotation"] != original or annotation["source_category"] != source["categories"][original["category_id"]] or annotation["class_id"] != original["category_id"]:
                issue(document["id"], "Original annotation/category metadata differs from source COCO.", annotation["id"])
            metadata_checked += 1
            expected = coco_segmentation_to_mask(original["segmentation"], document["height"], document["width"]) != 0
            current = segmentation_to_mask(annotation["segmentation"], document["height"], document["width"]) != 0
            png = cv2.imread(str(store.root / annotation["mask_path"]), cv2.IMREAD_GRAYSCALE)
            if not np.array_equal(current, expected):
                issue(document["id"], "Current segmentation pixels differ from original COCO.", annotation["id"])
            if png is None or not np.array_equal(png != 0, expected):
                issue(document["id"], "Saved mask PNG pixels differ from original COCO.", annotation["id"])
            masks_checked += 1
            pngs_checked += 1
    validation = store.validate()
    with store._db() as database:
        after = database.execute("SELECT image_id,revision,document FROM revisions ORDER BY image_id,revision").fetchall()
    revisions_unchanged = revisions == after
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "mode": "read-only SQLite URI; original COCO/images read only",
              "root": str(store.root), "sqlite_integrity": sqlite_integrity,
              "image_count": len(documents), "annotation_count": sum(len(document["annotations"]) for document in documents),
              "image_status_counts": dict(Counter(document["status"] for document in documents)),
              "annotation_status_counts": dict(Counter(annotation["status"] for document in documents for annotation in document["annotations"])),
              "split_counts": dict(Counter(document["split"] for document in documents)),
              "revision_count": len(revisions), "revision_numbers": dict(Counter(str(document["revision"]) for document in documents)),
              "source_files_checked": len(snapshot["files"]), "changed_or_missing_source_files": source_changed,
              "source_coco_sha256": source_hashes, "source_annotation_metadata_checked": metadata_checked,
              "current_masks_compared_to_original_COCO": masks_checked, "saved_PNG_masks_compared_to_original_COCO": pngs_checked,
              "parity_errors": errors, "read_only_import_idempotence": {"expected_keys": len(import_keys), "existing_keys": len(imports),
                  "all_keys_already_present": import_keys == set(imports), "reimport_executed": False,
                  "method": "All deterministic hash:split:source_image_id import keys resolve to existing image IDs; no importer mutation called."},
              "revisions_unchanged_by_QA": revisions_unchanged,
              "validation": {**validation, "warning_count": len(validation["warnings"]), "warnings": validation["warnings"][:25],
                             "warning_messages": dict(Counter(w["message"] for w in validation["warnings"]))},
              "passed": sqlite_integrity == "ok" and not source_changed and not errors and validation["valid"] and revisions_unchanged and import_keys == set(imports)}
    write_report("final_default_store_snapshot.json", result)
    assert result["passed"], "Read-only default dataset verification failed; inspect report."
    return result


def main():
    # Thousands of small masks are faster without per-mask native thread pools.
    cv2.setNumThreads(1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-store", action="store_true", help="Also inspect all persisted default manual images and masks read only.")
    arguments = parser.parse_args()
    metrics = reference_metrics()
    summary = {name: {key: metrics[name][key] for key in ("class_agnostic_box_matches", "correct_classes", "matched_part_class_accuracy",
                "nonrectangular_GT_class_correct_matched_masks", "mean_matched_nonrectangular_mask_IoU")}
               for name in ("real_models", "real_annotation_incumbent")}
    if arguments.verify_store:
        snapshot = store_snapshot()
        summary["default_store"] = {key: snapshot[key] for key in ("image_count", "annotation_count", "passed")}
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
