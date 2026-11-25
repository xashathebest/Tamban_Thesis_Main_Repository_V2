"""Anatomy safety contracts using synthetic software fixtures, not fish validation.

The drawn silhouettes deliberately exercise intact, headless, bodyless and
rotated outlines. They are not photographs, expert anatomy labels, or evidence
of real-world false-rejection accuracy.
"""

from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json

import cv2
import numpy as np
import pytest

from src.inference.anatomical_verification import (
    apply_anatomical_gate,
    inspect_silhouette,
    load_anatomical_evidence,
    verify_anatomy,
)
from src.inference.grading_policy import FishGradingInput, GradingPolicy, grade_fish
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.body_width import BodyWidthConfig
from src.inference.association import ParentAnchor
from src.inference.part_types import PartDetection
from src.inference.preprocessing import CropBounds, RuntimeMaskContext
from src.evaluation.fish_level_validation import EvaluationRules, recompute_final_verdict


FISH_ID = 7
FRAME_ID = "synthetic-frame-1"
SYNTHETIC_FRAME = np.full((320, 320, 3), 90, dtype=np.uint8)
SOURCE = {
    "source_id": "synthetic-anatomy-unit-fixture",
    "frame_pixels_sha256": hashlib.sha256(SYNTHETIC_FRAME.tobytes()).hexdigest(),
}


def review(region="Head", state="confirmed_absent", **changes):
    """A source-bound claim for software testing, never a real expert review."""
    return {
        "region": region,
        "state": state,
        "source": "expert_review",
        "fish_id": FISH_ID,
        "frame_id": FRAME_ID,
        **SOURCE,
        "reviewed": True,
        "ownership_validated": True,
        "visibility_validated": True,
        "reviewer": "synthetic-software-fixture",
        "review_id": "synthetic-review-1",
        "confidence": .99,
        **changes,
    }


def verify(presence=None, **kwargs):
    return verify_anatomy(
        {"Head": 0., "Body": .91} if presence is None else presence,
        threshold=kwargs.pop("threshold", .25),
        fish_id=kwargs.pop("fish_id", FISH_ID),
        frame_id=kwargs.pop("frame_id", FRAME_ID),
        source=kwargs.pop("source", SOURCE),
        **kwargs,
    )


def quality_decision(*, missing=()):
    presence = {region: 0. if region in missing else .9 for region in ("Head", "Body", "Tail")}
    scores = {
        region: {"Class A": confidence, "Class B": 0., "Class C": 0., "Rejected": 0.}
        for region, confidence in presence.items()
    }
    return grade_fish(
        FishGradingInput(part_scores=scores, presence_confidence=presence),
        GradingPolicy(grading_mode="tail_optional_v1"),
    )


class ForbiddenGeometry(Mapping):
    """Access would prove the unnecessary secondary path ran."""

    def __getitem__(self, _key):
        raise AssertionError("Intact Model 2 evidence must skip secondary geometry")

    def __iter__(self):
        raise AssertionError("Intact Model 2 evidence must skip secondary geometry")

    def __len__(self):
        raise AssertionError("Intact Model 2 evidence must skip secondary geometry")


def test_both_required_detections_skip_secondary_geometry_and_review_catalog():
    report = verify(
        {"Head": .92, "Body": .89}, geometry=ForbiddenGeometry(),
        evidence=[review("Head")],
    )
    assert report["status"] == "PRESENT"
    assert report["activated"] is False
    assert report["geometry"] == {}
    assert report["automatic_rejection"] is False
    assert all(part["source"] == "model2" for part in report["parts"].values())
    decision = quality_decision()
    assert apply_anatomical_gate(decision, report) is decision


@pytest.mark.parametrize("presence, missing", [
    ({"Head": 0., "Body": .91}, ["Head"]),
    ({"Head": .91, "Body": 0.}, ["Body"]),
    ({"Head": 0., "Body": 0.}, ["Head", "Body"]),
    ({}, ["Head", "Body"]),
])
def test_missing_required_detection_activates_without_inventing_absence(presence, missing):
    report = verify(presence)
    assert report["activated"] is True
    assert report["undetected_regions"] == missing
    assert report["missing_regions"] == []
    assert report["status"] == "UNCERTAIN"
    assert report["automatic_rejection"] is False
    assert report["rejection_reason"] is None
    assert all(report["parts"][region]["state"] == "UNCERTAIN" for region in missing)


@pytest.mark.parametrize("confidence", [0., .01, .249, None, True, False, float("nan"), float("inf"), -.1, 1.1, ".8"])
def test_zero_weak_or_invalid_primary_confidence_does_not_prove_absence(confidence):
    report = verify({"Head": confidence, "Body": .91})
    assert report["primary"]["Head"]["detected"] is False
    assert report["parts"]["Head"]["state"] == "UNCERTAIN"
    assert report["automatic_rejection"] is False


def test_zero_confidence_is_not_detected_even_with_zero_threshold():
    report = verify({"Head": 0., "Body": .91}, threshold=0.)
    assert report["primary"]["Head"]["detected"] is False
    assert report["activated"] is True


def test_exact_threshold_is_a_real_primary_detection():
    report = verify({"Head": .25, "Body": .25})
    assert report["status"] == "PRESENT"
    assert report["activated"] is False


@pytest.mark.parametrize("tail", [None, 0., .01, .99])
def test_tail_never_triggers_secondary_rejection(tail):
    report = verify({"Head": .91, "Body": .93, "Tail": tail}, evidence=[review("Tail")])
    assert report["status"] == "PRESENT"
    assert report["activated"] is False
    assert set(report["parts"]) == {"Head", "Body"}
    assert report["automatic_rejection"] is False


