"""All seven captured records survive API repair and JSON serialization."""

from copy import deepcopy
import csv
import importlib
import json
from pathlib import Path
from unittest.mock import Mock

import cv2
from fastapi.testclient import TestClient
import numpy as np
import pytest

from src.api.image_analysis import RESULTS_SCHEMA_VERSION, complete_inspection_payload
from src.inference.body_width import BodyWidthConfig


app_module = importlib.import_module("src.api.app")
FIXTURE = Path(__file__).parent / "fixtures" / "fish-inspection-upload-all.csv"


def reproduction():
    with FIXTURE.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    return [json.loads(row["Complete fish event"]) for row in rows], json.loads(rows[0]["Source metadata"])


def test_api_normalizes_all_seven_without_models_or_state_changes(monkeypatch):
    records, metadata = reproduction()
    before = deepcopy(records)
    detector = Mock(side_effect=AssertionError("Normalization must not run Model 1"))
    infer = Mock(side_effect=AssertionError("Normalization must not run Model 2"))
    monkeypatch.setattr(app_module.model, "detect", detector)
    monkeypatch.setattr(app_module.quality_model, "predict", infer)
    state_before = app_module.state.tracking.counters().copy()
    client = TestClient(app_module.app, client=("127.0.0.1", 40500))
    response = client.post("/api/inspection-results/normalize", json={"fish": records, "source_metadata": metadata})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["results_schema_version"] == RESULTS_SCHEMA_VERSION
    assert len(result["fish"]) == 7
    for original, repaired in zip(records, result["fish"]):
        analysis = repaired["analysis"]
        assert repaired["quality"] == original["quality"]
        assert analysis["final_score"] == original["analysis"]["final_score"]
        assert analysis["weighted_scores"] == original["analysis"]["weighted_scores"]
        assert analysis["part_results"] == original["analysis"]["part_results"]
        assert analysis["geometric_support"]["original_grade"] == original["quality"]
        assert analysis["geometric_support"]["final_grade"] == original["quality"]
        assert analysis["geometric_support"]["width_changed_classification"] is False
        assert analysis["body_width"]["score_status"] == "Not calibrated"
        assert analysis["body_width"]["threshold_configuration"]
        assert repaired["timestamp"] == metadata["analyzed_at"]
    assert records == before
    assert app_module.state.tracking.counters() == state_before
    detector.assert_not_called()
    infer.assert_not_called()


def test_analyze_image_api_completes_old_adapter_results_before_serialization(monkeypatch):
    records, metadata = reproduction()
    frame = np.zeros((2160, 3840, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", frame)
    assert ok
    analyzer = Mock()
    analyzer.analyze.return_value = {"fish": records, "fish_detected": 7, "source_metadata": metadata}
    monkeypatch.setattr(app_module, "image_analyzer", analyzer)
    monkeypatch.setattr(app_module.model, "model", object())
    client = TestClient(app_module.app, client=("127.0.0.1", 40501))
    response = client.post("/api/analyze-image", content=encoded.tobytes(), headers={"x-filename": "existing-fish.jpg"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["results_schema_version"] == RESULTS_SCHEMA_VERSION
    assert result["quality_counters"]["Class B"] == 2
    assert result["quality_counters"]["Ungraded"] == 5
    assert [round(result["fish"][i - 1]["analysis"]["body_width"]["relative_width_proxy"], 3) for i in (1, 2, 3, 5)] == [.386, .481, .265, .302]
    assert all(fish["timestamp"] == metadata["analyzed_at"] for fish in result["fish"])
    analyzer.analyze.assert_called_once()


def test_serialization_marker_does_not_hide_empty_evidence_and_roundtrip_is_idempotent():
    records, metadata = reproduction()
    old = {"fish": records, "source_metadata": metadata, "results_schema_version": RESULTS_SCHEMA_VERSION}
    first = complete_inspection_payload(old, body_width_config=BodyWidthConfig())
    serialized = json.loads(json.dumps(first, allow_nan=False))
    second = complete_inspection_payload(serialized)
    assert second == serialized
    assert all(fish["analysis"]["body_width"] for fish in second["fish"])
    assert first["fish"][0]["analysis"]["geometric_support"]["original_grade"] == "Class B"


@pytest.mark.parametrize("payload,status", [
    ({}, 422), ({"fish": "invalid"}, 422), ({"fish": [None]}, 422),
    ({"fish": [{}] * 1001}, 422), ({"fish": [], "source_metadata": None}, 422),
])
def test_invalid_normalization_payloads_are_rejected(payload, status):
    response = TestClient(app_module.app, client=("127.0.0.1", 40502)).post("/api/inspection-results/normalize", json=payload)
    assert response.status_code == status


def test_normalization_byte_limit_applies_before_json_decode(monkeypatch):
    monkeypatch.setattr(app_module, "FISH_UPLOAD_MAX_BYTES", 8)
    response = TestClient(app_module.app, client=("127.0.0.1", 40503)).post("/api/inspection-results/normalize", content=b'{"fish":[]}')
    assert response.status_code == 413
