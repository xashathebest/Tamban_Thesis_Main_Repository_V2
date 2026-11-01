"""Regression against the seven actual disconnected exported inspection rows."""

from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path

import pytest

from src.inference.body_width import BodyWidthConfig
from src.inference.inspection_results import normalize_inspection_results, resolve_inspection_timestamp


FIXTURE = Path(__file__).parent / "fixtures" / "fish-inspection-upload-all.csv"


def exported_records():
    with FIXTURE.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    return [json.loads(row["Complete fish event"]) for row in rows], json.loads(rows[0]["Source metadata"])


def test_fixture_is_the_exact_seven_exported_records():
    records, metadata = exported_records()
    assert len(records) == 7
    assert [record["id"] for record in records] == list(range(1, 8))
    assert all(not record["analysis"].get("body_width") for record in records)
    assert metadata["analyzed_at"] == "2026-11-01T00:20:20.811Z"
    # A fixture is retained verbatim, including the disconnected payload.
    original = Path(r"C:/Users/User/Downloads/fish-inspection-upload-all.csv")
    if original.is_file():
        assert hashlib.sha256(FIXTURE.read_bytes()).digest() == hashlib.sha256(original.read_bytes()).digest()


@pytest.mark.parametrize("fish_id,expected", [(1, .386), (2, .481), (3, .265), (5, .302)])
def test_existing_integer_roi_measurements_supply_expected_proxies(fish_id, expected):
    records, metadata = exported_records()
    result = normalize_inspection_results(records, source_metadata=metadata)[fish_id - 1]
    width = result["analysis"]["body_width"]
    assert round(width["relative_width_proxy"], 3) == expected
    assert width["relative_width_proxy"] == width["roi_relative_width_proxy"]
    assert width["relative_width_proxy_source"] == "existing_ROI_measurements"
    assert width["measurement_method"] == "existing_rectangular_roi_pixel_proxy"
    assert width["detector_body_width_px"] > 0
    assert width["body_roi_width_px"] > 0
    assert width["threshold_configuration"]
    assert width["calibration_status"] == "Not Calibrated"
    assert width["score_status"] == "Not calibrated"
    assert width["class_c_supporting_points"] is None
    assert width["score_contributed"] is False


@pytest.mark.parametrize("fish_id", [4, 6, 7])
def test_missing_bodies_never_borrow_neighbor_detections(fish_id):
    records, metadata = exported_records()
    result = normalize_inspection_results(records, source_metadata=metadata)[fish_id - 1]
    width = result["analysis"]["body_width"]
    assert width["measurement_status"] == "Missing Detection"
    assert width["body_width_px"] is None
    assert width["relative_width_proxy"] is None
    assert "body_evidence_unavailable" in width["reliability_reasons"]


def test_all_seven_baseline_grades_scores_and_raw_features_are_unchanged():
    records, metadata = exported_records()
    original = deepcopy(records)
    results = normalize_inspection_results(records, source_metadata=metadata)
    assert records == original
    for before, after in zip(records, results):
        assert after["quality"] == before["quality"]
        assert after["quality_confidence"] == before["quality_confidence"]
        assert after["parts"] == before["parts"]
        for key in ("final_grade", "final_score", "weighted_scores", "part_results", "effective_weights", "supporting_image_measurements"):
            assert after["analysis"][key] == before["analysis"][key]
        geometry = after["analysis"]["geometric_support"]
        assert geometry["original_grade"] == before["quality"]
        assert geometry["final_grade"] == before["quality"]
        assert geometry["original_scores"] == before["analysis"]["weighted_scores"]
        assert geometry["final_scores"] == before["analysis"]["weighted_scores"]
        assert geometry["original_support"] == before["analysis"]["final_score"]
        assert geometry["applied_score_shift"] == 0
        assert geometry["width_changed_classification"] is False
        assert after["timestamp"] == metadata["analyzed_at"]
        assert after["analysis"]["grading_config"]["part_weights"] == {"Head": .3, "Body": .5, "Tail": .2}