@pytest.mark.parametrize("region", ["Head", "Body"])
@pytest.mark.parametrize("state, expected", [("present", "PRESENT"), ("confirmed_absent", "MISSING")])
def test_independent_review_can_verify_each_missing_required_region(region, state, expected):
    presence = {"Head": .91, "Body": .93, region: 0.}
    report = verify(presence, evidence=[review(region, state)])
    assert report["activated"] is True
    assert report["primary"][region]["detected"] is False
    assert report["primary"][region]["confidence"] is None
    assert report["parts"][region]["state"] == expected
    assert report["parts"][region]["source"] == "reviewed_anatomy"
    assert report["parts"][region]["confidence"] == .99
    assert report["status"] == expected
    assert report["automatic_rejection"] is (expected == "MISSING")
    if expected == "MISSING":
        assert region in report["rejection_reason"]


def test_confirmed_absence_rejects_even_when_other_required_region_is_uncertain():
    report = verify({}, evidence=[review("Body")])
    assert report["parts"]["Head"]["state"] == "UNCERTAIN"
    assert report["parts"]["Body"]["state"] == "MISSING"
    assert report["automatic_rejection"] is True


@pytest.mark.parametrize("changes", [
    {"fish_id": FISH_ID + 1}, {"fish_id": True},
    {"frame_id": "stale-frame"}, {"source_id": "other-camera"},
    {"frame_pixels_sha256": "0" * 64},
    {"reviewed": False}, {"ownership_validated": False},
    {"visibility_validated": False}, {"reviewer": ""}, {"review_id": " "},
    {"source": "verified_detector"}, {"state": "suspected_absent"},
    {"confidence": .94}, {"confidence": None}, {"confidence": float("nan")},
    {"clipped": True}, {"occluded": True}, {"overlapping": True},
    {"ownership_ambiguous": True},
])
@pytest.mark.parametrize("region", ["Head", "Body"])
def test_stale_unverified_occluded_or_wrong_source_claim_cannot_reject(region, changes):
    report = verify({"Head": .91, "Body": .93, region: 0.}, evidence=[review(region, **changes)])
    assert report["parts"][region]["state"] == "UNCERTAIN"
    assert report["status"] == "UNCERTAIN"
    assert report["automatic_rejection"] is False


@pytest.mark.parametrize("source", [None, {}, {**SOURCE, "frame_pixels_sha256": "invalid"}])
def test_valid_claim_still_requires_current_source_identity(source):
    report = verify(source=source, evidence=[review()])
    assert report["status"] == "UNCERTAIN"
    assert report["automatic_rejection"] is False


@pytest.mark.parametrize("region", ["Head", "Body"])
def test_conflicting_independent_reviews_remain_uncertain(region):
    records = [review(region, "present"), review(region, "confirmed_absent", review_id="synthetic-review-2")]
    report = verify({"Head": .91, "Body": .93, region: 0.}, evidence=records)
    assert report["status"] == "UNCERTAIN"
    assert "conflicts" in report["parts"][region]["reason"]
    assert report["automatic_rejection"] is False


@pytest.mark.parametrize("quality", [
    {"parent_uncertain": True}, {"association_ambiguous": True},
    {"out_of_frame": True}, {"frame_clipped": True},
    {"parent_frame_clipped": True}, {"parent_crop_clipped": True},
    {"overlapping": True}, {"usable": False}, {"parent_usable": False},
    {"association_status": "AMBIGUOUS"},
])
def test_uncertain_capture_blocks_even_reviewed_missing_head(quality):
    report = verify(evidence=[review()], frame_quality=quality)
    assert report["status"] == "UNCERTAIN"
    assert report["automatic_rejection"] is False
    assert "blocked" in report["parts"]["Head"]["reason"].lower()


def test_model2_unavailable_never_activates_secondary_absence_decision():
    report = verify({}, evidence=[review()], model2_available=False)
    assert report["status"] == "UNAVAILABLE"
    assert report["activated"] is False
    assert report["automatic_rejection"] is False


def synthetic_silhouette(kind, angle):
    mask = np.zeros((320, 320), np.uint8)
    polygon = np.array([
        [35, 160], [60, 145], [110, 133], [180, 137], [225, 151],
        [262, 135], [252, 160], [262, 185], [225, 169],
        [180, 183], [110, 187], [60, 175],
    ], np.int32)
    cv2.fillPoly(mask, [polygon], 1)
    if kind == "headless":
        mask[:, :100] = 0
    elif kind == "bodyless":
        mask[:, 100:] = 0
    transform = cv2.getRotationMatrix2D((160, 160), angle, 1.)
    rotated = cv2.warpAffine(mask, transform, (320, 320), flags=cv2.INTER_NEAREST)
    anchor = np.array([249., 145., 1.]) if kind != "bodyless" else np.array([58., 160., 1.])
    x, y = transform @ anchor
    region, class_id = ("Tail", 2) if kind != "bodyless" else ("Head", 1)
    part = PartDetection.from_source_class(class_id, .92, (x-3, y-3, x+3, y+3))
    assert part.region == region
    return rotated.astype(bool), [part]


