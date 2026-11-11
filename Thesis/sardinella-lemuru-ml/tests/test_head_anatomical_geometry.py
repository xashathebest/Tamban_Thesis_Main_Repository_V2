"""Anatomical geometry must use one signed native silhouette coordinate system."""

import cv2
import numpy as np
import pytest

from src.inference.anatomical_measurements import measure_mask_anatomy


def _part(region, binary):
    ys, xs = np.nonzero(binary)
    return {"region": region, "confidence": 0.95,
            "bbox": (float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1))}


def _headless(angle=0):
    body = np.zeros((360, 360), np.uint8)
    tail = np.zeros_like(body)
    cv2.rectangle(body, (90, 145), (215, 195), 1, -1)
    cv2.fillPoly(tail, [np.array(((215, 148), (290, 170), (215, 192)))], 1)
    transform = cv2.getRotationMatrix2D((179.5, 179.5), -angle, 1.0)
    body = cv2.warpAffine(body, transform, (360, 360), flags=cv2.INTER_NEAREST)
    tail = cv2.warpAffine(tail, transform, (360, 360), flags=cv2.INTER_NEAREST)
    return body | tail, [_part("Body", body), _part("Tail", tail)]


@pytest.mark.parametrize("angle", (0, -45, 45, 90, 135, 180, 225, 270))
def test_tail_polarity_and_cut_share_the_same_signed_axis_in_every_quadrant(angle):
    mask, parts = _headless(angle)
    measured = measure_mask_anatomy(mask, parts)
    assert measured["cut_end_confirmed"] is True
    assert measured["tail_anterior_end"] == measured["cut_end_axis"]
    assert measured["anatomical_orientation_reliable"] is True
    assert measured["orientation_confidence"]["polarity_reliable"] is True
    assert measured["anatomical_length_px"] == pytest.approx(201, abs=3)
    assert measured["terminal_width_ratio"] == pytest.approx(1.0, abs=0.05)
    assert "tail_cut_polarity_conflict" not in measured["reasons"]


def test_body_detector_box_cannot_change_full_silhouette_end_geometry():
    mask = np.zeros((280, 420), np.uint8)
    cv2.fillPoly(mask, [np.array(((20, 115), (190, 115), (330, 140), (190, 165), (120, 165)))], 1)
    boxes = ((120, 118, 200, 145), (140, 140, 260, 165), (20, 115, 331, 166))
    results = [measure_mask_anatomy(mask, [{"region": "Body", "confidence": .95, "bbox": box}]) for box in boxes]
    expected = measure_mask_anatomy(mask)["cut_end_metrics"]
    assert expected["cut_character"] == "slanted"
    for measured in results:
        assert measured["cut_end_metrics"] == expected
        assert measured["cut_end_confirmed"] is True


@pytest.mark.parametrize("angle", (0, -45, 135))
def test_profile_sections_are_native_pixel_measurements_with_bounded_diagnostics(angle):
    mask, parts = _headless(angle)
    measured = measure_mask_anatomy(mask, parts)
    sections = measured["cross_section_profile"]
    assert len(sections) == len(measured["centerline_px"]) == 21
    assert sections[0]["length_fraction"] == 0
    assert sections[-1]["length_fraction"] == 1
    assert measured["profile_coordinate_space"] == "crop_local_native_pixels"
    for section in sections:
        endpoints = np.asarray(section["endpoints_px"])
        assert np.linalg.norm(endpoints[1] - endpoints[0]) + 1 == pytest.approx(section["width_px"], abs=.001)
        assert np.isfinite(endpoints).all()
        assert (endpoints >= 0).all() and (endpoints < 360).all()
    assert len(measured["terminal_width_ratios"]) == len(measured["body_taper"]) == 2
    assert measured["truncation_evidence"]["character"] == "blunt"


def test_morphological_polarity_can_measure_extension_without_inventing_a_tail():
    mask, _ = _headless()
    body = {"region": "Body", "confidence": .95, "bbox": (105, 145, 216, 196)}
    measured = measure_mask_anatomy(mask, [body])
    assert measured["tail_pixels"] == 0
    assert measured["tail_anterior_end"] is None
    assert measured["posterior_source"] == "silhouette_morphology"
    assert measured["anterior_extension_px"] == pytest.approx(15, abs=.001)
    assert measured["anterior_extension_length_ratio"] == pytest.approx(15 / 201, abs=.001)


@pytest.mark.parametrize("tail_box,reason", (
    ((145, 150, 170, 190), "tail_body_polarity_uncertain"),
    ((90, 150, 115, 190), "tail_cut_polarity_conflict"),
))
def test_conflicting_tail_landmarks_do_not_claim_reliable_anatomical_orientation(tail_box, reason):
    mask, parts = _headless()
    parts[1] = {"region": "Tail", "confidence": .95, "bbox": tail_box}
    measured = measure_mask_anatomy(mask, parts)
    assert measured["orientation_reliable"] is True  # The axis itself is elongated.
    assert measured["anatomical_orientation_reliable"] is False
    assert measured["orientation_confidence"]["polarity_reliable"] is False
    assert measured["anterior_extension_px"] is None
    assert reason in measured["reasons"]
