"""Software geometry checks; synthetic silhouettes are not fish validation data."""

from dataclasses import replace
import json

import cv2
import numpy as np
import pytest

from src.inference.fish_geometry import (
    FishGeometryConfig,
    PhysicalCalibration,
    load_fish_geometry_config,
    load_physical_calibration,
    measure_fish_geometry,
)
from src.inference.part_types import PartDetection


def ellipse_case(angle=0):
    mask = np.zeros((240, 240), np.uint8)
    cv2.ellipse(mask, (120, 120), (80, 25), angle, 0, 360, 1, -1)
    radians = np.deg2rad(angle)
    axis = np.array((np.cos(radians), np.sin(radians)))
    normal = np.array((-axis[1], axis[0]))
    corners = np.array([np.array((120, 120)) + axis * x + normal * y
                        for x in (-35, 35) for y in (-26, 26)])
    body_box = (*corners.min(axis=0), *corners.max(axis=0))
    body = PartDetection.from_source_class(0, 0.95, body_box)
    # Source class zero is Body A in the canonical dataset.
    assert body.region == "Body"
    ys, xs = np.nonzero(mask)
    parent = (float(xs.min() + 97), float(ys.min() + 97),
              float(xs.max() + 104), float(ys.max() + 104))
    kwargs = dict(parent_bbox=parent, crop_bounds=(100, 100, 340, 340),
                  frame_shape=(500, 500, 3), association_reliable=True)
    return mask, [body], kwargs


@pytest.mark.parametrize("angle", (0, 15, 30, 45, 60, 75, 90, 120, 165))
def test_ellipse_rotations_measure_full_silhouette_not_skeleton_or_aabb(angle):
    mask, parts, kwargs = ellipse_case(angle)
    result = measure_fish_geometry(mask, parts, **kwargs)
    assert result["status"] == "measured", result
    assert result["fish_length_px"] == pytest.approx(161, abs=3)
    assert result["max_body_width_px"] == pytest.approx(51, abs=3)
    assert result["relative_width_ratio"] == pytest.approx(51 / 161, abs=0.02)
    difference = abs(result["orientation_degrees"] - angle % 180)
    assert min(difference, 180 - difference) < 1
    assert result["candidate_measurements"]["profile_bin_width_px"] == 1
    assert result["measurement_validated"] is False
    assert result["used_for_grading"] is False
    assert result["fish_length_cm"] is None
    assert result["max_body_width_cm"] is None


def test_body_region_excludes_wider_head_and_uses_mask_not_body_box_height():
    mask = np.zeros((240, 240), np.uint8)
    polygon = np.array([(20, 120), (50, 85), (85, 105), (200, 110),
                        (220, 120), (200, 130), (85, 135), (50, 155)])
    cv2.fillPoly(mask, [polygon], 1)
    body = PartDetection.from_source_class(0, 0.9, (100, 95, 190, 145))
    result = measure_fish_geometry(mask, [body], parent_bbox=(117, 182, 324, 259),
                                   crop_bounds=(100, 100, 340, 340), frame_shape=(500, 500),
                                   association_reliable=True)
    assert result["status"] == "measured", result
    assert result["fish_length_px"] == pytest.approx(201, abs=2)
    assert 26 <= result["max_body_width_px"] <= 31
    assert result["max_body_width_px"] < body.bbox[3] - body.bbox[1]


@pytest.mark.parametrize("angle", (0, 30, 60, 90))
def test_capsule_length_includes_both_blunt_tips(angle):
    straight = np.zeros((240, 240), np.uint8)
    cv2.rectangle(straight, (60, 95), (180, 145), 1, -1)
    cv2.circle(straight, (60, 120), 25, 1, -1)
    cv2.circle(straight, (180, 120), 25, 1, -1)
    transform = cv2.getRotationMatrix2D((120, 120), -angle, 1)
    mask = cv2.warpAffine(straight, transform, (240, 240), flags=cv2.INTER_NEAREST)
    _, parts, kwargs = ellipse_case(angle)
    ys, xs = np.nonzero(mask)
    kwargs["parent_bbox"] = (xs.min() + 97, ys.min() + 97, xs.max() + 104, ys.max() + 104)
    result = measure_fish_geometry(mask, parts, **kwargs)
    assert result["status"] == "measured", result
    assert result["fish_length_px"] == pytest.approx(171, abs=3)
    assert result["max_body_width_px"] == pytest.approx(51, abs=3)