@pytest.mark.parametrize("kind", ["intact", "headless", "bodyless"])
@pytest.mark.parametrize("angle", [0, 37, 90, 160])
def test_synthetic_outline_geometry_never_automatically_proves_anatomical_absence(kind, angle):
    mask, parts = synthetic_silhouette(kind, angle)
    geometry = inspect_silhouette(mask, {"parent_isolation_reliable": True, "source": "synthetic_fixture"}, parts)
    report = verify({"Head": 0., "Body": 0.}, geometry=geometry)
    assert geometry["validated_for_absence"] is False
    assert geometry["status"] in {"candidate", "unavailable"}
    assert report["status"] == "UNCERTAIN"
    assert report["automatic_rejection"] is False


@pytest.mark.parametrize("metadata", [
    {"parent_isolation_reliable": False},
    {"parent_isolation_reliable": True, "overlapping": True},
    {"parent_isolation_reliable": True, "clipped": True},
    {"parent_isolation_reliable": True, "ownership_ambiguous": True},
    {"parent_isolation_reliable": True, "partial_silhouette": True},
])
def test_unowned_overlapping_or_clipped_mask_produces_no_anatomical_claim(metadata):
    mask, parts = synthetic_silhouette("intact", 0)
    geometry = inspect_silhouette(mask, metadata, parts)
    assert geometry["status"] == "unavailable"
    assert geometry["orientation"] == "UNCERTAIN"
    assert verify(geometry=geometry)["status"] == "UNCERTAIN"


def test_foreshortened_round_fish_mask_has_uncertain_orientation():
    mask = np.zeros((160, 160), np.uint8)
    cv2.circle(mask, (80, 80), 34, 1, -1)
    geometry = inspect_silhouette(mask, {"parent_isolation_reliable": True})
    assert geometry["orientation"] == "UNCERTAIN"
    assert geometry["status"] == "unavailable"
    assert verify(geometry=geometry)["automatic_rejection"] is False


def test_elongated_mask_without_owned_direction_anchor_is_uncertain():
    mask, _parts = synthetic_silhouette("intact", 37)
    geometry = inspect_silhouette(mask, {"parent_isolation_reliable": True})
    assert geometry["status"] == "candidate"
    assert geometry["orientation"] == "UNCERTAIN"
    assert geometry["expected_regions"] == {}


@pytest.mark.parametrize("mask", [None, np.zeros((12, 12)), np.ones((3, 4, 2)), np.full((30, 30), .7), np.full((30, 30), np.nan)])
def test_missing_or_malformed_mask_remains_uncertain(mask):
    geometry = inspect_silhouette(mask, {"parent_isolation_reliable": True})
    assert geometry["status"] == "unavailable"
    assert verify(geometry=geometry)["status"] == "UNCERTAIN"


@pytest.mark.parametrize("region", ["Head", "Body"])
def test_independent_absence_rejection_preserves_all_quality_math_and_null_support(region):
    original = quality_decision(missing=(region,))
    snapshot = deepcopy(original.to_dict())
    report = verify({"Head": .91, "Body": .93, region: 0.}, evidence=[review(region)])
    final = apply_anatomical_gate(original, report)
    assert final.final_grade == "Rejected"
    assert final.final_support is None
    assert final.reason_codes == (f"RJ_CONFIRMED_MISSING_{region.upper()}",)
    assert final.override["source"] == "secondary_anatomical_verification"
    assert final.override["quality_scores_unchanged"] is True
    for key in ("weighted_scores", "observed_regions", "evidence_coverage", "effective_weights", "contributions", "top_support", "second_support", "grade_margin"):
        assert getattr(final, key) == getattr(original, key)
    assert original.to_dict() == snapshot


def test_uncertain_anatomy_holds_grade_without_mutating_quality_evidence():
    original = quality_decision()
    assert original.final_grade == "Class A"
    final = apply_anatomical_gate(original, verify())
    assert final.final_grade is None
    assert final.final_support is None
    assert "UG_ANATOMY_UNCERTAIN" in final.reason_codes
    assert final.weighted_scores == original.weighted_scores
    assert final.effective_weights == original.effective_weights
    assert final.contributions == original.contributions


def test_reviewed_presence_does_not_invent_quality_score_for_missing_model2_part():
    original = quality_decision(missing=("Body",))
    assert original.final_grade is None
    report = verify({"Head": .91, "Body": 0.}, evidence=[review("Body", "present")])
    assert report["status"] == "PRESENT"
    assert apply_anatomical_gate(original, report) is original
    assert original.contributions["Body"]["Class A"] == 0.


def engine(**config):
    return WeightedGradingEngine(GradingConfig(image_diagnostics_enabled=False, grading_mode="tail_optional_v1", **config))


def engine_parts(*, missing=()):
    definitions = [("Head", 1, (35., 145., 80., 175.)), ("Body", 0, (80., 135., 225., 185.))]
    return [PartDetection.from_source_class(class_id, .9, box) for region, class_id, box in definitions if region not in missing]


def test_engine_intact_required_parts_keep_optional_tail_weights_and_skip_secondary_geometry():
    verdict = engine().evaluate(FISH_ID, SYNTHETIC_FRAME, engine_parts(), stabilize=False, frame_id=FRAME_ID)
    assert verdict.final_grade == "Class A"
    assert verdict.final_score == pytest.approx(.9)
    assert verdict.effective_weights == pytest.approx({"Head": .375, "Body": .625, "Tail": 0.})
    assert verdict.anatomical_verification["activated"] is False
    assert verdict.anatomical_verification["geometry"] == {}


