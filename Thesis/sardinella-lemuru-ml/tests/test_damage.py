import cv2
import numpy as np

from src.features.damage import analyze_surface_damage
from src.preprocessing.scientific_image_utils import PreprocessingError


def fish_mask(height=120, width=180):
    mask = np.zeros((height, width), dtype=bool)
    mask[10:-10, 10:-10] = True
    return mask


def test_uniform_texture_does_not_report_damage():
    image = np.full((120, 180, 3), 150, dtype=np.uint8)

    result = analyze_surface_damage(image, fish_mask())

    assert result["status"] == "not_detected"
    assert result["locations"] == []
    assert result["confidence"] is None
    assert result["mask_validated_for_cracks"] is False


def test_elongated_discontinuity_reports_supporting_evidence():
    image = np.full((120, 180, 3), 150, dtype=np.uint8)
    for offset in (0, 20):
        cv2.line(image, (30, 30 + offset), (150, 90 + offset), (20, 20, 20), 6)

    result = analyze_surface_damage(image, fish_mask())

    assert result["status"] == "suspected"
    assert result["confidence"] is not None
    assert result["estimated_length_px"] >= 8
    assert result["locations"]
    assert result["mask_validated_for_cracks"] is False


def test_damage_requires_aligned_image_and_mask():
    image = np.zeros((20, 20, 3), dtype=np.uint8)
    mask = np.zeros((10, 10), dtype=bool)

    try:
        analyze_surface_damage(image, mask)
    except PreprocessingError as error:
        assert "aligned RGB image and mask" in str(error)
    else:
        raise AssertionError("Mismatched image and mask should fail explicitly.")
