"""Dataset boundaries in library views and saved exports use one canonical store."""
from copy import deepcopy
from io import BytesIO
import json
import zipfile

import cv2
from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
import pytest

from src.annotation.store import AnnotationStore
from src.api.annotation_library import create_library_router, normalize_document


API = "/api/annotation-library"
PRIMARY = "fish-annotations-cleaned-dbf50ab47c1d"
LEGACY = "v2-coco-v7"


def pixels(value):
    ok, data = cv2.imencode(".png", np.full((24, 32, 3), value, np.uint8))
    assert ok
    return data.tobytes()


def client_for(store):
    app = FastAPI()
    app.include_router(create_library_router(store))
    return TestClient(app)


def saved_image(store, value, dataset_id, *, annotated=True, approved=False):
    document = store.upload(pixels(value), f"fish-{value}.png")
    fish_class = next(category["id"] for category in store.classes()["classes"] if category["kind"] == "whole_fish")
    annotations = [{"id": f"fish-{value}", "class_id": fish_class, "parent_id": None,
        "segmentation": [[2, 2, 20, 2, 20, 18, 2, 18]], "confidence": .9,
        "source": "automated", "status": "unreviewed", "flags": [],
        "metadata": {"source_metadata": {"camera": "synthetic", "retain": [1, 2]}}}] if annotated else []
    document = store.save(document["id"], document["revision"], annotations,
        metadata={"dataset_id": dataset_id, "source_metadata": {"license": "fixture", "retain": True}})
    # Seed explicit fixture ownership through the canonical transaction, rather
    # than creating another registry or annotation database for these tests.
    with store.connection(write=True) as connection:
        document = store._get(connection, document["id"])
        document["dataset_id"] = dataset_id
        document["revision"] += 1
        document = store._persist(connection, document)
    if approved:
        document = store.approve(document["id"], document["revision"])
    return document


@pytest.fixture
def datasets(tmp_path, monkeypatch):
    store = AnnotationStore(tmp_path / "workspace", tmp_path / "missing-source")
    primary = saved_image(store, 40, PRIMARY, approved=True)
    primary_second = saved_image(store, 50, PRIMARY)
    pending = saved_image(store, 60, PRIMARY, annotated=False)
    legacy = saved_image(store, 70, LEGACY, approved=True)
    registry = {"datasets": [
        {"id": PRIMARY, "name": "Fish Annotations Cleaned", "primary": True,
         "source_type": "zip", "source_sha256": "fixture-primary-sha", "training_certified": False,
         "reference_eligible": False, "status": "imported"},
        {"id": LEGACY, "name": "Retained V2 baseline", "primary": False,
         "source_type": "coco", "source_sha256": "fixture-legacy-sha", "status": "retained"},
    ], "primary_dataset_id": PRIMARY}
    monkeypatch.setattr(store, "datasets", lambda: deepcopy(registry), raising=False)
    with client_for(store) as client:
        yield store, client, primary, primary_second, pending, legacy, registry


def test_catalog_retains_canonical_primary_identity_and_metadata(datasets):
    _, client, _, _, _, _, registry = datasets
    response = client.get(f"{API}/datasets")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["primary_dataset_id"] == PRIMARY
    assert {dataset["id"]: dataset["image_count"] for dataset in data["datasets"]} == {PRIMARY: 3, LEGACY: 1}
    for original, exposed in zip(registry["datasets"], data["datasets"]):
        assert all(exposed[key] == value for key, value in original.items())
        assert exposed["dataset_id"] == original["id"]
    assert "image_count" not in registry["datasets"][0]


def test_dashboard_and_gallery_dataset_filters_do_not_mix_primary_and_legacy(datasets):
    _, client, primary, second, pending, legacy, _ = datasets
    summary = client.get(f"{API}/summary", params={"dataset_id": PRIMARY}).json()
    assert summary["total_images"] == 3 and summary["total_annotated_objects"] == 2
    assert summary["completed_annotations"] == 2 and summary["pending_annotations"] == 1
    assert summary["approved_annotations"] == 1 and summary["saved_datasets"] == 1
    assert summary["dataset_id"] == PRIMARY and summary["primary_dataset_id"] == PRIMARY
    page = client.get(f"{API}/images", params={"dataset_id": PRIMARY, "page_size": 2}).json()
    assert page["total"] == 3 and page["pages"] == 2
    assert all(image["dataset_id"] == PRIMARY for image in page["images"])
    completed = client.get(f"{API}/images", params={"dataset_id": PRIMARY, "completed": True}).json()
    assert {image["image_id"] for image in completed["images"]} == {primary["id"], second["id"]}
    retained = client.get(f"{API}/images", params={"dataset_id": LEGACY}).json()
    assert retained["total"] == 1 and retained["images"][0]["image_id"] == legacy["id"]
    assert client.get(f"{API}/summary").json()["total_images"] == 4
    assert client.get(f"{API}/images").json()["total"] == 4