@pytest.mark.parametrize("region", ["Head", "Body"])
def test_engine_source_bound_missing_anatomy_rejects_without_quality_confidence(region):
    parts = engine_parts(missing=(region,))
    baseline = engine().evaluate(FISH_ID, SYNTHETIC_FRAME, parts, stabilize=False, frame_id=FRAME_ID)
    verdict = engine().evaluate(
        FISH_ID, SYNTHETIC_FRAME, parts, stabilize=False, frame_id=FRAME_ID,
        source_context=SOURCE, anatomical_evidence=[review(region)],
    )
    assert verdict.final_grade == "Rejected"
    assert verdict.final_score is None
    assert verdict.override["source"] == "secondary_anatomical_verification"
    assert verdict.weighted_scores == baseline.weighted_scores
    assert verdict.effective_weights == baseline.effective_weights
    assert verdict.part_results[region]["present"] is False
    assert verdict.anatomical_verification["missing_regions"] == [region]
    serialized = verdict.to_dict()
    assert serialized["final_support"] is None
    assert serialized["anatomical_verification"]["parts"][region]["state"] == "MISSING"


@pytest.mark.parametrize("region", ["Head", "Body"])
def test_engine_independently_present_part_cannot_synthesize_missing_grade(region):
    verdict = engine().evaluate(
        FISH_ID, SYNTHETIC_FRAME, engine_parts(missing=(region,)), stabilize=False, frame_id=FRAME_ID,
        source_context=SOURCE, anatomical_evidence=[review(region, "present")],
    )
    assert verdict.anatomical_verification["status"] == "PRESENT"
    assert verdict.final_grade is None
    assert verdict.override is None
    assert verdict.part_results[region]["present"] is False
    assert "UG_ANATOMY_UNCERTAIN" not in verdict.reason_codes


def test_engine_reviewed_presence_continues_standard_grading_when_its_existing_gates_pass():
    standard = WeightedGradingEngine(GradingConfig(image_diagnostics_enabled=False))
    parts = engine_parts(missing=("Head",)) + [PartDetection.from_source_class(2, .9, (225., 150., 260., 170.))]
    verdict = standard.evaluate(
        FISH_ID, SYNTHETIC_FRAME, parts, stabilize=False, frame_id=FRAME_ID,
        source_context=SOURCE, anatomical_evidence=[review("Head", "present")],
    )
    assert verdict.anatomical_verification["status"] == "PRESENT"
    assert verdict.final_grade == "Class A"
    assert verdict.final_score == pytest.approx(.63)
    assert verdict.part_results["Head"]["present"] is False


def test_engine_temporal_absence_claim_cannot_reject_a_later_frame():
    temporal = engine(minimum_track_observations=1)
    first = temporal.evaluate(
        FISH_ID, SYNTHETIC_FRAME, engine_parts(missing=("Head",)), stabilize=True, frame_id=FRAME_ID,
        source_context=SOURCE, anatomical_evidence=[review()],
    )
    assert first.final_grade == "Rejected"
    latest = temporal.evaluate(
        FISH_ID, SYNTHETIC_FRAME, engine_parts(missing=("Head",)), stabilize=True, frame_id="synthetic-frame-2",
        source_context=SOURCE, anatomical_evidence=[review()],
    )
    assert latest.anatomical_verification["status"] == "UNCERTAIN"
    assert latest.final_grade is None
    assert latest.override is None


@pytest.mark.parametrize("context", [{"parent_usable": False}, {"association_status": "ambiguous"}])
def test_engine_explicit_uncertain_parent_or_association_blocks_absence_rejection(context):
    verdict = engine().evaluate(
        FISH_ID, SYNTHETIC_FRAME, engine_parts(missing=("Head",)), stabilize=False, frame_id=FRAME_ID,
        source_context=SOURCE, anatomical_evidence=[review()], **context,
    )
    assert verdict.final_grade is None
    assert verdict.anatomical_verification["automatic_rejection"] is False


class SyntheticMaskService:
    """Decoder test double, with no model load or authenticated anatomy."""

    def __init__(self):
        self.prompt_calls = 0
        self.frame_calls = 0

    @contextmanager
    def open_frame(self, frame, key):
        self.frame_calls += 1
        self.frame, self.key = frame, key
        yield self

    def predict(self, identity, box, **_options):
        self.prompt_calls += 1
        if identity != FISH_ID:
            return {"status": "unavailable", "mask": None, "reason": "Synthetic neighboring proposal unavailable."}
        mask, _ = synthetic_silhouette("intact", 0)
        return {"status": "candidate", "parent_id": identity, "mask": mask, "score": .999,
                "provenance": {"backend": "mobilesam_experimental", "parent_id": identity,
                    "frame_key": self.key, "coordinate_space": "original_frame", "mask_shape": list(mask.shape),
                    "original_bbox_global": list(box), "prompt_bbox_global": list(box)}}

    def diagnostics(self):
        return {"embedding_calls": self.frame_calls, "prompt_calls": self.prompt_calls}


def candidate_context(monkeypatch, *, neighbor=False):
    source = SYNTHETIC_FRAME.copy()
    service = SyntheticMaskService()
    monkeypatch.setattr("src.inference.mobilesam_backend.get_mobilesam_service", lambda: service)
    parents = [ParentAnchor(FISH_ID, (20., 120., 280., 200.), .99)]
    if neighbor:
        parents.append(ParentAnchor(8, (240., 130., 290., 190.), .99))
    context = RuntimeMaskContext(source, frame_id=FRAME_ID, backend="mobilesam_experimental")
    context.prepare_instances(parents, engine_parts(missing=("Head",)))
    return context, source, service


