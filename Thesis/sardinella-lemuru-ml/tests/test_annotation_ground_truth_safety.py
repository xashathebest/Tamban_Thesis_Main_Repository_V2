"""Independent source-preservation and mask-safety acceptance checks.

The original manual dataset is optional in model-free source copies. Its checks
are skipped there, while lossless mask validation always runs on synthetic data.
The fixed source hashes intentionally make baseline edits visible to reviewers.
"""

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.annotation.masks import mask_to_rle, segmentation_to_mask, yolo_polygon
from src.annotation.store import AnnotationStore
from src.preprocessing.audit_v7_exports import SOURCE_CLASSES, source_image_name


BASELINE = Path(__file__).resolve().parents[1] / "Dried Fish Quality Grading.v7i.coco-segmentation"
ORIGINAL_COCO_SHA256 = {
    "train": "198b7448e307265aa269d6993a2e2cbbf993a5ee66829d4e989dede5b115b20f",
    "valid": "b48a3ac59ac8b7a5b96c048017089e76a655f03ff6b87621ecb38b8612e1bc0e",
    "test": "762ac7674bba5d7758d250299c8c1cf6db6bb4720c3be4a1b27afca3d61438aa",
}


def _source_documents():
    if not all((BASELINE / split / "_annotations.coco.json").is_file() for split in ORIGINAL_COCO_SHA256):
        pytest.skip("Original manual COCO baseline is not present in this source copy.")
    return {split: json.loads((BASELINE / split / "_annotations.coco.json").read_bytes()) for split in ORIGINAL_COCO_SHA256}


@pytest.mark.parametrize("split,expected", ORIGINAL_COCO_SHA256.items())
def test_original_manual_coco_labels_remain_byte_identical(split, expected):
    path = BASELINE / split / "_annotations.coco.json"
    if not path.is_file():
        pytest.skip("Original manual COCO baseline is not present in this source copy.")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, "The immutable original manual labels changed."


def test_original_source_groups_do_not_cross_evaluation_splits():
    documents = _source_documents()
    groups = defaultdict(set)
    for split, document in documents.items():
        for image in document["images"]:
            groups[source_image_name(image).casefold()].add(split)
    conflicts = {group: sorted(splits) for group, splits in groups.items() if len(splits) > 1}
    assert not conflicts, f"Original/augmented image groups cross evaluation splits: {conflicts}"
    assert len(groups) == 337


def test_original_class_names_have_exact_shared_mapping():
    for split, document in _source_documents().items():
        category_names = {category["id"]: category["name"] for category in document["categories"]}
        assert {index: category_names[index + 1] for index in SOURCE_CLASSES} == SOURCE_CLASSES, split
        assert all(annotation["category_id"] in range(1, 13) for annotation in document["annotations"])


def test_rle_preserves_disconnected_objects_and_holes():
    mask = np.zeros((16, 24), dtype=np.uint8)
    mask[2:13, 2:12] = 1
    mask[5:9, 5:8] = 0
    mask[3:7, 18:22] = 1
    encoded = mask_to_rle(mask)
    assert np.array_equal(segmentation_to_mask(encoded, 16, 24), mask)
    with pytest.raises(ValueError, match="disconnected|holes"):
        yolo_polygon(mask)


def test_multiple_coco_polygon_islands_are_not_joined():
    segmentation = [[1, 1, 5, 1, 5, 5, 1, 5], [14, 2, 18, 2, 18, 6, 14, 6]]
    decoded = segmentation_to_mask(segmentation, 12, 20)
    assert decoded[3, 3] == decoded[4, 16] == 1
    assert decoded[:, 7:13].sum() == 0
    assert np.array_equal(segmentation_to_mask(mask_to_rle(decoded), 12, 20), decoded)


@pytest.mark.parametrize("polygon", [
    [2, 2, 2, 2, 2, 2],
    [2, 2, 3, 3, 4, 4],
    [2, 2, 8, 8, 2, 8, 8, 2],
])
def test_zero_area_polygon_cannot_become_verified_ground_truth(polygon):
    with pytest.raises(ValueError, match="area|degenerate|distinct|intersect"):
        segmentation_to_mask([polygon], 12, 20)


def test_missing_mask_is_never_replaced_by_a_bounding_box():
    with pytest.raises(ValueError, match="actual|nonempty|segmentation"):
        segmentation_to_mask([], 12, 20)


def _manual_fixture(tmp_path):
    manual = tmp_path / "original-manual"
    split = manual / "train"
    split.mkdir(parents=True)
    Image.new("RGB", (20, 16), (23, 45, 67)).save(split / "fish.png")
    source = {
        "categories": [{"id": 0, "name": "dried-fish-quality-grades", "supercategory": "none"}]
        + [{"id": index + 1, "name": name, "supercategory": "dried-fish-quality-grades"} for index, name in SOURCE_CLASSES.items()],
        "images": [{"id": 1, "file_name": "fish.png", "width": 20, "height": 16, "extra": {"name": "original-fish.png"}}],
        "annotations": [{"id": 8, "image_id": 1, "category_id": 2, "bbox": [2, 2, 6, 6],
                         "segmentation": [[2, 2, 8, 2, 8, 8, 2, 8]], "area": 36, "iscrowd": 0}],
    }
    path = split / "_annotations.coco.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    store = AnnotationStore(tmp_path / "workspace", manual_source=manual)
    report = store.import_manual(["train"])
    assert report["imported"] == 1 and not report["errors"]
    return store, report["image_ids"][0], path


def test_manual_corrections_save_separate_history_and_survive_restart(tmp_path):
    store, image_id, source_path = _manual_fixture(tmp_path)
    source_bytes = source_path.read_bytes()
    original = store.get(image_id)
    assert original["annotations"][0]["parent_id"] is None
    baseline_path = store.root / original["baseline"]["path"]
    baseline_bytes = baseline_path.read_bytes()
    corrections = deepcopy(original["annotations"])
    corrections[0].update(class_id=1, segmentation=[[2, 2, 9, 2, 9, 8, 2, 8]])
    corrections.append({"id": "human-added-tail", "class_id": 3, "parent_id": None,
                        "segmentation": [[11, 3, 16, 3, 16, 8, 11, 8]], "confidence": None})
    changed = store.save(image_id, original["revision"], corrections)
    verified = store.approve(image_id, changed["revision"])
    restarted = AnnotationStore(store.root, manual_source=store.manual_source)
    saved = restarted.get(image_id)
    assert saved["revision"] == verified["revision"]
    assert saved["annotations"][0]["class_id"] == 1
    assert len(saved["annotations"]) == 2
    original_revision = restarted.get_revision(image_id, original["revision"])
    assert original_revision["annotations"] == original["annotations"]
    assert source_path.read_bytes() == source_bytes
    assert baseline_path.read_bytes() == baseline_bytes == source_bytes


def test_declining_manual_review_preserves_source_pixels_and_baseline(tmp_path):
    store, image_id, source_path = _manual_fixture(tmp_path)
    original = store.get(image_id)
    source_bytes = source_path.read_bytes()
    source_image = source_path.parent / "fish.png"
    image_bytes = source_image.read_bytes()
    declined = store.save(image_id, original["revision"], original["annotations"], status="rejected")
    assert declined["status"] == "rejected"
    assert source_path.read_bytes() == source_bytes
    assert source_image.read_bytes() == image_bytes
    assert store.pixels_path(image_id).is_file()
    assert (store.root / original["baseline"]["path"]).read_bytes() == source_bytes
    assert len(store.history(image_id)["revisions"]) == 2