@pytest.mark.parametrize("scope", ["all", "approved", "current", "selected"])
def test_export_saved_dataset_scope_retains_masks_and_source_metadata(datasets, scope):
    store, client, first, second, _, legacy, _ = datasets
    ids = [first["id"]] if scope == "current" else [first["id"], second["id"]]
    response = client.post(f"{API}/export", json={"scope": scope, "dataset_id": PRIMARY, "image_ids": ids})
    assert response.status_code == 200, response.text
    exported = json.loads(response.content)
    expected = {first["id"]} if scope in {"approved", "current"} else {first["id"], second["id"]}
    assert {image["image_id"] for image in exported["images"]} == expected
    assert legacy["id"] not in expected
    assert exported["dataset"]["dataset_id"] == PRIMARY
    assert exported["dataset"]["name"] == "Fish Annotations Cleaned"
    assert [dataset["id"] for dataset in exported["dataset"]["source_datasets"]] == [PRIMARY]
    for image in exported["images"]:
        native = store.get(image["image_id"])
        assert image["dataset_id"] == PRIMARY
        assert image["annotations"][0]["segmentation"] == native["annotations"][0]["segmentation"]
        assert image["metadata"]["source_metadata"] == native["metadata"]["source_metadata"]
        assert image["annotations"][0]["metadata"]["source_metadata"] == native["annotations"][0]["metadata"]["source_metadata"]


@pytest.mark.parametrize("scope", ["current", "selected"])
def test_current_and_selected_export_reject_images_from_another_dataset(datasets, scope):
    _, client, primary, _, _, legacy, _ = datasets
    ids = [legacy["id"]] if scope == "current" else [primary["id"], legacy["id"]]
    response = client.post(f"{API}/export", json={"scope": scope, "dataset_id": PRIMARY, "image_ids": ids})
    assert response.status_code == 422 and "another dataset" in response.json()["detail"]
    assert "content-disposition" not in response.headers


def test_dataset_package_contains_only_matching_originals_and_saved_annotations(datasets):
    store, client, first, second, _, legacy, _ = datasets
    response = client.post(f"{API}/export", json={"scope": "all", "dataset_id": PRIMARY, "package": True})
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        assert archive.testzip() is None
        data = json.loads(archive.read("annotations/dataset.json"))
        assert {image["image_id"] for image in data["images"]} == {first["id"], second["id"]}
        assert all(legacy["id"] not in name for name in archive.namelist())
        for image in data["images"]:
            document = store.get(image["image_id"])
            assert archive.read(image["original_image_path"]) == (store.root / document["original_path"]).read_bytes()


@pytest.mark.parametrize("value", ["", " ", "unknown", "*", " primary "])
def test_invalid_dataset_query_never_falls_back_to_all_datasets(datasets, value):
    _, client, *_ = datasets
    for route in ("summary", "images"):
        response = client.get(f"{API}/{route}", params={"dataset_id": value})
        assert response.status_code == 422


@pytest.mark.parametrize("value", [None, "", " ", "unknown", [], {}, 12, True])
def test_invalid_export_dataset_never_generates_download(datasets, value):
    _, client, *_ = datasets
    response = client.post(f"{API}/export", json={"scope": "all", "dataset_id": value})
    assert response.status_code == 422 and "content-disposition" not in response.headers


def test_existing_duplicate_upload_never_reassigns_dataset_or_loses_metadata(datasets):
    store, client, first, *_ = datasets
    before = deepcopy(store.get(first["id"]))
    history = deepcopy(store.history(first["id"]))
    response = client.post(f"{API}/upload", content=pixels(40), headers={"X-Filename": "renamed.png", "X-Dataset-ID": LEGACY})
    assert response.status_code == 200, response.text
    assert response.json()["image_id"] == first["id"] and response.json()["dataset_id"] == PRIMARY
    assert store.get(first["id"]) == before and store.history(first["id"]) == history