@pytest.mark.parametrize("gate, reason", [
    ({"overlapping": True}, "overlapping_parent_fish"),
    ({"association_reliable": False}, "parent_association_uncertain"),
    ({"parent_bbox": (0, 190, 304, 250)}, "parent_touches_frame_boundary"),
    ({"crop_bounds": (100, 100, 300, 340)}, "mask_crop_dimensions_mismatch"),
    ({"mask_metadata": {"foreground_touches_initialization_boundary": True}}, "silhouette_may_be_truncated"),
    ({"mask_metadata": {"raw_second_component_fraction": 0.25, "raw_component_count": 2}}, "multiple_foreground_components"),
])
def test_unreliable_geometry_retains_candidates_but_withholds_measurements(gate, reason):
    mask, parts, kwargs = ellipse_case()
    original = mask.copy()
    kwargs.update(gate)
    result = measure_fish_geometry(mask, parts, **kwargs)
    assert result["status"] == "unreliable"
    assert reason in result["reasons"]
    assert result["candidate_measurements"]["fish_length_px"] > 150
    for name in ("fish_length_px", "max_body_width_px", "relative_width_ratio", "fish_length_cm", "max_body_width_cm"):
        assert result[name] is None
    assert result["used_for_grading"] is False
    np.testing.assert_array_equal(mask, original)


def test_disconnected_second_fish_is_not_silently_discarded():
    mask, parts, kwargs = ellipse_case()
    cv2.ellipse(mask, (120, 50), (40, 12), 0, 0, 360, 1, -1)
    result = measure_fish_geometry(mask, parts, **kwargs)
    assert "multiple_foreground_components" in result["reasons"]
    assert result["fish_length_px"] is None
    assert result["candidate_measurements"]["component_count"] == 2


def test_discarded_many_small_components_cannot_bypass_single_instance_quality_gate():
    mask, parts, kwargs = ellipse_case()
    result = measure_fish_geometry(mask, parts, mask_metadata={"raw_component_count": 8,
                                   "raw_largest_component_fraction": 0.90,
                                   "raw_second_component_fraction": 0.015}, **kwargs)
    assert "multiple_foreground_components" in result["reasons"]
    assert result["fish_length_px"] is None


@pytest.mark.parametrize("fraction", [-1, 1.01, float("nan"), "bad"])
def test_malformed_component_fractions_are_withheld(fraction):
    mask, parts, kwargs = ellipse_case()
    result = measure_fish_geometry(mask, parts, mask_metadata={"raw_largest_component_fraction": fraction}, **kwargs)
    assert "invalid_component_metadata" in result["reasons"]
    assert result["fish_length_px"] is None
    json.dumps(result, allow_nan=False)


def test_crop_contact_is_detected_separately_from_parent_frame_clipping():
    mask, parts, kwargs = ellipse_case()
    mask[0:96, 119:122] = 1
    result = measure_fish_geometry(mask, parts, **kwargs)
    assert "silhouette_touches_crop_boundary" in result["reasons"]
    assert "parent_touches_frame_boundary" not in result["reasons"]


def test_orientation_ambiguous_round_mask_is_withheld():
    mask, parts, kwargs = ellipse_case()
    mask[:] = 0
    cv2.circle(mask, (120, 120), 24, 1, -1)
    result = measure_fish_geometry(mask, parts, **kwargs)
    assert "orientation_uncertain" in result["reasons"]
    assert result["fish_length_px"] is None


def test_bent_mask_requires_a_separately_validated_curvilinear_method():
    mask, parts, kwargs = ellipse_case()
    mask[:] = 0
    points = np.array([(x, 100 + int(0.008 * (x - 120) ** 2)) for x in range(40, 201)])
    cv2.polylines(mask, [points], False, 1, 22)
    kwargs["parent_bbox"] = (120, 180, 320, 280)
    result = measure_fish_geometry(mask, parts, **kwargs)
    assert "curved_silhouette_requires_validated_centerline" in result["reasons"]
    assert result["fish_length_px"] is None


def test_large_segmentation_hole_is_withheld():
    mask, parts, kwargs = ellipse_case()
    cv2.circle(mask, (120, 120), 12, 0, -1)
    result = measure_fish_geometry(mask, parts, **kwargs)
    assert "segmentation_has_large_holes" in result["reasons"]


