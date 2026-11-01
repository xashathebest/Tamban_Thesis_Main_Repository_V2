"""Real grading-stage integration without model checkpoints or calibration claims."""

from dataclasses import replace

import numpy as np
import pytest

from src.inference.body_width import BodyWidthConfig, analyze_body_width
from src.inference.geometric_support import integrate_geometric_support
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.grading_policy import FishGradingInput, GradingPolicy, grade_fish
from src.inference.part_types import PartDetection
from src.api.domain import Detection, QualitySummary, TrackingConfig, TrackingManager


def calibrated(**changes):
    return BodyWidthConfig(scoring_enabled=True, calibration_validated=True,
                           calibration_id="synthetic-software-test-only", validation_sample_count=30,
                           normal_reference_min=.1, normal_reference_max=.2, extreme_reference=.4,
                           **changes)


BOXES = {"Body": (40, 5, 140, 45), "Head": (5, 10, 30, 40), "Tail": (170, 10, 195, 40)}


def evidence(b=.54, c=.46, rejected=0):
    values = []
    for offset, region in enumerate(("Body", "Head", "Tail")):
        if b:
            values.append(PartDetection.from_source_class(3 + offset, b, BOXES[region]))
        if c:
            values.append(PartDetection.from_source_class(6 + offset, c, BOXES[region]))
        if rejected:
            values.append(PartDetection.from_source_class(9 + offset, rejected, BOXES[region]))
    return values


def width(config, **flags):
    parts = [PartDetection.from_source_class(1, .9, (25, 40, 45, 80)),
             PartDetection.from_source_class(0, .9, (60, 24, 160, 96)),
             PartDetection.from_source_class(2, .9, (180, 40, 210, 80))]
    return analyze_body_width((20, 10, 220, 110), parts, config=config, **flags)


def evaluate(config, parts=None, measured=None, **options):
    return WeightedGradingEngine(GradingConfig(), body_width_config=config).evaluate(
        9, np.full((50, 200, 3), 100, dtype=np.uint8), evidence() if parts is None else parts,
        stabilize=False, body_width=width(config) if measured is None else measured, **options)


def test_validated_width_changes_borderline_b_to_c_after_original_weighted_classification():
    cfg = calibrated()
    verdict = evaluate(cfg)
    original = verdict.geometric_support
    assert original["original_grade"] == "Class B"
    assert original["original_support"] == pytest.approx(.54)
    assert verdict.body_width["class_c_supporting_points"] == pytest.approx(8)
    assert verdict.final_grade == "Class C"
    assert verdict.final_score == pytest.approx(.54)
    assert original["width_changed_classification"] is True
    assert verdict.body_width["applied_geometric_score_shift"] == pytest.approx(.08)
    assert verdict.body_width["applied_body_score_shift"] == 0
    assert sum(verdict.weighted_scores.values()) == pytest.approx(1)
    assert {key: part["original_weight"] for key, part in verdict.part_results.items()} == {"Body": .5, "Head": .3, "Tail": .2}
    assert verdict.part_results["Body"]["grade"] == "Class B"
    assert verdict.part_results["Body"]["grade_evidence"]["Class C"] == .46
    assert verdict.part_results["Body"]["adjusted_grade_evidence"]["Class C"] == .46
    assert "changed Class B to Class C" in verdict.verdict_reason_text
    assert verdict.to_dict()["best_evidence_class"] == "Class B"
    assert verdict.to_dict()["best_evidence_score"] == pytest.approx(.54)


@pytest.mark.parametrize("change,reason", [
    ({"calibration_validated": False}, "not_calibrated"),
    ({"scoring_enabled": False}, "scoring_disabled"),
])
def test_missing_calibration_and_disabled_scoring_preserve_baseline_exactly(change, reason):
    cfg = replace(calibrated(), **change)
    verdict = evaluate(cfg)
    assert verdict.final_grade == "Class B"
    assert verdict.weighted_scores["Class B"] == pytest.approx(.54)
    assert verdict.geometric_support["contribution_reason"] == reason
    assert not verdict.body_width["score_applied"]


@pytest.mark.parametrize("flags", [{"overlapping": True}, {"clipped": True}, {"association_reliable": False}])
def test_diagnostic_proxy_on_unreliable_fish_never_supplies_class_c_points(flags):
    cfg = calibrated()
    measured = width(cfg, **flags)
    assert measured["relative_width_proxy"] == pytest.approx(.36)
    assert measured["measurement_status"] == "Unreliable"
    verdict = evaluate(cfg, measured=measured)
    assert verdict.final_grade == "Class B"
    assert not verdict.body_width["score_contributed"]


