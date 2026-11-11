"""Independent head review explains all gates without borrowing anatomy."""

from copy import deepcopy
from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from test_head_integrity import assess, ownership, specimen
from src.inference.association import ParentAnchor
from src.inference.fish_geometry import FishGeometryConfig
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.head_integrity import apply_head_integrity
from src.inference.part_types import PartDetection
from src.inference.preprocessing import RuntimeMaskContext
from src.inference.yolo_quality_model import YoloQualityModel


def gates(report):
    return {row["gate"]: row for row in report["rejection_gates"]}


def test_confirmed_removal_has_independent_gates_and_preserves_ungraded_trace():
    mask, parts = specimen()
    report = assess(mask, parts)
    assert report["classification"] == "confirmed_absent"
    assert all(row["passed"] for row in report["rejection_gates"])
    assert report["terminal_width_ratio"] > 0
    assert report["truncation_evidence"]
    assert report["orientation_confidence"]["polarity_reliable"]
    assert report["head_detection_status"]["missing_detection_proves_absence"] is False
    analysis = {"final_grade": "Ungraded", "final_score": .8, "final_support": .8, "reason_codes": ["UG_MISSING_HEAD"],
                "verdict_reason_code": "UG_MISSING_HEAD", "verdict_reason_text": "Head not detected."}
    assert apply_head_integrity(analysis, "Ungraded", report) == "Rejected"
    assert analysis["head_integrity"]["quality_grading_before_integrity"]["reason_codes"] == ["UG_MISSING_HEAD"]
    assert analysis["head_integrity"]["quality_grading_before_integrity"]["final_score"] == .8
    assert analysis["final_score"] is analysis["final_support"] is None
    json.dumps(analysis, allow_nan=False)


def test_all_failures_are_visible_even_when_detector_is_unavailable():
    mask, parts = specimen()
    metadata = ownership()
    metadata["ownership"].update(mask_geometry_checks_passed=False, conflicting_parent_ids=[2],
        reasons=["overlapping_mask_ownership_conflict", "mask_touches_frame_boundary"])
    report = assess(mask, parts, model2_available=False, clipped=True,
                    overlapping=True, association_reliable=False, mask_metadata=metadata)
    assert report["decision_reason"] == "model2_unavailable"
    for name in ("model2_available", "mask_ownership", "no_mask_contamination", "native_frame_complete", "part_association"):
        assert not gates(report)[name]["passed"]
    assert report["used_for_grading"] is False


def test_positive_eligibility_summary_cannot_override_failed_ownership():
    mask, parts = specimen()
    metadata = ownership(head_integrity_eligibility={"eligible": True})
    metadata["ownership"]["mask_geometry_checks_passed"] = False
    metadata["ownership"]["reasons"].append("overlapping_mask_ownership_conflict")
    report = assess(mask, parts, mask_metadata=metadata)
    assert report["grade_effect"] == "none"
    assert not gates(report)["mask_ownership"]["passed"]


def test_positive_summary_cannot_replace_missing_ownership_checks():
    mask, parts = specimen()
    report = assess(mask, parts, mask_metadata={"backend": "mobilesam_experimental",
                    "head_integrity_eligibility": {"eligible": True}})
    assert report["grade_effect"] == "none"
    assert report["ownership_gap"] == "ownership_not_recorded"


@pytest.mark.parametrize("confidence,expected", [(.001, "reject"), (.05, "reject"), (.249, "reject"), (.25, "none")])
def test_debug_only_head_candidates_cannot_change_anatomical_verdict(confidence, expected):
    mask, parts = specimen()
    candidate = PartDetection.from_source_class(1, confidence, (110, 120, 150, 160))
    ordinary = assess(mask, parts)
    debug = assess(mask, parts, unassigned_heads=[candidate])
    assert ordinary["grade_effect"] == "reject"
    assert debug["grade_effect"] == expected
    if confidence < .25:
        assert debug["head_detection_status"]["diagnostic_only_head_intersects"] is True
        assert debug["head_detection_status"]["diagnostic_candidates_affect_grading"] is False


def test_raw_head_evidence_respects_a_higher_configured_detector_threshold():
    mask, parts = specimen()
    raw = PartDetection.from_source_class(1, .4, (110, 120, 150, 160))
    report = assess(mask, parts, unassigned_heads=[raw], minimum_candidate_head_confidence=.5)
    assert report["grade_effect"] == "reject"
    assert report["head_detection_status"]["candidate_evidence_threshold"] == .5