def test_foreign_body_cannot_supply_width():
    mask, _, kwargs = ellipse_case()
    foreign = PartDetection.from_source_class(0, 0.9, (5, 5, 40, 35))
    result = measure_fish_geometry(mask, [foreign], **kwargs)
    assert result["status"] == "unreliable"
    assert "body_outside_parent" in result["reasons"]
    assert "insufficient_associated_body_profile" in result["reasons"]
    assert result["max_body_width_px"] is None


def test_silhouette_must_belong_to_the_declared_parent_not_just_intersect_body():
    mask, parts, kwargs = ellipse_case()
    kwargs["parent_bbox"] = (180, 190, 250, 250)
    result = measure_fish_geometry(mask, parts, **kwargs)
    assert "foreground_outside_parent" in result["reasons"]
    assert result["fish_length_px"] is None


def test_explicit_foreign_mask_parent_id_is_withheld():
    mask, parts, kwargs = ellipse_case()
    result = measure_fish_geometry(mask, parts, mask_metadata={"expected_parent_id": 7, "instance_id": 8}, **kwargs)
    assert "mask_parent_mismatch" in result["reasons"]
    assert result["max_body_width_px"] is None


def test_conflicting_body_instances_are_withheld():
    mask, parts, kwargs = ellipse_case()
    parts.append(PartDetection.from_source_class(0, 0.85, (150, 95, 195, 145)))
    result = measure_fish_geometry(mask, parts, **kwargs)
    assert "multiple_body_associations" in result["reasons"]
    assert result["relative_width_ratio"] is None


def test_body_instance_segmentation_is_used_when_present():
    mask, parts, kwargs = ellipse_case()
    polygon = ((90, 105), (150, 105), (150, 135), (90, 135))
    parts[0] = replace(parts[0], mask=polygon)
    result = measure_fish_geometry(mask, parts, **kwargs)
    assert result["status"] == "measured", result
    assert result["body_region_source"] == "associated_body_segmentation"
    assert result["max_body_width_px"] == pytest.approx(31, abs=1)


@pytest.mark.parametrize("bad_mask", [None, [], np.zeros((5, 5)), np.zeros((25, 25, 3)),
                                      np.full((25, 25), np.nan)])
def test_missing_or_invalid_segmentation_never_falls_back_to_box_measurements(bad_mask):
    _, parts, kwargs = ellipse_case()
    result = measure_fish_geometry(bad_mask, parts, **kwargs)
    assert result["status"] == "unavailable"
    assert result["fish_length_px"] is None
    assert result["max_body_width_px"] is None
    assert result["used_for_grading"] is False


def test_no_body_detection_does_not_invent_an_anatomical_body_region():
    mask, _, kwargs = ellipse_case()
    result = measure_fish_geometry(mask, [], **kwargs)
    assert "associated_body_region_unavailable" in result["reasons"]
    assert result["max_body_width_px"] is None
    assert "fish_length_px" in result["candidate_measurements"]


@pytest.mark.parametrize("gate,reason", [
    ({"overlapping": True}, "overlapping_parent_fish"),
    ({"parent_bbox": (0, 190, 304, 250)}, "parent_touches_frame_boundary"),
    ({"mask_metadata": {"clipped": True}}, "segmentation_reported_clipped"),
    ({"mask_metadata": {"expected_parent_id": 7, "parent_track_id": 8}}, "mask_parent_mismatch"),
])
def test_missing_mask_preserves_known_overlap_clipping_or_ownership_problem(gate, reason):
    _, parts, kwargs = ellipse_case()
    kwargs.update(gate)
    result = measure_fish_geometry(None, parts, **kwargs)
    assert result["status"] == "unreliable"
    assert reason in result["reasons"]
    assert "per_fish_segmentation_unavailable" in result["reasons"]
    assert result["fish_length_px"] is None


@pytest.mark.parametrize("with_mask", [True, False])
def test_parent_quality_risks_are_preserved_even_when_no_segmentation_exists(with_mask):
    mask, parts, kwargs = ellipse_case()
    result = measure_fish_geometry(mask if with_mask else None, parts,
                                   mask_metadata={"context_reliability_reasons": ["parent_uncertain", "low_parent_confidence"]},
                                   **kwargs)
    assert result["status"] == "unreliable"
    assert "parent_uncertain" in result["reasons"]
    assert "low_parent_confidence" in result["reasons"]
    assert result["fish_length_px"] is None


