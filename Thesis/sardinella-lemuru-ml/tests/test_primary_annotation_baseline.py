"""Selected ZIP baseline fidelity, immutable legacy records and safe scoping."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat
import zipfile

import cv2
import numpy as np
import pytest

from src.annotation.masks import coco_segmentation_to_mask, segmentation_to_mask
from src.annotation.primary_baseline import CATEGORY_ALIASES, LEGACY_DATASET_ID, dataset_id, primary_profile
from src.annotation.store import AnnotationError, AnnotationStore
from src.preprocessing.audit_v7_exports import SOURCE_CLASSES


def png(value=40):
    ok, encoded = cv2.imencode(".png", np.full((36, 48, 3), value, np.uint8))
    assert ok
    return encoded.tobytes()


@pytest.fixture
def store(tmp_path):
    source = tmp_path / "v2" / "train"
    source.mkdir(parents=True)
    (source / "legacy.png").write_bytes(png(7))
    categories = [{"id": 0, "name": "parts", "supercategory": "none"}] + [
        {"id": i + 1, "name": name, "supercategory": "parts"} for i, name in SOURCE_CLASSES.items()]
    source_data = {"categories": categories, "images": [{"id": 1, "file_name": "legacy.png", "width": 48, "height": 36}],
                   "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [2, 2, 10, 10],
                                    "segmentation": [[2, 2, 12, 2, 12, 12, 2, 12]]}]}
    (source / "_annotations.coco.json").write_text(json.dumps(source_data), encoding="utf-8")
    result = AnnotationStore(tmp_path / "workspace", source.parent)
    result.import_manual(["train"])
    return result


def source_zip(tmp_path, *, bad_mask=False, bad_path=False, unknown=False, missing=False, prefix="", splits=None):
    splits = splits or ["train", "val", "test"]
    images = [{"id": i + 1, "file_name": f"images/{i + 1}.png", "width": 48, "height": 36,
               "custom": {"keep": i}} for i in range(len(splits))]
    if bad_path:
        images[0]["file_name"] = "../escape.png"
    categories = [{"id": 1, "name": "Class_C_Body", "supercategory": "fish"},
                  {"id": 2, "name": "Grade_A_Head", "supercategory": "fish"}]
    if unknown:
        categories[0]["name"] = "Invented_Fish_Part"
    # Deliberately self-touching source vertices: decode exact original COCO
    # pixels instead of using the stricter interactive polygon editor's rules.
    polygon = [3, 3, 15, 15, 3, 15, 15, 3, 9, 20]
    annotations = [{"id": 100 + i, "image_id": i + 1, "category_id": 1 if i == 0 else 2,
                    "bbox": [3, 3, 12, 17], "segmentation": [polygon], "iscrowd": 0,
                    "custom": "original annotation"} for i in range(len(splits))]
    if bad_mask:
        annotations[0]["segmentation"] = [[3, 3, 3, 3, 3, 3]]
    source = {"info": {"original": "preserve all JSON bytes"}, "images": images,
              "annotations": annotations, "categories": categories}
    provenance = [{"image": image["file_name"], "sources": [f"source_1/{split}/capture{i}.rf.variant.png"],
                   "original_splits": [split], "requires_review": False}
                  for i, (image, split) in enumerate(zip(images, splits))]
    raw = json.dumps(source, indent=3).encode()
    path = tmp_path / "Fish_Annotations_Cleaned.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(prefix + "clean_segmentation.json", raw)
        archive.writestr(prefix + "provenance.json", json.dumps(provenance))
        archive.writestr(prefix + "cleaning_report.json", json.dumps({"near_duplicate_pairs": 1}))
        archive.writestr(prefix + "near_duplicate_candidates.csv", "image_1,image_2,hash_distance\nimages/1.png,images/2.png,1\n")
        for i, image in enumerate(images):
            if missing and i == 0:
                continue
            archive.writestr(prefix + image["file_name"], png(20 + i))
    return path, raw, source


def test_primary_zip_semantic_mapping_preserves_originals_exact_pixels_and_legacy(store, tmp_path):
    before = {i["id"]: store.get(i["id"]) for i in store.list()["images"]}
    original_class = next(c for c in store.classes()["classes"] if c["model_class_id"] == 6)
    path, raw, source = source_zip(tmp_path)
    original_archive = path.read_bytes()
    report = store.import_primary_zip(path)
    assert report["imported"] == 3 and report["errors"] == []
    assert report["profile"]["split_counts"] == {"train": 1, "valid": 1, "test": 1}
    assert report["profile"]["training_certified"] is True
    for identifier, document in before.items():
        assert store.get(identifier) == document
        assert dataset_id(document) == LEGACY_DATASET_ID
        assert len(store.history(identifier)["revisions"]) == 1
    doc = store.get(report["image_ids"][0])
    assert doc["status"] == "manual_verified" and doc["revision"] == 1
    assert doc["dataset_id"] == report["dataset_id"] == dataset_id(doc)
    assert doc["annotations"][0]["class_id"] == original_class["id"] == 7
    assert doc["annotations"][0]["class_id"] != source["annotations"][0]["category_id"]
    assert doc["annotations"][0]["original_annotation"] == source["annotations"][0]
    assert doc["annotations"][0]["source_category"] == source["categories"][0]
    assert doc["source_record"] == source["images"][0]
    assert (store.root / doc["baseline"]["path"]).read_bytes() == raw
    assert (store.root / doc["baseline"]["source_zip_path"]).read_bytes() == original_archive
    assert path.read_bytes() == original_archive
    expected = coco_segmentation_to_mask(source["annotations"][0]["segmentation"], 36, 48)
    actual = segmentation_to_mask(doc["annotations"][0]["segmentation"], 36, 48)
    saved = cv2.imread(str(store.root / doc["annotations"][0]["mask_path"]), 0)
    assert np.array_equal(expected, actual)
    assert np.array_equal(saved != 0, expected != 0)
    entry = next(c for c in store.classes()["classes"] if c["id"] == 7)
    assert entry["name"] == "Class_C_Body"
    assert entry["source_name"] == "Grade_C_Body" and entry["model_class_id"] == 6


def test_primary_selection_restart_export_scope_upload_idempotency_and_explicit_secondary(store, tmp_path):
    legacy = store.list()["images"][0]
    path, _, _ = source_zip(tmp_path)
    report = store.import_primary_zip(path)
    registry = store.datasets()
    assert registry["primary_dataset_id"] == report["dataset_id"]
    assert {d["id"] for d in registry["datasets"]} == {report["dataset_id"], LEGACY_DATASET_ID}
    assert next(d for d in registry["datasets"] if d["id"] == LEGACY_DATASET_ID)["primary"] is False
    assert {d["id"] for d in store._selected(approved_only=True)} == set(report["image_ids"])
    assert [d["id"] for d in store._selected([legacy["id"]], approved_only=True)] == [legacy["id"]]
    uploaded = store.upload(png(91), "new.png")
    assert uploaded["dataset_id"] == report["dataset_id"]
    assert store.upload(png(91), "again.png", dataset_id=LEGACY_DATASET_ID) == uploaded
    assert store.upload(png(92), "secondary.png", dataset_id=LEGACY_DATASET_ID)["dataset_id"] == LEGACY_DATASET_ID
    with pytest.raises(AnnotationError, match="not registered"):
        store.upload(png(93), "invalid.png", dataset_id="absent")
    reopened = AnnotationStore(store.root, store.manual_source)
    assert reopened.datasets() == registry
    assert reopened.get(uploaded["id"]) == uploaded
    assert reopened.import_primary_zip(path)["skipped"] == 3
    assert len(reopened.history(report["image_ids"][0])["revisions"]) == 1


def test_train_only_reference_descriptor_and_source_holdout_near_duplicate_protection(store, tmp_path):
    path, _, _ = source_zip(tmp_path, prefix="nested/", splits=["train", "val", "test", "train"])
    report = store.import_primary_zip(path)
    docs = [store.get(i) for i in report["image_ids"]]
    assert [d["split"] for d in docs] == ["train", "valid", "test", "train"]
    assert docs[0]["metadata"]["leakage_group_id"] == docs[1]["metadata"]["leakage_group_id"]
    assert docs[0]["metadata"]["protected_split"] == "valid"
    descriptor = json.loads((store.root / report["profile"]["reference_profile_path"]).read_bytes())
    assert descriptor["whole_fish_ground_truth_available"] is False
    assert descriptor["annotation_unit"] == "fish_part"
    assert descriptor["source_splits"] == ["train"]
    # The original train record linked to a validation near duplicate is also
    # held out of contextual class references. Independent train data remains.
    assert set(descriptor["classes"]) == {"Grade_A_Head"}
    assert descriptor["classes"]["Grade_A_Head"][0]["split"] == "train"
    assert descriptor["classes"]["Grade_A_Head"][0]["area_fraction"] > 0
    assert descriptor["classes"]["Grade_A_Head"][0]["image_id"] == docs[3]["id"]
    assert docs[0]["metadata"]["source_provenance"]["original_splits"] == ["train"]


@pytest.mark.parametrize("option", ["bad_path", "unknown"])
def test_invalid_archive_does_not_replace_selected_baseline(store, tmp_path, option):
    good_dir = tmp_path / "good"
    good_dir.mkdir()
    path, _, _ = source_zip(good_dir)
    initial = store.import_primary_zip(path)
    before = deepcopy(store.list())
    invalid_dir = tmp_path / "bad"
    invalid_dir.mkdir()
    bad, _, _ = source_zip(invalid_dir, **{option: True})
    with pytest.raises(AnnotationError):
        store.import_primary_zip(bad)
    assert primary_profile(store)["dataset_id"] == initial["dataset_id"]
    assert store.list() == before


def test_invalid_mask_and_missing_image_never_become_verified_or_certified(store, tmp_path):
    path, _, _ = source_zip(tmp_path, bad_mask=True)
    report = store.import_primary_zip(path)
    assert report["errors"] and not report["profile"]["training_certified"]
    assert report["profile"]["status"] == "needs_review"
    bad = store.get(report["image_ids"][0])
    assert bad["status"] == "unreviewed"
    assert bad["metadata"]["source_validation_errors"]
    assert bad["baseline"]["path"].endswith(".coco.json")
    repeated = store.import_primary_zip(path)
    assert repeated["skipped"] == 3 and repeated["errors"]
    assert repeated["profile"]["training_certified"] is False
    other = tmp_path / "missing"
    other.mkdir()
    missing, _, _ = source_zip(other, missing=True)
    failed = store.import_primary_zip(missing)
    assert failed["errors"] and failed["imported"] == 2
    assert failed["profile"]["training_certified"] is False


@pytest.mark.parametrize("kind", ["traversal", "symlink", "duplicate"])
def test_zip_security_rejects_unsafe_members_before_switch(store, tmp_path, kind):
    path, _, _ = source_zip(tmp_path)
    with zipfile.ZipFile(path, "a") as archive:
        if kind == "traversal":
            archive.writestr("../escape.txt", "unsafe")
        elif kind == "symlink":
            entry = zipfile.ZipInfo("symlink")
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(entry, "../outside")
        else:
            archive.writestr("images/1.png", png(44))
    with pytest.raises(AnnotationError):
        store.import_primary_zip(path)
    assert primary_profile(store) is None
    assert len(store.list()["images"]) == 1


def test_all_rejected_annotations_cannot_be_approved_as_an_empty_scene(store):
    doc = store.get(store.list()["images"][0]["id"])
    rejected = deepcopy(doc["annotations"])
    for annotation in rejected:
        annotation["status"] = "rejected"
    saved = store.save(doc["id"], doc["revision"], rejected)
    with pytest.raises(AnnotationError, match="Every annotation is rejected"):
        store.approve(doc["id"], saved["revision"])
    assert store.get(doc["id"])["status"] == "corrected"


def test_export_keeps_declared_near_duplicate_groups_in_protected_holdout(store, tmp_path):
    path, _, _ = source_zip(tmp_path)
    report = store.import_primary_zip(path)
    docs = [store.get(i) for i in report["image_ids"]]
    with zipfile.ZipFile(store.export("coco", report["image_ids"], split=True)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assignments = {i["id"]: i["split"] for i in manifest["images"]}
    assert assignments[docs[0]["id"]] == assignments[docs[1]["id"]] == "valid"
    assert assignments[docs[2]["id"]] == "test"
    # Even when the matching validation image is not selected, its preserved
    # protected_split prevents this train duplicate becoming training data.
    with zipfile.ZipFile(store.export("coco", [docs[0]["id"]], split=True)) as archive:
        selected = json.loads(archive.read("manifest.json"))
    assert selected["images"][0]["split"] == "valid"


def test_registry_dataset_identity_cannot_be_reused_for_a_different_archive(store, tmp_path):
    first = tmp_path / "first"
    first.mkdir()
    path, _, _ = source_zip(first)
    initial = store.import_primary_zip(path, dataset_id="fixed-baseline")
    second = tmp_path / "second"
    second.mkdir()
    other, _, _ = source_zip(second, splits=["train"])
    with pytest.raises(AnnotationError, match="different immutable source"):
        store.import_primary_zip(other, dataset_id="fixed-baseline")
    assert primary_profile(store)["source_sha256"] == initial["profile"]["source_sha256"]


def test_canonical_binary_bbox_matches_reference_at_full_resolution():
    from src.annotation.masks import mask_bbox
    from src.annotation.store import _pixel_bbox
    rng = np.random.default_rng(120)
    for shape in [(1, 1), (36, 48), (2160, 3840)]:
        mask = np.zeros(shape, np.uint8)
        ys = rng.integers(0, shape[0], size=20)
        xs = rng.integers(0, shape[1], size=20)
        mask[ys, xs] = 1
        assert _pixel_bbox(mask) == mask_bbox(mask)
    with pytest.raises(ValueError, match="no foreground"):
        _pixel_bbox(np.zeros((32, 32), np.uint8))


def test_baseline_metadata_review_edits_preserve_immutable_source_and_holdout(store, tmp_path):
    path, _, _ = source_zip(tmp_path)
    report = store.import_primary_zip(path)
    original = store.get(report["image_ids"][0])
    updated = store.save(original["id"], original["revision"], original["annotations"],
                         metadata={"review_status": "needs_correction", "note": "Check tail"})
    for key, value in original["metadata"].items():
        assert updated["metadata"][key] == value
    assert updated["metadata"]["review_status"] == "needs_correction"
    for field, value in [("protected_split", "train"), ("leakage_group_id", "new-group"),
                         ("dataset_group_id", "new-group"), ("source_provenance", {}),
                         ("dataset_id", "another-dataset"), ("source_annotation_count", 0)]:
        with pytest.raises(AnnotationError, match="provenance"):
            store.save(updated["id"], updated["revision"], updated["annotations"], metadata={field: value})
    assert store.get(updated["id"]) == updated
    with zipfile.ZipFile(store.export("coco", [updated["id"]], split=True)) as archive:
        selected = json.loads(archive.read("manifest.json"))
    assert selected["images"][0]["split"] == "valid"


def test_uploaded_feedback_still_accepts_explicit_custom_group_metadata(store):
    document = store.upload(png(100), "feedback.png")
    metadata = {"dataset_group_id": "known-independent-capture", "protected_split": "train"}
    updated = store.save(document["id"], document["revision"], [], metadata=metadata)
    assert updated["metadata"] == metadata


def test_primary_import_class_allocation_never_reuses_a_deleted_class_id(tmp_path):
    fresh = AnnotationStore(tmp_path / "fresh-workspace", tmp_path / "absent-manual-source")
    temporary = fresh.add_class({"name": "Temporary custom class", "kind": "anatomy"})
    fresh.delete_class(temporary["id"])
    path, _, _ = source_zip(tmp_path)
    report = fresh.import_primary_zip(path)
    assert report["errors"] == []
    imported_ids = {mapping["registry_class_id"] for mapping in report["profile"]["category_mapping"]}
    assert min(imported_ids) > temporary["id"]
    assert temporary["id"] not in {entry["id"] for entry in fresh.classes()["classes"]}


def test_exact_roi_overlap_counts_match_full_masks_for_holes_duplicates_and_disjoint_objects():
    from src.annotation.store import _mask_intersection, _pixel_bbox
    masks = []
    for x, y, width, height in [(2, 3, 20, 18), (30, 3, 20, 18), (12, 13, 20, 18), (2, 3, 20, 18)]:
        mask = np.zeros((64, 80), np.uint8)
        mask[y:y + height, x:x + width] = 1
        masks.append(mask)
    holed = masks[0].copy()
    holed[8:12, 8:12] = 0
    holed[50:53, 65:68] = 1
    masks.append(holed)
    for first in masks:
        for second in masks:
            assert _mask_intersection(first, second, _pixel_bbox(first), _pixel_bbox(second)) == int(np.count_nonzero(first & second))
