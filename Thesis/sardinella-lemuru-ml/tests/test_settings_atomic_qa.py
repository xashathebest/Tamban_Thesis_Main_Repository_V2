"""Rejected multi-setting requests must not mutate running settings."""
import asyncio
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.api import app
from src.api.domain import InspectionState


@pytest.fixture
def isolated(monkeypatch):
    state = InspectionState()
    detector = SimpleNamespace(confidence_threshold=state.confidence_threshold)
    quality = SimpleNamespace(confidence_threshold=state.quality_confidence_threshold, active_model_id="old", model=object())
    monkeypatch.setattr(app, "state", state)
    monkeypatch.setattr(app, "model", detector)
    monkeypatch.setattr(app, "quality_model", quality)
    monkeypatch.setattr(app, "service", SimpleNamespace(has_live_worker=lambda: False))
    monkeypatch.setattr(app, "inspection_sessions", SimpleNamespace(active=False))
    monkeypatch.setattr(app, "_status_payload", lambda: {})
    return state, detector, quality


@pytest.mark.parametrize("payload", [
    {"detection_confidence_threshold": 0.61, "display_settings": {"fish_ids": "yes"}},
    {"detection_confidence_threshold": 0.61, "quality_confidence_threshold": 2},
    {"detection_confidence_threshold": 0.61, "model2_id": 123},
    {"quality_confidence_threshold": 0.61, "display_settings": []},
])
def test_invalid_mixed_request_preserves_all_software_settings(isolated, payload):
    state, detector, quality = isolated
    before = (state.confidence_threshold, state.quality_confidence_threshold, state.current_display_settings(), detector.confidence_threshold, quality.confidence_threshold)
    with pytest.raises(HTTPException):
        app._update_settings_locked(payload)
    assert (state.confidence_threshold, state.quality_confidence_threshold, state.current_display_settings(), detector.confidence_threshold, quality.confidence_threshold) == before


def test_apply_exception_rolls_back_all_software_settings(isolated, monkeypatch):
    state, detector, quality = isolated
    previous = (state.confidence_threshold, state.quality_confidence_threshold, state.current_display_settings())
    monkeypatch.setattr(state, "set_display_settings", MagicMock(side_effect=RuntimeError("injected failure")))
    with pytest.raises(HTTPException, match="Settings could not be applied"):
        app._update_settings_locked({"detection_confidence_threshold": 0.8, "quality_confidence_threshold": 0.7, "display_settings": {"fish_ids": False}})
    assert (state.confidence_threshold, state.quality_confidence_threshold, state.current_display_settings()) == previous
    assert (detector.confidence_threshold, quality.confidence_threshold) == previous[:2]


def test_failed_session_rotation_rolls_back_thresholds(isolated, monkeypatch):
    state, detector, quality = isolated
    monkeypatch.setattr(app, "inspection_sessions", SimpleNamespace(active=True))
    monkeypatch.setattr(app, "rotate_durable_session", MagicMock(side_effect=OSError("database unavailable")))
    previous = (state.confidence_threshold, state.quality_confidence_threshold)
    with pytest.raises(HTTPException):
        app._update_settings_locked({"detection_confidence_threshold": 0.8, "quality_confidence_threshold": 0.7})
    assert (state.confidence_threshold, state.quality_confidence_threshold) == previous
    assert (detector.confidence_threshold, quality.confidence_threshold) == previous


def test_successful_policy_update_rotates_active_session(isolated, monkeypatch):
    state, detector, quality = isolated
    monkeypatch.setattr(app, "inspection_sessions", SimpleNamespace(active=True))
    rotate = MagicMock()
    monkeypatch.setattr(app, "rotate_durable_session", rotate)
    result = app._update_settings_locked({"detection_confidence_threshold": 0.8, "quality_confidence_threshold": 0.7, "display_settings": {"fish_ids": False}})
    assert result["updated"]
    assert (state.confidence_threshold, detector.confidence_threshold) == (0.8, 0.8)
    assert (state.quality_confidence_threshold, quality.confidence_threshold) == (0.7, 0.7)
    assert state.current_display_settings()["fish_ids"] is False
    rotate.assert_called_once()


