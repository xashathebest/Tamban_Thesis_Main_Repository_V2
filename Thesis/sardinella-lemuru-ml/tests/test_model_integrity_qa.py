"""Checkpoint identity and integrity checks use only tiny fake files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import cv2
import numpy as np
from fastapi.testclient import TestClient

from src.inference.model_registry import ModelRegistry
from src.inference.yolo_quality_model import YoloQualityModel
from src.preprocessing.audit_v7_exports import SOURCE_CLASSES


def registry_fixture(tmp_path: Path, monkeypatch, expected: str | None = None):
    models = tmp_path / "models"
    models.mkdir()
    checkpoint = models / "registered.pt"
    checkpoint.write_bytes(b"registered bytes")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    payload = {"default_model2": "registered", "models": [{
        "id": "registered", "role": "model2_part_quality", "path": "models/registered.pt",
        "display_name": "Registered", "sha256": digest if expected is None else expected,
        "adapter": "yolo_detection", "is_compatible_grading": True,
    }]}
    (models / "MODEL_REGISTRY.json").write_text(json.dumps(payload), encoding="utf-8")
    registry = ModelRegistry(tmp_path)
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    monkeypatch.delenv("FISH_STRICT_MODEL_INTEGRITY", raising=False)
    return checkpoint, digest


def test_explicit_id_must_match_checkpoint_path(tmp_path, monkeypatch):
    registry_fixture(tmp_path, monkeypatch)
    other = tmp_path / "other.pt"
    other.write_bytes(b"other bytes")
    factory = MagicMock(return_value=SimpleNamespace(task="detect", names=SOURCE_CLASSES))
    quality = YoloQualityModel(other, model_id="registered", model_factory=factory, device="cpu")
    assert not quality.load()
    assert "path" in quality.error.lower()
    factory.assert_not_called()


def test_strict_mode_rejects_registered_hash_mismatch_before_loading(tmp_path, monkeypatch):
    checkpoint, _ = registry_fixture(tmp_path, monkeypatch, expected="0" * 64)
    monkeypatch.setenv("FISH_STRICT_MODEL_INTEGRITY", "1")
    factory = MagicMock(return_value=SimpleNamespace(task="detect", names=SOURCE_CLASSES))
    quality = YoloQualityModel(checkpoint, model_id="registered", model_factory=factory, device="cpu")
    assert not quality.load()
    assert "sha-256" in quality.error.lower()
    factory.assert_not_called()


def test_custom_override_is_labeled_custom_and_strict_mode_rejects_it(tmp_path, monkeypatch):
    registry_fixture(tmp_path, monkeypatch)
    other = tmp_path / "other.pt"
    other.write_bytes(b"custom bytes")
    factory = lambda _path: SimpleNamespace(task="detect", names=SOURCE_CLASSES)
    quality = YoloQualityModel(other, model_factory=factory, device="cpu")
    assert quality.load(), quality.error
    assert quality.active_model_id == "custom_model2"
    assert quality.diagnostics()["checkpoint_integrity"] == "unverified_custom"
    monkeypatch.setenv("FISH_STRICT_MODEL_INTEGRITY", "1")
    strict = YoloQualityModel(other, model_factory=factory, device="cpu")
    assert not strict.load()
    assert "unregistered" in strict.error.lower()


def test_matching_checkpoint_records_full_load_time_hash(tmp_path, monkeypatch):
    checkpoint, digest = registry_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("FISH_STRICT_MODEL_INTEGRITY", "1")
    quality = YoloQualityModel(checkpoint, model_id="registered", device="cpu", model_factory=lambda _: SimpleNamespace(task="detect", names=SOURCE_CLASSES))
    assert quality.load(), quality.error
    assert quality.checkpoint_sha256_full == digest
    assert quality.diagnostics()["checkpoint_integrity"] == "verified"


def test_registered_hash_mismatch_is_rejected_even_outside_strict_mode(tmp_path, monkeypatch):
    checkpoint, _ = registry_fixture(tmp_path, monkeypatch, expected="0" * 64)
    factory = MagicMock()
    quality = YoloQualityModel(checkpoint, model_id="registered", model_factory=factory, device="cpu")
    assert not quality.load()
    assert "sha-256" in quality.error.lower()
    factory.assert_not_called()


def test_unregistered_model_must_expose_actual_class_names(tmp_path, monkeypatch):
    registry_fixture(tmp_path, monkeypatch)
    custom = tmp_path / "custom.pt"
    custom.write_bytes(b"custom")
    quality = YoloQualityModel(custom, model_factory=lambda _: SimpleNamespace(task="detect"), device="cpu")
    assert not quality.load()
    assert "class mapping" in quality.error.lower()


def test_strict_model1_checks_path_and_hash_before_factory(tmp_path, monkeypatch):
    from src.inference.yolo_fish_detector import YoloFishDetector
    checkpoint, digest = registry_fixture(tmp_path, monkeypatch)
    registry_path = tmp_path / "models" / "MODEL_REGISTRY.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["default_model1"] = "fish"
    payload["models"].append({"id": "fish", "role": "model1_fish_detector", "path": "models/registered.pt", "sha256": digest})
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    registry = ModelRegistry(tmp_path)
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    monkeypatch.setenv("FISH_STRICT_MODEL_INTEGRITY", "1")
    factory = MagicMock(return_value=SimpleNamespace(task="detect", names={0: "item"}))
    detector = YoloFishDetector(checkpoint, model_factory=factory, tracker_factory=lambda _: object(), device="cpu")
    assert detector.load(), detector.error
    assert detector.checkpoint_sha256_full == digest
    assert detector.checkpoint_integrity == "verified"
    checkpoint.write_bytes(b"tampered")
    bad_factory = MagicMock()
    bad = YoloFishDetector(checkpoint, model_factory=bad_factory, tracker_factory=lambda _: object(), device="cpu")
    assert not bad.load()
    assert "sha-256" in bad.error.lower()
    bad_factory.assert_not_called()


def test_session_snapshot_uses_hash_from_loaded_bytes(tmp_path, monkeypatch):
    import importlib
    app_module = importlib.import_module("src.api.app")
    checkpoint, digest = registry_fixture(tmp_path, monkeypatch)
    quality = YoloQualityModel(checkpoint, model_id="registered", device="cpu", model_factory=lambda _: SimpleNamespace(task="detect", names=SOURCE_CLASSES))
    assert quality.load(), quality.error
    checkpoint.write_bytes(b"changed after loading")
    monkeypatch.setattr(app_module, "quality_model", quality)
    monkeypatch.setattr(app_module, "_camera_settings_snapshot", lambda: {})
    monkeypatch.setattr(app_module, "_device_report", lambda: {})
    monkeypatch.setattr(app_module, "_git_commit", lambda: None)
    snapshot = app_module._session_metadata()
    assert snapshot["model2_path"] == str(checkpoint)
    assert snapshot["model2_sha256"] == digest
    assert snapshot["runtime_settings"]["model2"]["checkpoint_integrity"] == "verified"


def test_strict_mode_blocks_unverified_inspection_and_image_analysis(monkeypatch):
    import importlib
    from src.api.camera import CameraInspectionService
    from src.api.domain import InspectionState
    app_module = importlib.import_module("src.api.app")
    monkeypatch.setenv("FISH_STRICT_MODEL_INTEGRITY", "1")
    detector = SimpleNamespace(model=object(), checkpoint_integrity="not_checked")
    quality = SimpleNamespace(model=object(), checkpoint_integrity="unverified_custom")
    service = CameraInspectionService(InspectionState(), detector, quality_model=quality)
    assert not service.prepare_models()
    monkeypatch.setattr(app_module, "model", detector)
    monkeypatch.setattr(app_module, "quality_model", quality)
    monkeypatch.setattr(app_module, "image_analyzer", SimpleNamespace(analyze=MagicMock()))
    ok, encoded = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok
    response = TestClient(app_module.app).post("/api/analyze-image", content=encoded.tobytes(), headers={"x-filename": "fish.jpg"})
    assert response.status_code == 503
    assert "verified" in response.json()["detail"]


def test_wrong_registry_class_metadata_is_rejected_before_loading(tmp_path, monkeypatch):
    checkpoint, _ = registry_fixture(tmp_path, monkeypatch)
    registry_path = tmp_path / "models" / "MODEL_REGISTRY.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["models"][0]["class_names"] = {"0": "wrong class"}
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: ModelRegistry(tmp_path))
    factory = MagicMock()
    quality = YoloQualityModel(checkpoint, model_id="registered", model_factory=factory, device="cpu")
    assert not quality.load()
    assert "class mapping" in quality.error.lower()
    factory.assert_not_called()


def test_hash_mismatch_on_switch_preserves_original_model(tmp_path, monkeypatch):
    from unittest.mock import patch
    checkpoint, _ = registry_fixture(tmp_path, monkeypatch, expected="0" * 64)
    quality = YoloQualityModel(checkpoint, model_id="old", device="cpu")
    previous = object()
    quality.model = previous
    quality.adapter = MagicMock(is_loaded=True)
    quality._grading_engine._tracks[3] = object()
    replacement = MagicMock()
    with patch("src.inference.model_adapters.create_part_adapter", return_value=replacement):
        try:
            quality.switch_model("registered")
            assert False, "The mismatched checkpoint was accepted"
        except RuntimeError as exc:
            assert "SHA-256" in str(exc)
    assert quality.model is previous and 3 in quality._grading_engine._tracks
    replacement.load.assert_not_called()


def test_implicit_registered_override_uses_its_actual_registry_identity(tmp_path, monkeypatch):
    registry_fixture(tmp_path, monkeypatch)
    registry_path = tmp_path / "models" / "MODEL_REGISTRY.json"
    other = tmp_path / "models" / "other.pt"
    other.write_bytes(b"other registered checkpoint")
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["models"].append({"id": "other", "role": "model2_part_quality", "path": "models/other.pt",
                              "sha256": hashlib.sha256(other.read_bytes()).hexdigest(), "adapter": "yolo_detection"})
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    registry = ModelRegistry(tmp_path)
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    quality = YoloQualityModel(other, model_factory=lambda _: SimpleNamespace(task="detect", names=SOURCE_CLASSES), device="cpu")
    assert quality.load(), quality.error
    assert quality.active_model_id == "other"
    assert quality.checkpoint_integrity == "verified"


def test_loaded_model_is_not_rehashed_on_repeated_load(tmp_path, monkeypatch):
    from unittest.mock import patch
    from src.inference.model_traceability import full_sha256
    checkpoint, _ = registry_fixture(tmp_path, monkeypatch)
    quality = YoloQualityModel(checkpoint, model_id="registered", device="cpu", model_factory=lambda _: SimpleNamespace(task="detect", names=SOURCE_CLASSES))
    with patch("src.inference.yolo_quality_model.full_sha256", wraps=full_sha256) as compute:
        assert quality.load(), quality.error
        assert quality.load(), quality.error
    compute.assert_called_once_with(checkpoint)
