"""Native overlay provenance checks; synthetic fixtures do not validate fish."""

import json

import cv2
import numpy as np
import pytest

from src.features.damage import analyze_surface_damage
from src.inference.fish_geometry import measure_fish_geometry
from src.inference.frame_diagnostics import parent_damage
from src.inference.part_types import PartDetection
from src.inference.preprocessing import CropBounds, RuntimeMaskContext


def geometry_case(angle=0, *, estimated=False, with_body=True, offset=(103, 67)):
    mask = np.zeros((240, 240), np.uint8)
    cv2.ellipse(mask, (120, 120), (80, 25), angle, 0, 360, 1, -1)
    body = PartDetection.from_source_class(0, .95, (82, 82, 158, 158))
    x, y = offset
    metadata = {"frame_id": "recorded-frame-8", "expected_parent_id": 7, "parent_track_id": 7}
    if estimated:
        metadata.update(experimental=True, sampling={"estimated": True, "mode": "mobilesam_candidate"})
    return mask, [body] if with_body else [], dict(
        parent_bbox=(x + 15, y + 15, x + 225, y + 225),
        crop_bounds=(x, y, x + 240, y + 240), frame_shape=(450, 500, 3),
        association_reliable=True, mask_metadata=metadata,
    )


@pytest.mark.parametrize("angle", (0, 30, 75, 90, 135))
def test_estimated_mobilesam_overlay_uses_actual_profile_with_original_frame_origin(angle):
    mask, parts, kwargs = geometry_case(angle, estimated=True)
    geometry = measure_fish_geometry(mask, parts, **kwargs)
    visual = geometry["candidate_visualization"]
    assert geometry["fish_length_px"] is None and not geometry.get("visualization")
    assert not geometry["used_for_grading"] and not visual["used_for_grading"]
    assert visual["status"] == "estimated" and visual["measured"] is False
    assert visual["coordinate_space"] == "original_frame"
    assert (visual["frame_width_px"], visual["frame_height_px"]) == (500, 450)
    assert visual["frame_id"] == "recorded-frame-8" and visual["parent_track_id"] == 7
    assert "experimental_mask_requires_ownership_validation" in visual["reasons"]
    expected_center = np.array((223, 187))
    assert np.linalg.norm(np.mean(visual["principal_axis"], axis=0) - expected_center) < 3
    np.testing.assert_allclose(np.asarray(visual["length_path"])[[0, -1]], visual["principal_axis"])
    assert np.linalg.norm(np.diff(visual["length_path"], axis=0), axis=1).sum() + 1 == pytest.approx(
        geometry["candidate_measurements"]["fish_length_px"], abs=.1)
    for key, metric in (("width_axis", geometry["candidate_measurements"]["max_body_width_px"]),
                        ("representative_width_axis", visual["representative_width_axis_value_px"])):
        endpoints = np.asarray(visual[key])
        assert np.linalg.norm(endpoints[1] - endpoints[0]) + 1 == pytest.approx(metric, abs=.01)
        # The endpoints must touch observed native silhouette pixels within
        # the one-pixel nearest-neighbor rotation footprint.
        for px, py in np.rint(endpoints - np.array((103, 67))).astype(int):
            assert mask[max(0, py - 1):py + 2, max(0, px - 1):px + 2].any()
    json.dumps(geometry, allow_nan=False)


def test_missing_body_keeps_estimated_fish_path_and_withholds_width_lines():
    mask, parts, kwargs = geometry_case(estimated=True, with_body=False)
    geometry = measure_fish_geometry(mask, parts, **kwargs)
    visual = geometry["candidate_visualization"]
    assert visual["status"] == "estimated" and visual["length_path"]
    assert visual["body_width_status"] == "unavailable"
    assert "associated_body_region_unavailable" in visual["body_width_reasons"]
    assert "width_axis" not in visual and "representative_width_axis" not in visual
    assert geometry["max_body_width_px"] is None


@pytest.mark.parametrize("change,reason", [
    ({"association_reliable": False}, "parent_association_uncertain"),
    ({"overlapping": True}, "overlapping_parent_fish"),
    ({"crop_bounds": (103, 67, 300, 307)}, "mask_crop_dimensions_mismatch"),
])
def test_failed_fish_attribution_or_coordinates_withhold_candidate_lines(change, reason):
    mask, parts, kwargs = geometry_case(estimated=True)
    kwargs.update(change)
    geometry = measure_fish_geometry(mask, parts, **kwargs)
    visual = geometry["candidate_visualization"]
    assert visual["status"] == "unavailable" and reason in visual["reasons"]
    for key in ("principal_axis", "length_path", "width_axis", "representative_width_axis"):
        assert key not in visual
    assert geometry["candidate_measurements"]["fish_length_px"] > 150
    assert geometry["fish_length_px"] is None


def test_representative_line_is_a_real_observed_section():
    mask, parts, kwargs = geometry_case()
    result = measure_fish_geometry(mask, parts, **kwargs)
    visual = result["visualization"]
    assert result["status"] == "measured" and visual["status"] == "estimated"
    assert "Observed" in visual["representative_width_axis_method"]
    assert visual["representative_width_axis_value_px"].is_integer()
    assert not result["measurement_validated"]