def test_failed_model_load_rolls_back_mixed_settings(isolated, monkeypatch, tmp_path):
    state, detector, quality = isolated
    checkpoint = tmp_path / "candidate.pt"
    checkpoint.write_bytes(b"stub")
    entry = SimpleNamespace(display_name="Candidate")
    registry = SimpleNamespace(get_model=lambda _: entry, validate_compatibility=lambda *_: (True, None), resolve_checkpoint_path=lambda _: checkpoint)
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    quality.device = "cpu"
    quality.switch_model = MagicMock(side_effect=RuntimeError("load failed"))
    previous = (state.confidence_threshold, state.quality_confidence_threshold, state.current_display_settings(), state.segmenter_status)
    with pytest.raises(HTTPException):
        app._update_settings_locked({"model2_id": "candidate", "detection_confidence_threshold": 0.8, "display_settings": {"fish_ids": False}})
    assert (state.confidence_threshold, state.quality_confidence_threshold, state.current_display_settings(), state.segmenter_status) == previous
    assert detector.confidence_threshold == previous[0] and quality.active_model_id == "old"


def test_successful_model_and_threshold_update(isolated, monkeypatch, tmp_path):
    state, detector, quality = isolated
    checkpoint = tmp_path / "candidate.pt"
    checkpoint.write_bytes(b"stub")
    entry = SimpleNamespace(display_name="Candidate")
    registry = SimpleNamespace(get_model=lambda _: entry, validate_compatibility=lambda *_: (True, None), resolve_checkpoint_path=lambda _: checkpoint)
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    quality.device = "cpu"
    quality.switch_model = lambda model_id: setattr(quality, "active_model_id", model_id)
    assert app._update_settings_locked({"model2_id": "candidate", "detection_confidence_threshold": 0.8})["updated"]
    assert quality.active_model_id == "candidate"
    assert state.confidence_threshold == detector.confidence_threshold == 0.8
    assert state.segmenter_name == "Candidate"


def test_model_change_rejected_if_session_is_still_active(isolated, monkeypatch, tmp_path):
    state, detector, quality = isolated
    monkeypatch.setattr(app, "inspection_sessions", SimpleNamespace(active=True))
    entry = SimpleNamespace(display_name="Candidate")
    registry = SimpleNamespace(get_model=lambda _: entry, validate_compatibility=lambda *_: (True, None))
    monkeypatch.setattr("src.inference.model_registry.get_model_registry", lambda: registry)
    before = state.confidence_threshold
    with pytest.raises(HTTPException) as rejected:
        app._update_settings_locked({"model2_id": "candidate", "detection_confidence_threshold": 0.8})
    assert rejected.value.status_code == 409
    assert state.confidence_threshold == detector.confidence_threshold == before


def test_committed_settings_are_reported_when_optional_status_fails(isolated, monkeypatch):
    state, detector, _ = isolated
    monkeypatch.setattr(app, "_status_payload", MagicMock(side_effect=RuntimeError("status unavailable")))
    result = app._update_settings_locked({"detection_confidence_threshold": 0.8})
    assert result["updated"] and result["detection_confidence_threshold"] == 0.8
    assert state.confidence_threshold == detector.confidence_threshold == 0.8
    assert result["status_detail"] == "Full status is temporarily unavailable."


def test_concurrent_settings_requests_serialize_complete_updates(isolated, monkeypatch):
    state, detector, _ = isolated
    first_in_update, release_first, second_started, second_done = Event(), Event(), Event(), Event()
    original = state.set_confidence_threshold
    errors = []

    def blocked_set(value):
        if value == .61:
            first_in_update.set()
            if not release_first.wait(3):
                raise RuntimeError("first settings update did not resume")
        original(value)

    monkeypatch.setattr(state, "set_confidence_threshold", blocked_set)

    def apply(value, started=None, done=None):
        async def body():
            return {"detection_confidence_threshold": value}

        try:
            if started:
                started.set()
            asyncio.run(app.update_settings(SimpleNamespace(json=body)))
        except Exception as exc:
            errors.append(exc)
        finally:
            if done:
                done.set()

    first = Thread(target=apply, args=(.61,))
    second = Thread(target=apply, args=(.73, second_started, second_done))
    try:
        first.start()
        assert first_in_update.wait(2)
        second.start()
        assert second_started.wait(2)
        assert not second_done.wait(.05)
    finally:
        release_first.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert not first.is_alive() and not second.is_alive() and not errors
    assert state.confidence_threshold == detector.confidence_threshold == .73
