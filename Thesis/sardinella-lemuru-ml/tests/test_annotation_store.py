"""Exercise durable artifacts and review/export behavior, without model stubs as truth."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import zipfile

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.annotation.masks import coco_segmentation_to_mask, mask_to_rle, segmentation_to_mask, yolo_polygon
from src.annotation.store import AnnotationError, AnnotationStore, RevisionConflict
from src.api.annotation_workspace import create_annotation_router


def png(width=64, height=48, value=40):
    frame = np.full((height, width, 3), value, dtype=np.uint8)
    ok, data = cv2.imencode(".png", frame)
    assert ok
    return data.tobytes()


@pytest.fixture
def store(tmp_path):
    source = tmp_path / "manual"
    split = source / "train"
    split.mkdir(parents=True)
    (split / "fish.png").write_bytes(png())
    data = {"info": {"note": "Original author data"}, "categories": [
        {"id": 0, "name": "dried-fish-quality-grades", "supercategory": "none"},
        {"id": 1, "name": "Grade_A_Body", "supercategory": "dried-fish-quality-grades"},
        {"id": 2, "name": "Grade_A_Head", "supercategory": "dried-fish-quality-grades"}],
        "images": [{"id": 9, "file_name": "fish.png", "width": 64, "height": 48, "extra": {"original": "preserve"}}],
        "annotations": [{"id": 7, "image_id": 9, "category_id": 1, "bbox": [10, 10, 20, 10], "segmentation": [[10, 10, 30, 10, 30, 20, 10, 20]], "iscrowd": 0, "extra": "retained"}]}
    (split / "_annotations.coco.json").write_text(json.dumps(data, indent=3), encoding="utf-8")
    return AnnotationStore(tmp_path / "workspace", source)


def annotation(store, identifier="fish", class_id=None, x=5, y=5, w=12, h=18, parent=None):
    class_id = class_id if class_id is not None else next(c["id"] for c in store.classes()["classes"] if c["kind"] == "whole_fish")
    mask = np.zeros((48, 64), dtype=np.uint8)
    mask[y:y + h, x:x + w] = 1
    return {"id": identifier, "class_id": class_id, "parent_id": parent, "segmentation": mask_to_rle(mask),
            "bbox": [x, y, w, h], "confidence": 0.85, "status": "unreviewed", "source": "automated", "flags": []}


def uploaded(store):
    return store.upload(png(value=80), "new.png")


def automated(store, objects=None):
    doc = uploaded(store)
    objects = objects if objects is not None else [annotation(store)]
    return store.auto(doc["id"], doc["revision"], lambda doc, frame, classes: {"annotations": objects, "automation": {"test": "synthetic output only"}})


def test_manual_original_bytes_snapshot_idempotent_and_restart(store):
    source = store.manual_source / "train" / "_annotations.coco.json"
    original = source.read_bytes()
    report = store.import_manual(["train"])
    assert report["imported"] == 1 and report["errors"] == []
    document = store.get(report["image_ids"][0])
    assert document["status"] == "manual_verified"
    assert document["annotations"][0]["original_annotation"]["extra"] == "retained"
    assert document["source_record"]["extra"]["original"] == "preserve"
    assert document["annotations"][0]["bbox"] == [10, 10, 20, 10]
    assert document["annotations"][0]["area"] == 200
    assert (store.root / document["baseline"]["path"]).read_bytes() == original
    store._verify_artifact(store.root / document["baseline"]["path"])
    assert source.read_bytes() == original
    assert store.import_manual(["train"])["skipped"] == 1
    reopened = AnnotationStore(store.root, store.manual_source)
    assert reopened.get(document["id"]) == document
    assert reopened.history(document["id"])["revisions"][0]["revision"] == 1
    assert reopened.validate()["valid"]


def test_original_mask_and_ground_truth_survive_edit_and_restore(store):
    doc = store.get(store.import_manual(["train"])["image_ids"][0])
    original = deepcopy(doc)
    edited = deepcopy(doc["annotations"])
    edited[0]["class_id"] = 2
    result = store.save(doc["id"], 1, edited)
    assert result["annotations"][0]["status"] == "corrected"
    assert result["annotations"][0]["source"] == "user"
    assert result["annotations"][0]["region"] == "head"
    assert store.get_revision(doc["id"], 1) == original
    restored = store.restore(doc["id"], result["revision"], 1)
    assert restored["annotations"] == original["annotations"]
    assert restored["status"] == "manual_verified"
    with pytest.raises(RevisionConflict):
        store.auto(doc["id"], restored["revision"], lambda *args: [])


def test_actual_png_masks_rle_holes_and_islands_are_lossless(store):
    mask = np.zeros((48, 64), np.uint8)
    mask[4:20, 6:22] = 1
    mask[8:12, 10:14] = 0
    mask[30:34, 40:44] = 1
    assert np.array_equal(segmentation_to_mask(mask_to_rle(mask), 48, 64), mask)
    item = annotation(store)
    item["segmentation"] = mask_to_rle(mask)
    document = automated(store, [item])
    persisted = cv2.imread(str(store.root / document["annotations"][0]["mask_path"]), 0)
    assert np.array_equal(persisted != 0, mask != 0)
    document = store.approve(document["id"], document["revision"])
    with zipfile.ZipFile(store.export("coco")) as archive:
        coco = json.loads(archive.read("_annotations.coco.json"))
        restored = segmentation_to_mask(coco["annotations"][0]["segmentation"], 48, 64)
        assert np.array_equal(restored, mask)
        manifest = json.loads(archive.read("manifest.json"))
        path = manifest["images"][0]["annotations"][0]["mask_path"]
        encoded_mask = cv2.imdecode(np.frombuffer(archive.read(path), np.uint8), 0)
        assert np.array_equal(encoded_mask != 0, mask != 0)
    with pytest.raises(AnnotationError, match="holes"):
        store.export("yolo_segmentation")


def test_conflicts_approved_protection_and_no_duplicate_saves(store):
    doc = automated(store)
    approved = store.approve(doc["id"], doc["revision"])
    with pytest.raises(RevisionConflict):
        store.save(doc["id"], doc["revision"], [])
    with pytest.raises(RevisionConflict):
        store.auto(doc["id"], approved["revision"], lambda *args: [])
    assert store.save(doc["id"], approved["revision"], approved["annotations"]) == approved
    assert store.upload(png(value=80), "renamed.png") == approved
    assert len(store.list()["images"]) == 1
    assert len(store.history(doc["id"])["revisions"]) == 3


@pytest.mark.parametrize("status", ["unreviewed", "corrected"])
def test_explicit_image_review_demotion_blocks_export(store, status):
    doc = automated(store)
    approved = store.approve(doc["id"], doc["revision"])
    demoted = store.save(doc["id"], approved["revision"], approved["annotations"],
                         status=status, metadata={"review_status": "needs_correction"})
    assert demoted["status"] == status
    assert demoted["metadata"]["review_status"] == "needs_correction"
    assert demoted["annotations"] == approved["annotations"]
    with pytest.raises(AnnotationError, match="No approved"):
        store.export()
    assert store.get_revision(doc["id"], approved["revision"])["status"] == "approved"


def test_unreviewed_never_exported_and_cannot_forge_manual_or_approved(store):
    doc = uploaded(store)
    forged = annotation(store)
    forged.update(source="manual", status="manual_verified")
    saved = store.save(doc["id"], 1, [forged], status="approved")
    assert saved["status"] == "corrected"
    assert saved["annotations"][0]["source"] == "user"
    assert saved["annotations"][0]["status"] == "corrected"
    with pytest.raises(AnnotationError, match="No approved"):
        store.export()
    with pytest.raises(AnnotationError, match="unreviewed"):
        store.export(image_ids=[doc["id"]])


def test_missing_mask_draft_retained_and_cannot_approve(store):
    item = annotation(store)
    item["segmentation"] = None
    doc = automated(store, [item])
    assert doc["annotations"][0]["segmentation"] is None
    assert "missing_segmentation" in doc["annotations"][0]["flags"]
    assert not store.validate()["valid"]
    with pytest.raises(AnnotationError, match="Incomplete segmentation"):
        store.approve(doc["id"], doc["revision"])
    item = deepcopy(doc["annotations"][0])
    item["status"] = "rejected"
    doc = store.save(doc["id"], doc["revision"], [item])
    with pytest.raises(AnnotationError, match="Every annotation is rejected"):
        store.approve(doc["id"], doc["revision"])
    assert doc["annotations"][0]["status"] == "rejected"
    # A discarded proposal does not certify an image as an empty scene. Once
    # a real object is added, the rejected draft remains part of the audit.
    doc = store.save(doc["id"], doc["revision"], [item, annotation(store, "valid-fish")])
    doc = store.approve(doc["id"], doc["revision"])
    assert store.export().exists()


def test_editing_class_and_boundary_one_object_preserves_another(store):
    first, second = annotation(store, "fish1"), annotation(store, "fish2", x=30)
    doc = automated(store, [first, second])
    doc = store.approve(doc["id"], doc["revision"])
    unchanged = deepcopy(doc["annotations"][1])
    edited = deepcopy(doc["annotations"])
    edited[0]["class_id"] = 2
    replacement = annotation(store, x=3, y=6, w=15, h=22)
    edited[0]["segmentation"] = replacement["segmentation"]
    result = store.save(doc["id"], doc["revision"], edited)
    assert result["annotations"][1] == unchanged
    assert result["annotations"][0]["bbox"] == [3, 6, 15, 22]
    assert result["annotations"][0]["class_id"] == 2
    assert result["status"] == "corrected"


def test_add_missing_object_class_management_mapping_and_yolo_roundtrip(store):
    created = store.add_class({"name": "Missing fin", "kind": "anatomy", "color": "#123456", "region": "fin"})
    doc = uploaded(store)
    item = annotation(store, class_id=created["id"])
    doc = store.save(doc["id"], doc["revision"], [item])
    renamed = store.update_class(created["id"], {"name": "Fin"})
    assert renamed["id"] == created["id"]
    with pytest.raises(AnnotationError, match="used"):
        store.delete_class(created["id"])
    unused = store.add_class({"name": "Unused"})
    store.delete_class(unused["id"])
    next_class = store.add_class({"name": "Later class"})
    assert next_class["id"] > unused["id"]
    doc = store.approve(doc["id"], doc["revision"])
    for fmt in ("yolo_detection", "yolo_segmentation"):
        with zipfile.ZipFile(store.export(fmt)) as archive:
            label = archive.read(f"labels/{doc['id']}.txt").decode().split()
            mapping = json.loads(archive.read("classes.json"))
            assert mapping[int(label[0])]["source_id"] == created["id"]
            assert mapping[int(label[0])]["name"] == "Fin"
            assert json.loads(archive.read("validation_report.json"))["valid"]
            if fmt == "yolo_segmentation":
                coordinates = [float(x) for x in label[1:]]
                polygon = [v * (64 if i % 2 == 0 else 48) for i, v in enumerate(coordinates)]
                assert np.array_equal(segmentation_to_mask([polygon], 48, 64), segmentation_to_mask(item["segmentation"], 48, 64))


def test_duplicate_and_parent_association_validation(store):
    first, duplicate = annotation(store, "first"), annotation(store, "duplicate")
    doc = automated(store, [first, duplicate])
    report = store.validate()
    assert any("duplicate" in e["message"] for e in report["errors"])
    with pytest.raises(AnnotationError, match="duplicate"):
        store.approve(doc["id"], doc["revision"])
    duplicate["parent_id"] = "absent"
    with pytest.raises(AnnotationError, match="association"):
        store.save(doc["id"], doc["revision"], [first, duplicate])


def test_disjoint_part_parent_cannot_approve_individually_or_batch(store):
    fish = annotation(store, "parent", x=1, y=1, w=20, h=20)
    part = annotation(store, "head", class_id=2, x=40, y=30, w=10, h=10, parent="parent")
    doc = automated(store, [fish, part])
    with pytest.raises(AnnotationError, match="disjoint"):
        store.approve(doc["id"], doc["revision"])
    individually = deepcopy(doc["annotations"])
    individually[1]["status"] = "approved"
    with pytest.raises(AnnotationError, match="disjoint"):
        store.save(doc["id"], doc["revision"], individually)
    assert store.get(doc["id"]) == doc


@pytest.mark.parametrize("field", ["region", "quality_grade"])
@pytest.mark.parametrize("value", [[], {}, 5, ""])
def test_invalid_class_semantic_metadata_rejected(store, field, value):
    with pytest.raises(AnnotationError, match=field):
        store.update_class(1, {field: value})


def test_class_rename_updates_export_metadata_without_rewriting_history(store):
    doc = automated(store)
    doc = store.approve(doc["id"], doc["revision"])
    fish_id = doc["annotations"][0]["class_id"]
    store.update_class(fish_id, {"name": "Reviewed whole fish"})
    assert store.get(doc["id"]) == doc
    with zipfile.ZipFile(store.export("coco")) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["images"][0]["annotations"][0]["class_name"] == "Reviewed whole fish"
    with zipfile.ZipFile(store.export("yolo_detection")) as archive:
        config = json.loads(archive.read("data.yaml"))
        assert config["train"] == "images" and config["val"] is None and config["test"] is None
        assert not json.loads(archive.read("validation_report.json"))["training_ready"]


def test_provenance_fields_cannot_be_forged_in_edit(store):
    doc = store.get(store.import_manual(["train"])["image_ids"][0])
    altered = deepcopy(doc["annotations"])
    original = deepcopy(altered[0]["original_annotation"])
    altered[0]["original_annotation"] = {"id": "forged"}
    altered[0]["source_category"] = {"name": "forged"}
    saved = store.save(doc["id"], doc["revision"], altered)
    assert saved["annotations"][0]["original_annotation"] == original
    assert saved["annotations"][0]["source_category"] == doc["annotations"][0]["source_category"]


def test_source_coco_pixels_keep_boundary_convention_separate_from_drawing():
    polygon = [[10, 10, 30, 10, 30, 20, 10, 20]]
    source = coco_segmentation_to_mask(polygon, 48, 64)
    drawing = segmentation_to_mask(polygon, 48, 64)
    assert source.sum() == 200 and drawing.sum() == 231
    assert np.all(source[10:20, 10:30] == 1) and source[20, 30] == 0


def test_coco_rasterizer_matches_optional_official_reference():
    official = pytest.importorskip("pycocotools.mask")
    examples = [
        [[10, 10, 30, 10, 30, 20, 10, 20]],
        [[.4, .2, 19.3, 8.7, 12.8, 30.1, 2.2, 14.4]],
        [[0, 0, 64, 0, 64, 48, 0, 48]],
        [[1, 1, 8, 1, 8, 9, 1, 9], [30, 20, 50, 21, 45, 40]],
    ]
    for segmentation in examples:
        expected = official.decode(official.merge(official.frPyObjects(segmentation, 48, 64)))
        assert np.array_equal(coco_segmentation_to_mask(segmentation, 48, 64), expected)
        compressed = official.encode(np.asfortranarray(expected))
        compressed["counts"] = compressed["counts"].decode("ascii")
        assert np.array_equal(coco_segmentation_to_mask(compressed, 48, 64), expected)


@pytest.mark.parametrize("shape", [(99, 101), (640, 640), (1080, 1920)])
def test_yolo_float32_training_loader_keeps_exact_native_mask(shape):
    mask = np.zeros(shape, np.uint8)
    mask[7:65, 11:81] = 1
    points = yolo_polygon(mask)
    serialized = " ".join(f"{v:.12g}" for v in points)
    loaded = np.asarray(serialized.split(), dtype=np.float32).reshape(-1, 2)
    loaded *= np.asarray([shape[1], shape[0]], dtype=np.float32)
    trainer_mask = np.zeros(shape, np.uint8)
    cv2.fillPoly(trainer_mask, [loaded.astype(np.int32)], 1)
    assert np.array_equal(mask, trainer_mask)


def test_overlapping_rotated_partial_multiple_fish_and_unknown_absence(store):
    items = [annotation(store, "first", x=0, y=0, w=25, h=20), annotation(store, "second", x=15, y=5, w=24, h=30)]
    rotated = annotation(store, "rotated")
    rotated["segmentation"] = [[40, 2, 61, 20, 50, 35, 35, 15]]
    items.append(rotated)
    doc = automated(store, items)
    report = store.validate()
    assert report["valid"]
    assert any("partially visible" in w["message"] for w in report["warnings"])
    assert any("overlap" in w["message"] for w in report["warnings"])
    assert any("absence unverified" in w["message"] for w in report["warnings"])
    assert store.approve(doc["id"], doc["revision"])["status"] == "approved"


def test_corrupt_png_and_source_snapshot_fail_validation_and_export(store):
    doc = store.get(store.import_manual(["train"])["image_ids"][0])
    (store.root / doc["annotations"][0]["mask_path"]).write_bytes(b"corrupt")
    report = store.validate()
    assert not report["valid"] and any("corrupt" in e["message"] for e in report["errors"])
    with pytest.raises(AnnotationError, match="validation"):
        store.export()
    (store.root / doc["baseline"]["path"]).write_bytes(b"corrupt source")
    assert any("snapshot" in e["message"] for e in store.validate()["errors"])


@pytest.mark.parametrize("segmentation", [
    [[1, 1, 1, 1, 1, 1]], [[1, 1, 3, 3, 6, 6]], [[1, 1, 8, 8, 1, 8, 8, 1]],
    [[-1, 1, 4, 1, 4, 8]], {"size": [48, 64], "counts": [2, 8]},
    {"size": [12, 12], "counts": [144]}, [[1, 1, float("nan"), 8, 8, 1]],
])
def test_invalid_coordinates_and_corrupt_masks_rejected(store, segmentation):
    doc = uploaded(store)
    item = annotation(store)
    item["segmentation"] = segmentation
    with pytest.raises(AnnotationError):
        store.save(doc["id"], doc["revision"], [item])
    assert store.get(doc["id"])["revision"] == 1


def test_same_pixels_never_leak_across_export_splits(store):
    train = store.manual_source / "train"
    valid = store.manual_source / "valid"
    valid.mkdir()
    (valid / "fish.png").write_bytes((train / "fish.png").read_bytes())
    (valid / "_annotations.coco.json").write_bytes((train / "_annotations.coco.json").read_bytes())
    assert store.import_manual(["train", "valid"])["imported"] == 2
    with zipfile.ZipFile(store.export(split=True)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert len({i["split"] for i in manifest["images"]}) == 1
        assert any("Identical image content" in w["message"] for w in manifest["validation"]["warnings"])


def test_model_mapping_stays_stable_on_rename(store):
    original = next(c for c in store.classes()["classes"] if c["id"] == 1)
    renamed = store.update_class(1, {"name": "Body"})
    assert renamed["model_class_id"] == original["model_class_id"] == 0
    assert renamed["source_name"] == "Grade_A_Body"
    with pytest.raises(AnnotationError, match="immutable"):
        store.update_class(1, {"model_class_id": 10})


def test_unused_original_model_and_source_classes_remain_available_before_import(store):
    # No source image has been imported yet, but deleting its reserved category
    # would make both Auto-Annotate and the baseline importer unrecoverable.
    assert not store.list()["images"]
    for category in store.classes()["classes"]:
        if category.get("source_name") is not None:
            with pytest.raises(AnnotationError, match="used by"):
                store.delete_class(category["id"])
    with pytest.raises(AnnotationError, match="must remain available"):
        store.update_class(1, {"active": False})
    with pytest.raises(AnnotationError, match="must remain available"):
        store.update_class(1, {"kind": "quality"})
    assert store.import_manual(["train"])["imported"] == 1


def test_api_upload_edit_review_export_restart_and_pixels(store):
    app = FastAPI()
    app.include_router(create_annotation_router(store, automation=lambda d, f, c: [annotation(store)]))
    client = TestClient(app)
    response = client.post("/api/annotations/images", content=png(value=80), headers={"X-Filename": "sample.png"})
    assert response.status_code == 200
    doc = response.json()
    pixels = client.get(f"/api/annotations/images/{doc['id']}/pixels")
    assert pixels.status_code == 200 and pixels.headers["content-type"] == "image/png"
    doc = client.post(f"/api/annotations/images/{doc['id']}/auto", json={"expected_revision": 1}).json()
    assert doc["annotations"][0]["source"] == "automated"
    approved = client.post(f"/api/annotations/images/{doc['id']}/approve", json={"expected_revision": doc["revision"]})
    assert approved.status_code == 200
    assert client.post(f"/api/annotations/images/{doc['id']}/approve", json={"expected_revision": 1}).status_code == 409
    response = client.post("/api/annotations/export", json={"format": "coco"})
    assert response.status_code == 200 and response.content.startswith(b"PK")
    restarted_app = FastAPI()
    restarted_app.include_router(create_annotation_router(AnnotationStore(store.root, store.manual_source)))
    reopened = TestClient(restarted_app).get(f"/api/annotations/images/{doc['id']}")
    assert reopened.json() == approved.json()


def test_class_and_image_path_inputs_remain_inside_workspace(store):
    with pytest.raises(AnnotationError):
        store.upload(b"not an image", "../../fish.png")
    doc = store.upload(png(value=80), "../../fish.png")
    assert doc["filename"] == "fish.png"
    assert (store.root / doc["original_path"]).resolve().is_relative_to(store.root)
    with pytest.raises(AnnotationError):
        store.add_class({"name": "Fish", "color": "red; background:url(example)"})


@pytest.mark.parametrize("field,value", [("kind", []), ("kind", {}), ("name", None), ("name", [])])
def test_malformed_class_types_return_validation_errors(store, field, value):
    with pytest.raises(AnnotationError):
        store.add_class({"name": "New class", field: value})


def test_malformed_status_split_format_and_revision_return_validation_errors(store):
    document = uploaded(store)
    with pytest.raises(AnnotationError):
        store.save(document["id"], 1, [], status={})
    with pytest.raises(AnnotationError):
        store.import_manual("train")
    with pytest.raises(AnnotationError):
        store.export(format=[])
    with pytest.raises(AnnotationError):
        store.restore(document["id"], 1, [])
