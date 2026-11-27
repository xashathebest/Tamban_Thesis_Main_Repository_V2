"""Independent checks of persistence, provenance, and review eligibility."""
from copy import deepcopy
import json
from pathlib import Path
import zipfile

import cv2
import numpy as np
import pytest

from src.annotation.masks import mask_to_rle
from src.annotation.store import AnnotationError, AnnotationStore, RevisionConflict


def image_bytes(value=37, width=64, height=48):
    ok, encoded = cv2.imencode(".png", np.full((height, width, 3), value, np.uint8))
    assert ok
    return encoded.tobytes()


@pytest.fixture
def local_store(tmp_path):
    source = tmp_path / "manual"
    split = source / "train"
    split.mkdir(parents=True)
    (split / "fish.png").write_bytes(image_bytes())
    baseline = {
        "info": {"author": "manual", "arbitrary": ["keep", 123]},
        "categories": [
            {"id": 1, "name": "Grade_A_Body", "supercategory": "fish"},
            {"id": 2, "name": "Grade_A_Head", "supercategory": "fish"},
        ],
        "images": [{"id": 4, "file_name": "fish.png", "width": 64, "height": 48}],
        "annotations": [{"id": 7, "image_id": 4, "category_id": 1,
                         "bbox": [4, 5, 12, 10],
                         "segmentation": [[4, 5, 16, 5, 16, 15, 4, 15]],
                         "iscrowd": 0, "author_note": "do not mutate"}],
    }
    (split / "_annotations.coco.json").write_text(json.dumps(baseline), encoding="utf-8")
    return AnnotationStore(tmp_path / "workspace", source)


def item(store, identifier, box, category=None, parent=None):
    if category is None:
        category = next(c["id"] for c in store.classes()["classes"] if c["kind"] == "whole_fish")
    mask = np.zeros((48, 64), np.uint8)
    x, y, width, height = box
    mask[y:y + height, x:x + width] = 1
    return {"id": identifier, "class_id": category, "parent_id": parent,
            "bbox": box, "segmentation": mask_to_rle(mask), "confidence": .9,
            "status": "unreviewed", "flags": []}


def predict(store, annotations):
    doc = store.upload(image_bytes(99), "new.png")
    return store.auto(doc["id"], doc["revision"], lambda *_: annotations)


def test_disjoint_part_parent_association_is_flagged(local_store):
    parent = item(local_store, "left-fish", [2, 5, 18, 25])
    head = item(local_store, "right-head", [40, 10, 10, 8], category=2, parent="left-fish")
    doc = predict(local_store, [parent, head])
    report = local_store.validate([doc["id"]])
    issues = report["errors"] + report["warnings"]
    assert any(issue.get("annotation_id") == "right-head" and
               any(term in issue["message"].lower() for term in ("parent", "ownership", "association"))
               for issue in issues), "A head entirely outside its fish parent must flag an association error."


@pytest.mark.parametrize("field,value", [("region", []), ("region", {}), ("quality_grade", [])])
def test_class_semantic_metadata_cannot_accept_container_values(local_store, field, value):
    with pytest.raises(AnnotationError):
        local_store.update_class(2, {field: value})


def test_exported_annotation_name_matches_renamed_registry(local_store):
    doc = predict(local_store, [item(local_store, "head", [5, 5, 10, 8], category=2)])
    doc = local_store.approve(doc["id"], doc["revision"])
    local_store.update_class(2, {"name": "Head renamed"})
    with zipfile.ZipFile(local_store.export("coco", [doc["id"]])) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        coco = json.loads(archive.read("_annotations.coco.json"))
        name = next(c["name"] for c in coco["categories"] if c["source_id"] == 2)
        assert manifest["images"][0]["annotations"][0]["class_name"] == name