def test_thin_segmentation_artifact_cannot_be_reported_as_reliable_fish():
    mask, parts, kwargs = ellipse_case()
    mask[:] = 0
    mask[119:121, 40:201] = 1
    result = measure_fish_geometry(mask, parts, **kwargs)
    assert "insufficient_transverse_resolution" in result["reasons"]
    assert result["max_body_width_px"] is None


def test_feature_mask_status_does_not_claim_measurement_validation():
    mask, parts, kwargs = ellipse_case()
    result = measure_fish_geometry(mask, parts, mask_metadata={"status": "validated_for_features"}, **kwargs)
    assert result["status"] == "measured"
    assert result["measurement_validated"] is False
    assert result["measurement_validation_status"] == "Not validated"
    assert result["used_for_grading"] is False


def calibration():
    return PhysicalCalibration(validated=True, calibration_id="reviewed-ruler-2026-11",
                               pixels_per_cm=10, reference_frame_size=(500, 500),
                               source_id="fixed-camera-and-plane-1")


def test_centimeters_require_reviewed_scale_and_matching_acquisition_context():
    mask, parts, kwargs = ellipse_case()
    result = measure_fish_geometry(mask, parts, physical_calibration=calibration(),
                                   source_context="fixed-camera-and-plane-1", **kwargs)
    assert result["physical_calibration"]["status"] == "Applied"
    assert result["physical_calibration"]["validated"] is True
    assert result["physical_calibration"]["applied"] is True
    assert result["fish_length_cm"] == pytest.approx(result["fish_length_px"] / 10)
    assert result["max_body_width_cm"] == pytest.approx(result["max_body_width_px"] / 10)
    assert result["measurement_validated"] is False
    assert result["used_for_grading"] is False


@pytest.mark.parametrize("cal,source", [
    (replace(calibration(), validated=False), "fixed-camera-and-plane-1"),
    (replace(calibration(), pixels_per_cm=None), "fixed-camera-and-plane-1"),
    (replace(calibration(), pixels_per_cm=0), "fixed-camera-and-plane-1"),
    (replace(calibration(), calibration_id=None), "fixed-camera-and-plane-1"),
    (replace(calibration(), reference_frame_size=(1000, 1000)), "fixed-camera-and-plane-1"),
    (calibration(), "another-camera-or-plane"),
    (calibration(), None),
])
def test_incomplete_unvalidated_or_mismatched_calibration_never_converts(cal, source):
    mask, parts, kwargs = ellipse_case()
    result = measure_fish_geometry(mask, parts, physical_calibration=cal, source_context=source, **kwargs)
    assert result["status"] == "measured"
    assert result["physical_calibration"]["validated"] is False
    assert result["physical_calibration"]["applied"] is False
    assert result["fish_length_cm"] is None
    assert result["max_body_width_cm"] is None


def test_valid_scale_does_not_convert_unreliable_geometry():
    mask, parts, kwargs = ellipse_case()
    result = measure_fish_geometry(mask, parts, overlapping=True,
                                   physical_calibration=calibration(),
                                   source_context="fixed-camera-and-plane-1", **kwargs)
    assert result["fish_length_cm"] is None
    assert result["physical_calibration"]["status"] != "Applied"
    assert result["physical_calibration"]["applied"] is False


@pytest.mark.parametrize("bad_scale,bad_resolution", [
    (True, [500, 500]), (float("nan"), [500, 500]), (float("inf"), [500, 500]),
    ("10", [500, 500]), (10, [500.9, 500]), (10, [True, 500]),
])
def test_malformed_physical_reference_is_not_coerced_to_a_validated_scale(bad_scale, bad_resolution):
    mask, parts, kwargs = ellipse_case()
    physical = {"validated": True, "calibration_id": "ref", "pixels_per_cm": bad_scale,
                "reference_frame_size": bad_resolution, "source_id": "camera"}
    result = measure_fish_geometry(mask, parts, physical_calibration=physical, source_context="camera", **kwargs)
    assert result["physical_calibration"]["validated"] is False
    assert result["fish_length_cm"] is None
    json.dumps(result, allow_nan=False)


def test_default_configuration_has_no_physical_calibration_or_grading_switch():
    assert load_fish_geometry_config() == FishGeometryConfig()
    physical = load_physical_calibration()
    assert physical.validated is False
    assert physical.pixels_per_cm is None
    assert not hasattr(load_fish_geometry_config(), "scoring_enabled")


def test_output_is_strict_json_serializable():
    mask, parts, kwargs = ellipse_case()
    result = measure_fish_geometry(mask, parts, **kwargs)
    json.dumps(result, allow_nan=False)
