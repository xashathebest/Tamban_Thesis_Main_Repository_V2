"""Model-free tests exercise real data isolation, feedback, and promotion logic."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import threading

import numpy as np
from PIL import Image
import pytest

from src.annotation.masks import mask_to_rle
from src.annotation_learning import LearningService, _pixels
from src.api.database import InspectionDatabase
from src.preprocessing.audit_v7_exports import SOURCE_CLASSES


def annotation(class_id=1, *, fish_id=None):
    return {"id": "part", "fish_id": fish_id, "class_id": class_id, "class_name": SOURCE_CLASSES[class_id],
            "bbox": [8, 8, 29, 29], "mask": [[8, 8], [28, 8], [28, 28], [8, 28]], "confidence": 0.3}


class Store:
    def __init__(self, path):
        self.database = InspectionDatabase(path)
        self.rows = []

    def initialize(self):
        self.database.initialize()

    def verified_examples(self):
        return deepcopy(self.rows)

    def stats(self):
        return {"verified_examples": len(self.rows)}


def example(tmp_path, name, *, class_id=1, source="manual", split="train", group=None, annotations=None, color=(70, 100, 130)):
    image = Image.new("RGB", (48, 48), color)
    # Content-independent identity, with identical object crops across examples.
    image.putpixel((0, 0), (len(name), sum(map(ord, name)) % 255, 0))
    path = tmp_path / (name + ".png")
    image.save(path)
    labels = annotations if annotations is not None else [annotation(class_id)]
    return {"image_id": name, "image_sha256": sha256(path.read_bytes()).hexdigest(), "pixel_sha256": _pixels(image),
            "image_path": str(path), "width": 48, "height": 48, "dataset_id": "baseline", "split": split,
            "group_id": group or name, "source": source, "status": "approved", "annotations": labels,
            "original_annotations": deepcopy(labels) if source == "manual" else None,
            "predictions": [], "revision": 1, "model_version": "original", "corrections": []}


@pytest.fixture
def pool(tmp_path):
    store = Store(tmp_path / "inspection.sqlite")
    store.rows = [example(tmp_path, "manual-train")]
    val = [dict(annotation(index), id=f"val-{index}", mask=[[index * 3, 0], [index * 3 + 2, 0], [index * 3 + 2, 8], [index * 3, 8]]) for index in SOURCE_CLASSES]
    store.rows.append(example(tmp_path, "manual-val", split="val", annotations=val))
    store.rows.append(example(tmp_path, "manual-test", split="test"))
    return store


class FakeTrainer:
    def __init__(self, delta=0.05, recall_delta=0, gate=None, started=None):
        self.delta, self.recall_delta = delta, recall_delta
        self.calls = []
        self.gate, self.started = gate, started

    def train(self, checkpoint, data_yaml, output_dir):
        self.calls.append(("train", checkpoint, data_yaml))
        if self.started:
            self.started.set()
        if self.gate:
            assert self.gate.wait(5)
        output_dir.mkdir(parents=True)
        candidate = output_dir / "candidate.pt"
        candidate.write_bytes(b"candidate checkpoint")
        return candidate

    def evaluate(self, checkpoint, data_yaml, output_dir):
        self.calls.append(("evaluate", checkpoint, data_yaml))
        candidate = checkpoint.name.startswith("annotation-")
        return {"segmentation_map50_95": 0.65 + (self.delta if candidate else 0),
                "detection_precision": 0.8, "detection_recall": 0.75 + (self.recall_delta if candidate else 0)}


def service(tmp_path, store, adapter=None, **kwargs):
    checkpoint = tmp_path / "source.pt"
    checkpoint.write_bytes(b"permanent source checkpoint")
    return LearningService(store, tmp_path / "learning", base_checkpoint=checkpoint, adapter=adapter or FakeTrainer(), **kwargs)


def test_references_use_verified_train_only_and_never_self(tmp_path):
    store = Store(tmp_path / "inspection.sqlite")
    allowed = example(tmp_path, "train")
    declined = example(tmp_path, "declined", source="ai_generated")
    declined["status"] = "declined"
    pending = example(tmp_path, "pending", source="ai_generated")
    pending["status"] = "pending"
    store.rows = [allowed, declined, pending, example(tmp_path, "val", split="val"), example(tmp_path, "test", split="test")]
    query = example(tmp_path, "query")
    learner = LearningService(store, tmp_path / "learning")
    assert [row["image_id"] for row in learner.references(query["image_path"])] == ["train"]
    assert learner.references(allowed["image_path"]) == []
    assert learner.status()["deployed_model_version"] == "reference-only"
    assert learner.status()["measured_improvement"] is False


def test_feedback_changes_subsequent_context_without_copying_masks(tmp_path):
    store = Store(tmp_path / "inspection.sqlite")
    learner = LearningService(store, tmp_path / "learning")
    query = example(tmp_path, "query", class_id=4)
    original = deepcopy(query["annotations"])
    assert learner.adapt(query["image_path"], original)["references"] == []
    store.rows.extend(example(tmp_path, f"corrected-{index}", class_id=1, source="human_corrected") for index in range(3))
    adapted = learner.adapt(query["image_path"], original)
    evidence = adapted["annotations"][0]["adaptive_evidence"]
    assert evidence["suggested_class_id"] == 1
    assert evidence["strong_support"] is True
    assert evidence["supporting_images"] == 3
    assert evidence["applied"] is False
    assert adapted["annotations"][0]["mask"] == original[0]["mask"]
    assert original == query["annotations"]
    assert not any("Fish None" in text for text in adapted["warnings"])


def test_opt_in_class_change_requires_independent_strong_same_part_evidence(tmp_path):
    store = Store(tmp_path / "inspection.sqlite")
    store.rows.extend(example(tmp_path, f"corrected-{index}", class_id=1, source="human_corrected") for index in range(3))
    learner = LearningService(store, tmp_path / "learning", enable_reference_class_updates=True)
    query = example(tmp_path, "query", class_id=4)
    adapted = learner.adapt(query["image_path"], query["annotations"])
    assert adapted["annotations"][0]["class_id"] == 1
    assert adapted["annotations"][0]["mask"] == query["annotations"][0]["mask"]
    high_confidence = deepcopy(query["annotations"])
    high_confidence[0]["confidence"] = 0.99
    assert learner.adapt(query["image_path"], high_confidence)["annotations"][0]["class_id"] == 4
    wrong_part = deepcopy(query["annotations"])
    wrong_part[0].update(class_id=3, class_name=SOURCE_CLASSES[3])
    assert learner.adapt(query["image_path"], wrong_part)["annotations"][0]["class_id"] == 3
    store.rows[1]["group_id"] = store.rows[0]["group_id"]
    store.rows[2]["group_id"] = store.rows[0]["group_id"]
    assert learner.adapt(query["image_path"], query["annotations"])["annotations"][0]["class_id"] == 4


def test_conflicting_references_raise_uncertainty(tmp_path):
    store = Store(tmp_path / "inspection.sqlite")
    store.rows.extend(example(tmp_path, f"corrected-{index}", class_id=1 if index < 3 else 4) for index in range(4))
    learner = LearningService(store, tmp_path / "learning", enable_reference_class_updates=True)
    query = example(tmp_path, "query", class_id=4)
    result = learner.adapt(query["image_path"], query["annotations"])
    assert result["annotations"][0]["class_id"] == 4
    assert result["annotations"][0]["needs_review"] is True
    assert result["annotations"][0]["adaptive_evidence"]["strong_support"] is False


def test_versioned_dataset_retains_baseline_and_fixed_splits(tmp_path, pool):
    feedback = example(tmp_path, "feedback", source="human_corrected")
    pool.rows.append(feedback)
    before = {row["image_path"]: Path(row["image_path"]).read_bytes() for row in pool.rows}
    baseline_labels = deepcopy(pool.rows[0]["annotations"])
    pool.rows[0]["annotations"][0].update(class_id=4, class_name=SOURCE_CLASSES[4])
    learner = LearningService(pool, tmp_path / "learning")
    first, second = learner.build_dataset(), learner.build_dataset()
    assert first["version"] != second["version"]
    assert CounterLike(first["examples"], "split") == {"train": 2, "val": 1, "test": 1}
    assert first["validation_fingerprint"] == second["validation_fingerprint"]
    snapshot = json.loads((Path(first["manifest_path"]).parent / "source_annotations.json").read_text())
    assert snapshot[0]["annotations"] == baseline_labels
    assert all(Path(path).read_bytes() == content for path, content in before.items())
    assert any("immutable baseline" in item["reason"] for item in first["exclusions"])


def CounterLike(rows, key):
    from collections import Counter
    return dict(Counter(row[key] for row in rows))


def test_duplicate_and_conflicting_pixels_do_not_become_independent_examples(tmp_path, pool):
    duplicate = deepcopy(pool.rows[0])
    duplicate.update(image_id="duplicate", source="human_corrected")
    pool.rows.append(duplicate)
    learner = LearningService(pool, tmp_path / "learning")
    assert len(learner.build_dataset()["examples"]) == 3
    duplicate["annotations"][0].update(class_id=4, class_name=SOURCE_CLASSES[4])
    with pytest.raises(ValueError, match="Contradictory"):
        learner.build_dataset()


@pytest.mark.parametrize("change", ["pixels", "group"])
def test_cross_split_leakage_blocks_dataset(tmp_path, pool, change):
    if change == "pixels":
        duplicate = deepcopy(pool.rows[0])
        duplicate.update(image_id="leaking", split="val")
        pool.rows.append(duplicate)
    else:
        pool.rows[1]["group_id"] = pool.rows[0]["group_id"]
    with pytest.raises(ValueError, match="cross"):
        LearningService(pool, tmp_path / "learning").build_dataset()


def test_inconsistent_mapping_and_unrepresentable_masks_fail_safely(tmp_path, pool):
    learner = LearningService(pool, tmp_path / "learning")
    pool.rows[0]["original_annotations"][0]["class_name"] = "invented"
    with pytest.raises(ValueError, match="disagree"):
        learner.build_dataset()
    pool.rows[0]["original_annotations"][0]["class_name"] = SOURCE_CLASSES[1]
    binary = np.zeros((48, 48), dtype=np.uint8)
    binary[8:20, 8:20] = 1
    binary[30:40, 30:40] = 1
    incompatible = annotation()
    incompatible["segmentation"] = mask_to_rle(binary)
    incompatible["mask"] = []
    pool.rows.append(example(tmp_path, "islands", annotations=[incompatible]))
    result = learner.build_dataset()
    assert "islands" not in {row["image_id"] for row in result["examples"]}
    assert any("losslessly" in row["reason"] for row in result["exclusions"])
    pool.rows[-1]["split"] = "val"
    with pytest.raises(ValueError, match="evaluation masks"):
        learner.build_dataset()


def test_candidate_is_evaluated_against_incumbent_before_promotion_and_rollback(tmp_path, pool):
    pool.rows.append(example(tmp_path, "feedback", source="human_corrected"))
    adapter = FakeTrainer()
    learner = service(tmp_path, pool, adapter)
    original_version = learner.deployed_version()
    original_path = learner.deployed_checkpoint()
    result = learner.train_candidate()
    assert result["status"] == "promoted"
    assert learner.deployed_version() != original_version
    assert [call[0] for call in adapter.calls] == ["train", "evaluate", "evaluate"]
    assert adapter.calls[1][2] == adapter.calls[2][2]
    assert Path(original_path).read_bytes() == b"permanent source checkpoint"
    assert (tmp_path / "source.pt").read_bytes() == b"permanent source checkpoint"
    assert learner.status()["pending_training_examples"] == 0
    restarted = LearningService(pool, tmp_path / "learning")
    assert restarted.deployed_version() == learner.deployed_version()
    assert restarted.rollback()["deployed_model_version"] == original_version


@pytest.mark.parametrize("delta,recall_delta", [(-0.01, 0), (0.1, -0.01), (0.001, 0)])
def test_worse_or_unimproved_candidate_never_replaces_model(tmp_path, pool, delta, recall_delta):
    learner = service(tmp_path, pool, FakeTrainer(delta, recall_delta))
    original = learner.deployed_version()
    result = learner.train_candidate()
    assert result["status"] == "rejected"
    assert learner.deployed_version() == original
    with pytest.raises(ValueError, match="original or previously promoted"):
        learner.rollback(result["candidate_version"])


def test_invalid_metrics_cannot_promote():
    good = {"segmentation_map50_95": 0.6, "detection_precision": 0.8, "detection_recall": 0.7}
    assert not LearningService.compare_metrics(good, dict(good, segmentation_map50_95=float("nan")))["promote"]
    assert not LearningService.compare_metrics(good, {"segmentation_map50_95": 0.9})["promote"]


def test_threshold_scheduling_is_nonblocking_and_prevents_parallel_training(tmp_path, pool):
    gate, started = threading.Event(), threading.Event()
    learner = service(tmp_path, pool, FakeTrainer(gate=gate, started=started), min_examples=2)
    pool.rows.append(example(tmp_path, "feedback-1", source="human_corrected"))
    assert learner.maybe_schedule()["scheduled"] is False
    pool.rows.append(example(tmp_path, "feedback-2", source="human_corrected"))
    result = learner.maybe_schedule()
    assert result["scheduled"] is True
    assert started.wait(5)
    # Human work and model selection are usable during expensive fitting.
    query = example(tmp_path, "query")
    assert learner.references(query["image_path"])
    assert learner.maybe_schedule()["scheduled"] is False
    assert learner.train_candidate()["status"] == "busy"
    gate.set()
    learner._thread.join(5)
    assert not learner._thread.is_alive()
    assert learner.status()["latest_evaluation"]["status"] == "promoted"
    assert learner.maybe_schedule()["scheduled"] is False


def test_no_model_or_holdout_reports_failure_without_claiming_learning(tmp_path, pool):
    learner = LearningService(pool, tmp_path / "learning")
    result = learner.train_candidate()
    assert result["status"] == "failed"
    assert learner.status()["measured_improvement"] is False
    learner = service(tmp_path, pool)
    pool.rows = [row for row in pool.rows if row["split"] == "train"]
    assert learner.train_candidate()["status"] == "failed"


def test_abandoned_training_is_recovered_without_promoting_candidate(tmp_path, pool, monkeypatch):
    learner = service(tmp_path, pool)
    original = learner.deployed_version()
    with pool.database._connection() as connection:
        connection.execute("INSERT INTO annotation_learning_runs VALUES ('crashed','training','2026-01-01T00:00:00+00:00',NULL,NULL,?)",
                           (json.dumps({"owner_pid": 123456789, "owner_token": "previous-process"}),))
    monkeypatch.setattr("src.annotation_learning._process_alive", lambda pid: False)
    restarted = LearningService(pool, tmp_path / "learning", adapter=FakeTrainer())
    assert restarted.status()["latest_evaluation"]["status"] == "interrupted"
    assert restarted.deployed_version() == original
    # The unique running-job gate is free for subsequent verified batches.
    assert restarted.train_candidate()["status"] == "promoted"


def test_incomplete_validation_blocks_automatic_training_and_qa_cannot_promote(tmp_path, pool):
    pool.rows[1]["annotations"] = [a for a in pool.rows[1]["annotations"] if a["class_id"] not in {3, 4}]
    pool.rows[1]["original_annotations"] = deepcopy(pool.rows[1]["annotations"])
    pool.rows.append(example(tmp_path, "new-feedback", source="human_corrected"))
    learner = service(tmp_path, pool, min_examples=1)
    original = learner.deployed_version()
    assert learner.maybe_schedule()["scheduled"] is False
    assert learner.status()["missing_validation_classes"] == ["Grade_B_Body", "Grade_B_Head"]
    assert learner.train_candidate()["status"] == "failed"
    result = learner.train_candidate(allow_incomplete_validation=True)
    assert result["status"] == "rejected"
    assert "Incomplete" in result["comparison"]["reason"]
    assert learner.deployed_version() == original


def test_repeated_augmented_source_group_cannot_trigger_training(tmp_path, pool):
    pool.rows.extend(example(tmp_path, f"augmentation-{i}", source="human_corrected", group="same-original") for i in range(3))
    learner = service(tmp_path, pool, min_examples=2)
    assert learner.status()["pending_training_examples"] == 3
    assert learner.status()["pending_independent_groups"] == 1
    assert learner.maybe_schedule()["scheduled"] is False


def test_modified_versioned_labels_cannot_promote(tmp_path, pool):
    class MutatingTrainer(FakeTrainer):
        def train(self, checkpoint, data_yaml, output_dir):
            result = super().train(checkpoint, data_yaml, output_dir)
            label_path = next((data_yaml.parent / "val" / "labels").glob("*.txt"))
            label_path.write_text("0 0 0 1 0 1 1\n", encoding="utf-8")
            return result
    learner = service(tmp_path, pool, MutatingTrainer())
    original = learner.deployed_version()
    result = learner.train_candidate()
    assert result["status"] == "failed"
    assert "dataset" in result["error"] or "labels changed" in result["error"]
    assert learner.deployed_version() == original


def test_reapproval_or_metadata_revision_is_not_new_training_data(tmp_path, pool):
    feedback = example(tmp_path, "new-feedback", source="human_corrected")
    pool.rows.append(feedback)
    learner = service(tmp_path, pool)
    assert learner.train_candidate()["status"] == "promoted"
    feedback["revision"] += 5
    assert learner.status()["pending_training_examples"] == 0
    feedback["annotations"][0].update(class_id=4, class_name=SOURCE_CLASSES[4])
    assert learner.status()["pending_training_examples"] == 1


def test_model_selection_and_completed_evaluation_are_atomic(tmp_path, pool):
    learner = service(tmp_path, pool)
    original = learner.deployed_version()
    with pool.database._connection() as connection:
        connection.execute("CREATE TRIGGER reject_promotion_record BEFORE UPDATE ON annotation_learning_runs WHEN NEW.status='promoted' BEGIN SELECT RAISE(ABORT, 'evaluation audit failure'); END")
    result = learner.train_candidate()
    assert result["status"] == "failed"
    assert learner.deployed_version() == original
    assert "evaluation audit failure" in result["error"]


def test_reference_features_survive_restart_without_recomputing_masks(tmp_path, pool, monkeypatch):
    from src import annotation_learning
    query = example(tmp_path, "query")
    learner = LearningService(pool, tmp_path / "learning")
    original = learner.references(query["image_path"])
    descriptor = annotation_learning._descriptor
    def query_only(image, annotation=None):
        assert annotation is None, "A restart should reuse stored verified-object features"
        return descriptor(image)
    monkeypatch.setattr(annotation_learning, "_descriptor", query_only)
    restarted = LearningService(pool, tmp_path / "learning")
    assert restarted.references(query["image_path"]) == original
    with pool.database._connection() as connection:
        features = connection.execute("SELECT features_json FROM annotation_learning_reference_features").fetchall()
    assert len(features) == 1
    assert "segmentation" not in features[0][0]
    assert "class_name" not in features[0][0]
    # A corrected label revision invalidates the feature cache.
    monkeypatch.setattr(annotation_learning, "_descriptor", descriptor)
    pool.rows[0]["revision"] += 1
    pool.rows[0]["annotations"][0].update(class_id=4, class_name=SOURCE_CLASSES[4])
    assert restarted.references(query["image_path"])[0]["class_counts"] == {SOURCE_CLASSES[4]: 1}


def test_background_reference_index_does_not_hold_up_prediction_review(tmp_path, pool, monkeypatch):
    learner = LearningService(pool, tmp_path / "learning")
    original = learner._reference_rows
    started, gate = threading.Event(), threading.Event()
    def delayed(*args, **kwargs):
        started.set()
        assert gate.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(learner, "_reference_rows", delayed)
    assert learner.prepare_references()
    assert started.wait(5)
    query = example(tmp_path, "query")
    result = learner.adapt(query["image_path"], query["annotations"])
    assert learner._reference_thread.is_alive() and not gate.is_set()
    assert result["annotations"] == query["annotations"]
    assert result["references"] == [] and "background" in result["warnings"][0]
    gate.set()
    learner._reference_thread.join(5)
    assert not learner._reference_thread.is_alive()
    assert learner.status()["reference_index"]["status"] == "ready"


def test_rle_references_validate_exact_runs_without_native_bitmap_allocation(tmp_path, monkeypatch):
    from src import annotation_learning
    store = Store(tmp_path / "inspection.sqlite")
    mask = np.zeros((48, 48), dtype=np.uint8)
    mask[8:29, 8:29] = 1
    label = annotation()
    label["segmentation"] = mask_to_rle(mask)
    store.rows = [example(tmp_path, "reference", annotations=[label])]
    learner = LearningService(store, tmp_path / "learning")
    def no_native_raster(*_):
        raise AssertionError("Reference RLE validation allocated a native bitmap")
    monkeypatch.setattr(annotation_learning, "segmentation_to_mask", no_native_raster)
    query = example(tmp_path, "new-query")
    assert learner.references(query["image_path"])[0]["image_id"] == "reference"
    assert store.rows[0]["annotations"][0]["segmentation"] == label["segmentation"]


@pytest.mark.parametrize("rle", [
    {"size": [48, 47], "counts": [0, 2304]},
    {"size": [48, 48], "counts": [0, -1, 2305]},
    {"size": [48, 48], "counts": [False, 2304]},
    {"size": [48, 48], "counts": [0, 2303]},
    {"size": [48, 48], "counts": [2304]},
])
def test_fast_rle_validation_rejects_invalid_and_empty_masks(rle):
    from src.annotation_learning import _validated
    label = annotation()
    label["segmentation"] = rle
    with pytest.raises(ValueError):
        _validated([label], 48, 48)