@pytest.mark.parametrize("height,width", [(99, 101), (1080, 1920)])
def test_yolo_export_mask_survives_training_float32_and_int32_decode(local_store, height, width):
    doc = local_store.upload(image_bytes(value=27, width=width, height=height), "wide.png")
    mask = np.zeros((height, width), np.uint8)
    mask[7:38, 11:58] = 1
    category = next(c["id"] for c in local_store.classes()["classes"] if c["kind"] == "whole_fish")
    annotation = {"id": "fish", "class_id": category, "segmentation": mask_to_rle(mask),
                  "bbox": [11, 7, 47, 31], "parent_id": None, "status": "unreviewed"}
    doc = local_store.auto(doc["id"], doc["revision"], lambda *_: [annotation])
    doc = local_store.approve(doc["id"], doc["revision"])
    with zipfile.ZipFile(local_store.export("yolo_segmentation", [doc["id"]])) as archive:
        label = archive.read(f"labels/{doc['id']}.txt").decode().split()
    # Match the installed Ultralytics label dtype and polygon2mask's int32 cast.
    points = np.asarray(label[1:], np.float32).reshape(-1, 2)
    points *= np.asarray([width, height], np.float32)
    actual = np.zeros_like(mask)
    cv2.fillPoly(actual, [points.astype(np.int32)], 1)
    assert np.array_equal(actual, mask), "Training's float32 scaling/int32 rasterization changed reviewed pixels."


def test_failed_transaction_preserves_approved_revision_and_baseline(local_store):
    report = local_store.import_manual(["train"])
    doc = local_store.get(report["image_ids"][0])
    previous = deepcopy(doc)
    baseline_bytes = (local_store.root / doc["baseline"]["path"]).read_bytes()
    annotations = deepcopy(doc["annotations"])
    annotations[0]["segmentation"] = {"size": [48, 64], "counts": [1]}
    with pytest.raises(AnnotationError):
        local_store.save(doc["id"], doc["revision"], annotations)
    reopened = AnnotationStore(local_store.root, local_store.manual_source)
    assert reopened.get(doc["id"]) == previous
    assert len(reopened.history(doc["id"])["revisions"]) == 1
    assert (local_store.root / doc["baseline"]["path"]).read_bytes() == baseline_bytes


def test_rejected_parent_cannot_own_approved_part(local_store):
    parent = item(local_store, "fish", [2, 2, 30, 30])
    head = item(local_store, "head", [3, 3, 8, 8], category=2, parent="fish")
    doc = predict(local_store, [parent, head])
    annotations = deepcopy(doc["annotations"])
    annotations[0]["status"] = "rejected"
    with pytest.raises(AnnotationError, match="rejected"):
        local_store.save(doc["id"], doc["revision"], annotations)
    assert local_store.get(doc["id"]) == doc


def test_stale_second_store_cannot_overwrite_approved_annotations(local_store):
    doc = predict(local_store, [item(local_store, "fish", [2, 2, 20, 20])])
    second_store = AnnotationStore(local_store.root, local_store.manual_source)
    approved = local_store.approve(doc["id"], doc["revision"])
    with pytest.raises(RevisionConflict):
        second_store.save(doc["id"], doc["revision"], [])
    assert second_store.get(doc["id"]) == approved
    assert len(second_store.list()["images"]) == 1


def test_interrupted_revision_publication_rolls_back_database(local_store, monkeypatch):
    doc = predict(local_store, [item(local_store, "fish", [2, 2, 20, 20])])
    approved = local_store.approve(doc["id"], doc["revision"])
    previous_history = local_store.history(doc["id"])
    original_artifact = local_store._artifact

    def interrupted_artifact(directory, data, suffix):
        path = original_artifact(directory, data, suffix)
        if directory == "revisions":
            raise OSError("simulated interruption after durable artifact publication")
        return path

    monkeypatch.setattr(local_store, "_artifact", interrupted_artifact)
    changed = deepcopy(approved["annotations"])
    changed[0]["class_id"] = 1
    with pytest.raises(OSError, match="interruption"):
        local_store.save(doc["id"], approved["revision"], changed)
    reopened = AnnotationStore(local_store.root, local_store.manual_source)
    assert reopened.get(doc["id"]) == approved
    assert reopened.history(doc["id"]) == previous_history
    assert reopened.validate([doc["id"]])["valid"]


def test_user_cannot_promote_changed_object_by_forging_review_state(local_store):
    doc = predict(local_store, [item(local_store, "head", [4, 4, 10, 8], category=2)])
    approved = local_store.approve(doc["id"], doc["revision"])
    annotations = deepcopy(approved["annotations"])
    annotations[0].update(class_id=1, source="manual", status="manual_verified")
    edited = local_store.save(doc["id"], approved["revision"], annotations, status="approved")
    assert edited["status"] == "corrected"
    assert edited["annotations"][0]["source"] == "user"
    assert edited["annotations"][0]["status"] == "corrected"
    with pytest.raises(AnnotationError, match="unreviewed"):
        local_store.export("coco", [doc["id"]])
