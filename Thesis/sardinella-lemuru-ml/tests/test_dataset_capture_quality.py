import numpy as np

from src.api.dataset_capture.quality import assess_quality


def test_quality_is_descriptive_bounded_and_does_not_mutate_native_frame():
    frame = np.full((1080, 1920, 3), 128, dtype=np.uint8)
    result = assess_quality(frame)
    assert result["width"] == 1920 and result["height"] == 1080
    assert result["focus_score"] == 0 and "LOW_FOCUS_SCORE" in result["warnings"]
    assert len(result["background_signature"]) == 64
    assert "grade" in result["caveat"] and np.all(frame == 128)


def test_clipping_duplicate_and_background_warnings_never_establish_identity():
    dark = np.zeros((480, 640, 3), dtype=np.uint8)
    first = assess_quality(dark)
    bright = assess_quality(np.full_like(dark, 255), first)
    assert first["underexposed_ratio"] == bright["overexposed_ratio"] == 1
    assert "BACKGROUND_DRIFT_REVIEW" in bright["warnings"]
    assert "NEAR_DUPLICATE_REVIEW" in bright["warnings"]
    assert "specimen identity" in bright["caveat"]


def test_review_thresholds_are_adjustable_without_changing_source_image():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    assert "LOW_FOCUS_SCORE" not in assess_quality(frame, thresholds={"focus_min": 0})["warnings"]
