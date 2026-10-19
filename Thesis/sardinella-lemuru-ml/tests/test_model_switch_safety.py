"""Model changes must not race with or alter an active inspection."""
from __future__ import annotations

import asyncio
import importlib
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

app_module = importlib.import_module("src.api.app")


@pytest.mark.parametrize("status", ["starting", "running", "stopping"])
@pytest.mark.parametrize("route", ["select", "settings", "upload"])
def test_all_model_change_routes_reject_active_inspections(monkeypatch, status, route):
    quality = SimpleNamespace(active_model_id="old", switch_model=MagicMock())
    monkeypatch.setattr(app_module, "quality_model", quality)
    monkeypatch.setattr(app_module.state, "snapshot", lambda: {"inspection_status": status})
    registry = SimpleNamespace(get_model=lambda _id: object(), validate_compatibility=lambda *_: (True, None))
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    client = TestClient(app_module.app)
    if route == "select":
        response = client.post("/api/models/select", json={"model_id": "new"})
    elif route == "settings":
        response = client.post("/api/settings", json={"model2_id": "new"})
    else:
        ok, image = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
        assert ok
        response = client.post("/api/analyze-image", content=image.tobytes(), headers={"x-filename": "fish.jpg", "x-model-id": "new"})
    assert response.status_code == 409
    quality.switch_model.assert_not_called()


@pytest.mark.parametrize("status", ["stopped", "errored"])
def test_model_switch_rejects_a_still_alive_worker(monkeypatch, status):
    quality = SimpleNamespace(active_model_id="old", switch_model=MagicMock())
    monkeypatch.setattr(app_module, "quality_model", quality)
    monkeypatch.setattr(app_module.state, "snapshot", lambda: {"inspection_status": status})
    monkeypatch.setattr(app_module.service, "_thread", SimpleNamespace(is_alive=lambda: True))
    registry = SimpleNamespace(get_model=lambda _id: object(), validate_compatibility=lambda *_: (True, None))
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    response = TestClient(app_module.app).post("/api/models/select", json={"model_id": "new"})
    assert response.status_code == 409
    quality.switch_model.assert_not_called()


def test_rejected_mixed_settings_does_not_change_display(monkeypatch):
    monkeypatch.setattr(app_module.state, "snapshot", lambda: {"inspection_status": "running"})
    apply_display = MagicMock()
    monkeypatch.setattr(app_module.state, "set_display_settings", apply_display)
    response = TestClient(app_module.app).post("/api/settings", json={"display_settings": {"features": False}, "model2_id": "new"})
    assert response.status_code == 409
    apply_display.assert_not_called()


def test_switch_clears_temporal_evidence_only_after_success(tmp_path, monkeypatch):
    from src.inference.yolo_quality_model import YoloQualityModel
    path = tmp_path / "new.pt"
    path.write_bytes(b"fake model")
    entry = SimpleNamespace(id="new", display_name="new model", input_size=640)
    registry = SimpleNamespace(validate_compatibility=lambda *_: (True, None), get_model=lambda _id: entry,
                               resolve_checkpoint_path=lambda _entry: path, persist_model2_selection=MagicMock())
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    old_adapter = MagicMock(is_loaded=True)
    quality = YoloQualityModel(path, model_id="old", device="cpu")
    quality.adapter, quality.model, quality.device = old_adapter, object(), "cpu"
    quality._grading_engine._tracks[17] = object()
    failed = MagicMock(is_loaded=False, error="load failed")
    failed.load.return_value = False
    monkeypatch.setattr("src.inference.model_adapters.create_part_adapter", lambda *_args, **_kwargs: failed)
    with pytest.raises(RuntimeError, match="load failed"):
        quality.switch_model("new")
    assert quality.active_model_id == "old" and 17 in quality._grading_engine._tracks
    old_adapter.unload.assert_not_called()
    registry.persist_model2_selection.assert_not_called()
    replacement = MagicMock(is_loaded=True)
    replacement.load.return_value = True
    monkeypatch.setattr("src.inference.model_adapters.create_part_adapter", lambda *_args, **_kwargs: replacement)
    quality.switch_model("new")
    assert quality.active_model_id == "new" and quality.model_path == path
    assert not quality._grading_engine._tracks


