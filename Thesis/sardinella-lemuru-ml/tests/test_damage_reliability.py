"""Controlled image evidence tests, not validation on labeled real fish."""

import json

import cv2
import numpy as np
import pytest

from src.features.damage import analyze_surface_damage
from src.preprocessing.scientific_image_utils import PreprocessingError


def scene():
    image = np.full((120, 180, 3), 150, dtype=np.uint8)
    mask = np.zeros(image.shape[:2], dtype=bool)
    mask[10:-10, 10:-10] = True
    return image, mask


def line_scene():
    image, mask = scene()
    cv2.line(image, (30, 35), (145, 85), (20, 20, 20), 3)
    return image, mask


def assert_no_evidence(result, *, status="not_detected"):
    assert result["status"] == status
    assert result["label"] == result["evidence_state"] == "No reliable evidence"
    assert result["confidence"] is None
    assert result["estimated_length_px"] is None
    assert result["locations"] == []
    assert not result["overlay_mask"].any()


def test_single_isolated_line_has_original_rgb_support_and_native_pixel_extent():
    image, mask = line_scene()
    result = analyze_surface_damage(image, mask)
    assert result["status"] == "suspected"
    assert result["label"] == result["evidence_state"] == "Suspected Damage"
    assert result["coordinate_space"] == "crop_local_pixels"
    # Reference is the known drawn line; the support includes the stroke caps.
    reference_length = np.hypot(145 - 30, 85 - 35)
    assert abs(result["estimated_length_px"] - reference_length) / reference_length < 0.08
    assert len(result["locations"]) == 1
    location = result["locations"][0]
    assert location["original_rgb_support_fraction"] >= 0.6
    assert location["original_rgb_contrast_255"] == 130.0
    overlay = result["overlay_mask"] > 0
    assert np.all(mask[overlay])
    assert np.all(image[overlay] == 20)
    for x, y in location["endpoints"]:
        assert overlay[y, x]
        assert location["x"] <= x < location["x"] + location["width"]
        assert location["y"] <= y < location["y"] + location["height"]


def test_clear_limits_and_no_grading_or_validated_severity_claims():
    image, mask = line_scene()
    for image in (image, np.full_like(image, 150)):
        result = analyze_surface_damage(image, mask)
        assert result["validation_status"] == "unvalidated"
        assert result["mask_validated_for_cracks"] is False
        assert result["confidence_calibrated"] is False
        assert result["confidence_kind"] == "heuristic_not_probability"
        assert result["severity"] == "unassessed"
        assert result["grade_adjustment"] == 0.0
        assert "not_full_crack_length" in result["length_method"]
        assert result["label"] != "Validated Damage"


@pytest.mark.parametrize("kind", ["shadow_step", "broad_dark_band", "boundary", "scales", "repeated_bands", "bright_line"])
def test_controlled_nuisance_patterns_do_not_become_damage(kind):
    image, mask = scene()
    if kind == "shadow_step":
        image[:, 90:] = 70
    elif kind == "broad_dark_band":
        image[:, 65:110] = 20
    elif kind == "boundary":
        cv2.line(image, (11, 20), (11, 100), (0, 0, 0), 3)
    elif kind == "scales":
        for y in range(25, 100, 12):
            for x in range(25, 160, 12):
                cv2.circle(image, (x, y), 3, (60, 60, 60), 1)
    elif kind == "repeated_bands":
        for y in (30, 60, 90):
            cv2.line(image, (30, y), (145, y), (20, 20, 20), 3)
    elif kind == "bright_line":
        cv2.line(image, (30, 35), (145, 85), (245, 245, 245), 3)
    result = analyze_surface_damage(image, mask)
    assert_no_evidence(result)
    if kind == "repeated_bands":
        assert result["rejection_counts"]["repeated_parallel_texture"] == 3


def test_background_does_not_change_inside_mask_evidence_or_expand_mask():
    image, mask = line_scene()
    original_mask = mask.copy()
    other = image.copy()
    other[~mask] = np.random.default_rng(2).integers(0, 256, size=(int((~mask).sum()), 3), dtype=np.uint8)
    first = analyze_surface_damage(image, mask)
    second = analyze_surface_damage(other, mask)
    np.testing.assert_array_equal(mask, original_mask)
    np.testing.assert_array_equal(first.pop("overlay_mask"), second.pop("overlay_mask"))
    assert first == second


@pytest.mark.parametrize("flag", ["overlapping", "ambiguous", "clipped", "partially_visible"])
def test_known_ambiguous_parent_abstains_despite_visible_line(flag):
    image, mask = line_scene()
    result = analyze_surface_damage(image, mask, parent_context={flag: True})
    assert_no_evidence(result, status="unavailable")
    assert result["reasons"]
    assert result["parent_context"][flag] is True


@pytest.mark.parametrize("metadata", [{"validation_passed": False}, {"valid": False}, {"status": "unavailable"}])
def test_explicitly_rejected_mask_abstains(metadata):
    image, mask = line_scene()
    assert_no_evidence(analyze_surface_damage(image, mask, mask_metadata=metadata), status="unavailable")


def test_foreground_feature_validation_never_implies_crack_validation():
    image, mask = line_scene()
    result = analyze_surface_damage(image, mask, mask_metadata={"status": "validated_for_features"})
    assert result["status"] == "suspected"
    assert result["validation_status"] == "unvalidated"
    assert result["mask_validated_for_cracks"] is False


def test_empty_and_thin_masks_have_honest_missing_evidence():
    image, mask = scene()
    assert_no_evidence(analyze_surface_damage(image, np.zeros_like(mask)), status="unavailable")
    mask[:] = False
    mask[30:35, 25:150] = True
    assert_no_evidence(analyze_surface_damage(image, mask), status="unavailable")


def test_normalized_float_rgb_matches_uint8_and_payload_is_json_safe():
    image, mask = line_scene()
    integer_result = analyze_surface_damage(image, mask)
    float_result = analyze_surface_damage(image.astype(np.float64) / 255.0, mask)
    np.testing.assert_array_equal(integer_result.pop("overlay_mask"), float_result.pop("overlay_mask"))
    assert integer_result == float_result
    assert len(integer_result["locations"]) <= 12
    json.dumps(integer_result, allow_nan=False)


@pytest.mark.parametrize("kind", ["four_channels", "nan_rgb", "out_of_range_rgb", "nan_mask"])
def test_invalid_rgb_or_mask_is_explicitly_rejected(kind):
    image, mask = scene()
    if kind == "four_channels":
        image = np.zeros((*mask.shape, 4), dtype=np.uint8)
    elif kind == "nan_rgb":
        image = image.astype(float) / 255.0
        image[0, 0, 0] = np.nan
    elif kind == "out_of_range_rgb":
        image = image.astype(float)
    else:
        mask = mask.astype(float)
        mask[0, 0] = np.nan
    with pytest.raises(PreprocessingError):
        analyze_surface_damage(image, mask)