def test_accepted_head_whose_pixels_disagree_with_mask_prevents_geometry_rejection():
    mask, _ = specimen()
    head = PartDetection.from_source_class(1, .9, (60, 110, 100, 170),
                                           mask=((1, 1), (10, 1), (10, 10)))
    report = assess(mask, [head])
    assert report["measurements"]["head_pixels"] == 0
    assert report["grade_effect"] == "none"
    assert not gates(report)["no_owned_head"]["passed"]


def test_crowded_native_torso_can_support_head_integrity_without_fabricated_body_detection():
    mask, parts = specimen()
    metadata = ownership()
    metadata["ownership"]["reasons"].append("required_body_evidence_unavailable")
    report = assess(mask, [], overlapping=True, mask_metadata=metadata)
    assert report["classification"] == "confirmed_absent", report
    assert report["body_support"]["source"] == "silhouette_torso_geometry"
    assert report["measurements"]["body_pixels"] == 0
    assert report["measurements"]["head_to_body_size_ratio"] is None
    assert report["body_support"]["geometric_torso"]["model2_body_pixels_synthesized"] is False


@pytest.mark.parametrize("failure", ["overlapping_mask_ownership_conflict", "mask_touches_frame_boundary",
                                     "candidate_omits_detected_head_region", "required_anatomical_ownership_ambiguous"])
def test_geometry_torso_never_waives_occlusion_ownership_or_head_conflicts(failure):
    mask, _ = specimen()
    metadata = ownership()
    metadata["ownership"]["reasons"].extend(["required_body_evidence_unavailable", failure])
    report = assess(mask, [], mask_metadata=metadata)
    assert report["grade_effect"] == "none"
    assert not report["mask_eligibility"]["eligible"]


def test_explicit_native_clipping_overrules_an_interior_candidate():
    mask, parts = specimen()
    report = assess(mask, parts, clipped=False, mask_metadata=ownership(explicit_native_clipping=True))
    assert report["classification"] == "ungraded_out_of_frame"
    assert not gates(report)["native_frame_complete"]["passed"]


def test_multiple_owned_head_detections_cannot_be_mistaken_for_absence():
    mask, parts = specimen()
    parts.extend([PartDetection.from_source_class(1, .9, (65, 115, 90, 165)),
                  PartDetection.from_source_class(4, .8, (68, 116, 92, 164))])
    report = assess(mask, parts)
    assert report["grade_effect"] == "none"
    assert report["decision_reason"] == "owned_head_evidence_not_separable"
    assert not gates(report)["no_owned_head"]["passed"]


@pytest.mark.parametrize("reason", ["source_frame_unusable", "parent_detection_unreliable", "source_crop_pixels_mismatch"])
def test_independent_path_preserves_source_reliability_safeguards(reason):
    mask, parts = specimen()
    report = assess(mask, parts, mask_metadata=ownership(context_reliability_reasons=[reason]))
    assert report["classification"] == "unverified_source"
    assert report["grade_effect"] == "none"
    assert not gates(report)["source_context"]["passed"]


def test_tail_at_body_center_cannot_establish_headless_orientation():
    mask, parts = specimen()
    parts = [part for part in parts if part.region != "Tail"]
    parts.append(PartDetection.from_source_class(2, .95, (110, 120, 150, 160)))
    report = assess(mask, parts)
    assert report["cut_end_confirmed"] is True
    assert report["grade_effect"] == "none"
    assert "tail_body_polarity_uncertain" in report["polarity_conflicts"]
    assert not gates(report)["tail_polarity"]["passed"]


def test_crop_truncation_is_reported_separately_from_frame_clipping():
    mask, parts = specimen()
    metadata = ownership()
    metadata["ownership"].update(mask_geometry_checks_passed=False,
        reasons=["required_head_evidence_unavailable", "analysis_crop_truncates_silhouette"])
    report = assess(mask, parts, mask_metadata=metadata)
    assert report["classification"] == "unverified_crop_truncation"
    assert gates(report)["native_frame_complete"]["passed"]
    assert not gates(report)["analysis_crop_complete"]["passed"]


