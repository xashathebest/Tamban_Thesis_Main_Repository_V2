"""Exercise saved library workflows against the canonical store, without models.

Fixtures deliberately use synthetic pixels/masks: these tests establish data
integrity and API behavior, not the accuracy of automated annotations.
"""
from copy import deepcopy
from io import BytesIO
import json
import sqlite3
import zipfile

import cv2
from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
import pytest

from src.annotation.masks import mask_to_rle, segmentation_to_mask
from src.annotation.store import AnnotationStore
from src.api.annotation_library import create_library_router


API = "/api/annotation-library"
WIDTH, HEIGHT = 64, 48


def png(value=40):
    success, data = cv2.imencode(".png", np.full((HEIGHT, WIDTH, 3), value, np.uint8))
    assert success
    return data.tobytes()


def client_for(store):
    app = FastAPI()
    app.include_router(create_library_router(store))
    return TestClient(app)


@pytest.fixture
def library(tmp_path):
    source = tmp_path / "synthetic_manual"
    split = source / "train"
    split.mkdir(parents=True)
    (split / "baseline.png").write_bytes(png())
    coco = {
        "info": {"description": "Synthetic baseline, immutable author metadata"},
        "licenses": [{"id": 8, "name": "Synthetic fixture"}],
        "categories": [
            {"id": 0, "name": "dried-fish-quality-grades", "supercategory": "none"},
            {"id": 1, "name": "Grade_A_Body", "supercategory": "fish"},
            {"id": 2, "name": "Grade_A_Head", "supercategory": "fish"},
        ],
        "images": [{"id": 19, "file_name": "baseline.png", "width": WIDTH, "height": HEIGHT,
                    "license": 8, "camera_metadata": {"original": "keep"}}],
        "annotations": [{"id": 27, "image_id": 19, "category_id": 1,
                         "bbox": [10, 10, 20, 10], "segmentation": [[10, 10, 30, 10, 30, 20, 10, 20]],
                         "iscrowd": 0, "source_custom": {"author": "fixture"}}],
    }
    (split / "_annotations.coco.json").write_text(json.dumps(coco, indent=2), encoding="utf-8")
    store = AnnotationStore(tmp_path / "workspace", source)
    imported = store.import_manual(["train"])
    assert imported["errors"] == [] and imported["imported"] == 1
    with client_for(store) as client:
        yield store, client, imported["image_ids"][0], coco


def objects(store, *, multiple=False, holes=False):
    fish_class = next(category["id"] for category in store.classes()["classes"] if category["kind"] == "whole_fish")
    whole = {"id": "fish-001", "class_id": fish_class, "parent_id": None,
             "segmentation": [[3, 3, 28, 3, 28, 28, 3, 28]], "confidence": 0.91,
             "status": "unreviewed", "source": "automated", "flags": [],
             "metadata": {"model": "synthetic", "extra": {"preserve": True}},
             "pipeline_extension": {"unknown_future_field": [1, 2]}}
    result = [whole]
    if multiple or holes:
        mask = np.zeros((HEIGHT, WIDTH), np.uint8)
        mask[6:23, 6:23] = 1
        if holes:
            mask[10:14, 10:14] = 0
            mask[24:26, 24:26] = 1
        result.append({"id": "part-001", "class_id": 1, "parent_id": "fish-001",
                       "segmentation": mask_to_rle(mask), "confidence": 0.83,
                       "status": "unreviewed", "source": "automated", "flags": []})
    if multiple:
        result.append({"id": "fish-002", "class_id": fish_class, "parent_id": None,
                       "segmentation": [[34, 6, 57, 6, 57, 32, 34, 32]], "confidence": 0.87,
                       "status": "unreviewed", "source": "automated", "flags": []})
    return result


def automated(store, filename="ai.png", value=80, **options):
    document = store.upload(png(value), filename)
    predictions = objects(store, **options)
    return store.auto(document["id"], document["revision"], lambda *_: {
        "annotations": predictions, "automation": {"test_only": True, "model": "synthetic"}})


