"""Contract tests for the active Model 2 COCO part compatibility evaluator."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from src.evaluation.evaluate_active_model2_parts import (
    CocoPartEvaluationError,
    load_coco_part_split,
    training_manifest_overlap,
)
from src.preprocessing.audit_v7_exports import SOURCE_CLASSES


def _write_split(root: Path, *, parent_annotation: bool = False) -> Path:
    split = root / "valid"
    split.mkdir(parents=True)
    image = split / "fish.jpg"
    image.write_bytes(b"synthetic-image-bytes")
    categories = [{"id": 0, "name": "dried-fish-quality-grades"}]
    categories.extend({"id": index + 1, "name": name} for index, name in SOURCE_CLASSES.items())
    payload = {
        "images": [{"id": 10, "file_name": image.name, "width": 64, "height": 32}],
        "categories": categories,
        "annotations": [
            {
                "id": 1,
                "image_id": 10,
                "category_id": 0 if parent_annotation else 1,
                "bbox": [1, 2, 10, 12],
                "iscrowd": 0,
            }
        ],
    }
    (split / "_annotations.coco.json").write_text(json.dumps(payload), encoding="utf-8")
    return image


def test_load_coco_part_split_maps_by_exact_category_name(tmp_path: Path) -> None:
    _write_split(tmp_path)

    loaded = load_coco_part_split(tmp_path, "valid")

    assert loaded.category_mapping == {index + 1: index for index in SOURCE_CLASSES}
    assert len(loaded.records) == 1
    assert loaded.records[0]["image"] == "fish.jpg"
    assert loaded.records[0]["labels"] == [0]
    assert loaded.records[0]["boxes"] == [[1.0, 2.0, 11.0, 14.0]]


def test_load_coco_part_split_rejects_non_part_parent_annotation(tmp_path: Path) -> None:
    _write_split(tmp_path, parent_annotation=True)

    with pytest.raises(CocoPartEvaluationError, match="not one of the 12 trained part categories"):
        load_coco_part_split(tmp_path, "valid")


def test_training_manifest_overlap_uses_exact_image_hashes(tmp_path: Path) -> None:
    image = _write_split(tmp_path)
    split = load_coco_part_split(tmp_path, "valid")
    manifest = tmp_path / "historical_manifest.csv"
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    with manifest.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["original_sha256"])
        writer.writeheader()
        writer.writerow({"original_sha256": digest})

    overlap = training_manifest_overlap(split.records, manifest)

    assert overlap is not None
    assert overlap["matching_export_images"] == 1
    assert overlap["evaluated_export_images"] == 1
    assert overlap["independent"] is False