def test_tail_only_ambiguity_does_not_veto_independent_body_and_silhouette():
    tail = {"ambiguous": True, "parts": [{"status": "AMBIGUOUS", "part": {"region": "Tail"}}]}
    assert YoloQualityModel._head_integrity_association_reliable(tail)
    for region in ("Head", "Body", None):
        summary = deepcopy(tail)
        summary["parts"][0]["part"]["region"] = region
        assert not YoloQualityModel._head_integrity_association_reliable(summary)
    assert not YoloQualityModel._head_integrity_association_reliable({"ambiguous": True})


@pytest.mark.parametrize("explicit_native_clipping,expected", [(False, "Rejected"), (True, "Ungraded")])
def test_native_fallback_disproves_only_bbox_clipping(explicit_native_clipping, expected):
    mask, parts = specimen()
    metadata = ownership()
    metadata["ownership"]["metrics"] = {
        "mask_touches_frame_boundary": False, "foreground_bbox": [70, 115, 251, 166]}
    metadata.update(crop_bounds=[0, 0, 280, 280], native_frame_shape=[280, 280])
    context = SimpleNamespace(head_integrity_mask=lambda *_: (mask, metadata))
    model = SimpleNamespace(_fish_geometry_config=FishGeometryConfig(),
                            _grading_engine=SimpleNamespace(config=SimpleNamespace(minimum_part_confidence=.25)))
    analysis = {"fish_id": 1, "final_grade": "Ungraded", "reason_codes": ["UG_MISSING_HEAD"]}
    result = YoloQualityModel._apply_head_integrity(model, analysis, "Ungraded", parts, None,
        {"clipped": True, "parent_bbox_frame_contact": True, "explicit_native_clipping": explicit_native_clipping},
        inference_metadata={}, bounds=[0, 0, 280, 280], model2_available=True, model2_failed=False,
        overlapping=False, clipped=True, association_reliable=True, mask_context=context)
    assert result == expected


def test_strict_existing_centerline_safeguard_withholds_terminal_inference():
    mask, parts = specimen(angle=45)
    report = assess(mask, parts, config=FishGeometryConfig(maximum_centerline_tortuosity=1.0))
    assert report["measurements"]["centerline_quality"]["centerline_tortuosity"] > 1.0
    assert report["grade_effect"] == "none"
    assert not gates(report)["centerline_geometry"]["passed"]


def test_full_frame_independent_path_rejects_with_owned_body_and_no_gradeable_head(monkeypatch):
    mask, parts = specimen()
    body = next(part for part in parts if part.region == "Body")
    frame = np.random.default_rng(42).integers(30, 220, (*mask.shape, 3), dtype=np.uint8)

    class Service:
        @contextmanager
        def open_frame(self, source, key):
            self.key = key
            yield self

        def predict(self, parent, box, **options):
            return {"status": "candidate", "parent_id": parent, "mask": mask.astype(bool), "score": .99,
                "provenance": {"backend": "mobilesam_experimental", "parent_id": parent,
                    "frame_key": self.key, "coordinate_space": "original_frame", "mask_shape": list(mask.shape),
                    "original_bbox_global": list(box), "prompt_bbox_global": list(box)}}

        def diagnostics(self):
            return {}

    model = YoloQualityModel(Path("fixture-head-integrity.pt"), device="cpu", model_id="integrity-test",
        quality_inference_mode="full_frame", grading_engine=WeightedGradingEngine(GradingConfig(
            grading_mode="tail_optional_v1", image_diagnostics_enabled=False)))
    model.model = object()
    model._infer_parts = lambda _: ([body], [body])
    monkeypatch.setattr("src.inference.mobilesam_backend.get_mobilesam_service", lambda: Service())
    masks = RuntimeMaskContext(frame, frame_id="independent", backend="mobilesam_experimental")
    observations = model.predict_full_frame(frame, [ParentAnchor(1, (55, 100, 265, 180), .99)],
        stabilize=False, frame_id="independent", mask_context=masks)
    result = observations[1][0]
    assert result.quality == "Rejected"
    assert result.quality_confidence is None
    report = result.analysis["head_integrity"]
    assert report["quality_grading_before_integrity"]["grade"] == "Ungraded"
    assert report["classification"] == "confirmed_absent"
    assert report["failed_rejection_gates"] == []
    assert result.analysis["weighted_scores"] == {"Class A": .475, "Class B": 0., "Class C": 0., "Rejected": 0.}
    json.dumps(result.analysis, allow_nan=False)
