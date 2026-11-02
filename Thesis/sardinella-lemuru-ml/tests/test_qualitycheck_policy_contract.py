"""Current operating policy and historical snapshots survive feature optimization.

Only recorded Model 2 evidence and small CPU arrays are used; no checkpoint or
training process is accessed by these tests.
"""

from copy import deepcopy
import csv
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from src.api.image_analysis import StillImageAnalyzer
from src.inference.body_width import BodyWidthConfig, analyze_body_width
from src.inference.grading_engine import WeightedGradingEngine, load_grading_config
from src.inference.grading_policy import GRADE_NAMES
from src.inference.inspection_results import normalize_inspection_results
from src.inference.part_types import PartDetection


ROOT = Path(__file__).resolve().parents[1]
IMAGE = np.full((32, 64, 3), 100, dtype=np.uint8)
REGIONS = ("Body", "Head", "Tail")
BOXES = ((20, 5, 45, 25), (2, 5, 20, 25), (45, 5, 60, 25))


def part(region, confidence=.9, grade="Class A"):
    index = REGIONS.index(region)
    return PartDetection.from_source_class(GRADE_NAMES.index(grade) * 3 + index, confidence, BOXES[index])


def active_engine(**options):
    config = load_grading_config()
    assert config.config_version == "4.0" and config.grading_mode == "tail_optional_v1"
    assert config.to_policy().required_regions() == ("Body", "Head")
    return WeightedGradingEngine(config, **options)


@pytest.mark.parametrize("regions", [(), ("Body",), ("Head",), ("Tail",), ("Body", "Tail"), ("Head", "Tail")])
def test_current_runtime_requires_both_body_and_head(regions):
    verdict = active_engine().evaluate(1, IMAGE, [part(region) for region in regions], stabilize=False)
    assert verdict.final_grade is None
    assert "UG_MISSING_PART_EVIDENCE" in verdict.reason_codes


@pytest.mark.parametrize("grade", GRADE_NAMES)
@pytest.mark.parametrize("tail_confidence", [None, .24, .9])
def test_optional_tail_preserves_current_support_math(grade, tail_confidence):
    parts = [part("Body", .87, grade), part("Head", .79, grade)]
    if tail_confidence is not None:
        parts.append(part("Tail", tail_confidence, grade))
    result = active_engine().evaluate(1, IMAGE, parts, stabilize=False).to_dict()
    evaluated = tail_confidence is not None and tail_confidence >= .25
    assert result["final_grade"] == grade
    assert result["weighted_scores"][grade] == pytest.approx(.852 if evaluated else .84)
    assert result["effective_weights"] == pytest.approx(
        {"Body": .5, "Head": .3, "Tail": .2} if evaluated else {"Body": .625, "Head": .375, "Tail": 0.}
    )
    assert result["original_weight_coverage"] == pytest.approx(1. if evaluated else .8)
    assert result["grading_config"]["grading_mode"] == "tail_optional_v1"


@pytest.mark.parametrize("context,reason", [
    ({"parent_usable": False}, "UG_PARENT_UNCERTAIN"),
    ({"association_status": "ambiguous"}, "UG_ASSOCIATION_AMBIGUOUS"),
    ({"frame_quality": {"association_ambiguous": True}}, "UG_ASSOCIATION_AMBIGUOUS"),
    ({"model2_available": False}, "UG_MODEL2_UNAVAILABLE"),
])
def test_current_required_parts_do_not_bypass_ownership_or_availability(context, reason):
    # Actual unavailable-model callers supply no newly inferred detections.
    parts = [] if context.get("model2_available") is False else [part("Body"), part("Head")]
    verdict = active_engine().evaluate(7, IMAGE, parts, stabilize=False, **context)
    assert verdict.final_grade is None
    assert reason in verdict.reason_codes


def test_an_empty_detection_frame_creates_no_fish_ids_or_quality_work():
    detector = SimpleNamespace(model=object(), detect=Mock(return_value=[]))
    quality = SimpleNamespace(model=object(), predict=Mock(), predict_full_frame=Mock())
    result = StillImageAnalyzer(detector, quality).analyze(IMAGE)
    assert result["fish_detected"] == 0 and result["fish"] == []
    quality.predict.assert_not_called()
    quality.predict_full_frame.assert_not_called()


def test_uncalibrated_width_cannot_change_active_policy_support():
    parts = [part("Body", .87), part("Head", .79)]
    rules = BodyWidthConfig(scoring_enabled=True, calibration_validated=False)
    width = analyze_body_width((0, 0, 64, 32), parts, config=rules)
    baseline = active_engine(body_width_config=rules).evaluate(7, IMAGE, parts, stabilize=False).to_dict()
    measured = active_engine(body_width_config=rules).evaluate(7, IMAGE, parts, stabilize=False, body_width=width).to_dict()
    assert measured["weighted_scores"] == baseline["weighted_scores"]
    assert measured["final_grade"] == baseline["final_grade"] == "Class A"
    assert measured["geometric_support"]["applied_score_shift"] == 0
    assert measured["geometric_support"]["contribution_reason"] == "not_calibrated"
    assert measured["body_width"]["class_c_supporting_points"] is None


def test_seven_recorded_snapshots_are_not_regraded_by_current_operating_rules():
    with (ROOT / "tests/fixtures/fish-inspection-upload-all.csv").open(encoding="utf-8-sig", newline="") as stream:
        saved = list(csv.DictReader(stream))
    assert len(saved) == 7
    raw = [json.loads(row["Complete fish event"]) for row in saved]
    original = deepcopy(raw)
    metadata = json.loads(saved[0]["Source metadata"])
    normalized = normalize_inspection_results(raw, source_metadata=metadata)
    assert raw == original
    assert [row["quality"] for row in normalized] == [row["quality"] for row in original]
    assert sum(row["quality"] == "Class B" for row in normalized) == 2
    assert sum(row["quality"] == "Ungraded" for row in normalized) == 5
    for before, after in zip(original, normalized):
        assert after["id"] == before["id"]
        assert after["analysis"]["weighted_scores"] == before["analysis"]["weighted_scores"]
        for name, value in before["analysis"]["grading_config"].items():
            assert after["analysis"]["grading_config"][name] == value
        # Normalization may append explicit disabled width-calibration
        # provenance; it cannot replace any recorded operating rule.
        assert after["analysis"]["grading_config"]["body_width"]["scoring_enabled"] is False
        assert after["analysis"]["geometric_support"]["applied_score_shift"] == 0