def test_clipping_overlap_and_ambiguous_ownership_block_scoring_without_hiding_measurements():
    records, metadata = exported_records()
    results = normalize_inspection_results(records, source_metadata=metadata)
    for index in (0, 1, 2, 4):
        width = results[index]["analysis"]["body_width"]
        assert width["measurement_status"] == "Unreliable"
        assert width["relative_width_proxy"] is not None
        assert not width["reliable_for_scoring"]
        assert "overlapping_fish" in width["reliability_reasons"]
    assert "clipped_fish" in results[0]["analysis"]["body_width"]["reliability_reasons"]
    assert "clipped_fish" in results[1]["analysis"]["body_width"]["reliability_reasons"]
    assert "association_unreliable" in results[3]["analysis"]["body_width"]["reliability_reasons"]
    assert "association_unreliable" in results[6]["analysis"]["body_width"]["reliability_reasons"]


def test_normalization_is_idempotent_and_preserves_already_computed_geometry():
    records, metadata = exported_records()
    once = normalize_inspection_results(records, source_metadata=metadata)
    twice = normalize_inspection_results(once, source_metadata=metadata)
    assert twice == once


def test_timestamp_prefers_existing_record_and_never_substitutes_current_time():
    assert resolve_inspection_timestamp({"timestamp": "2026-10-30T09:00:00-04:00"}, {"analyzed_at": "2026-11-01T00:20:20.811Z"}) == "2026-10-30T09:00:00-04:00"
    assert resolve_inspection_timestamp({"analysis": {"inspection_source": {"analyzed_at": "2026-11-01T00:20:20.811Z"}}}) == "2026-11-01T00:20:20.811Z"
    assert resolve_inspection_timestamp({"analysis": {}}) is None


def test_truthy_missing_body_placeholder_is_repaired_from_existing_parts():
    records, metadata = exported_records()
    records[0]["analysis"]["body_width"] = {"measurement_status": "Missing Detection", "body_width_px": None}
    result = normalize_inspection_results(records, source_metadata=metadata)[0]
    assert result["analysis"]["body_width"]["body_roi_width_px"] == 583
    assert round(result["analysis"]["body_width"]["relative_width_proxy"], 3) == .386


def test_existing_roi_only_measurements_are_visible_without_fabricating_detector_geometry():
    records, metadata = exported_records()
    records[0]["parts"] = []
    records[0]["analysis"]["model2_debug"]["selected_detections"] = []
    result = normalize_inspection_results(records, source_metadata=metadata)[0]
    width = result["analysis"]["body_width"]
    assert round(width["relative_width_proxy"], 3) == .386
    assert width["body_bbox"] is None
    assert width["body_roi_width_px"] == 583
    assert width["measurement_available"] is True
    assert width["measurement_status"] == "Unreliable"
    assert not width["reliable_for_scoring"]
    assert result["quality"] == "Class B"


def test_legacy_grade_without_recorded_weighted_scores_is_not_replaced_or_invented():
    result = normalize_inspection_results([{"id": 1, "bbox": [10, 10, 210, 60], "quality": "A"}])[0]
    geometry = result["analysis"]["geometric_support"]
    assert result["quality"] == geometry["original_grade"] == geometry["final_grade"] == "A"
    assert geometry["original_scores"] == geometry["final_scores"] == {}


def test_same_pixel_boxes_from_different_live_frames_do_not_establish_overlap():
    records, _ = exported_records()
    first, second = deepcopy(records[0]), deepcopy(records[0])
    first["id"], second["id"] = 1, 2
    first["analysis"]["frame_quality"]["latest"]["frame_id"] = 10
    second["analysis"]["frame_quality"]["latest"]["frame_id"] = 20
    normalized = normalize_inspection_results([first, second])
    assert all("overlapping_fish" not in event["analysis"]["body_width"]["reliability_reasons"] for event in normalized)