def test_persistence_failure_keeps_loaded_model_and_temporal_evidence(tmp_path, monkeypatch):
    from src.inference.yolo_quality_model import YoloQualityModel
    path = tmp_path / "new.pt"
    path.write_bytes(b"fake model")
    entry = SimpleNamespace(id="new", display_name="new model", input_size=640)
    registry = SimpleNamespace(validate_compatibility=lambda *_: (True, None), get_model=lambda _id: entry,
                               resolve_checkpoint_path=lambda _entry: path,
                               persist_model2_selection=MagicMock(side_effect=OSError("write failed")))
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    replacement, old_adapter = MagicMock(is_loaded=True), MagicMock(is_loaded=True)
    replacement.load.return_value = True
    monkeypatch.setattr("src.inference.model_adapters.create_part_adapter", lambda *_args, **_kwargs: replacement)
    quality = YoloQualityModel(path, model_id="old", device="cpu")
    previous_model = object()
    quality.adapter, quality.model, quality.device = old_adapter, previous_model, "cpu"
    quality._grading_engine._tracks[17] = object()
    with pytest.raises(OSError, match="write failed"):
        quality.switch_model("new")
    assert quality.model is previous_model and quality.adapter is old_adapter
    assert quality.active_model_id == "old" and 17 in quality._grading_engine._tracks
    old_adapter.unload.assert_not_called()
    replacement.unload.assert_called_once()


def test_reset_failure_keeps_selection_and_temporal_evidence(tmp_path, monkeypatch):
    from src.inference.yolo_quality_model import YoloQualityModel
    path = tmp_path / "new.pt"
    path.write_bytes(b"fake model")
    entry = SimpleNamespace(id="new", display_name="new model", input_size=640)
    registry = SimpleNamespace(validate_compatibility=lambda *_: (True, None), get_model=lambda _id: entry,
                               resolve_checkpoint_path=lambda _entry: path, persist_model2_selection=MagicMock())
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    replacement = MagicMock(is_loaded=True)
    replacement.load.return_value = True
    monkeypatch.setattr("src.inference.model_adapters.create_part_adapter", lambda *_args, **_kwargs: replacement)
    quality = YoloQualityModel(path, model_id="old", device="cpu")
    old_model = object()
    quality.adapter, quality.model = MagicMock(is_loaded=True), old_model
    quality._grading_engine._tracks[17] = object()
    def failing_reset():
        quality._grading_engine._tracks.clear()
        raise RuntimeError("reset failed")
    monkeypatch.setattr(quality, "reset_tracks", failing_reset)
    with pytest.raises(RuntimeError, match="reset failed"):
        quality.switch_model("new")
    assert quality.active_model_id == "old" and quality.model is old_model
    assert 17 in quality._grading_engine._tracks
    registry.persist_model2_selection.assert_not_called()
    replacement.unload.assert_called_once()


def test_atomic_persistence_preserves_existing_json_on_replace_failure(tmp_path, monkeypatch):
    from src.inference.model_registry import ModelRegistry
    registry = object.__new__(ModelRegistry)
    registry._entries = {"new": object()}
    registry.settings_path = tmp_path / "active_model.json"
    registry.settings_path.write_text('{"selected_model2":"old"}', encoding="utf-8")
    monkeypatch.setattr("src.inference.model_registry.os.replace", MagicMock(side_effect=OSError("replace failed")))
    with pytest.raises(OSError, match="replace failed"):
        registry.persist_model2_selection("new")
    assert registry.settings_path.read_text(encoding="utf-8") == '{"selected_model2":"old"}'
    assert list(tmp_path.iterdir()) == [registry.settings_path]