def test_explicitly_reviewed_native_pixels_are_the_only_validated_overlay():
    mask, parts, kwargs = geometry_case()
    body_mask = np.zeros_like(mask, dtype=bool)
    body_mask[105:136, 90:151] = True
    kwargs["mask_metadata"].update(
        measurement_validated=True, ownership_validated=True,
        validation_provenance="Synthetic software fixture whole-fish review",
    )
    kwargs.update(body_mask=body_mask, body_mask_metadata={
        "validated": True, "body_region_validated": True, "parent_track_id": 7,
        "validation_provenance": "Synthetic software fixture Body review",
    })
    geometry = measure_fish_geometry(mask, parts, **kwargs)
    assert geometry["measurement_validated"]
    assert geometry["visualization"]["status"] == geometry["visualization"]["body_width_status"] == "validated"
    assert geometry["visualization"]["measurement_validated"]
    assert not geometry["used_for_grading"]


def test_invalid_body_polygon_does_not_prevent_valid_estimated_fish_length():
    mask, parts, kwargs = geometry_case(estimated=True)
    parts = [{"region": "Body", "confidence": .95, "bbox": parts[0].bbox, "mask": "invalid polygon"}]
    geometry = measure_fish_geometry(mask, parts, **kwargs)
    visual = geometry["candidate_visualization"]
    assert visual["status"] == "estimated" and visual["length_path"]
    assert visual["body_width_status"] == "unavailable"
    assert "invalid_body_segmentation" in visual["body_width_reasons"]
    assert "width_axis" not in visual and "body_region_boundary" not in visual


def overlapping_native_candidate():
    mask, parts, kwargs = geometry_case(estimated=True)
    kwargs["overlapping"] = True
    kwargs["mask_metadata"].update(
        source="mobilesam_experimental_candidate", backend="mobilesam_experimental",
        parent_isolation_reliable=True,
        ownership={"status": "checks_passed_unvalidated", "engineering_checks_passed": True,
                   "mask_geometry_checks_passed": True, "reasons": [], "conflicting_parent_ids": [],
                   "coordinate_space": "original_frame", "frame_shape": [450, 500], "parent_id": 7},
        candidate_provenance={"coordinate_space": "original_frame", "mask_shape": [450, 500], "parent_id": 7},
    )
    return mask, parts, kwargs


def test_verified_native_mask_can_show_estimated_axes_despite_overlapping_detector_boxes():
    mask, parts, kwargs = overlapping_native_candidate()
    geometry = measure_fish_geometry(mask, parts, **kwargs)
    visual = geometry["candidate_visualization"]
    assert geometry["status"] == "unreliable" and geometry["fish_length_px"] is None
    assert "overlapping_parent_fish" in geometry["reasons"]
    assert not geometry["measurement_validated"] and not geometry["used_for_grading"]
    assert not geometry.get("visualization")
    assert visual["status"] == "estimated" and visual["bbox_overlap_display_only"]
    assert visual["length_path"] and visual["width_axis"] and visual["representative_width_axis"]


@pytest.mark.parametrize("fault", ["rejected", "conflicts", "ownership_reason", "not_isolated", "shape", "parent", "provenance", "backend"])
def test_overlap_display_exception_never_bypasses_failed_native_ownership(fault):
    mask, parts, kwargs = overlapping_native_candidate()
    metadata = kwargs["mask_metadata"]
    if fault == "rejected": metadata["ownership"]["status"] = "rejected"
    elif fault == "conflicts": metadata["ownership"]["conflicting_parent_ids"] = [8]
    elif fault == "ownership_reason": metadata["ownership"]["reasons"] = ["neighbor_mask_overlap"]
    elif fault == "not_isolated": metadata["parent_isolation_reliable"] = False
    elif fault == "shape": metadata["ownership"]["frame_shape"] = [240, 240]
    elif fault == "parent": metadata["ownership"]["parent_id"] = 8
    elif fault == "provenance": metadata["candidate_provenance"]["coordinate_space"] = "crop_local"
    else: metadata["backend"] = "grabcut"
    geometry = measure_fish_geometry(mask, parts, **kwargs)
    visual = geometry["candidate_visualization"]
    assert visual["status"] == "unavailable" and "length_path" not in visual
    assert "overlapping_parent_fish" in geometry["reasons"]
    assert not geometry["used_for_grading"] and geometry["fish_length_px"] is None


def line_scene():
    image = np.full((120, 180, 3), 150, np.uint8)
    mask = np.zeros((120, 180), bool)
    mask[10:-10, 10:-10] = True
    cv2.line(image, (30, 35), (145, 85), (20, 20, 20), 3)
    return image, mask


def test_crack_contour_vertices_are_retained_rgb_supported_pixels():
    image, mask = line_scene()
    result = analyze_surface_damage(image, mask)
    assert result["status"] == "suspected"
    assert result["severity"] == "unassessed" and result["validation_status"] == "unvalidated"
    assert not result["used_for_grading"]
    for location in result["locations"]:
        assert location["contours"]
        for contour in location["contours"]:
            for x, y in contour:
                assert result["overlay_mask"][y, x] == 255
                assert mask[y, x] and np.array_equal(image[y, x], [20, 20, 20])


def test_crack_contours_keep_exact_crop_to_original_frame_translation(monkeypatch):
    image, mask = line_scene()
    frame = np.full((220, 300, 3), 150, np.uint8)
    bounds = CropBounds(37, 51, 217, 171)
    frame[bounds.y1:bounds.y2, bounds.x1:bounds.x2] = image
    context = RuntimeMaskContext(frame, frame_id="crack-frame")
    monkeypatch.setattr(context, "get", lambda *_: (mask, {"source": "synthetic native test mask"}))
    damage = parent_damage(frame, bounds, 7, mask_context=context, frame_id="crack-frame")
    assert damage["frame_id"] == "crack-frame" and damage["parent_track_id"] == 7
    assert damage["locations"]
    for location in damage["locations"]:
        for local, original in zip(location["contours"], location["frame_contours"]):
            np.testing.assert_array_equal(np.asarray(original), np.asarray(local) + [37, 51])