def test_missing_primary_head_does_not_circularly_block_existing_mask_investigation(monkeypatch):
    context, _frame, service = candidate_context(monkeypatch)
    bounds = CropBounds(20, 120, 280, 200)
    ordinary, _ = context.get(FISH_ID, bounds)
    assert ordinary is None  # Usual feature contract requires Head and Body.
    before = (service.frame_calls, service.prompt_calls)
    mask, metadata = context.anatomical_candidate(FISH_ID, bounds)
    again, _ = context.anatomical_candidate(FISH_ID, bounds)
    assert mask.shape == (80, 260)
    assert np.array_equal(mask, again)
    assert metadata["parent_isolation_reliable"] is True
    assert metadata["ownership_validated"] is False
    assert metadata["validated_for_absence"] is False
    assert metadata["clipped"] is False
    assert (service.frame_calls, service.prompt_calls) == before


def test_anatomy_mask_cannot_borrow_neighbor_pixels_even_without_neighbor_mask(monkeypatch):
    context, _frame, service = candidate_context(monkeypatch, neighbor=True)
    mask, metadata = context.anatomical_candidate(FISH_ID, CropBounds(20, 120, 280, 200))
    assert mask is None
    assert metadata["overlapping"] is True
    assert metadata["parent_isolation_reliable"] is False
    assert service.frame_calls == 1


def test_anatomy_candidate_rejects_stale_full_frame_pixels_without_new_inference(monkeypatch):
    context, frame, service = candidate_context(monkeypatch)
    frame[0, 0, 0] ^= 1
    before = (service.frame_calls, service.prompt_calls)
    mask, metadata = context.anatomical_candidate(FISH_ID, CropBounds(20, 120, 280, 200))
    assert mask is None
    assert metadata["parent_isolation_reliable"] is False
    assert (service.frame_calls, service.prompt_calls) == before


def test_anatomy_candidate_crop_losing_tissue_marks_geometry_incomplete(monkeypatch):
    context, _frame, _service = candidate_context(monkeypatch)
    mask, metadata = context.anatomical_candidate(FISH_ID, CropBounds(100, 120, 280, 200))
    assert mask is not None
    assert metadata["clipped"] is True
    assert inspect_silhouette(mask, metadata)["status"] == "unavailable"


def test_loader_is_optional_and_filters_to_current_physical_fish(tmp_path, monkeypatch):
    monkeypatch.delenv("FISH_ANATOMICAL_EVIDENCE_PATH", raising=False)
    records, status = load_anatomical_evidence(fish_id=FISH_ID, frame_id=FRAME_ID, source=SOURCE)
    assert records == []
    assert status["status"] == "not_configured"
    path = tmp_path / "synthetic-anatomy-reviews.json"
    path.write_text(json.dumps({"schema_version": "anatomical_evidence_v1", "records": [review(), review(fish_id=8), review(frame_id="stale"), None]}), encoding="utf-8")
    monkeypatch.setenv("FISH_ANATOMICAL_EVIDENCE_PATH", str(path))
    records, status = load_anatomical_evidence(fish_id=FISH_ID, frame_id=FRAME_ID, source=SOURCE)
    assert status == {"status": "loaded", "matching_records": 1}
    assert records == [review()]


@pytest.mark.parametrize("contents", ["{bad json", "[]", '{"schema_version":"wrong","records":[]}', '{"schema_version":"anatomical_evidence_v1","records":{}}'])
def test_malformed_review_catalog_fails_closed(tmp_path, monkeypatch, contents):
    path = tmp_path / "malformed.json"
    path.write_text(contents, encoding="utf-8")
    monkeypatch.setenv("FISH_ANATOMICAL_EVIDENCE_PATH", str(path))
    records, status = load_anatomical_evidence(fish_id=FISH_ID, frame_id=FRAME_ID, source=SOURCE)
    assert records == []
    assert status["status"] == "unavailable"


def test_absent_review_file_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("FISH_ANATOMICAL_EVIDENCE_PATH", str(tmp_path / "absent.json"))
    records, status = load_anatomical_evidence(fish_id=FISH_ID, frame_id=FRAME_ID, source=SOURCE)
    assert records == []
    assert status["status"] == "unavailable"


@pytest.mark.parametrize("state", [[], {}, ["confirmed_absent"]])
def test_unhashable_matching_catalog_state_is_ignored_without_breaking_inference(tmp_path, monkeypatch, state):
    path = tmp_path / "synthetic-malformed-state.json"
    path.write_text(json.dumps({"schema_version": "anatomical_evidence_v1", "records": [review(state=state)]}), encoding="utf-8")
    monkeypatch.setenv("FISH_ANATOMICAL_EVIDENCE_PATH", str(path))
    records, status = load_anatomical_evidence(fish_id=FISH_ID, frame_id=FRAME_ID, source=SOURCE)
    assert status["status"] == "loaded"
    report = verify(evidence=records)
    assert report["status"] == "UNCERTAIN"
    assert report["automatic_rejection"] is False
    verdict = engine().evaluate(
        FISH_ID, SYNTHETIC_FRAME, engine_parts(missing=("Head",)), stabilize=False, frame_id=FRAME_ID,
        source_context=SOURCE, anatomical_evidence=records,
    )
    assert verdict.final_grade is None
    assert verdict.anatomical_verification["status"] == "UNCERTAIN"