@pytest.mark.parametrize("route", ["select", "settings"])
def test_same_model_is_noop_while_stopped(monkeypatch, route):
    quality = SimpleNamespace(active_model_id="current", model=object(), name="current model",
                              weights_path="current.pt", switch_model=MagicMock())
    monkeypatch.setattr(app_module, "quality_model", quality)
    monkeypatch.setattr(app_module.state, "snapshot", lambda: {"inspection_status": "stopped"})
    set_segmenter, rotate = MagicMock(), MagicMock()
    monkeypatch.setattr(app_module.state, "set_segmenter", set_segmenter)
    monkeypatch.setattr(app_module, "rotate_durable_session", rotate)
    monkeypatch.setattr(app_module, "_status_payload", lambda: {})
    registry = SimpleNamespace(get_model=lambda _id: object(), validate_compatibility=lambda *_: (True, None))
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    client = TestClient(app_module.app)
    response = (client.post("/api/models/select", json={"model_id": "current"}) if route == "select"
                else client.post("/api/settings", json={"model2_id": "current"}))
    assert response.status_code == 200
    quality.switch_model.assert_not_called()
    set_segmenter.assert_not_called()
    rotate.assert_not_called()


@pytest.mark.parametrize("route", ["select", "settings"])
def test_same_model_selection_is_rejected_while_running(monkeypatch, route):
    quality = SimpleNamespace(active_model_id="current", model=object(), switch_model=MagicMock())
    monkeypatch.setattr(app_module, "quality_model", quality)
    monkeypatch.setattr(app_module.state, "snapshot", lambda: {"inspection_status": "running"})
    registry = SimpleNamespace(get_model=lambda _id: object(), validate_compatibility=lambda *_: (True, None))
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    client = TestClient(app_module.app)
    response = (client.post("/api/models/select", json={"model_id": "current"}) if route == "select"
                else client.post("/api/settings", json={"model2_id": "current"}))
    assert response.status_code == 409
    quality.switch_model.assert_not_called()