def detail(client, image_id):
    response = client.get(f"{API}/images/{image_id}")
    assert response.status_code == 200, response.text
    return response.json()


def save_review(client, image_id, review_status="reviewed", status="needs_review", annotations=None):
    current = detail(client, image_id)
    payload = {"base_version": current["version"], "status": status, "review_status": review_status}
    if annotations is not None:
        payload["annotations"] = annotations
    response = client.put(f"{API}/images/{image_id}", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def approve(client, *documents):
    return client.post(f"{API}/approve", json={"images": [
        {"image_id": document["image_id"], "base_version": document["version"]} for document in documents]})


def test_dashboard_counts_filters_search_pagination_and_sorting(library, monkeypatch):
    store, client, manual_id, _ = library
    store.upload(png(50), "pending.png")
    ai = automated(store, "Zebra-AI.png", 60, multiple=True)
    approved = automated(store, "Approved.png", 70)
    reviewed = save_review(client, approved["id"])
    assert approve(client, reviewed).status_code == 200
    correction = automated(store, "Correction.png", 80)
    save_review(client, correction["id"], "needs_correction", "edited")
    rejected = store.upload(png(90), "Rejected.png")
    save_review(client, rejected["id"], "rejected", "rejected")

    response = client.get(f"{API}/summary")
    assert response.status_code == 200
    summary = response.json()
    expected = {"total_images": 6, "completed_annotations": 4, "pending_annotations": 1,
                "approved_annotations": 1, "needs_correction": 1, "needs_review": 2,
                "rejected_images": 1, "saved_datasets": 2, "total_annotated_objects": 6}
    assert {key: summary[key] for key in expected} == expected
    assert summary["storage_path"] == str(store.root / "annotations.sqlite3")
    assert detail(client, manual_id)["status"] == "needs_review"
    assert detail(client, manual_id)["review_status"] == "needs_review"

    found = client.get(f"{API}/images", params={"search": "ZEBRA-ai", "completed": True}).json()
    assert found["total"] == 1 and found["images"][0]["image_id"] == ai["id"]
    assert found["images"][0]["fish_count"] == 2 and found["images"][0]["part_count"] == 1
    assert found["images"][0]["status"] == "ai_annotated"
    for status, image_id in [("approved", approved["id"]), ("needs_correction", correction["id"]),
                             ("rejected", rejected["id"])]:
        page = client.get(f"{API}/images", params={"status": status}).json()
        assert page["total"] == 1 and page["images"][0]["image_id"] == image_id
    assert client.get(f"{API}/images", params={"completed": True}).json()["total"] == 4
    assert client.get(f"{API}/images", params={"status": "saved"}).json()["total"] == 6

    rows = store.list()["images"]
    names = sorted(row["filename"] for row in rows)
    for sort, expected_names in [("filename", sorted(names, key=str.casefold)),
                                 ("filename_asc", sorted(names, key=str.casefold)),
                                 ("filename_desc", sorted(names, key=str.casefold, reverse=True))]:
        page = client.get(f"{API}/images", params={"sort": sort}).json()
        assert [image["file_name"] for image in page["images"]] == expected_names
    by_date = sorted(rows, key=lambda row: (row["updated_at"], row["id"]))
    assert [image["image_id"] for image in client.get(f"{API}/images", params={"sort": "date_asc"}).json()["images"]] == [row["id"] for row in by_date]
    for order, ordered in [("updated_asc", by_date), ("updated_desc", list(reversed(by_date)))]:
        page = client.get(f"{API}/images", params={"sort": order})
        assert page.status_code == 200
        assert [image["image_id"] for image in page.json()["images"]] == [row["id"] for row in ordered]
    statuses = client.get(f"{API}/images", params={"sort": "status"}).json()["images"]
    assert [image["status"] for image in statuses] == sorted(image["status"] for image in statuses)

    reads = []
    native_get = store.get
    def tracked_get(image_id):
        reads.append(image_id)
        return native_get(image_id)
    monkeypatch.setattr(store, "get", tracked_get)
    page = client.get(f"{API}/images", params={"page": 2, "page_size": 2, "sort": "filename"}).json()
    assert page["total"] == 6 and page["pages"] == 3 and len(page["images"]) == 2
    assert len(reads) == 2
    assert all("annotations" not in image and image["saved"] for image in page["images"])
    assert client.get(f"{API}/images", params={"page": 99}).json()["images"] == []


def test_normalization_preserves_classes_masks_fish_and_source_metadata(library):
    store, client, manual_id, coco = library
    manual = detail(client, manual_id)
    annotation = manual["annotations"][0]
    assert annotation["class_id"] == 1 and annotation["class_name"] == "Grade_A_Body"
    assert annotation["fish_id"] is None and annotation["source"] == "imported"
    assert annotation["status"] == annotation["review_status"] == "needs_review"
    assert annotation["metadata"]["workspace_fields"]["original_annotation"] == coco["annotations"][0]
    assert annotation["metadata"]["workspace_status"] == "manual_verified"
    assert manual["metadata"]["source_record"] == coco["images"][0]
    assert manual["metadata"]["source_dataset_metadata"]["info"] == coco["info"]
    assert manual["metadata"]["source_dataset_metadata"]["licenses"] == coco["licenses"]

    native = automated(store, multiple=True, holes=True)
    normalized = detail(client, native["id"])
    assert normalized["fish_count"] == 2 and normalized["part_count"] == 1
    assert [item["fish_id"] for item in normalized["annotations"]] == ["fish-001", "fish-001", "fish-002"]
    for original, exported in zip(native["annotations"], normalized["annotations"]):
        assert exported["annotation_id"] == original["id"]
        assert exported["class_id"] == original["class_id"]
        assert exported["confidence"] == original["confidence"]
        assert exported["source"] == "ai_generated"
        assert np.array_equal(segmentation_to_mask(exported["segmentation"], HEIGHT, WIDTH),
                              segmentation_to_mask(original["segmentation"], HEIGHT, WIDTH))
    assert normalized["annotations"][0]["metadata"]["workspace_fields"]["pipeline_extension"] == {"unknown_future_field": [1, 2]}
    assert normalized["annotations"][0]["metadata"]["extra"] == {"preserve": True}


def test_edit_save_reopen_history_and_unrelated_metadata_survive(library):
    store, client, _, _ = library
    native = automated(store, holes=True)
    native = store.save(native["id"], native["revision"], native["annotations"],
                        metadata={"learning": {"protected": True}, "source_split": "train"})
    before = detail(client, native["id"])
    edited = deepcopy(before["annotations"])
    edited[1]["class_id"], edited[1]["class_name"] = 2, "Grade_A_Head"
    edited[1]["segmentation"]["counts"] = deepcopy(edited[1]["segmentation"]["counts"])
    saved = save_review(client, native["id"], "needs_review", "edited", edited)
    assert saved["saved"] is True and saved["version"] == before["version"] + 1
    assert saved["annotations"][1]["class_name"] == "Grade_A_Head"
    assert saved["annotations"][1]["source"] == "human_corrected"
    assert saved["metadata"]["learning"] == {"protected": True}
    assert saved["metadata"]["source_split"] == "train"
    assert saved["annotations"][0]["segmentation"] == before["annotations"][0]["segmentation"]

    restarted = AnnotationStore(store.root, store.manual_source)
    with client_for(restarted) as reopened:
        assert detail(reopened, native["id"]) == saved
        history = reopened.get(f"{API}/images/{native['id']}/history").json()["versions"]
        assert history[0]["version"] == saved["version"] and len(history) == saved["version"]
        original = reopened.get(f"{API}/images/{native['id']}", params={"version": before["version"]}).json()
        assert original == before
    assert restarted.get_revision(native["id"], before["version"])["annotations"][1]["class_id"] == 1


def test_mask_correction_add_and_delete_preserve_other_fish(library):
    store, client, _, _ = library
    native = automated(store, multiple=True, holes=True)
    before = detail(client, native["id"])
    edited = deepcopy(before["annotations"])
    edited[1]["segmentation"] = [[5, 6, 22, 6, 22, 16, 5, 16], [23, 19, 25, 19, 25, 21, 23, 21]]
    added = deepcopy(edited[1])
    added.update(annotation_id="part-002", object_id="part-002", fish_id="fish-002",
                 class_id=2, class_name="Grade_A_Head", segmentation=[[35, 8, 42, 8, 42, 16, 35, 16]])
    edited.append(added)
    saved = save_review(client, native["id"], "needs_review", "edited", edited)
    assert saved["annotation_count"] == 4 and saved["fish_count"] == 2 and saved["part_count"] == 2
    assert saved["annotations"][0]["segmentation"] == before["annotations"][0]["segmentation"]
    assert saved["annotations"][2]["segmentation"] == before["annotations"][2]["segmentation"]
    assert saved["annotations"][1]["segmentation"] == edited[1]["segmentation"]
    assert saved["annotations"][3]["source"] == "human_corrected"
    assert store.get(native["id"])["annotations"][3]["parent_id"] == "fish-002"
    remaining = [annotation for annotation in saved["annotations"] if annotation["annotation_id"] != "part-002"]
    deleted = save_review(client, native["id"], "needs_review", "edited", remaining)
    assert deleted["annotation_count"] == 3 and deleted["part_count"] == 1
    assert len(store.get_revision(native["id"], saved["version"])["annotations"]) == 4
    assert len(AnnotationStore(store.root, store.manual_source).get(native["id"])["annotations"]) == 3


def test_correcting_imported_annotation_keeps_immutable_manual_baseline(library):
    store, client, manual_id, coco = library
    source_path = store.manual_source / "train" / "_annotations.coco.json"
    source_bytes = source_path.read_bytes()
    initial = deepcopy(store.get(manual_id))
    imported = detail(client, manual_id)
    corrected = deepcopy(imported["annotations"])
    corrected[0].update(class_id=2, class_name="Grade_A_Head",
                        segmentation=[[8, 9, 25, 9, 25, 22, 8, 22]])
    saved = save_review(client, manual_id, "needs_review", "edited", corrected)
    assert saved["annotations"][0]["source"] == "human_corrected"
    assert saved["annotations"][0]["metadata"]["workspace_fields"]["original_annotation"] == coco["annotations"][0]
    assert store.get_revision(manual_id, 1) == initial
    assert source_path.read_bytes() == source_bytes
    assert (store.root / initial["baseline"]["path"]).read_bytes() == source_bytes
    initial_version = client.get(f"{API}/images/{manual_id}", params={"version": 1}).json()
    assert initial_version == imported


def test_failed_save_rolls_back_and_stale_version_retains_saved_record(library, monkeypatch):
    store, client, _, _ = library
    native = automated(store)
    previous = deepcopy(store.get(native["id"]))
    previous_history = deepcopy(store.history(native["id"]))
    native_persist = store._persist
    def fail_after_write(connection, document):
        native_persist(connection, document)
        raise sqlite3.OperationalError("synthetic disk failure")
    with monkeypatch.context() as patch:
        patch.setattr(store, "_persist", fail_after_write)
        response = client.put(f"{API}/images/{native['id']}", json={
            "base_version": native["revision"], "status": "edited", "review_status": "reviewed"})
    assert response.status_code == 503 and "previous saved version" in response.json()["detail"]
    assert store.get(native["id"]) == previous
    assert store.history(native["id"]) == previous_history
    saved = save_review(client, native["id"])
    response = client.put(f"{API}/images/{native['id']}", json={
        "base_version": previous["revision"], "annotations": [], "status": "not_annotated"})
    assert response.status_code == 409
    assert detail(client, native["id"]) == saved


def test_native_edit_invalidates_review_marker_and_requires_fresh_review(library):
    store, client, _, _ = library
    native = automated(store)
    reviewed = save_review(client, native["id"])
    assert reviewed["review_status"] == "reviewed"
    current = store.get(native["id"])
    changed = deepcopy(current["annotations"])
    changed[0]["confidence"] = 0.7
    store.save(native["id"], current["revision"], changed)
    edited = detail(client, native["id"])
    assert edited["review_status"] == "needs_review" and edited["status"] == "edited"
    row = client.get(f"{API}/images", params={"search": native["filename"]}).json()["images"][0]
    assert row["review_status"] == "needs_review" and row["status"] == "edited"
    assert approve(client, edited).status_code == 422
    assert approve(client, reviewed).status_code == 409
    assert approve(client, save_review(client, native["id"])).status_code == 200


def test_flagging_approved_image_revokes_approval_and_requires_review(library):
    store, client, _, _ = library
    native = automated(store)
    assert approve(client, save_review(client, native["id"])).status_code == 200
    flagged = save_review(client, native["id"], "needs_correction", "needs_review")
    assert flagged["status"] == "needs_review" and flagged["review_status"] == "needs_correction"
    assert store.get(native["id"])["status"] != "approved"
    summary = client.get(f"{API}/summary").json()
    assert summary["approved_annotations"] == 0 and summary["needs_correction"] == 1
    assert approve(client, flagged).status_code == 422
    empty = client.post(f"{API}/export", json={"scope": "approved"})
    assert empty.status_code == 422 and "No saved annotations" in empty.json()["detail"]
    assert approve(client, save_review(client, native["id"])).status_code == 200


def test_bulk_approval_requires_review_and_is_atomic_on_failures(library, monkeypatch):
    store, client, _, _ = library
    first, second = automated(store, "first.png", 80), automated(store, "second.png", 81)
    first_review = save_review(client, first["id"])
    unreviewed = detail(client, second["id"])
    first_before = deepcopy(store.get(first["id"]))
    assert approve(client, first_review, unreviewed).status_code == 422
    assert store.get(first["id"]) == first_before
    second_review = save_review(client, second["id"])
    second_before = deepcopy(store.get(second["id"]))
    native_persist = store._persist
    def fail_second(connection, document):
        if document["id"] == second["id"]:
            raise OSError("synthetic second-image storage failure")
        return native_persist(connection, document)
    with monkeypatch.context() as patch:
        patch.setattr(store, "_persist", fail_second)
        assert approve(client, first_review, second_review).status_code == 503
    assert store.get(first["id"]) == first_before
    assert store.get(second["id"]) == second_before
    response = approve(client, first_review, second_review)
    assert response.status_code == 200 and response.json()["approved"] == 2
    assert all(image["status"] == "approved" for image in response.json()["images"])
    assert client.get(f"{API}/summary").json()["approved_annotations"] == 2


@pytest.mark.parametrize("scope", ["current", "selected", "all", "approved"])
def test_json_export_scopes_saved_geometry_and_metadata_roundtrip(library, scope):
    store, client, manual_id, coco = library
    first = automated(store, "first.png", 80, holes=True)
    second = automated(store, "second.png", 81)
    store.upload(png(82), "pending.png")
    assert approve(client, save_review(client, first["id"])).status_code == 200
    selected_ids = [manual_id] if scope == "current" else [manual_id, first["id"]]
    payload = {"scope": scope, "image_ids": selected_ids,
               "annotations": [{"segmentation": "frontend values must never be exported"}]}
    response = client.post(f"{API}/export", json=payload)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert f"fish-annotations-{scope}-" in response.headers["content-disposition"]
    exported = json.loads(response.content)
    assert json.loads(json.dumps(exported, allow_nan=False)) == exported
    expected_ids = ({manual_id} if scope == "current" else {manual_id, first["id"]} if scope == "selected"
                    else {first["id"]} if scope == "approved" else {manual_id, first["id"], second["id"]})
    assert {image["image_id"] for image in exported["images"]} == expected_ids
    assert exported["dataset"]["image_count"] == len(expected_ids)
    assert exported["dataset"]["bbox_format"] == "xywh"
    assert exported["dataset"]["annotation_count"] == sum(len(image["annotations"]) for image in exported["images"])
    for image in exported["images"]:
        saved = store.get(image["image_id"])
        assert image["version"] == saved["revision"] and image["saved"]
        assert image["width"] == WIDTH and image["height"] == HEIGHT
        assert image["created_at"] and image["updated_at"]
        assert len(image["annotations"]) == len(saved["annotations"])
        for annotation, native in zip(image["annotations"], saved["annotations"]):
            assert annotation["annotation_id"] == native["id"]
            assert annotation["object_id"] == native["id"]
            assert annotation["class_id"] == native["class_id"]
            assert annotation["bbox"] == native["bbox"] and annotation["segmentation"]
            assert annotation["created_at"] and annotation["updated_at"]
            assert np.array_equal(segmentation_to_mask(annotation["segmentation"], HEIGHT, WIDTH),
                                  segmentation_to_mask(native["segmentation"], HEIGHT, WIDTH))
            if image["image_id"] == manual_id:
                assert annotation["metadata"]["workspace_fields"]["original_annotation"] == coco["annotations"][0]
                assert image["metadata"]["source_record"] == coco["images"][0]
                assert image["status"] != "approved"
    if scope == "approved":
        assert all(image["status"] == "approved" for image in exported["images"])


def test_complete_package_contains_verified_original_pixels_masks_and_json(library):
    store, client, manual_id, _ = library
    native = automated(store, holes=True)
    response = client.post(f"{API}/export", json={"scope": "selected", "image_ids": [manual_id, native["id"]], "package": True})
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        assert archive.testzip() is None
        exported = json.loads(archive.read("annotations/dataset.json"))
        assert len(exported["images"]) == 2
        assert "COCO polygon/RLE" in archive.read("README.txt").decode()
        for image in exported["images"]:
            saved = store.get(image["image_id"])
            assert archive.read(image["original_image_path"]) == (store.root / saved["original_path"]).read_bytes()
            canonical = cv2.imdecode(np.frombuffer(archive.read(image["image_path"]), np.uint8), cv2.IMREAD_COLOR)
            assert np.array_equal(canonical, store.frame(image["image_id"]))
            for annotation in saved["annotations"]:
                member = f"masks/{image['image_id']}/{annotation['mask_path'].split('/')[-1]}"
                mask = cv2.imdecode(np.frombuffer(archive.read(member), np.uint8), 0)
                assert np.array_equal(mask != 0, segmentation_to_mask(annotation["segmentation"], HEIGHT, WIDTH) != 0)


def test_package_missing_original_fails_without_download_and_preserves_annotations(library):
    store, client, manual_id, _ = library
    native = store.get(manual_id)
    (store.root / native["original_path"]).unlink()
    response = client.post(f"{API}/export", json={"scope": "current", "image_ids": [manual_id], "package": True})
    assert response.status_code == 422 and "artifact" in response.json()["detail"]
    assert (store.root / native["original_path"]).name in response.json()["detail"]
    assert "content-disposition" not in response.headers
    assert store.get(manual_id) == native


def test_corrupted_immutable_baseline_is_rejected_for_detail_and_export(library):
    store, client, manual_id, _ = library
    native = store.get(manual_id)
    (store.root / native["baseline"]["path"]).write_bytes(b"corrupted synthetic source")
    assert client.get(f"{API}/images/{manual_id}").status_code == 422
    response = client.post(f"{API}/export", json={"scope": "current", "image_ids": [manual_id]})
    assert response.status_code == 422 and "content-disposition" not in response.headers


@pytest.mark.parametrize("payload", [
    {"scope": "unknown"}, {"scope": "current", "image_ids": []},
    {"scope": "selected", "image_ids": ["absent"]}, {"scope": "all", "package": "yes"},
])
def test_export_invalid_requests_report_errors(library, payload):
    _, client, _, _ = library
    assert client.post(f"{API}/export", json=payload).status_code in {404, 422}


def test_upload_media_thumbnail_and_scan_are_idempotent(library):
    store, client, manual_id, _ = library
    original = (store.manual_source / "train" / "_annotations.coco.json").read_bytes()
    response = client.post(f"{API}/upload", content=png(100), headers={"X-Filename": "new%20fish.png"})
    assert response.status_code == 200
    document = response.json()
    assert document["file_name"] == "new fish.png" and document["status"] == "not_annotated"
    duplicate = client.post(f"{API}/upload", content=png(100), headers={"X-Filename": "again.png"}).json()
    assert duplicate["image_id"] == document["image_id"]
    full = client.get(f"{API}/images/{document['image_id']}/media")
    raw = client.get(f"{API}/images/{document['image_id']}/media", params={"original": True})
    thumbnail = client.get(f"{API}/images/{manual_id}/media", params={"thumbnail": True})
    assert full.status_code == raw.status_code == thumbnail.status_code == 200
    assert raw.content == png(100)
    assert thumbnail.headers["content-type"] == "image/jpeg"
    assert cv2.imdecode(np.frombuffer(thumbnail.content, np.uint8), cv2.IMREAD_COLOR).shape[:2] == (HEIGHT, WIDTH)
    scan = client.post(f"{API}/scan").json()
    assert scan["imported"] == 0 and scan["existing"] == 1
    assert (store.manual_source / "train" / "_annotations.coco.json").read_bytes() == original
    assert len(store.list()["images"]) == 2


def test_one_object_review_and_edit_preserve_other_fish_exactly(library):
    store, client, _, _ = library
    native = automated(store, multiple=True)
    original_peer = deepcopy(native["annotations"][-1])
    record = detail(client, native["id"])
    record["annotations"][0]["status"] = "approved"
    saved = save_review(client, native["id"], "needs_review", "edited", record["annotations"])
    assert saved["status"] == "edited"
    assert saved["annotations"][0]["review_status"] == "approved"
    assert store.get(native["id"])["annotations"][-1] == original_peer
    saved["annotations"][0]["class_id"] = 1
    saved["annotations"][0]["class_name"] = "Grade_A_Body"
    saved["annotations"][0]["fish_id"] = None
    # Remove its parented part explicitly when converting the whole fish class.
    saved["annotations"][1]["fish_id"] = None
    save_review(client, native["id"], "needs_review", "edited", saved["annotations"])
    assert store.get(native["id"])["annotations"][-1] == original_peer


def test_export_reads_each_shared_immutable_baseline_once(tmp_path, monkeypatch):
    source = tmp_path / "source"
    split = source / "train"
    split.mkdir(parents=True)
    images = [{"id": i, "file_name": f"fish_{i}.png", "width": WIDTH, "height": HEIGHT} for i in (1, 2)]
    for image in images:
        (split / image["file_name"]).write_bytes(png())
    data = {"images": images, "categories": [{"id": 1, "name": "Grade_A_Body", "supercategory": "fish"}],
            "annotations": [{"id": i, "image_id": i, "category_id": 1, "bbox": [4, 4, 10, 10],
                             "segmentation": [[4, 4, 14, 4, 14, 14, 4, 14]]} for i in (1, 2)]}
    (split / "_annotations.coco.json").write_text(json.dumps(data), encoding="utf-8")
    store = AnnotationStore(tmp_path / "workspace", source)
    assert store.import_manual(["train"])["imported"] == 2
    verifies = []
    verify = store._verify_artifact
    def counting_verify(path):
        if path.name.endswith(".coco.json"):
            verifies.append(path)
        return verify(path)
    monkeypatch.setattr(store, "_verify_artifact", counting_verify)
    with client_for(store) as client:
        response = client.post(f"{API}/export", json={"scope": "all"})
    assert response.status_code == 200, response.text
    assert len(response.json()["images"]) == 2
    assert len(verifies) == 1