def test_required_body_missing_never_bypasses_ungraded_and_keeps_actual_pixels():
    cfg = calibrated()
    parts = [part for part in evidence() if part.region != "Body"]
    verdict = evaluate(cfg, parts=parts)
    assert verdict.final_grade is None
    assert "UG_MISSING_PART_EVIDENCE" in verdict.reason_codes
    assert not verdict.body_width["score_applied"]
    assert verdict.supporting_image_measurements["regions"]["Whole Fish"]["status"] == "measured"
    assert verdict.supporting_image_measurements["regions"]["Body"]["status"] == "unavailable"
    assert verdict.supporting_image_measurements["diagnostic_only_fallback"] is False  # still images keep observed Head/Tail diagnostics


def test_temporal_gate_and_no_parts_keep_diagnostics_but_never_invent_grade():
    cfg = calibrated()
    engine = WeightedGradingEngine(GradingConfig(), body_width_config=cfg)
    crop = np.full((50, 200, 3), 100, dtype=np.uint8)
    empty = engine.evaluate(9, crop, [], stabilize=True, frame_id=1)
    assert empty.final_grade is None
    assert empty.supporting_image_measurements["regions"]["Whole Fish"]["status"] == "measured"
    assert empty.supporting_image_measurements["diagnostic_only_fallback"] is True
    for frame_id in (2, 3, 4):
        verdict = engine.evaluate(9, crop, evidence(), stabilize=True, frame_id=frame_id, body_width=width(cfg))
        if frame_id == 2:
            assert verdict.final_grade is None
            assert not verdict.body_width["score_applied"]
        else:
            assert verdict.final_grade == "Class C"
            assert verdict.weighted_scores["Class C"] == pytest.approx(.54)
    repeated = engine.evaluate(9, crop, evidence(), stabilize=True, frame_id=4, body_width=width(cfg))
    assert repeated.weighted_scores == verdict.weighted_scores
    missing = engine.evaluate(9, crop, evidence(), stabilize=True, frame_id=5)
    assert missing.final_grade == "Class B"
    assert not missing.body_width["score_applied"]


def test_rejected_safeguard_and_normalized_rejected_share_are_preserved():
    cfg = calibrated()
    rejected = evaluate(cfg, parts=evidence(.15, .15, .8))
    assert rejected.final_grade == "Rejected"
    assert rejected.body_width["contribution_reason"] == "rejected_safeguard"
    verdict = evaluate(cfg, parts=evidence(.6, .5, .05))
    assert sum(verdict.weighted_scores.values()) == pytest.approx(1)
    assert verdict.weighted_scores["Rejected"] == pytest.approx(.05 / 1.15)


def test_shared_final_stage_cannot_apply_width_twice():
    cfg = calibrated()
    scores = {region: {"Class B": .54, "Class C": .46} for region in BOXES}
    policy = GradingPolicy()
    baseline = grade_fish(FishGradingInput(scores, {region: .54 for region in BOXES}), policy)
    once = integrate_geometric_support(baseline, width(cfg), cfg, policy, part_scores=scores)
    twice = integrate_geometric_support(once[0], once[1], cfg, policy, part_scores=scores)
    assert twice == once


def test_large_boxes_without_independent_class_c_evidence_cannot_change_grade():
    cfg = calibrated()
    verdict = evaluate(cfg, parts=evidence(.9, 0))
    assert verdict.final_grade == "Class B"
    assert not verdict.body_width["score_applied"]
    assert verdict.body_width["contribution_reason"] == "independent_class_c_evidence_required"


def test_geometric_grade_update_preserves_tracked_identity_and_counts_once():
    cfg = calibrated()
    tracker = TrackingManager(TrackingConfig(line_position=.5))
    before = evaluate(cfg, measured={"measurement_status": "Missing Detection"})
    after = evaluate(cfg)
    assert before.final_grade == "Class B" and after.final_grade == "Class C"
    for timestamp, x, verdict in ((0, 30, before), (.1, 60, after), (.2, 180, after), (.3, 210, after)):
        summary = QualitySummary(9, verdict.final_grade, verdict.final_score,
                                 tuple(part.to_dict() for part in evidence()),
                                 verdict.weighted_scores, verdict.to_dict())
        tracker.update([Detection(0, "Fish", .95, (x, 20, x + 20, 70), 9)],
                       (300, 120), timestamp=timestamp, grades={9: summary})
    assert tracker.counters()["total"] == 1
    assert tracker.quality_counters()["Class C"] == 1
    assert tracker.quality_counters()["Class B"] == 0
    history = tracker.history()
    assert len(history) == 1
    assert history[0]["track_id"] == 9
    assert history[0]["analysis"]["geometric_support"]["original_grade"] == "Class B"
    assert history[0]["analysis"]["geometric_support"]["width_changed_classification"] is True
