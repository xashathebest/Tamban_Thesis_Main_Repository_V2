"""Explicit real-primary YOLO export/readback QA; never approve or edit labels.

Creates small canonical exports and copies them into ignored QA artifacts. All
original images and all canonical image/revision documents are checked unchanged.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import zipfile

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.annotation.masks import segmentation_to_mask
from src.annotation.store import AnnotationError, AnnotationStore

WORKSPACE = ROOT / "dataset/annotation_workspace"
OUTPUT = ROOT / "results/qa/annotation_workflow/primary_real_exports"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def database_snapshot():
    connection = sqlite3.connect((WORKSPACE / "annotations.sqlite3").as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        latest = [(row[0], sha(row[1].encode("utf-8"))) for row in connection.execute("SELECT id,document FROM images ORDER BY id")]
        revisions = [(row[0], row[1], sha(row[2].encode("utf-8")), row[3]) for row in connection.execute(
            "SELECT image_id,revision,document,created_at FROM revisions ORDER BY image_id,revision")]
        profile = json.loads(connection.execute("SELECT value FROM meta WHERE key='primary_learning_dataset'").fetchone()[0])
        documents = [document for row in connection.execute("SELECT document FROM images")
                     if (document := json.loads(row[0])).get("dataset_id") == profile["dataset_id"]]
    finally:
        connection.close()
    return {"latest": latest, "revisions": revisions}, profile, documents


def split(document):
    return (document.get("metadata") or {}).get("protected_split") or document.get("split")


def verify_export(path, format, selected, classes):
    # Use the actual installed trainer rasterizer, including its float32 /
    # int32 coordinate path, rather than the export implementation's helper.
    from ultralytics.data.utils import polygon2mask

    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        manifest = json.loads(archive.read("manifest.json"))
        yaml = json.loads(archive.read("data.yaml"))  # JSON is valid YAML.
        mapping = json.loads(archive.read("classes.json"))
        validation = json.loads(archive.read("validation_report.json"))
        assert validation["valid"] and not validation["errors"]
        assert manifest["format"] == format and manifest["split_requested"] is True
        assert {row["id"] for row in manifest["images"]} == set(selected)
        assert mapping == manifest["class_mapping"]
        assert [row["export_id"] for row in mapping] == list(range(len(mapping)))
        assert int(yaml["nc"]) == len(mapping)
        by_export_id = {row["export_id"]: row for row in mapping}
        for category in mapping:
            original = classes[category["source_id"]]
            assert category["name"] == original["name"]
            assert yaml["names"][str(category["export_id"])] == original["name"]
        image_results, mask_count, label_count = [], 0, 0
        for item in manifest["images"]:
            document = selected[item["id"]]
            subset = split(document)
            assert item["split"] == subset and item["path"].startswith(subset + "/images/")
            assert item["revision"] == document["revision"] and item["status"] == document["status"]
            assert (item["baseline"] or {}).get("dataset_id") == document["dataset_id"]
            assert archive.read(item["path"]) == (WORKSPACE / document["pixels_path"]).read_bytes()
            assert archive.read(item["original_path"]) == (WORKSPACE / document["original_path"]).read_bytes()
            assert sha(archive.read(item["original_path"])) == document["image_sha256"]
            decoded = cv2.imdecode(np.frombuffer(archive.read(item["path"]), np.uint8), cv2.IMREAD_COLOR)
            assert decoded is not None and decoded.shape[:2] == (document["height"], document["width"])
            restored = json.loads(archive.read(f"reviewed_documents/{document['id']}.json"))
            assert restored == document
            label_path = f"{subset}/labels/{document['id']}.txt"
            lines = archive.read(label_path).decode("utf-8").splitlines()
            expected_annotations = [ann for ann in document["annotations"] if ann["status"] != "rejected"]
            assert len(lines) == len(expected_annotations) == len(item["annotations"])
            for line, annotation, exported in zip(lines, expected_annotations, item["annotations"]):
                values = line.split()
                label = int(values[0])
                coordinates = np.asarray(values[1:], dtype=np.float64)
                assert np.isfinite(coordinates).all() and (coordinates >= 0).all() and (coordinates <= 1).all()
                assert by_export_id[label]["source_id"] == annotation["class_id"]
                assert exported["id"] == annotation["id"] and exported["export_class_id"] == label
                assert exported["status"] == annotation["status"]
                assert exported["class_name"] == classes[annotation["class_id"]]["name"]
                expected = segmentation_to_mask(annotation["segmentation"], document["height"], document["width"])
                png = cv2.imdecode(np.frombuffer(archive.read(exported["mask_path"]), np.uint8), cv2.IMREAD_GRAYSCALE)
                assert png is not None and np.array_equal(png != 0, expected != 0)
                assert np.array_equal(segmentation_to_mask(exported["segmentation"], document["height"], document["width"]), expected)
                if format == "yolo_detection":
                    assert len(coordinates) == 4
                    center_x, center_y, width, height = coordinates * [document["width"], document["height"], document["width"], document["height"]]
                    restored_bbox = [center_x - width / 2, center_y - height / 2, width, height]
                    assert np.allclose(restored_bbox, cv2.boundingRect(expected), rtol=0, atol=1e-6)
                else:
                    assert len(coordinates) >= 6 and len(coordinates) % 2 == 0
                    native = np.asarray(values[1:], dtype=np.float32).reshape(-1, 2)
                    native *= np.array([document["width"], document["height"]], dtype=np.float32)
                    trainer_mask = polygon2mask((document["height"], document["width"]), [native.reshape(-1)], color=1, downsample_ratio=1)
                    assert np.array_equal(trainer_mask != 0, expected != 0), f"Trainer changed pixels for {annotation['id']}"
                mask_count += 1
                label_count += 1
            image_results.append({"image_id": document["id"], "source_image_id": document["baseline"]["source_image_id"],
                                  "source_filename": document["filename"], "split": subset,
                                  "original_dimensions": [document["width"], document["height"]],
                                  "revision": document["revision"], "status": document["status"],
                                  "reviewed_annotations": len(expected_annotations)})
        actual_splits = set(row["split"] for row in image_results)
        for subset, key in (("train", "train"), ("valid", "val"), ("test", "test")):
            assert yaml[key] == (f"{subset}/images" if subset in actual_splits else None)
        assert manifest["validation"]["training_ready"] == ({"train", "valid"} <= actual_splits)
    return {"format": format, "zip_path": str(path), "zip_sha256": file_sha(path), "structural_validation_passed": True,
            "image_count": len(image_results), "label_count": label_count, "exact_mask_pngs_checked": mask_count,
            "exact_native_trainer_polygon_masks_checked": mask_count if format == "yolo_segmentation" else 0,
            "class_count": len(mapping), "available_splits": sorted(actual_splits),
            "split_organization_valid": True, "images": image_results,
            "exporter_structural_training_ready": manifest["validation"]["training_ready"],
            "accuracy_or_class_coverage_certified": False,
            "validation_warnings": validation["warnings"]}


def main():
    cv2.setNumThreads(1)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    before, profile, documents = database_snapshot()
    assert profile["status"] == "ready" and len(documents) == 345
    source_before = file_sha(profile["source_path"])
    selected = []
    for subset in ("train", "valid"):
        candidates = [document for document in documents if split(document) == subset and document["status"] == "manual_verified"]
        selected.append(min(candidates, key=lambda document: (len(document["annotations"]), document["baseline"]["source_image_id"])))
    selected.append(next(document for document in documents if document["baseline"]["source_image_id"] == 331))
    selected_by_id = {document["id"]: document for document in selected}
    store = AnnotationStore(WORKSPACE)
    classes = {category["id"]: category for category in store.classes()["classes"]}
    outcomes, refusals = [], []
    for format in ("yolo_detection", "yolo_segmentation"):
        try:
            original_export = store.export(format=format, image_ids=list(selected_by_id), split=True)
        except AnnotationError as error:
            refusals.append({"format": format, "selection": list(selected_by_id), "message": str(error)})
            if format != "yolo_segmentation":
                raise
            # A correct lossless refusal of one source mask must not imply the
            # entire format failed. Try these same three real images separately.
            for document in selected:
                try:
                    original_export = store.export(format=format, image_ids=[document["id"]], split=True)
                except AnnotationError as single_error:
                    refusals.append({"format": format, "selection": [document["id"]], "message": str(single_error)})
                    continue
                copied = OUTPUT / f"{format}-{document['baseline']['source_image_id']}.zip"
                shutil.copy2(original_export, copied)
                verified = verify_export(copied, format, {document["id"]: document}, classes)
                verified["canonical_export_path"] = str(original_export)
                outcomes.append(verified)
                break
            continue
        copied = OUTPUT / f"{format}.zip"
        shutil.copy2(original_export, copied)
        verified = verify_export(copied, format, selected_by_id, classes)
        verified["canonical_export_path"] = str(original_export)
        outcomes.append(verified)
        print(json.dumps({key: value for key, value in verified.items() if key not in {"images", "validation_warnings"}}), flush=True)
    after, after_profile, _ = database_snapshot()
    assert before == after, "An export changed an image or revision document."
    assert after_profile == profile and file_sha(profile["source_path"]) == source_before
    report = {"dataset_id": profile["dataset_id"], "primary_images_indexed": len(documents),
              "source_archive": profile["source_path"], "source_archive_sha256_before": source_before,
              "source_archive_sha256_after": file_sha(profile["source_path"]),
              "selected_original_source_image_ids": [document["baseline"]["source_image_id"] for document in selected],
              "image_documents_checked_unchanged": len(before["latest"]), "revision_documents_checked_unchanged": len(before["revisions"]),
              "all_image_and_revision_documents_unchanged": True, "primary_registry_unchanged": True,
              "exports": outcomes, "lossless_export_refusals": refusals,
              "successful_formats": sorted({row["format"] for row in outcomes}),
              "limitations": ["Three-image structural round-trip smoke, not a complete training dataset or a new accuracy evaluation.",
                  "Training-ready flag here indicates train/validation folders exist; adequate class coverage and independent evaluation remain separate requirements.",
                  "No labels were edited, approved, imported, inferred, or trained during this QA."]}
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    assert set(report["successful_formats"]) == {"yolo_detection", "yolo_segmentation"}, "No compatible real primary YOLO segmentation image was found."
    print(json.dumps({"selected_source_ids": report["selected_original_source_image_ids"],
                      "formats": report["successful_formats"], "refusals": refusals,
                      "all_image_and_revision_documents_unchanged": True}, indent=2), flush=True)


if __name__ == "__main__":
    main()