@pytest.mark.parametrize("length", [80, 100_000])
@pytest.mark.parametrize("vertical", [False, True])
def test_thin_failed_segmentation_cannot_divide_by_zero_or_resize_to_zero(length, vertical):
    shape = (length, 1) if vertical else (1, length)
    mask = np.ones(shape, dtype=bool)
    geometry = inspect_silhouette(mask, {"parent_isolation_reliable": True, "source": "synthetic_failed_mask"})
    assert geometry["status"] == "unavailable"
    assert geometry["validated_for_absence"] is False
    assert geometry["orientation"] == "UNCERTAIN"
    assert verify(geometry=geometry)["automatic_rejection"] is False


def test_reviewed_current_absence_overrides_retained_temporal_quality_after_geometry_without_numeric_support():
    # Synthetic calibration is deliberately local to this software regression.
    width_config = BodyWidthConfig(
        scoring_enabled=True, calibration_validated=True,
        calibration_id="synthetic-anatomy-regression-only", validation_sample_count=20,
        normal_reference_min=.1, normal_reference_max=.2, extreme_reference=.4,
    )
    temporal = WeightedGradingEngine(
        GradingConfig(image_diagnostics_enabled=False, grading_mode="tail_optional_v1", minimum_track_observations=1),
        body_width_config=width_config,
    )
    body_c = PartDetection.from_source_class(6, .3, (80., 135., 225., 185.))
    width = {"reliable_for_scoring": True, "measurement_available": True,
             "score_status": "Calibrated", "class_c_supporting_points": 10.}
    previous = temporal.evaluate(
        FISH_ID, SYNTHETIC_FRAME, engine_parts() + [body_c], stabilize=True,
        frame_id=FRAME_ID, source_context=SOURCE, body_width=width,
    )
    assert previous.geometric_support["contribution_applied"] is True
    current_frame = "synthetic-frame-2"
    latest = temporal.evaluate(
        FISH_ID, SYNTHETIC_FRAME, engine_parts(missing=("Head",)) + [body_c], stabilize=True,
        frame_id=current_frame, source_context=SOURCE, body_width=width,
        anatomical_evidence=[review(frame_id=current_frame)],
    )
    assert latest.geometric_support["contribution_applied"] is True
    assert latest.part_results["Head"]["present"] is True  # Retained quality evidence.
    assert latest.anatomical_verification["primary"]["Head"]["detected"] is False  # Actual current frame.
    assert latest.final_grade == "Rejected"
    assert latest.final_score is None
    assert latest.weighted_scores == previous.weighted_scores
    assert latest.effective_weights == previous.effective_weights
    assert latest.feature_fusion["final_grade"] == "Rejected"
    assert latest.feature_fusion["final_support"] is None
    assert latest.feature_fusion["decision_fusion"]["final_fused_prediction"] == "Rejected"
    assert latest.feature_fusion["decision_fusion"]["decision_confidence"] is None
    replay = recompute_final_verdict(
        {"fish_id": FISH_ID, "analysis": latest.to_dict()},
        EvaluationRules(grading_mode="tail_optional_v1"),
    )
    assert replay["final_grade"] == "Rejected"
    assert replay["final_support"] is None
    assert replay["anatomical_verification"]["primary"]["Head"]["detected"] is False


def test_replay_new_model1_threshold_blocks_previously_reviewed_absence_rejection():
    verdict = engine().evaluate(
        FISH_ID, SYNTHETIC_FRAME, engine_parts(missing=("Head",)), stabilize=False, frame_id=FRAME_ID,
        source_context=SOURCE, anatomical_evidence=[review()],
    )
    assert verdict.final_grade == "Rejected"
    record = {"fish_id": FISH_ID, "model1_confidence": .4, "analysis": verdict.to_dict()}
    replay = recompute_final_verdict(record, EvaluationRules(grading_mode="tail_optional_v1", model1_confidence_threshold=.8))
    assert replay["final_grade"] == "Ungraded"
    assert replay["anatomical_verification"]["status"] == "UNCERTAIN"
    assert replay["anatomical_verification"]["automatic_rejection"] is False
    assert "UG_PARENT_UNCERTAIN" in replay["reason_codes"]


@pytest.mark.parametrize("quality", [
    {"association_ambiguous": True}, {"association_status": "ambiguous"},
    {"parent_usable": False}, {"parent_uncertain": True},
    {"source_pixels_mismatch": True}, {"evidence_identity_mismatch": True},
    {"anatomical_input_context": {"fish_id": FISH_ID + 1, "frame_id": FRAME_ID}},
    {"anatomical_input_context": {"fish_id": FISH_ID, "frame_id": "other-frame"}},
])
def test_both_primary_parts_require_current_fish_association_without_secondary_inference(quality):
    report = verify({"Head": .92, "Body": .89}, frame_quality=quality,
                    geometry=ForbiddenGeometry(), evidence=[review()])
    assert report["activated"] is False
    assert report["geometry"] == {}
    assert report["status"] == "UNCERTAIN"
    assert report["review_reason"]
    assert report["uncertainty_causes"]
    assert report["automatic_rejection"] is False
    for region in ("Head", "Body"):
        assert report["primary"][region]["detected"] is True
        assert report["primary"][region]["association_valid"] is False
        assert report["parts"][region]["state"] == "UNCERTAIN"


@pytest.mark.parametrize("flag", [
    "occluded", "partial_silhouette", "incomplete_visibility", "overlapping",
    "clipped", "ownership_ambiguous",
])
@pytest.mark.parametrize("region", ["Head", "Body"])
def test_current_visibility_hazards_block_even_a_matching_independent_absence_review(flag, region):
    report = verify({"Head": .91, "Body": .93, region: 0.},
                    evidence=[review(region)], frame_quality={flag: True})
    assert report["status"] == "UNCERTAIN"
    assert report["parts"][region]["state"] == "UNCERTAIN"
    assert report["automatic_rejection"] is False
    assert flag in report["uncertainty_causes"]
    assert flag in report["review_reason"]


