"""Explicit real CPU model QA; artifacts are quarantined, never training labels.

Run from the project root with ``python tests/annotation_workflow_smoke.py``.
It does not start/reconfigure the dashboard or alter any model/source dataset.
"""
from __future__ import annotations

import hashlib
import argparse
import json
import os
from pathlib import Path
import sys

os.environ["CUDA_VISIBLE_DEVICES"] = ""
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
import torch

from src.annotation.masks import segmentation_to_mask
from src.api.annotation_automation import generate_annotations
from src.evaluation.comparison_protocol import evaluate_boxes
from src.evaluation.evaluate_active_model2_parts import load_coco_part_split
from src.inference.model_registry import get_model_registry
from src.inference.mobilesam_backend import MobileSamService, MobileSamSettings
from src.inference.yolo_fish_detector import YoloFishDetector
from src.inference.yolo_quality_model import YoloQualityModel
from src.preprocessing.audit_v7_exports import SOURCE_CLASSES


OUTPUT = ROOT / "results/qa/annotation_workflow/real_models"
SOURCE = ROOT / "Dried Fish Quality Grading.v7i.coco-segmentation"
SCENARIOS = [
    ("one_diagonal_fish", "train", "WIN_20260823_20_10_07_Pro_jpg.rf.bf4c016dea7d84c6ac57bb19f0cdc76f.jpg"),
    ("crowded_crossing_partial", "valid", "WIN_20260823_22_03_45_Pro_jpg.rf.91366fccd7b13d49fa582c4d44c10109.jpg"),
    ("damaged_parts_tail_unobserved", "valid", "WIN_20260902_18_12_46_Pro_jpg.rf.790fd6ded13e7129850d3c160b24320d.jpg"),
    ("two_opposite_edge_clipped", "train", "WIN_20260823_20_18_24_Pro_jpg.rf.4513a095bccccfd49033cfc98775c5fc.jpg"),
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotation-incumbent", action="store_true", help="Exercise the annotation-only segmentation incumbent.")
    args = parser.parse_args()
    output_dir = OUTPUT.parent / "real_annotation_incumbent" if args.annotation_incumbent else OUTPUT
    torch.set_num_threads(1)
    cv2.setNumThreads(1)
    output_dir.mkdir(parents=True, exist_ok=True)
    registry = get_model_registry()
    m1 = registry.get_model(registry.get_default_model1_id())
    m2 = registry.get_model(registry.get_persisted_model2_id())
    detector = YoloFishDetector(registry.resolve_checkpoint_path(m1), device="cpu", image_size=m1.input_size,
                               confidence_threshold=.5, iou_threshold=.70, max_detections=132)
    quality = YoloQualityModel(registry.resolve_checkpoint_path(m2), model_id=m2.id, device="cpu",
                               image_size=m2.input_size, confidence_threshold=.25, quality_inference_mode="full_frame")
    if args.annotation_incumbent:
        from src.annotation.store import AnnotationStore
        from src.api.annotation_review import annotation_quality_model
        quality = annotation_quality_model(AnnotationStore(output_dir / "isolated_workspace", SOURCE))
        assert quality is not None, "Existing annotation segmentation checkpoint is unavailable."
    settings = MobileSamSettings(device="cpu")
    paths = {"model1": detector.weights_path, "model2": quality.weights_path, "mobilesam": settings.checkpoint}
    before = {name: digest(path) for name, path in paths.items()}
    source_before = {split: digest(SOURCE / split / "_annotations.coco.json") for split in ("train", "valid", "test")}
    assert detector.load(), detector.error
    if not args.annotation_incumbent:
        assert quality.load(), quality.error
    sam = MobileSamService(settings)
    classes = [{"id": index + 1, "name": name, "source_name": name, "model_class_id": index,
                "kind": "anatomy", "active": True} for index, name in SOURCE_CLASSES.items()]
    classes.append({"id": 13, "name": "Whole fish", "kind": "whole_fish", "active": True})
    split = load_coco_part_split(SOURCE, "test")
    cases = SCENARIOS + [("test_" + str(index), "test", row["image"]) for index, row in enumerate(split.records)]
    summaries, predictions = [], []
    for title, subset, filename in cases:
        # The evaluation loader uses the exact original export filename.
        filename = Path(filename).name
        path = SOURCE / subset / filename
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
        assert frame is not None, path
        result = generate_annotations({"id": title}, frame, classes, detector=detector, quality_model=quality,
                                      sam_service=sam, reference_root=SOURCE)
        (output_dir / (title + ".json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
        overlay = frame.copy()
        generated = 0
        for index, ann in enumerate(result["annotations"]):
            assert ann["status"] == "unreviewed" and ann["source"] == "automated"
            if ann["segmentation"] is None:
                assert "missing_segmentation" in ann["flags"]
                continue
            mask = segmentation_to_mask(ann["segmentation"], *frame.shape[:2])
            assert mask.shape == frame.shape[:2] and mask.any()
            assert ann["bbox"] == list(cv2.boundingRect(mask))
            generated += 1
            # Whole-fish overlay permits a reviewer to inspect crossing masks.
            if ann["parent_id"] is None and ann["class_id"] == 13:
                color = np.array([(61 + index * 81) % 255, (171 + index * 59) % 255, (237 + index * 43) % 255])
                overlay[mask != 0] = (.55 * overlay[mask != 0] + .45 * color).astype(np.uint8)
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(overlay, contours, -1, tuple(map(int, color)), 1)
        assert generated == result["automation"]["pixel_masks"]
        cv2.imwrite(str(output_dir / (title + ".png")), overlay)
        row = {"case": title, "source_split": subset, "filename": filename,
               **result["automation"], "missing_masks": len(result["annotations"]) - generated,
               "flagged_objects": sum(bool(a["flags"]) for a in result["annotations"]),
               "assigned_parts": sum(a["parent_id"] is not None for a in result["annotations"]),
               "all_unreviewed": True}
        summaries.append(row)
        if subset == "test":
            parts = [ann for ann in result["annotations"] if "model_class_id" in ann["metadata"]]
            predictions.append({"image": filename, "boxes": [p["metadata"]["detector_bbox_xyxy"] for p in parts],
                                "labels": [p["metadata"]["model_class_id"] for p in parts],
                                "scores": [p["confidence"] for p in parts]})
        print(f"{title}: fish={row['model1_detections']}, parts={row['model2_detections']}, "
              f"masks={generated}, missing={row['missing_masks']}, flagged={row['flagged_objects']}", flush=True)
    truth = [{"image": row["image"], "boxes": row["boxes"], "labels": row["labels"]} for row in split.records]
    metrics = evaluate_boxes(truth, predictions, confidence=.25)
    after = {name: digest(path) for name, path in paths.items()}
    source_after = {subset: digest(SOURCE / subset / "_annotations.coco.json") for subset in source_before}
    assert before == after and source_before == source_after
    report = {"cases": summaries, "case_count": len(summaries), "device": "cpu",
              "annotation_incumbent": args.annotation_incumbent,
              "checkpoints_before": before, "checkpoints_after": after, "source_before": source_before,
              "source_after": source_after, "cuda_initialized": torch.cuda.is_initialized(),
              "model2_part_box_metrics": metrics,
              "metric_limitations": ["Development compatibility only; source export has historical training overlap.",
                 "No independent whole-fish mask/ownership ground truth; no fish segmentation IoU or ownership accuracy claimed.",
                 "Most manual part masks are rectangles; boundary IoU would not establish true anatomical mask accuracy.",
                 "All candidates remain unreviewed. These QA artifacts must not be used as verified training labels."]}
    (output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"cases": len(summaries), "masks": sum(s["pixel_masks"] for s in summaries),
                      "missing": sum(s["missing_masks"] for s in summaries), "source_and_models_unchanged": True,
                      "cuda_initialized": torch.cuda.is_initialized(), "metrics": metrics}, indent=2), flush=True)


if __name__ == "__main__":
    main()
