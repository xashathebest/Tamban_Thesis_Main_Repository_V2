"""Explicit primary-baseline model QA; predictions stay quarantined and unreviewed.

Run --prepare to inspect the primary test contact sheet, then pass --image-ids
with visually inspected IDs. This script never changes original data, model
weights, or the canonical annotation database. Metrics describe this small
development sample, not independent generalization or an improvement claim.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import traceback
import zipfile

os.environ["CUDA_VISIBLE_DEVICES"] = ""
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
import torch

from src.annotation.masks import coco_segmentation_to_mask, segmentation_to_mask
from src.annotation.primary_baseline import CATEGORY_ALIASES
from src.api.annotation_automation import generate_annotations
from src.evaluation.comparison_protocol import evaluate_boxes
from src.inference.mobilesam_backend import MobileSamService, MobileSamSettings
from src.inference.model_registry import get_model_registry
from src.inference.yolo_fish_detector import YoloFishDetector
from src.preprocessing.audit_v7_exports import SOURCE_NAME_TO_ID

ARCHIVE = Path("C:/Users/User/Downloads/Tamban_Thesis_Main_Repository/Fish_Annotations_Cleaned.zip")
OUTPUT = ROOT / "results/qa/annotation_workflow/primary_real_models"
WORKSPACE = ROOT / "dataset/annotation_workspace"
SCENE_REVIEWS = {
    331: "One clearly visible isolated fish, horizontal orientation, head at right; three manually annotated parts.",
    324: "Crowded crossing fish with horizontal, diagonal and near-vertical orientations; occlusion and lower-frame clipping.",
    337: "Multiple diagonal and near-vertical fish with crossings; top and lower edges clip fish, including a lower fish head.",
    338: "Three mostly horizontal fish; the left-facing fish head intersects the left frame boundary and fish overlap locally.",
    334: "Five mostly horizontal fish with local overlaps and a diagonal fish at right; source includes the only Grade_B head/body pair in the primary test split.",
}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def read_primary():
    with zipfile.ZipFile(ARCHIVE) as archive:
        raw = archive.read("clean_segmentation.json")
        coco = json.loads(raw)
        provenance = {row["image"]: row for row in json.loads(archive.read("provenance.json"))}
    return coco, provenance, hashlib.sha256(raw).hexdigest()


def prepare(coco, provenance):
    by_image = Counter(a["image_id"] for a in coco["annotations"])
    images = [row for row in coco["images"] if provenance[row["file_name"]]["original_splits"] == ["test"]]
    images.sort(key=lambda row: row["id"])
    cells = []
    with zipfile.ZipFile(ARCHIVE) as archive:
        for image in images:
            frame = cv2.imdecode(np.frombuffer(archive.read(image["file_name"]), np.uint8), cv2.IMREAD_COLOR)
            assert frame is not None and frame.shape[:2] == (image["height"], image["width"])
            thumbnail = cv2.resize(frame, (960, 540))
            cv2.imwrite(str(OUTPUT / f"source_{image['id']}.jpg"), thumbnail)
            cell = cv2.resize(frame, (480, 270))
            label = np.full((34, 480, 3), 245, np.uint8)
            cv2.putText(label, f"test image {image['id']} / {by_image[image['id']]} manual parts", (8, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, .65, (10, 10, 10), 1, cv2.LINE_AA)
            cells.append(np.vstack((label, cell)))
    while len(cells) % 4:
        cells.append(np.full_like(cells[0], 245))
    sheet = np.vstack([np.hstack(cells[index:index + 4]) for index in range(0, len(cells), 4)])
    cv2.imwrite(str(OUTPUT / "test_contact_sheet.jpg"), sheet)
    (OUTPUT / "test_inventory.json").write_text(json.dumps([
        {**image, "manual_parts": by_image[image["id"]], "provenance": provenance[image["file_name"]]}
        for image in images], indent=2), encoding="utf-8")
    print(json.dumps({"test_images": len(images), "contact_sheet": str(OUTPUT / "test_contact_sheet.jpg")}), flush=True)


def ready_profile():
    database = sqlite3.connect((WORKSPACE / "annotations.sqlite3").as_uri() + "?mode=ro", uri=True)
    try:
        database.execute("PRAGMA query_only=ON")
        row = database.execute("SELECT value FROM meta WHERE key='primary_learning_dataset'").fetchone()
        profile = json.loads(row[0]) if row else None
        classes = [json.loads(row[0]) for row in database.execute("SELECT document FROM classes ORDER BY id")]
        assignments = {int(row[0]): row[1] for row in database.execute(
            "SELECT json_extract(document,'$.baseline.source_image_id'),COALESCE(json_extract(document,'$.metadata.protected_split'),json_extract(document,'$.split')) FROM images "
            "WHERE json_extract(document,'$.baseline.dataset_id')=?", (profile["dataset_id"],))} if profile else {}
    finally:
        database.close()
    if not profile or profile.get("status") != "ready":
        raise RuntimeError("Selected primary baseline is not ready; rerun after the import completes.")
    if profile.get("source_sha256") != digest(ARCHIVE):
        raise RuntimeError("Ready profile does not identify the selected original primary archive.")
    reference = WORKSPACE / profile["reference_profile_path"]
    descriptor = json.loads(reference.read_bytes())
    assert all(row["split"] == "train" for rows in descriptor["classes"].values() for row in rows)
    return profile, classes, reference, assignments


def box_iou(first, second):
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0., right - left) * max(0., bottom - top)
    area_first = max(0., first[2] - first[0]) * max(0., first[3] - first[1])
    area_second = max(0., second[2] - second[0]) * max(0., second[3] - second[1])
    union = area_first + area_second - intersection
    return intersection / union if union else 0.


def matches(truth, predictions, threshold=.5):
    candidates = [(box_iou(t, p), i, j) for i, t in enumerate(truth) for j, p in enumerate(predictions)]
    used_truth, used_predictions, output = set(), set(), []
    for overlap, i, j in sorted(candidates, key=lambda item: (-item[0], item[1], item[2])):
        if overlap < threshold:
            break
        if i not in used_truth and j not in used_predictions:
            used_truth.add(i)
            used_predictions.add(j)
            output.append((i, j, overlap))
    return output


def run(coco, provenance, source_coco_sha, image_ids):
    from src.annotation.store import AnnotationStore
    from src.api.annotation_review import annotation_quality_model, get_learning_service

    profile, classes, reference, protected_assignments = ready_profile()
    whole_fish_class_id = next(row["id"] for row in classes if row.get("kind") == "whole_fish" and row.get("active", True))
    all_images = {row["id"]: row for row in coco["images"]}
    selected = [all_images[index] for index in image_ids]
    assert len(set(image_ids)) == len(image_ids)
    assert all(provenance[row["file_name"]]["original_splits"] == ["test"] for row in selected)
    assert all(protected_assignments[row["id"]] == "test" for row in selected)
    assert all(row["id"] in SCENE_REVIEWS for row in selected), "Inspect each requested source image before adding a scene review."
    visual_reviews = [{"source_image_id": row["id"], "filename": row["file_name"],
                       "source_split": "test", "reviewed_preview": f"source_{row['id']}.jpg",
                       "observed_scene": SCENE_REVIEWS[row["id"]],
                       "scope": "Visual scene coverage only; not a claim of verified anatomical absence or fish ownership."}
                      for row in selected]
    (OUTPUT / "visual_scene_review.json").write_text(json.dumps(visual_reviews, indent=2), encoding="utf-8")
    by_image = defaultdict(list)
    for annotation in coco["annotations"]:
        by_image[annotation["image_id"]].append(annotation)
    category_names = {row["id"]: row["name"] for row in coco["categories"]}
    original_test_ids = {row["id"] for row in coco["images"] if provenance[row["file_name"]]["original_splits"] == ["test"]}
    protected_test_ids = {index for index, split in protected_assignments.items() if split == "test"}
    original_test_support = Counter(category_names[ann["category_id"]] for ann in coco["annotations"] if ann["image_id"] in original_test_ids)
    test_support = Counter(category_names[ann["category_id"]] for ann in coco["annotations"] if ann["image_id"] in protected_test_ids)
    sample_support = Counter(category_names[ann["category_id"]] for ann in coco["annotations"] if ann["image_id"] in image_ids)
    registry = get_model_registry()
    model1 = registry.get_model(registry.get_default_model1_id())
    detector = YoloFishDetector(registry.resolve_checkpoint_path(model1), device="cpu", image_size=model1.input_size,
                               confidence_threshold=.5, iou_threshold=.70, max_detections=132)
    # The annotation-only incumbent is read from a separate empty QA workspace.
    # The canonical baseline and live grading selection are never changed.
    isolated_store = AnnotationStore(OUTPUT / "isolated_workspace")
    service = get_learning_service(isolated_store)
    quality = annotation_quality_model(isolated_store)
    assert quality is not None, "Existing annotation segmentation incumbent is unavailable."
    settings = MobileSamSettings(device="cpu")
    paths = {"model1": detector.weights_path, "annotation_incumbent": quality.weights_path, "mobilesam": settings.checkpoint}
    if service.base_checkpoint:
        paths["original_annotation_checkpoint"] = service.base_checkpoint
    before = {name: digest(path) for name, path in paths.items()}
    archive_before = digest(ARCHIVE)
    reference_before = digest(reference)
    assert detector.load(), detector.error
    sam = MobileSamService(settings)
    cases, truth_rows, prediction_rows, spatial_outcomes, mask_shape_audit = [], [], [], [], []
    with zipfile.ZipFile(ARCHIVE) as archive:
        for image in selected:
            started = time.perf_counter()
            frame = cv2.imdecode(np.frombuffer(archive.read(image["file_name"]), np.uint8), cv2.IMREAD_COLOR)
            assert frame is not None and frame.shape[:2] == (image["height"], image["width"])
            case_id = f"test_image_{image['id']}"
            output = generate_annotations({"id": case_id}, frame, classes, detector=detector,
                                          quality_model=quality, sam_service=sam, reference_root=reference)
            (OUTPUT / f"{case_id}.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
            raw_truth = by_image[image["id"]]
            expected_boxes = [[ann["bbox"][0], ann["bbox"][1], ann["bbox"][0] + ann["bbox"][2], ann["bbox"][1] + ann["bbox"][3]] for ann in raw_truth]
            expected_labels = [SOURCE_NAME_TO_ID[CATEGORY_ALIASES.get(category_names[a["category_id"]], category_names[a["category_id"]])] for a in raw_truth]
            parts = [a for a in output["annotations"] if "model_class_id" in a.get("metadata", {})]
            part_boxes = [a["metadata"]["detector_bbox_xyxy"] for a in parts]
            part_labels = [a["metadata"]["model_class_id"] for a in parts]
            truth_rows.append({"image": image["file_name"], "boxes": expected_boxes, "labels": expected_labels})
            prediction_rows.append({"image": image["file_name"], "boxes": part_boxes, "labels": part_labels, "scores": [a["confidence"] for a in parts]})
            overlay = frame.copy()
            part_overlay = frame.copy()
            generated, missing = 0, 0
            flags = Counter()
            for index, annotation in enumerate(output["annotations"]):
                assert annotation["status"] == "unreviewed" and annotation["source"] == "automated"
                flags.update(annotation["flags"])
                if annotation.get("segmentation") is None:
                    missing += 1
                    assert "missing_segmentation" in annotation["flags"]
                    continue
                mask = segmentation_to_mask(annotation["segmentation"], *frame.shape[:2])
                assert mask.any() and mask.shape == frame.shape[:2]
                assert annotation["bbox"] == list(cv2.boundingRect(mask))
                generated += 1
                if annotation.get("class_id") == whole_fish_class_id:
                    color = np.array([(61 + index * 81) % 255, (171 + index * 59) % 255, (237 + index * 43) % 255])
                    overlay[mask != 0] = (.55 * overlay[mask != 0] + .45 * color).astype(np.uint8)
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    cv2.drawContours(overlay, contours, -1, tuple(map(int, color)), 3)
                elif "model_class_id" in annotation.get("metadata", {}):
                    model_id = annotation["metadata"]["model_class_id"]
                    bounds = cv2.boundingRect(mask)
                    foreground_fraction = int(np.count_nonzero(mask)) / (bounds[2] * bounds[3])
                    mask_shape_audit.append({"image_id": image["id"], "prediction_id": annotation["id"],
                        "foreground_fraction_of_bbox": foreground_fraction, "boxlike": foreground_fraction >= .995,
                        "mask_source": annotation["metadata"].get("mask_provenance", {}).get("source")})
                    color = np.array([(61 + model_id * 81) % 255, (171 + model_id * 59) % 255, (237 + model_id * 43) % 255])
                    part_overlay[mask != 0] = (.55 * part_overlay[mask != 0] + .45 * color).astype(np.uint8)
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    cv2.drawContours(part_overlay, contours, -1, tuple(map(int, color)), 3)
            assert generated == output["automation"]["pixel_masks"]
            cv2.imwrite(str(OUTPUT / f"{case_id}_fish_overlay.jpg"), cv2.resize(overlay, (960, 540)))
            cv2.imwrite(str(OUTPUT / f"{case_id}_parts_overlay.jpg"), cv2.resize(part_overlay, (960, 540)))
            for truth_index, prediction_index, overlap in matches(expected_boxes, part_boxes):
                expected = coco_segmentation_to_mask(raw_truth[truth_index]["segmentation"], *frame.shape[:2]) != 0
                predicted_ann = parts[prediction_index]
                class_correct = expected_labels[truth_index] == part_labels[prediction_index]
                iou = None
                if predicted_ann.get("segmentation") is not None:
                    predicted = segmentation_to_mask(predicted_ann["segmentation"], *frame.shape[:2]) != 0
                    union = np.count_nonzero(expected | predicted)
                    iou = float(np.count_nonzero(expected & predicted) / union) if union else None
                spatial_outcomes.append({"image_id": image["id"], "source_annotation_id": raw_truth[truth_index]["id"],
                                         "prediction_id": predicted_ann["id"], "box_iou": overlap, "class_correct": class_correct,
                                         "expected_model_class_id": expected_labels[truth_index], "predicted_model_class_id": part_labels[prediction_index],
                                         "mask_iou": iou})
            row = {"case": case_id, "source_image_id": image["id"], "source_split": "test", "filename": image["file_name"],
                   "original_resolution": [image["width"], image["height"]], "manual_annotations": len(raw_truth),
                   **output["automation"], "generated_masks": generated, "missing_masks": missing,
                   "all_predictions_unreviewed": True, "flags": dict(flags),
                   "assigned_parts": sum(annotation.get("parent_id") is not None for annotation in parts),
                   "association_status_counts": dict(Counter(annotation["metadata"]["association"]["status"] for annotation in parts)),
                   "part_confidence_scores": [a["confidence"] for a in parts],
                   "fish_confidence_scores": [a["confidence"] for a in output["annotations"] if "model_class_id" not in a.get("metadata", {})],
                   "elapsed_seconds": time.perf_counter() - started}
            cases.append(row)
            print(json.dumps({key: row[key] for key in ("case", "model1_detections", "model2_detections", "generated_masks", "missing_masks", "elapsed_seconds")}), flush=True)
    metrics = evaluate_boxes(truth_rows, prediction_rows, confidence=.25)
    tp = sum(row["true_positives"] for row in metrics["errors"])
    fp = sum(row["false_positives"] for row in metrics["errors"])
    fn = sum(row["missed_instances"] for row in metrics["errors"])
    pixel_values = [row["mask_iou"] for row in spatial_outcomes if row["mask_iou"] is not None]
    correct_pixel_values = [row["mask_iou"] for row in spatial_outcomes if row["class_correct"] and row["mask_iou"] is not None]
    after = {name: digest(path) for name, path in paths.items()}
    assert before == after and archive_before == digest(ARCHIVE) and reference_before == digest(reference)
    report = {"schema_version": 1, "dataset_id": profile["dataset_id"], "primary_dataset_name": profile["name"],
              "source_archive": str(ARCHIVE), "source_archive_sha256_before": archive_before,
              "source_archive_sha256_after": digest(ARCHIVE), "source_coco_entry": "clean_segmentation.json",
              "source_coco_sha256": source_coco_sha, "checkpoint_paths": {key: str(value) for key, value in paths.items()},
              "checkpoint_sha256_before": before, "checkpoint_sha256_after": after,
              "reference_profile_path": str(reference), "reference_profile_sha256_before": reference_before,
              "reference_profile_sha256_after": digest(reference), "reference_splits": ["train"],
              "device": "cpu", "torch_threads": torch.get_num_threads(), "cuda_initialized": torch.cuda.is_initialized(),
              "cases": cases, "case_count": len(cases), "sample_selection": "Purposive visually inspected test scenes; see visual_scene_review.json.",
              "visual_scene_reviews": visual_reviews,
              "manual_primary_original_test_class_support": dict(original_test_support),
              "manual_primary_protected_test_class_support": dict(test_support), "manual_sample_class_support": dict(sample_support),
              "primary_protected_split_counts": dict(Counter(protected_assignments.values())),
              "part_box_metrics": metrics, "micro_part_boxes_iou50_conf25": {"true_positive": tp, "false_positive": fp, "false_negative": fn,
                  "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None},
              "spatially_matched_part_class_accuracy": {"method": "Greedy descending IoU class-agnostic one-to-one detector boxes; IoU >= .5",
                  "spatial_matches": len(spatial_outcomes), "correct_classes": sum(row["class_correct"] for row in spatial_outcomes),
                  "accuracy": sum(row["class_correct"] for row in spatial_outcomes) / len(spatial_outcomes) if spatial_outcomes else None,
                  "correct_anatomical_regions": sum(row["expected_model_class_id"] % 3 == row["predicted_model_class_id"] % 3 for row in spatial_outcomes),
                  "correct_quality_grades": sum(row["expected_model_class_id"] // 3 == row["predicted_model_class_id"] // 3 for row in spatial_outcomes)},
              "matched_part_mask_iou": {"spatial_matches_with_masks": len(pixel_values), "mean": float(np.mean(pixel_values)) if pixel_values else None,
                  "class_correct_matches_with_masks": len(correct_pixel_values), "class_correct_mean": float(np.mean(correct_pixel_values)) if correct_pixel_values else None,
                  "outcomes": spatial_outcomes},
              "part_mask_shape_audit": {"part_masks_with_pixels": len(mask_shape_audit),
                  "boxlike_part_masks": sum(row["boxlike"] for row in mask_shape_audit),
                  "boxlike_fill_ratio_threshold": .995, "instances": mask_shape_audit},
              "all_predictions_unreviewed": True, "source_and_models_unchanged": True,
              "limitations": ["Small purposive development compatibility sample; not full primary test performance or proof of improvement.",
                  "Historical model training provenance may overlap the primary source captures; no independent generalization claim.",
                  "Class accuracy and mask IoU are conditional on one-to-one spatial matches; misses remain represented by detection recall.",
                  "Manual cleaned COCO part masks are the user-selected reference; boundaries have not been independently audited.",
                  "Primary test annotations cover Grade_A parts and only one Grade_B head/body each; no Grade_C, Rejected, or Grade_B tail test labels exist.",
                  "No whole-fish ownership or silhouette ground truth exists; fish mask/association accuracy cannot be quantified.",
                  "No human correction rate was measured. QA predictions remain unreviewed, quarantined, and ineligible for verified training."]}
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"cases": len(cases), "masks": sum(row["generated_masks"] for row in cases),
                      "missing_masks": sum(row["missing_masks"] for row in cases), "micro": report["micro_part_boxes_iou50_conf25"],
                      "class_accuracy": report["spatially_matched_part_class_accuracy"],
                      "mean_matched_mask_iou": report["matched_part_mask_iou"]["mean"]}, indent=2), flush=True)


def compare_runs(previous_name):
    """Compare paired saved boundaries only; never rerun or relabel predictions."""
    previous_dir = OUTPUT.parent / previous_name
    before = json.loads((previous_dir / "report.json").read_bytes())
    after = json.loads((OUTPUT / "report.json").read_bytes())
    assert before["source_archive_sha256_before"] == after["source_archive_sha256_before"]
    assert before["checkpoint_sha256_before"] == after["checkpoint_sha256_before"]
    assert before["reference_profile_sha256_before"] == after["reference_profile_sha256_before"]
    assert [row["source_image_id"] for row in before["cases"]] == [row["source_image_id"] for row in after["cases"]]
    detection_outputs_unchanged = True
    for row in after["cases"]:
        first = json.loads((previous_dir / (row["case"] + ".json")).read_bytes())
        second = json.loads((OUTPUT / (row["case"] + ".json")).read_bytes())
        def detector_outputs(document):
            return [(ann["id"], ann["class_id"], ann["confidence"], ann.get("parent_id"), ann["metadata"]["detector_bbox_xyxy"])
                    for ann in document["annotations"]]
        detection_outputs_unchanged &= detector_outputs(first) == detector_outputs(second)
    assert detection_outputs_unchanged, "Do not attribute boundary differences to one guard when detections also changed."
    def indexed(report):
        return {(row["image_id"], row["source_annotation_id"], row["prediction_id"]): row
                for row in report["matched_part_mask_iou"]["outcomes"]}
    first, second = indexed(before), indexed(after)
    assert first.keys() == second.keys(), "Spatial match membership changed; inspect comparison manually."
    paired = [{"image_id": key[0], "source_annotation_id": key[1], "prediction_id": key[2],
               "before_mask_iou": first[key]["mask_iou"], "after_mask_iou": second[key]["mask_iou"],
               "difference": second[key]["mask_iou"] - first[key]["mask_iou"]}
              for key in first if first[key]["mask_iou"] is not None and second[key]["mask_iou"] is not None]
    previous_shape_audit_path = previous_dir / "native_part_boundary_audit.json"
    old_shape = json.loads(previous_shape_audit_path.read_bytes()) if previous_shape_audit_path.is_file() else before.get("part_mask_shape_audit", {})
    comparison = {"method": "Paired identical saved detections and one-to-one spatialmatches; only generated boundaries may differ.",
        "before_run": previous_name, "after_run": OUTPUT.name, "source_and_checkpoints_identical": True,
        "detector_boxes_classes_confidence_and_associations_unchanged": detection_outputs_unchanged,
        "case_count": len(after["cases"]), "spatial_matches": len(first), "paired_nonmissing_masks": len(paired),
        "before_mean_paired_mask_iou": float(np.mean([row["before_mask_iou"] for row in paired])),
        "after_mean_paired_mask_iou": float(np.mean([row["after_mask_iou"] for row in paired])),
        "paired_masks_improved": sum(row["difference"] > 1e-9 for row in paired),
        "paired_masks_deteriorated": sum(row["difference"] < -1e-9 for row in paired),
        "paired_masks_equal": sum(abs(row["difference"]) <= 1e-9 for row in paired),
        "before_boxlike_part_masks": old_shape.get("boxlike_part_masks"),
        "after_boxlike_part_masks": after["part_mask_shape_audit"]["boxlike_part_masks"],
        "before_missing_masks": sum(row["missing_masks"] for row in before["cases"]),
        "after_missing_masks": sum(row["missing_masks"] for row in after["cases"]),
        "newly_available_spatially_matched_masks": sum(first[key]["mask_iou"] is None and second[key]["mask_iou"] is not None for key in first),
        "compound_class_accuracy_unchanged": before["spatially_matched_part_class_accuracy"]["accuracy"] == after["spatially_matched_part_class_accuracy"]["accuracy"],
        "class_aware_precision_recall_unchanged": before["micro_part_boxes_iou50_conf25"] == after["micro_part_boxes_iou50_conf25"],
        "paired_outcomes": paired,
        "limitations": ["Five purposive primary scenes only; no dataset-wide or independent generalization improvement claim.",
            "This boundary comparison does not fix the measured grade-label mismatch, missed detections, or ambiguous fish ownership.",
            "A nonrectangular mask can still have poor boundaries. Every candidate remains unreviewed."]}
    (OUTPUT / "mask_guard_comparison.json").write_text(json.dumps(comparison, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in comparison.items() if key not in {"paired_outcomes", "limitations"}}, indent=2), flush=True)


def main():
    global OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--image-ids", type=int, nargs="+")
    parser.add_argument("--run-name", default="primary_real_models", help="Separate QA artifact folder name; preserves earlier runs.")
    parser.add_argument("--compare-run", help="Compare this run to a prior saved primary_real_models folder without inference.")
    arguments = parser.parse_args()
    if (not arguments.run_name.startswith("primary_real_models") or len(arguments.run_name) > 80
            or any(not (character.isalnum() or character in "_-") for character in arguments.run_name)):
        parser.error("Run name must be a simple primary_real_models-prefixed QA folder name.")
    OUTPUT = OUTPUT.parent / arguments.run_name
    if arguments.compare_run and (not arguments.compare_run.startswith("primary_real_models") or len(arguments.compare_run) > 80
            or any(not (character.isalnum() or character in "_-") for character in arguments.compare_run)):
        parser.error("Comparison run must be a simple primary_real_models-prefixed QA folder name.")
    torch.set_num_threads(1)
    cv2.setNumThreads(1)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    coco, provenance, coco_sha = read_primary()
    if arguments.prepare:
        prepare(coco, provenance)
    if arguments.image_ids:
        run(coco, provenance, coco_sha, arguments.image_ids)
    if arguments.compare_run:
        compare_runs(arguments.compare_run)
    if not arguments.prepare and not arguments.image_ids and not arguments.compare_run:
        parser.error("Pass --prepare, explicit visually reviewed --image-ids, or --compare-run.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / "failure.json").write_text(json.dumps({
            "completed": False, "time": datetime.now(timezone.utc).isoformat(),
            "arguments": sys.argv[1:], "error_type": type(error).__name__,
            "error": str(error), "traceback": traceback.format_exc(),
            "predictions_are_verified_training_labels": False,
            "source_archive_sha256_at_failure": digest(ARCHIVE),
        }, indent=2), encoding="utf-8")
        raise