@pytest.mark.parametrize("flag", [
    "occluded", "clipped", "overlapping", "ownership_ambiguous",
    "partial_silhouette", "incomplete_visibility", "frame_clipped",
    "parent_frame_clipped", "parent_crop_clipped", "out_of_frame",
])
@pytest.mark.parametrize("value", [None, 0, 1, "false", [], {}])
def test_malformed_review_visibility_flags_cannot_authorize_absence(flag, value):
    report = verify(evidence=[review(**{flag: value})])
    assert report["status"] == "UNCERTAIN"
    assert report["parts"]["Head"]["state"] == "UNCERTAIN"
    assert report["automatic_rejection"] is False


@pytest.mark.parametrize("flag", ["visibility_validated", "complete_visibility", "complete_mask"])
@pytest.mark.parametrize("value", [None, False, 0, 1, "true"])
def test_review_visibility_confirmation_requires_literal_true(flag, value):
    report = verify(evidence=[review(**{flag: value})])
    assert report["status"] == "UNCERTAIN"
    assert report["automatic_rejection"] is False


@pytest.mark.parametrize("changes", [
    {"fish_id": float(FISH_ID)}, {"parent_track_id": FISH_ID + 1},
    {"parent_track_id": float(FISH_ID)}, {"parent_track_id": True},
    {"frame_id": True}, {"frame_id": 1.0},
])
def test_source_bound_review_rejects_coercible_or_mismatched_physical_identity(changes):
    report = verify(frame_id=1, evidence=[review(frame_id=1, **changes)]
                    if "frame_id" not in changes else [review(**changes)])
    assert report["status"] == "UNCERTAIN"
    assert report["automatic_rejection"] is False


@pytest.mark.parametrize("fish_id, frame_id, record", [
    (float(FISH_ID), FRAME_ID, review()),
    (FISH_ID, True, review(frame_id=1)),
    (FISH_ID, 1.0, review(frame_id=1)),
])
def test_review_binding_also_validates_current_identity_types(fish_id, frame_id, record):
    report = verify(fish_id=fish_id, frame_id=frame_id, evidence=[record])
    assert report["status"] == "UNCERTAIN"
    assert report["automatic_rejection"] is False


def test_omitted_review_confidence_remains_null_instead_of_inventing_a_score():
    record = review()
    del record["confidence"]
    report = verify(evidence=[record])
    assert report["status"] == "MISSING"
    assert report["parts"]["Head"]["confidence"] is None
    assert report["primary"]["Head"]["confidence"] is None


def test_unavailable_primary_head_body_and_tail_have_null_confidence():
    report = verify({"Head": .9, "Body": .9, "Tail": .9}, model2_available=False)
    for region in ("Head", "Body", "Tail"):
        primary = report["primary"][region]
        assert primary["detected"] is False
        assert primary["confidence"] is None
        assert primary["status"] == "unavailable"
        assert primary["association_valid"] is False
        assert primary["fish_id"] == FISH_ID
        assert primary["frame_id"] == FRAME_ID


@pytest.mark.parametrize("tail, expected_status, expected_confidence", [
    (None, "not_detected", None), (0., "not_detected", None),
    (.1, "below_threshold", .1), (.9, "detected", .9),
])
def test_tail_primary_evidence_is_reported_without_becoming_a_required_region(tail, expected_status, expected_confidence):
    report = verify({"Head": .9, "Body": .9, "Tail": tail}, geometry=ForbiddenGeometry())
    assert report["status"] == "PRESENT"
    assert report["activated"] is False
    assert report["primary"]["Tail"]["status"] == expected_status
    assert report["primary"]["Tail"]["confidence"] == expected_confidence
    assert report["primary"]["Tail"]["detected"] is (expected_status == "detected")
    assert report["primary"]["Tail"]["fish_id"] == FISH_ID
    assert report["primary"]["Tail"]["frame_id"] == FRAME_ID
    assert set(report["parts"]) == {"Head", "Body"}


@pytest.mark.parametrize("changes", [
    {"parent_track_id": FISH_ID + 1}, {"parent_track_id": float(FISH_ID)},
    {"parent_track_id": True}, {"frame_id": "wrong-frame"},
    {"frame_id": True}, {"frame_id": 1.0},
])
def test_silhouette_is_bound_to_the_requested_fish_and_frame(changes):
    mask, parts = synthetic_silhouette("intact", 0)
    metadata = {"parent_isolation_reliable": True, "parent_track_id": FISH_ID,
                "frame_id": 1, **changes}
    geometry = inspect_silhouette(mask, metadata, parts, fish_id=FISH_ID, frame_id=1)
    assert geometry["status"] == "unavailable"
    assert geometry["orientation"] == "UNCERTAIN"
    assert geometry["validated_for_absence"] is False
    assert "mask_identity_mismatch" in geometry["blockers"]


@pytest.mark.parametrize("visibility", [
    {"occluded": True}, {"incomplete_visibility": True},
    {"complete_visibility": False}, {"visibility_validated": False},
])
def test_occluded_or_incomplete_owned_silhouette_cannot_supply_anatomical_claims(visibility):
    mask, parts = synthetic_silhouette("intact", 0)
    geometry = inspect_silhouette(mask, {"parent_isolation_reliable": True,
        "parent_track_id": FISH_ID, "frame_id": FRAME_ID, **visibility}, parts,
        fish_id=FISH_ID, frame_id=FRAME_ID)
    assert geometry["status"] == "unavailable"
    assert geometry["orientation"] == "UNCERTAIN"
    assert geometry["validated_for_absence"] is False
    assert not geometry.get("expected_regions")