def test_explicit_dataset_upload_assigns_only_new_empty_record(datasets):
    store, client, *_ = datasets
    response = client.post(f"{API}/upload", content=pixels(90), headers={"X-Filename": "new.png", "X-Dataset-ID": LEGACY})
    assert response.status_code == 200, response.text
    image = response.json()
    document = store.get(image["image_id"])
    assert image["dataset_id"] == LEGACY
    assert not document["annotations"] and not document.get("baseline")
    assert client.get(f"{API}/images", params={"dataset_id": LEGACY}).json()["total"] == 2


def test_unknown_upload_dataset_rejects_before_creating_record(datasets):
    store, client, *_ = datasets
    before = deepcopy(store.list())
    response = client.post(f"{API}/upload", content=pixels(91), headers={"X-Filename": "new.png", "X-Dataset-ID": "unknown"})
    assert response.status_code == 422 and store.list() == before


def test_normalization_uses_canonical_identity_and_preserves_all_source_metadata(datasets):
    store, _, first, *_ = datasets
    document = deepcopy(store.get(first["id"]))
    document["metadata"]["dataset_id"] = LEGACY
    document["source_metadata"] = {"arbitrary": [1, {"retain": True}]}
    before = deepcopy(document)
    image = normalize_document(document, store.classes()["classes"])
    assert image["dataset_id"] == PRIMARY
    assert image["source_metadata"] == document["source_metadata"]
    assert image["metadata"]["dataset_id"] == LEGACY
    assert image["metadata"]["source_metadata"] == document["metadata"]["source_metadata"]
    assert document == before


def test_registry_fallback_derives_saved_documents_without_new_storage(tmp_path):
    store = AnnotationStore(tmp_path / "workspace", tmp_path / "missing-source")
    first = saved_image(store, 100, PRIMARY)
    saved_image(store, 101, LEGACY)
    class WithoutRegistry:
        def __getattr__(self, key):
            if key == "datasets":
                raise AttributeError(key)
            return getattr(store, key)
    with client_for(WithoutRegistry()) as client:
        data = client.get(f"{API}/datasets").json()
        assert {dataset["id"] for dataset in data["datasets"]} == {PRIMARY, LEGACY}
        assert data["primary_dataset_id"] is None
        assert client.get(f"{API}/images", params={"dataset_id": PRIMARY}).json()["images"][0]["image_id"] == first["id"]
    assert {path.name for path in store.root.glob("*.sqlite*")} <= {"annotations.sqlite3", "annotations.sqlite3-wal", "annotations.sqlite3-shm"}


@pytest.mark.parametrize("package", [False, True])
def test_approved_export_excludes_review_rejection_but_preserves_rejected_class(datasets, package):
    store, client, first, *_ = datasets
    rejected_class = store.add_class({"name": "Rejected_Body", "kind": "anatomy",
        "color": "#993333", "region": "body", "quality_grade": "Rejected"})
    current = store.get(first["id"])
    annotations = deepcopy(current["annotations"])
    annotations.extend([
        {"id": "review-rejected-fish", "class_id": annotations[0]["class_id"],
         "parent_id": None, "segmentation": [[23, 3, 29, 3, 29, 15, 23, 15]],
         "confidence": .6, "source": "user", "status": "rejected", "flags": [],
         "metadata": {"review_reason": "duplicate detection"}},
        {"id": "valid-rejected-quality-class", "class_id": rejected_class["id"],
         "parent_id": annotations[0]["id"], "segmentation": [[4, 4, 10, 4, 10, 10, 4, 10]],
         "confidence": .9, "source": "user", "status": "unreviewed", "flags": []},
    ])
    current = store.save(current["id"], current["revision"], annotations)
    current = store.approve(current["id"], current["revision"])
    before = deepcopy(current)
    response = client.post(f"{API}/export", json={"scope": "approved", "dataset_id": PRIMARY, "package": package})
    assert response.status_code == 200, response.text
    if package:
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            data = json.loads(archive.read("annotations/dataset.json"))
            masks = [name for name in archive.namelist() if name.startswith("masks/")]
            assert len(masks) == 2
    else:
        data = response.json()
    assert len(data["images"]) == 1
    exported = data["images"][0]["annotations"]
    assert {annotation["annotation_id"] for annotation in exported} == {current["annotations"][0]["id"], "valid-rejected-quality-class"}
    assert any(annotation["class_name"] == "Rejected_Body" for annotation in exported)
    assert data["dataset"]["excluded_annotation_count"] == 1
    assert "Review-rejected" in data["dataset"]["review_filter"]
    archival = client.post(f"{API}/export", json={"scope": "current", "image_ids": [current["id"]], "dataset_id": PRIMARY}).json()
    rejected = next(annotation for annotation in archival["images"][0]["annotations"] if annotation["annotation_id"] == "review-rejected-fish")
    assert rejected["review_status"] == "rejected" and rejected["metadata"]["review_reason"] == "duplicate detection"
    assert store.get(current["id"]) == before


