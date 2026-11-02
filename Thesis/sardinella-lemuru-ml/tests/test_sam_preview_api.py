"""Explicit mask generation is tied to pixels and cannot rerun grading."""
import asyncio
from copy import deepcopy
import hashlib
import importlib
from pathlib import Path
from threading import RLock
from types import SimpleNamespace

import cv2
from fastapi import HTTPException
import numpy as np
import pytest

from src.api.segmentation_preview import PreviewSnapshotCache, PreviewSnapshotError, generate_mask_preview
from src.inference.mobilesam_backend import MobileSamService, MobileSamSettings


class Engine:
    mode = "ellipse"
    def __init__(self, checkpoint, device): self.images, self.prompts = [], []
    def set_image(self, image): self.images.append(image)
    def reset_image(self): pass
    def predict(self, image, box, points, labels):
        self.prompts.append(tuple(box))
        mask = np.zeros(image.shape[:2], np.uint8)
        left, top, right, bottom = map(int, box)
        if self.mode == "ellipse":
            cv2.ellipse(mask, ((left+right)//2, (top+bottom)//2), ((right-left)//2-5, (bottom-top)//2-5), 0, 0, 360, 1, -1)
        elif self.mode == "rectangle": mask[top:bottom, left:right] = 1
        elif self.mode == "whole_image": mask[:] = 1
        return mask.astype(bool), .99


@pytest.fixture
def optional_model(tmp_path):
    path = tmp_path / "mobile_sam.pt"; path.write_bytes(b"synthetic decoder unit fixture")
    settings = MobileSamSettings(checkpoint=path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    return MobileSamService(settings, predictor_factory=Engine)


@pytest.fixture
def frame(): return np.full((120, 320, 3), 90, np.uint8)


FISH = [{"id": 7, "bbox": [20, 25, 140, 65], "parts": [], "detector_confidence": .9},
        {"id": 9, "bbox": [170, 40, 290, 80], "parts": [], "detector_confidence": .8}]


def detector():
    return SimpleNamespace(model=object(), confidence_threshold=.5, weights_path=Path("preserved.pt"), image_size=768)


def test_snapshot_retains_native_prompts_and_owned_parts_but_no_grades():
    cache = PreviewSnapshotCache(); source = deepcopy(FISH)
    source[0].update(quality="Class B", analysis={"model1_detection": {"bbox": [20.123456,25,140,65]}})
    model = detector(); token = cache.remember("pixels-a", (120,320,3), source, model)
    source[0]["bbox"][0] = 99
    actual = cache.resolve(token, "pixels-a", (120,320,3), model)
    assert actual[0]["bbox"][0] == 20.123456
    assert "quality" not in actual[0] and "analysis" not in actual[0]
    actual[0]["bbox"][0] = 88
    assert cache.resolve(token, "pixels-a", (120,320,3), model)[0]["bbox"][0] == 20.123456


@pytest.mark.parametrize("change", ["pixels", "dimensions", "settings", "model", "expiry", "eviction"])
def test_snapshot_never_reuses_boxes_for_another_source_or_model(change):
    clock = [0.]; cache = PreviewSnapshotCache(capacity=1, ttl_seconds=10, clock=lambda: clock[0])
    model = detector(); token = cache.remember("a", (120,320,3), FISH, model)
    digest, shape = "a", (120,320,3)
    if change == "pixels": digest = "b"
    elif change == "dimensions": shape = (320,120,3)
    elif change == "settings": model.confidence_threshold = .6
    elif change == "model": model.model = object()
    elif change == "expiry": clock[0] = 10.
    else: cache.remember("b", shape, FISH, model)
    with pytest.raises(PreviewSnapshotError): cache.resolve(token, digest, shape, model)


def test_preview_has_distinct_native_masks_one_encoder_no_grading_metadata(frame, optional_model):
    source = deepcopy(FISH)
    result = generate_mask_preview(frame, source, image_sha256="source", sam_service=optional_model, reused=True)
    assert source == FISH
    assert result["status"] == "generated" and result["generated_masks"] == 2
    assert result["review_required_masks"] == 2  # No reviewed anatomy/ownership supplied.
    assert result["detector_snapshot_reused"]
    assert len(optional_model._engine.images) == 1 and len(optional_model._engine.prompts) == 2
    assert result["fish"][0]["segmentation"]["mask_overlay"]["contours"] != result["fish"][1]["segmentation"]["mask_overlay"]["contours"]
    assert result["source"]["frame_width_px"] == 320
    for fish in result["fish"]:
        assert "quality" not in fish and "analysis" not in fish
        assert fish["segmentation"]["preview_usable"]
        assert fish["segmentation"]["used_for_grading"] is False
        assert fish["segmentation"]["measurement_validated"] is False
        assert fish["segmentation"]["mask_validated_for_cracks"] is False
    assert result["performance"]["segmentation_ms"] > 0


@pytest.mark.parametrize("mode", ["empty", "rectangle", "whole_image"])
def test_empty_or_rectangle_fills_never_report_preview_success(frame, optional_model, monkeypatch, mode):
    monkeypatch.setattr(Engine, "mode", mode)
    result = generate_mask_preview(frame, FISH, image_sha256="source", sam_service=optional_model)
    assert result["status"] == "unavailable" and result["generated_masks"] == 0
    assert result["errors"] and "failed" in result["message"].lower()


def test_missing_checkpoint_surfaces_actual_setup_error(frame, tmp_path):
    service = MobileSamService(MobileSamSettings(checkpoint=tmp_path / "missing.pt"), predictor_factory=Engine)
    result = generate_mask_preview(frame, FISH, image_sha256="source", sam_service=service)
    assert result["status"] == "unavailable"
    assert "checkpoint" in result["message"].lower()
    assert result["setup_command"] == "python -m src.evaluation.download_mobilesam_checkpoint"
    assert not service.status()["loaded"]


def test_no_fish_never_loads_mobile_model(frame, optional_model):
    result = generate_mask_preview(frame, [], image_sha256="source", sam_service=optional_model)
    assert result["status"] == "no_fish"
    assert result["generated_masks"] == 0 and not optional_model.status()["loaded"]


def request(data, token=None, filename="fish.png", declared=None):
    async def stream(): yield data
    headers = {"x-filename": filename}
    if token is not None: headers["x-preview-analysis-token"] = token
    if declared: headers["content-length"] = declared
    return SimpleNamespace(headers=headers, stream=stream)


@pytest.fixture
def api(monkeypatch, optional_model, frame):
    app = importlib.import_module("src.api.app")
    count = []
    model = detector()
    def detect(image):
        count.append(image.shape)
        return [SimpleNamespace(bbox=tuple(f["bbox"]), confidence=f["detector_confidence"]) for f in FISH]
    model.detect = detect
    monkeypatch.setattr(app, "model", model)
    monkeypatch.setattr(app, "service", SimpleNamespace(_processing_lock=RLock()))
    monkeypatch.setattr(app, "image_analyzer", object())
    monkeypatch.setattr(app, "mask_preview_snapshots", PreviewSnapshotCache())
    monkeypatch.setattr("src.inference.mobilesam_backend.get_mobilesam_service", lambda: optional_model)
    def prohibited(*args, **kwargs): raise AssertionError("Preview must not run Model2, grading or GrabCut")
    monkeypatch.setattr("src.inference.preprocessing.generate_runtime_fish_mask", prohibited)
    monkeypatch.setattr("src.inference.yolo_quality_model.YoloQualityModel.predict_full_frame", prohibited)
    ok, encoded = cv2.imencode(".png", frame); assert ok
    return SimpleNamespace(app=app, count=count, data=encoded.tobytes(), frame=frame)


def test_api_explicit_request_runs_real_detector_contract_once_without_model2(api):
    result = asyncio.run(api.app.segmentation_preview(request(api.data)))
    assert result["generated_masks"] == 2 and len(api.count) == 1
    assert result["source"]["image_sha256"] == hashlib.sha256(api.data).hexdigest()


def test_api_token_reuses_original_model1_ids_and_native_boxes_without_detector_or_model2(api):
    token = api.app.mask_preview_snapshots.remember(hashlib.sha256(api.data).hexdigest(), api.frame.shape, FISH, api.app.model)
    result = asyncio.run(api.app.segmentation_preview(request(api.data, token)))
    assert api.count == [] and result["detector_snapshot_reused"]
    assert [fish["id"] for fish in result["fish"]] == [7,9]
    assert [fish["bbox"] for fish in result["fish"]] == [fish["bbox"] for fish in FISH]


def test_api_invalid_snapshot_does_not_silently_redetect_different_ids(api):
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.app.segmentation_preview(request(api.data, "unknown")))
    assert error.value.status_code == 409 and api.count == []


def test_preview_honors_strict_model1_integrity_before_any_inference(api, monkeypatch):
    monkeypatch.setenv("FISH_STRICT_MODEL_INTEGRITY", "1")
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.app.segmentation_preview(request(api.data)))
    assert error.value.status_code == 503 and not api.count


def test_part_only_mode_cannot_invent_whole_fish_prompts(api, monkeypatch):
    monkeypatch.setattr(api.app, "image_analyzer", None)
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.app.segmentation_preview(request(api.data)))
    assert error.value.status_code == 503 and not api.count


@pytest.mark.parametrize("data,filename,declared,code", [(b"x","",None,400), (b"x","a.mp4",None,400),
    (b"not-image","a.png",None,400), (b"x","a.png",str(100*1024*1024),413)])
def test_api_rejects_invalid_upload_before_models(api, data, filename, declared, code):
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.app.segmentation_preview(request(data, filename=filename, declared=declared)))
    assert error.value.status_code == code and not api.count