@pytest.mark.parametrize("quality", [
    {"frame_id": "stale-frame"}, {"frame_id": True}, {"frame_id": 1.0},
    {"fusion_fish_id": FISH_ID + 1}, {"fusion_fish_id": float(FISH_ID)},
    {"anatomical_input_context": {"fish_id": FISH_ID + 1, "frame_id": 1}},
    {"anatomical_input_context": {"fish_id": FISH_ID, "frame_id": True}},
])
@pytest.mark.parametrize("missing", [(), ("Head",)])
def test_engine_identity_mismatch_blocks_primary_pass_and_reviewed_absence(quality, missing):
    verdict = engine().evaluate(
        FISH_ID, SYNTHETIC_FRAME, engine_parts(missing=missing), stabilize=False,
        frame_id=1, frame_quality=quality, source_context=SOURCE,
        anatomical_evidence=[review(frame_id=1)],
    )
    assert verdict.final_grade is None
    assert verdict.anatomical_verification["status"] == "UNCERTAIN"
    assert verdict.anatomical_verification["automatic_rejection"] is False
    assert verdict.anatomical_verification["fish_id"] == FISH_ID
    assert verdict.anatomical_verification["frame_id"] == 1


def test_quality_adapter_does_not_reuse_same_ndarray_mask_context_for_another_frame_id(monkeypatch):
    from pathlib import Path
    from src.inference.yolo_quality_model import YoloQualityModel

    context, frame, service = candidate_context(monkeypatch)
    assert context.is_for_frame(frame) is True  # Same pixels alone are insufficient.
    calls = []
    original = context.anatomical_candidate
    def record_candidate(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)
    monkeypatch.setattr(context, "anatomical_candidate", record_candidate)
    quality = YoloQualityModel(Path("anatomy-stale-context-test-only.pt"),
        device="cpu", model_id="test-only", grading_engine=engine())
    current_frame_id = "synthetic-frame-2"
    before = (service.frame_calls, service.prompt_calls)
    observation = quality._grade_parts(
        frame, FISH_ID, engine_parts(missing=("Head",)), stabilize=False,
        frame_id=current_frame_id,
        frame_quality={"usable": True, "source_context": SOURCE,
                       "anatomical_evidence": [review(frame_id=current_frame_id)]},
        detection_confidence=.99, parent_bbox=(20., 120., 280., 200.),
        frame_shape=frame.shape, inference_metadata={"crop_bounds": [0, 0, 320, 320]},
        measurement_frame=frame, mask_context=context,
    )
    report = observation.analysis["anatomical_verification"]
    assert observation.quality is None
    assert report["status"] == "UNCERTAIN"
    assert report["automatic_rejection"] is False
    assert report["fish_id"] == FISH_ID
    assert report["frame_id"] == current_frame_id
    assert calls == []
    assert (service.frame_calls, service.prompt_calls) == before


@pytest.mark.parametrize("overlapping", [False, True])
def test_crop_mode_required_parts_need_neighbor_ownership_without_changing_quality_scores(monkeypatch, overlapping):
    from pathlib import Path
    from src.inference.yolo_quality_model import YoloQualityModel

    def forbidden_secondary(*_args, **_kwargs):
        raise AssertionError("Paired primary detections must skip secondary anatomy geometry")
    monkeypatch.setattr("src.inference.yolo_quality_model.inspect_silhouette", forbidden_secondary)
    model = YoloQualityModel(Path("anatomy-crop-overlap-test-only.pt"),
        device="cpu", model_id="test-only", grading_engine=engine())
    observation = model._grade_parts(
        SYNTHETIC_FRAME, FISH_ID, engine_parts(), stabilize=False, frame_id=FRAME_ID,
        frame_quality={"usable": True, "width_context": {"overlapping": overlapping}},
        detection_confidence=.99, parent_bbox=(20., 120., 280., 200.),
        frame_shape=SYNTHETIC_FRAME.shape,
        inference_metadata={"mode": "crop", "crop_bounds": [0, 0, 320, 320]},
    )
    analysis = observation.analysis
    report = analysis["anatomical_verification"]
    assert report["activated"] is False
    assert report["geometry"] == {}
    assert report["automatic_rejection"] is False
    assert all(report["primary"][region]["detected"] for region in ("Head", "Body"))
    expected_scores = {"Class A": pytest.approx(.9), "Class B": 0., "Class C": 0., "Rejected": 0.}
    assert analysis["weighted_scores"] == expected_scores
    assert analysis["effective_weights"] == pytest.approx({"Head": .375, "Body": .625, "Tail": 0.})
    assert analysis["feature_fusion"]["primary_anatomical"]["scores"] == expected_scores
    assert analysis["feature_fusion"]["final_scores"] == expected_scores
    assert report["status"] == ("UNCERTAIN" if overlapping else "PRESENT")
    assert observation.quality == (None if overlapping else "Class A")
    if overlapping:
        assert "UG_ANATOMY_UNCERTAIN" in analysis["reason_codes"]
        assert "association_ambiguous" in report["review_reason"]
        assert all(not report["primary"][region]["association_valid"] for region in ("Head", "Body"))