def test_bulk_approval_rejects_image_with_only_review_rejected_objects_atomically(datasets):
    store, client, first, second, *_ = datasets
    response = client.get(f"{API}/images/{second['id']}")
    image = response.json()
    for annotation in image["annotations"]:
        annotation["status"] = "rejected"
    reviewed = client.put(f"{API}/images/{second['id']}", json={"base_version": image["version"],
        "annotations": image["annotations"], "status": "needs_review", "review_status": "reviewed"})
    assert reviewed.status_code == 200, reviewed.text
    before = deepcopy(store.get(second["id"]))
    first_before = deepcopy(store.get(first["id"]))
    response = client.post(f"{API}/approve", json={"images": [
        {"image_id": first["id"], "base_version": first_before["revision"]},
        {"image_id": second["id"], "base_version": before["revision"]},
    ]})
    assert response.status_code == 422 and "non-rejected" in response.json()["detail"]
    assert store.get(first["id"]) == first_before and store.get(second["id"]) == before


@pytest.mark.parametrize("selection", [None, PRIMARY])
def test_discovery_resumes_registered_primary_without_accepting_client_paths(datasets, monkeypatch, selection):
    store, client, first, *_, registry = datasets
    registry["datasets"][0].update(source_type="coco_zip", source_path="registered/immutable-baseline.zip", status="importing")
    before = deepcopy(store.get(first["id"]))
    calls = []
    def resume(path, **kwargs):
        calls.append((path, kwargs))
        return {"imported": 2, "skipped": 3, "errors": []}
    monkeypatch.setattr(store, "import_primary_zip", resume)
    monkeypatch.setattr(store, "import_manual", lambda: pytest.fail("Primary discovery must not import the secondary dataset"))
    payload = {"source_path": "untrusted/client-path.zip"}
    if selection:
        payload["dataset_id"] = selection
    response = client.post(f"{API}/scan", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["dataset_id"] == PRIMARY
    assert response.json()["imported"] == 2 and response.json()["existing"] == 3
    assert calls == [("registered/immutable-baseline.zip", {"dataset_id": PRIMARY, "name": "Fish Annotations Cleaned"})]
    assert store.get(first["id"]) == before


def test_discovery_of_secondary_uses_existing_importer(datasets, monkeypatch):
    store, client, *_ = datasets
    monkeypatch.setattr(store, "import_primary_zip", lambda *args, **kwargs: pytest.fail("Secondary discovery must not import primary"))
    monkeypatch.setattr(store, "import_manual", lambda: {"imported": 0, "skipped": 1, "errors": ["Source fixture unavailable"]})
    response = client.post(f"{API}/scan", json={"dataset_id": LEGACY})
    assert response.status_code == 200, response.text
    assert response.json()["dataset_id"] == LEGACY and response.json()["errors"] == ["Source fixture unavailable"]


@pytest.mark.parametrize("selection", ["unknown-dataset", "", None, PRIMARY])
def test_discovery_refuses_unknown_or_unregistered_source(datasets, monkeypatch, selection):
    store, client, *_ = datasets
    monkeypatch.setattr(store, "import_primary_zip", lambda *args, **kwargs: pytest.fail("Invalid source must not be imported"))
    monkeypatch.setattr(store, "import_manual", lambda: pytest.fail("Invalid source must not import the secondary dataset"))
    response = client.post(f"{API}/scan", json={"dataset_id": selection})
    assert response.status_code == 422 and "detail" in response.json()