def test_simultaneous_identical_selections_load_only_once(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    quality = SimpleNamespace(active_model_id="old", model=object(), name="model", weights_path="model.pt", device="cpu")
    def switch(model_id):
        entered.set()
        assert release.wait(5)
        quality.active_model_id = model_id
    quality.switch_model = MagicMock(side_effect=switch)
    monkeypatch.setattr(app_module, "quality_model", quality)
    monkeypatch.setattr(app_module.state, "snapshot", lambda: {"inspection_status": "stopped"})
    monkeypatch.setattr(app_module.state, "set_segmenter", MagicMock())
    monkeypatch.setattr(app_module, "inspection_sessions", SimpleNamespace(active=False))
    monkeypatch.setattr(app_module, "_status_payload", lambda: {})
    registry = SimpleNamespace(get_model=lambda _id: object(), validate_compatibility=lambda *_: (True, None))
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    class Request:
        async def json(self):
            return {"model_id": "new"}
    results = []
    def select():
        results.append(asyncio.run(app_module.select_model(Request())))
    first, second = threading.Thread(target=select), threading.Thread(target=select)
    first.start()
    assert entered.wait(5)
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    assert not first.is_alive() and not second.is_alive() and len(results) == 2
    quality.switch_model.assert_called_once_with("new")


def test_switch_waits_for_grading_to_finish(tmp_path, monkeypatch):
    from src.inference.yolo_quality_model import YoloQualityModel
    path = tmp_path / "new.pt"
    path.write_bytes(b"fake model")
    entry = SimpleNamespace(id="new", display_name="new model", input_size=640)
    registry = SimpleNamespace(validate_compatibility=lambda *_: (True, None), get_model=lambda _id: entry,
                               resolve_checkpoint_path=lambda _entry: path, persist_model2_selection=MagicMock())
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    replacement = MagicMock(is_loaded=True)
    replacement.load.return_value = True
    monkeypatch.setattr("src.inference.model_adapters.create_part_adapter", lambda *_args, **_kwargs: replacement)
    quality = YoloQualityModel(path, model_id="old", device="cpu")
    quality.adapter, quality.model, quality.device = MagicMock(is_loaded=True), object(), "cpu"
    monkeypatch.setattr(quality, "_infer_parts", lambda _image: ([], []))
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def grade(*_args, **_kwargs):
        entered.set()
        assert release.wait(5)
        return object()
    monkeypatch.setattr(quality, "_grade_parts", grade)
    prediction = threading.Thread(target=lambda: quality.predict(np.zeros((8, 8, 3), dtype=np.uint8), 1))
    def change():
        quality.switch_model("new")
        finished.set()
    prediction.start()
    assert entered.wait(5)
    changer = threading.Thread(target=change)
    changer.start()
    try:
        assert not finished.wait(.2)
    finally:
        release.set()
        prediction.join(5)
        changer.join(5)
    assert finished.is_set() and quality.active_model_id == "new"


def test_start_and_model_switch_are_serialized(monkeypatch):
    status = {"inspection_status": "stopped"}
    entered, release = threading.Event(), threading.Event()
    quality = SimpleNamespace(active_model_id="old", switch_model=MagicMock())
    monkeypatch.setattr(app_module, "quality_model", quality)
    monkeypatch.setattr(app_module.state, "snapshot", lambda: status.copy())
    monkeypatch.setattr(app_module, "_status_payload", lambda: {})
    monkeypatch.setattr(app_module.inspection_sessions, "start", lambda _metadata: None)
    monkeypatch.setattr(app_module, "_session_metadata", lambda: {})
    monkeypatch.setattr(app_module.service, "prepare_models", lambda: True)
    def start():
        entered.set()
        assert release.wait(5)
        status["inspection_status"] = "starting"
        return True
    monkeypatch.setattr(app_module.service, "start", start)
    registry = SimpleNamespace(get_model=lambda _id: object(), validate_compatibility=lambda *_: (True, None))
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    class Request:
        async def json(self):
            return {"model_id": "new"}
    result = []
    def switch():
        try:
            asyncio.run(app_module.select_model(Request()))
        except HTTPException as exc:
            result.append(exc.status_code)
    starter = threading.Thread(target=app_module.start_inspection)
    changer = threading.Thread(target=switch)
    starter.start()
    assert entered.wait(5)
    changer.start()
    release.set()
    starter.join(5)
    changer.join(5)
    assert not starter.is_alive() and not changer.is_alive()
    assert result == [409]
    quality.switch_model.assert_not_called()


def test_bad_upload_cannot_switch_models(monkeypatch):
    quality = SimpleNamespace(active_model_id="old", switch_model=MagicMock())
    monkeypatch.setattr(app_module, "quality_model", quality)
    client = TestClient(app_module.app)
    response = client.post("/api/analyze-image", content=b"invalid image", headers={"x-filename": "fish.jpg", "x-model-id": "new"})
    assert response.status_code == 400
    quality.switch_model.assert_not_called()


def test_upload_with_current_model_remains_available_during_inspection(monkeypatch):
    quality = SimpleNamespace(active_model_id="current", switch_model=MagicMock())
    monkeypatch.setattr(app_module, "quality_model", quality)
    monkeypatch.setattr(app_module.state, "snapshot", lambda: {"inspection_status": "running"})
    monkeypatch.setattr(app_module, "model", SimpleNamespace(model=object()))
    monkeypatch.setattr(app_module, "image_analyzer", SimpleNamespace(analyze=lambda _frame: {"ok": True}))
    ok, image = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok
    client = TestClient(app_module.app)
    response = client.post("/api/analyze-image", content=image.tobytes(), headers={"x-filename": "fish.jpg", "x-model-id": "current"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    quality.switch_model.assert_not_called()


def test_different_upload_model_does_not_change_stopped_live_selection(monkeypatch):
    quality = SimpleNamespace(active_model_id="old", switch_model=MagicMock(), name="old", weights_path="old.pt", device="cpu")
    monkeypatch.setattr(app_module, "quality_model", quality)
    monkeypatch.setattr(app_module.state, "snapshot", lambda: {"inspection_status": "stopped"})
    monkeypatch.setattr(app_module, "inspection_sessions", SimpleNamespace(active=False))
    monkeypatch.setattr(app_module, "model", SimpleNamespace(model=object()))
    monkeypatch.setattr(app_module, "image_analyzer", SimpleNamespace(analyze=lambda _frame: {"ok": True}))
    registry = SimpleNamespace(validate_compatibility=lambda *_: (True, None))
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    ok, image = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok
    response = TestClient(app_module.app).post("/api/analyze-image", content=image.tobytes(), headers={"x-filename": "fish.jpg", "x-model-id": "new"})
    assert response.status_code == 409
    quality.switch_model.assert_not_called()


def test_upload_rejects_unsupported_model_and_keeps_session(monkeypatch):
    quality = SimpleNamespace(active_model_id="old", switch_model=MagicMock())
    sessions = SimpleNamespace(active=True, session_id="existing")
    monkeypatch.setattr(app_module, "quality_model", quality)
    monkeypatch.setattr(app_module, "inspection_sessions", sessions)
    rotate = MagicMock()
    monkeypatch.setattr(app_module, "rotate_durable_session", rotate)
    registry = SimpleNamespace(validate_compatibility=lambda *_: (False, "Model not compatible"))
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    ok, image = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok
    response = TestClient(app_module.app).post("/api/analyze-image", content=image.tobytes(), headers={"x-filename": "fish.jpg", "x-model-id": "bad"})
    assert response.status_code == 400
    assert sessions.session_id == "existing"
    quality.switch_model.assert_not_called()
    rotate.assert_not_called()


def test_failed_upload_inference_does_not_change_model_or_session(monkeypatch):
    quality = SimpleNamespace(active_model_id="current", switch_model=MagicMock())
    sessions = SimpleNamespace(active=True, session_id="existing")
    monkeypatch.setattr(app_module, "quality_model", quality)
    monkeypatch.setattr(app_module, "inspection_sessions", sessions)
    monkeypatch.setattr(app_module, "model", SimpleNamespace(model=object()))
    monkeypatch.setattr(app_module, "image_analyzer", SimpleNamespace(analyze=MagicMock(side_effect=RuntimeError("analysis failed"))))
    ok, image = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok
    response = TestClient(app_module.app).post("/api/analyze-image", content=image.tobytes(), headers={"x-filename": "fish.jpg"})
    assert response.status_code == 503
    assert sessions.session_id == "existing" and quality.active_model_id == "current"
    quality.switch_model.assert_not_called()


def test_upload_waits_for_live_frame_processing(monkeypatch):
    processing_lock = threading.Lock()
    monkeypatch.setattr(app_module.service, "_processing_lock", processing_lock)
    quality = SimpleNamespace(active_model_id="current", switch_model=MagicMock())
    monkeypatch.setattr(app_module, "quality_model", quality)
    monkeypatch.setattr(app_module, "model", SimpleNamespace(model=object()))
    entered = threading.Event()
    def analyze(_frame):
        entered.set()
        return {"ok": True}
    monkeypatch.setattr(app_module, "image_analyzer", SimpleNamespace(analyze=analyze))
    ok, image = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok
    responses = []
    def upload():
        responses.append(TestClient(app_module.app).post("/api/analyze-image", content=image.tobytes(), headers={"x-filename": "fish.jpg"}))
    processing_lock.acquire()
    thread = threading.Thread(target=upload)
    thread.start()
    try:
        assert not entered.wait(.2)
    finally:
        processing_lock.release()
        thread.join(5)
    assert not thread.is_alive() and entered.is_set() and responses[0].status_code == 200
    quality.switch_model.assert_not_called()
