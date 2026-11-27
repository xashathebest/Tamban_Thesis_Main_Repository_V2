"""Acceptance tests against the real canonical store, HTTP routes and learning views."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import cv2
from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
import pytest

from src.annotation.masks import mask_to_rle, segmentation_to_mask
from src.annotation.store import AnnotationStore as CanonicalStore
from src.annotation_learning import LearningService
from src.api.annotation_review import apply_learning_context, bootstrap_manual_baseline, create_review_router, review_item, verify_review
from src.api.annotation_store import AnnotationStore
from src.preprocessing.audit_v7_exports import SOURCE_CLASSES


def png(value=50, extension=".png"):
    frame = np.full((48, 64, 3), value, dtype=np.uint8)
    frame[5:30, 8:40] += 15
    return cv2.imencode(extension, frame)[1].tobytes()


@pytest.fixture
def system(tmp_path):
    source = tmp_path / "manual"
    train = source / "train"
    train.mkdir(parents=True)
    (train / "manual.png").write_bytes(png())
    data = {"categories": [{"id": 0, "name": "dried-fish-quality-grades", "supercategory": "none"}] + [
        {"id": cid + 1, "name": name, "supercategory": "dried-fish-quality-grades"} for cid, name in SOURCE_CLASSES.items()],
        "images": [{"id": 0, "file_name": "manual.png", "width": 64, "height": 48, "extra": {"name": "manual-original.png"}}],
        "annotations": [{"id": 1, "image_id": 0, "category_id": 2, "bbox": [8, 8, 15, 15], "segmentation": [[8, 8, 23, 8, 23, 23, 8, 23]]}]}
    (train / "_annotations.coco.json").write_text(json.dumps(data), encoding="utf-8")
    store = CanonicalStore(tmp_path / "workspace", source)
    view = AnnotationStore(store)
    learning = LearningService(view, tmp_path / "learning", min_examples=25)
    app = FastAPI()
    app.include_router(create_review_router(store, learning))
    return store, view, learning, TestClient(app)


def label(object_id="head", class_id=2, *, complex_mask=False):
    mask = np.zeros((48, 64), np.uint8)
    mask[8:24, 8:24] = 1
    if complex_mask:
        mask[12:16, 12:16] = 0
        mask[30:33, 30:33] = 1
    return {"id": object_id, "class_id": class_id, "parent_id": None, "bbox": [8, 8, 16, 16],
        "segmentation": mask_to_rle(mask), "confidence": .7, "status": "unreviewed", "source": "automated"}


def predicted(store, value=90, labels=None, filename="new.png"):
    document = store.upload(png(value), filename)
    return store.auto(document["id"], document["revision"], lambda *_: {"annotations": labels or [label()], "automation": {"model_version": "test-original"}})


def test_approve_full_set_enters_same_database_pool_and_survives_restart(system):
    store, view, learning, client = system
    first = predicted(store)
    second = predicted(store, 100)
    response = client.post(f"/api/annotations/{first['id']}/review", json={"action": "approve", "revision": first["revision"], "review_time_ms": 2000})
    assert response.status_code == 200, response.text
    assert response.json()["next_image_id"] == second["id"]
    assert view.verified_examples()[0]["image_id"] == first["id"]
    assert view.stats()["approved_without_edit_rate"] == 1
    assert view.stats()["avg_review_time_ms"] == 2000
    assert learning.status()["pending_training_examples"] == 1
    restarted = CanonicalStore(store.root, store.manual_source)
    assert restarted.get(first["id"])["metadata"]["human_review"]["entire_annotation_set"] is True
    assert restarted.get_revision(first["id"], first["revision"])["annotations"] == first["annotations"]
    assert len(list(store.root.glob("*.sqlite3"))) == 1


def test_edit_class_mask_and_missing_tail_saves_one_atomic_verified_revision(system):
    store, view, _, client = system
    document = predicted(store)
    shown = client.get(f"/api/annotations/{document['id']}").json()
    head = shown["annotations"][0]
    head.update(class_id=5, class_name="Grade_B_Head", mask=[[7, 7], [24, 7], [24, 25], [7, 25]], mask_changed=True)
    tail = {"id": "new-tail", "class_id": 3, "class_name": "Grade_A_Tail", "fish_id": None,
        "mask": [[35, 30], [40, 30], [40, 35], [35, 35]], "mask_changed": True}
    response = client.post(f"/api/annotations/{document['id']}/review", json={"action": "edit", "revision": document["revision"], "annotations": [head, tail]})
    assert response.status_code == 200, response.text
    saved = store.get(document["id"])
    assert saved["revision"] == document["revision"] + 1
    assert saved["status"] == "approved" and all(a["status"] == "approved" for a in saved["annotations"])
    assert saved["annotations"][0]["source"] == "user"
    counts = view.get(document["id"])["corrections"]["counts"]
    assert counts["class_correction"] == counts["mask_correction"] == counts["missing_annotation"] == 1
    assert view.stats()["approved_without_edit_rate"] == 0


def test_class_only_edit_preserves_holes_and_disconnected_masks(system):
    store, _, _, client = system
    document = predicted(store, labels=[label(complex_mask=True)])
    displayed = client.get(f"/api/annotations/{document['id']}").json()["annotations"]
    assert displayed[0]["mask"] is None
    assert len(displayed[0]["contours"]) == 3
    displayed[0].update(class_id=5, class_name="Grade_B_Head")
    response = client.post(f"/api/annotations/{document['id']}/review", json={"action": "edit", "revision": document["revision"], "annotations": displayed})
    assert response.status_code == 200, response.text
    assert store.get(document["id"])["annotations"][0]["segmentation"] == document["annotations"][0]["segmentation"]


def test_decline_excludes_positive_labels_preserves_source_and_reason(system):
    store, view, learning, client = system
    document = predicted(store)
    pixels = store.pixels_path(document["id"]).read_bytes()
    response = client.post(f"/api/annotations/{document['id']}/review", json={"action": "decline", "revision": document["revision"], "reason": "unusable"})
    assert response.status_code == 200
    assert view.verified_examples() == []
    assert learning.status()["pending_training_examples"] == 0
    assert store.pixels_path(document["id"]).read_bytes() == pixels
    assert view.get(document["id"])["review_reason"] == "unusable"
    assert view.stats()["declined_rate"] == 1


def test_stale_revision_and_failed_edit_leave_complete_history_unchanged(system):
    store, _, _, client = system
    document = predicted(store)
    assert client.post(f"/api/annotations/{document['id']}/review", json={"action": "approve", "revision": 1}).status_code == 409
    displayed = client.get(f"/api/annotations/{document['id']}").json()["annotations"]
    displayed[0].update(mask_changed=True, mask=[[2, 2], [2, 2], [2, 2]])
    result = client.post(f"/api/annotations/{document['id']}/review", json={"action": "edit", "revision": document["revision"], "annotations": displayed})
    assert result.status_code == 422
    assert store.get(document["id"]) == document


def test_audit_failure_rolls_back_verified_labels(system):
    store, view, _, _ = system
    document = predicted(store)
    with store.connection(True) as db:
        db.execute("CREATE TRIGGER reject_review_metadata BEFORE INSERT ON annotation_feedback_metadata BEGIN SELECT RAISE(ABORT, 'review audit failed'); END")
    with pytest.raises(Exception, match="review audit failed"):
        verify_review(store, document["id"], {"action": "approve", "revision": document["revision"]})
    assert store.get(document["id"]) == document
    assert view.verified_examples() == []


def test_missing_mask_cannot_be_approved(system):
    store, _, _, client = system
    missing = label()
    missing["segmentation"] = None
    document = predicted(store, labels=[missing])
    result = client.post(f"/api/annotations/{document['id']}/review", json={"action": "approve", "revision": document["revision"]})
    assert result.status_code == 422


def test_manual_baseline_classes_and_protected_holdout_identity(system):
    store, view, _, _ = system
    imported = store.import_manual(["train"])
    manual = store.get(imported["image_ids"][0])
    row = view.get(manual["id"])
    assert row["annotations"][0]["class_id"] == 1
    assert row["annotations"][0]["class_name"] == "Grade_A_Head"
    assert row["annotations"][0]["fish_id"] is None
    assert row["group_id"] == "manual-original"
    # A held-out source group must reserve all matching feedback, even if the
    # copy is independently encoded or human-approved.
    with store.connection(True) as db:
        current = store._get(db, manual["id"])
        current["split"] = "test"
        current["revision"] += 1
        store._persist(db, current)
    copy = predicted(store, 110, filename="manual-original_jpg.rf.abcdef.png")
    verify_review(store, copy["id"], {"action": "approve", "revision": copy["revision"]})
    assert view.get(copy["id"])["quarantined"] is True
    assert not any(row["image_id"] == copy["id"] for row in view.verified_examples())


def test_duplicate_decoded_pixels_are_not_independent_feedback(system):
    store, view, _, _ = system
    first = predicted(store)
    verify_review(store, first["id"], {"action": "approve", "revision": first["revision"]})
    # Lossless BMP and PNG have different bytes but identical source pixels.
    copy = store.upload(png(90, ".bmp"), "same.bmp")
    copy = store.auto(copy["id"], copy["revision"], lambda *_: {"annotations": [label()], "automation": {"model_version": "same"}})
    verify_review(store, copy["id"], {"action": "approve", "revision": copy["revision"]})
    assert len(view.verified_examples()) == 1
    assert view.stats()["quarantined_examples"] == 1


def test_contradictory_verified_copies_quarantine_both(system):
    store, view, _, _ = system
    first = predicted(store)
    verify_review(store, first["id"], {"action": "approve", "revision": first["revision"]})
    copy = store.upload(png(90, ".bmp"), "same.bmp")
    copy = store.auto(copy["id"], copy["revision"], lambda *_: {"annotations": [label(class_id=5)], "automation": {"model_version": "other"}})
    verify_review(store, copy["id"], {"action": "approve", "revision": copy["revision"]})
    assert view.verified_examples() == []
    assert view.stats()["quarantined_examples"] == 2


def test_previous_verified_examples_affect_subsequent_prediction_context(system, monkeypatch):
    store, view, learning, _ = system
    first = predicted(store)
    verify_review(store, first["id"], {"action": "approve", "revision": first["revision"]})
    query = predicted(store, 91)
    from src.api import annotation_review
    monkeypatch.setattr(annotation_review, "get_learning_service", lambda *_: learning)
    original = {"annotations": deepcopy(query["annotations"]), "automation": {}}
    result = apply_learning_context(store, query, original)
    assert result["automation"]["learning_references"][0]["image_id"] == first["id"]
    assert result["annotations"][0]["segmentation"] == query["annotations"][0]["segmentation"]
    assert result["annotations"][0]["class_id"] == query["annotations"][0]["class_id"]
    assert result["annotations"][0]["status"] == "unreviewed"


def test_learning_status_uses_canonical_class_registry_and_unmeasured_metrics(system):
    _, _, _, client = system
    response = client.get("/api/annotations/learning/status")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["class_names"]["2"] == "Grade_A_Head"
    assert data["current_model_version"] == "reference-only"
    assert data["approved_without_edit_rate"] is None
    assert data["measured_improvement"] is False


def test_equivalent_polygon_and_rle_copy_keep_original_manual_baseline(system):
    store, view, _, _ = system
    imported = store.import_manual(["train"])
    original = store.get(imported["image_ids"][0])
    copy = store.upload(png(50, ".bmp"), "manual-copy.bmp")
    annotation = label()
    binary = segmentation_to_mask(original["annotations"][0]["segmentation"], 48, 64)
    annotation["segmentation"] = mask_to_rle(binary)
    copy = store.auto(copy["id"], copy["revision"], lambda *_: {"annotations": [annotation], "automation": {"model_version": "test"}})
    verify_review(store, copy["id"], {"action": "approve", "revision": copy["revision"]})
    assert [row["image_id"] for row in view.verified_examples()] == [original["id"]]
    assert view.get(copy["id"])["quarantined"]
    assert view.stats()["approved_images"] == 0


def test_contradictory_copy_cannot_displace_permanent_manual_truth(system):
    store, view, _, _ = system
    imported = store.import_manual(["train"])
    original = store.get(imported["image_ids"][0])
    copy = store.upload(png(50, ".bmp"), "manual-copy.bmp")
    annotation = deepcopy(original["annotations"][0])
    annotation.update(id="copied", class_id=5)
    copy = store.auto(copy["id"], copy["revision"], lambda *_: {"annotations": [annotation], "automation": {"model_version": "wrong"}})
    verify_review(store, copy["id"], {"action": "approve", "revision": copy["revision"]})
    assert [row["image_id"] for row in view.verified_examples()] == [original["id"]]
    assert "Contradictory" in view.get(copy["id"])["quarantine_reason"]


def test_manual_baseline_bootstrap_is_idempotent_and_original_files_unchanged(system):
    store, view, learning, _ = system
    path = store.manual_source / "train" / "_annotations.coco.json"
    original = path.read_bytes()
    first = bootstrap_manual_baseline(learning)
    assert first["state"] == "ready" and first["imported"] == 1
    assert len(view.verified_examples()) == 1
    assert bootstrap_manual_baseline(learning) == first
    assert len(store.list()["images"]) == 1
    assert path.read_bytes() == original
    # A changed original cannot silently replace the established baseline.
    modified = json.loads(original)
    modified["info"] = {"changed": True}
    path.write_text(json.dumps(modified), encoding="utf-8")
    assert bootstrap_manual_baseline(learning)["state"] == "source_changed"
    assert len(store.list()["images"]) == 1


def test_original_annotation_model_is_used_as_promotion_incumbent(system, monkeypatch, tmp_path):
    from src.api import annotation_review
    from src.annotation_learning import UltralyticsAnnotationTrainer
    checkpoint = tmp_path / "preserved-original.pt"
    checkpoint.write_bytes(b"local checkpoint test")
    learning = Mock()
    learning.deployed_version.return_value = "original-fixture"
    learning.deployed_checkpoint.return_value = str(checkpoint)
    underlying = Mock()
    monkeypatch.setattr(annotation_review, "get_learning_service", lambda *_: learning)
    monkeypatch.setattr(UltralyticsAnnotationTrainer, "_load", lambda path: underlying)
    annotation_review._candidate_models.clear()
    model = annotation_review.annotation_quality_model(system[0])
    assert model.version == "original-fixture"
    assert model.model is underlying
    assert model.weights_path == checkpoint
    annotation_review._candidate_models.clear()


def test_actual_prediction_version_is_retained_when_reference_model_differs(system, monkeypatch):
    store, _, learning, _ = system
    from src.api import annotation_review
    monkeypatch.setattr(annotation_review, "get_learning_service", lambda *_: learning)
    query = predicted(store)
    output = apply_learning_context(store, query, {"annotations": query["annotations"], "automation": {"prediction_model_version": "fallback-detector-sha"}})
    assert output["automation"]["learning_model_version"] == "fallback-detector-sha"


def test_explicit_dataset_and_source_group_associations_are_preserved(system):
    store, view, _, _ = system
    document = predicted(store)
    verified = verify_review(store, document["id"], {"action": "approve", "revision": document["revision"]})
    store.save(document["id"], verified["revision"], verified["annotations"], metadata={"dataset_id": "capture-batch-7", "group_id": "source-fish-8", "split": "validation"})
    row = view.get(document["id"])
    assert row["dataset_id"] == "capture-batch-7"
    assert row["group_id"] == "source-fish-8"
    assert row["split"] == "val"


def test_custom_class_labels_are_preserved_without_silently_dropping_training_labels(system):
    store, view, _, _ = system
    category = store.add_class({"name": "Eye", "kind": "anatomy"})
    document = predicted(store, labels=[label(class_id=category["id"])])
    saved = verify_review(store, document["id"], {"action": "approve", "revision": document["revision"]})
    assert saved["annotations"][0]["class_id"] == category["id"]
    assert view.verified_examples() == []
    assert "mapping" in view.get(document["id"])["quarantine_reason"]


def test_feedback_waits_for_baseline_identity_index_before_learning(system):
    store, view, _, _ = system
    document = predicted(store)
    verify_review(store, document["id"], {"action": "approve", "revision": document["revision"]})
    view.set_metadata("baseline_bootstrap", {"state": "indexing"})
    assert view.verified_examples() == []
    assert store.get(document["id"])["status"] == "approved"
    view.set_metadata("baseline_bootstrap", {"state": "ready"})
    assert len(view.verified_examples()) == 1


def primary_profile(store, *, status="ready"):
    source = store.import_manual(["train"])["image_ids"][0]
    original = store.get(source)
    primary = deepcopy(original)
    primary.update(id="primary-manual", dataset_id="cleaned-archive", revision=1)
    primary["baseline"]["dataset_id"] = "cleaned-archive"
    profile = {"dataset_id": "cleaned-archive", "id": "cleaned-archive", "name": "Cleaned manual annotations",
        "source_type": "coco_zip", "source_path": "preserved.zip", "training_certified": True, "reference_eligible": True, "status": status}
    with store.connection(True) as db:
        store._persist(db, primary)
        db.execute("INSERT INTO meta VALUES ('primary_learning_dataset',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(profile),))
        db.execute("INSERT INTO meta VALUES ('annotation_datasets',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (json.dumps([dict(profile, primary=True), {"id": "v2-coco-v7", "name": "Retained V2", "primary": False}]),))
    return original, primary


def test_selected_primary_is_not_displaced_by_retained_secondary_duplicate(system):
    store, view, learning, _ = system
    old, primary = primary_profile(store)
    assert [row["image_id"] for row in view.verified_examples()] == [primary["id"]]
    assert view.get(old["id"])["selected_for_learning"] is False
    assert view.stats()["retained_secondary_examples"] == 1
    query = predicted(store, 91)
    assert [r["image_id"] for r in learning.references(store.pixels_path(query["id"]))] == [primary["id"]]


def test_primary_importing_state_holds_feedback_and_skips_old_bootstrap(system):
    store, view, learning, _ = system
    primary_profile(store, status="importing")
    feedback = predicted(store)
    verify_review(store, feedback["id"], {"action": "approve", "revision": feedback["revision"]})
    status = bootstrap_manual_baseline(learning)
    assert status["state"] == "indexing"
    assert "fingerprint" not in status  # No fallback import of the V2 source.
    assert view.verified_examples() == []
    assert store.get(feedback["id"])["status"] == "approved"


def test_primary_manual_unknown_split_is_not_silently_training_data(system):
    store, view, learning, _ = system
    _, primary = primary_profile(store)
    with store.connection(True) as db:
        primary["split"] = None
        primary["revision"] += 1
        store._persist(db, primary)
    assert view.get(primary["id"])["split"] == "unassigned"
    query = predicted(store, 91)
    assert learning.references(store.pixels_path(query["id"])) == []


def test_primary_capture_groups_and_declared_holdout_protection_are_used(system):
    store, view, learning, _ = system
    _, primary = primary_profile(store)
    with store.connection(True) as db:
        primary["metadata"] = {"leakage_group_id": "capture-group-7", "protected_split": "valid"}
        primary["revision"] += 1
        store._persist(db, primary)
    row = view.get(primary["id"])
    assert row["group_id"] == "capture-group-7"
    assert row["split"] == "train"  # Original split remains auditable.
    assert row["protected_split"] == "val"
    assert row["quarantined"] and "validation/test" in row["quarantine_reason"]
    query = predicted(store, 91)
    assert learning.references(store.pixels_path(query["id"])) == []


@pytest.mark.parametrize("state", ["failed", "needs_review"])
def test_failed_or_incomplete_primary_never_falls_back_to_secondary(system, state):
    store, view, learning, _ = system
    primary_profile(store, status=state)
    status = bootstrap_manual_baseline(learning)
    assert status["state"] == "errors" and status["source_status"] == state
    assert view.verified_examples() == []
    assert view.stats()["retained_secondary_examples"] == 1


def test_completed_primary_releases_feedback_without_restarting_maintenance(system):
    store, view, learning, client = system
    primary_profile(store, status="importing")
    assert bootstrap_manual_baseline(learning)["state"] == "indexing"
    feedback = predicted(store)
    verify_review(store, feedback["id"], {"action": "approve", "revision": feedback["revision"]})
    with store.connection(True) as db:
        for key in ("primary_learning_dataset", "annotation_datasets"):
            value = json.loads(db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()[0])
            profiles = value if isinstance(value, list) else [value]
            for profile in profiles:
                if profile.get("dataset_id", profile.get("id")) == "cleaned-archive":
                    profile["status"] = "ready"
            db.execute("UPDATE meta SET value=? WHERE key=?", (json.dumps(value), key))
    assert not view.get(feedback["id"])["quarantined"]
    assert feedback["id"] in {r["image_id"] for r in view.verified_examples()}
    assert client.get("/api/annotations/learning/status").json()["baseline_indexing"]["state"] == "ready"


def test_existing_learning_schema_opens_during_competing_sqlite_write(system, tmp_path):
    import sqlite3
    import threading
    store, _, _, _ = system
    finished, errors = threading.Event(), []
    def open_learning():
        try:
            LearningService(AnnotationStore(store), tmp_path / "reopened-learning")
        except Exception as error:
            errors.append(error)
        finally:
            finished.set()
    with sqlite3.connect(store.root / "annotations.sqlite3") as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE meta SET value=value WHERE key='classes_revision'")
        worker = threading.Thread(target=open_learning)
        worker.start()
        completed_while_locked = finished.wait(2)
        writer.rollback()
    worker.join(5)
    assert completed_while_locked and not errors


def test_maintenance_retries_initialization_after_competing_writer(monkeypatch):
    import sqlite3
    from src.api import annotation_review
    service = Mock()
    getter = Mock(side_effect=[sqlite3.OperationalError("database is locked"), service])
    stop = Mock()
    stop.is_set.side_effect = [False, False, True]
    thread = Mock()
    thread_factory = Mock(return_value=thread)
    monkeypatch.setattr(annotation_review, "get_learning_service", getter)
    monkeypatch.setattr(annotation_review, "bootstrap_manual_baseline", lambda _: {"state": "ready", "dataset_id": "primary"})
    monkeypatch.setattr(annotation_review, "_maintenance_thread", None)
    monkeypatch.setattr(annotation_review, "_maintenance_stop", stop)
    monkeypatch.setattr(annotation_review, "Thread", thread_factory)
    annotation_review.start_learning_maintenance()
    thread_factory.call_args.kwargs["target"]()
    assert getter.call_count == 2
    service.prepare_references.assert_called_once()
    service.maybe_schedule.assert_called_once()
