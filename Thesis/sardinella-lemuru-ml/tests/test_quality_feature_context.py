"""Shared feature maps preserve native scopes and public scientific outputs."""
from copy import deepcopy

import numpy as np
import pytest

from src.features.color import ColorSettings, extract_color_features, rgb_to_lab
from src.features.runtime import RuntimeFeatureContext
from src.features.texture import TextureSettings, extract_texture_features
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.grading_engine import _texture_payload
from src.inference.part_types import PartDetection
from src.preprocessing.scientific_image_utils import PreprocessingError


def equal_features(actual, expected):
    assert actual.keys() == expected.keys()
    for key in actual:
        np.testing.assert_allclose(actual[key], expected[key], rtol=0, atol=0, equal_nan=True, err_msg=key)


@pytest.mark.parametrize("kind", ("rgb", "gray", "float", "low_contrast"))
def test_shared_color_and_texture_keep_exact_native_pixel_values(kind):
    rng = np.random.default_rng(29)
    image = rng.integers(0, 256, (31, 47, 3), dtype=np.uint8)
    if kind == "gray": image[:] = 180
    if kind == "float": image = image.astype(np.float64) / 255
    if kind == "low_contrast": image[:] = rng.integers(100, 104, image.shape, dtype=np.uint8)
    mask = rng.random(image.shape[:2]) > .3
    context = RuntimeFeatureContext(image)
    for bounds in ((0, 0, 47, 31), (3, 5, 25, 29), (20, 1, 44, 18)):
        left, top, right, bottom = bounds
        for region_mask in (None, mask[top:bottom, left:right]):
            actual = context.color_summary(bounds, region_mask)
            expected = extract_color_features(
                image[top:bottom, left:right],
                np.ones((bottom-top, right-left), bool) if region_mask is None else region_mask,
                ColorSettings(), summary_only=True,
            )
            equal_features(actual, expected)
    context.release_color_maps()
    assert context._hsv is context._lightness is None
    equal_features(context.texture_summary(mask), extract_texture_features(image, mask, TextureSettings()))
    assert context._rgb is None
    counts = context.diagnostics()
    assert counts["normalization_calls"] == counts["hsv_conversions"] == counts["lab_lightness_conversions"] == counts["gray_conversions"] == 1


def test_color_masks_remain_different_scopes_and_parent_snapshot_is_immutable():
    image = np.zeros((10, 20, 3), dtype=np.uint8)
    image[:, :10] = (255, 255, 0)
    image[:, 10:] = (20, 20, 20)
    mask = np.zeros((10, 20), bool); mask[:, :10] = True
    context = RuntimeFeatureContext(image)
    masked = context.color_summary((0, 0, 20, 10), mask)
    rectangular = context.color_summary((0, 0, 20, 10))
    assert masked["yellow_ratio_proxy"] == 1.0
    assert rectangular["yellow_ratio_proxy"] == .5
    source = image.copy()
    image[:] = 0
    equal_features(context.color_summary((10, 0, 20, 10)), extract_color_features(source[:, 10:], np.ones((10, 10), bool), ColorSettings(), summary_only=True))
    assert context._source.flags.writeable is False


def test_cached_results_cannot_mutate_later_readings_and_mask_edits_invalidate():
    image = np.full((12, 18, 3), 180, np.uint8)
    image[:, :9] = (255, 255, 0)
    context = RuntimeFeatureContext(image)
    mask = np.ones((12, 18), bool)
    first = context.color_summary((0, 0, 18, 12), mask)
    first["yellow_ratio_proxy"] = -99
    assert context.color_summary((0, 0, 18, 12), mask)["yellow_ratio_proxy"] == .5
    mask[:, 9:] = False
    assert context.color_summary((0, 0, 18, 12), mask)["yellow_ratio_proxy"] == 1.0
    expected = deepcopy(context.texture_summary(mask))
    context.texture_summary(mask)["lbp_entropy"] = -99
    equal_features(context.texture_summary(mask), expected)
    assert context.diagnostics()["color_computations"] == 2
    assert context.diagnostics()["color_cache_hits"] == 1
    assert context.diagnostics()["texture_computations"] == 1
    assert context.diagnostics()["texture_cache_hits"] == 2


@pytest.mark.parametrize("bounds", ((0, 0, 0, 2), (-1, 0, 3, 3), (0, 0, 21, 3), (0., 0, 3, 3), (False, 0, 3, 3)))
def test_context_rejects_invalid_or_non_native_roi(bounds):
    with pytest.raises(PreprocessingError):
        RuntimeFeatureContext(np.zeros((10, 20, 3), np.uint8)).color_summary(bounds)


def test_context_rejects_wrong_or_empty_masks_without_reusing_rectangular_data():
    context = RuntimeFeatureContext(np.full((10, 20, 3), 100, np.uint8))
    context.color_summary((0, 0, 20, 10))
    for mask in (np.zeros((10, 20), bool), np.ones((5, 20), bool)):
        with pytest.raises(PreprocessingError): context.color_summary((0, 0, 20, 10), mask)
        with pytest.raises(PreprocessingError): context.texture_summary(mask)


def test_lightness_only_lab_is_exact_full_lab_channel():
    rng = np.random.default_rng(77)
    image = rng.random((30, 41, 3))
    np.testing.assert_array_equal(rgb_to_lab(image, lightness_only=True), rgb_to_lab(image)[..., 0])


def test_frame_engine_exposes_separate_color_texture_timings_and_conversion_counts():
    rng = np.random.default_rng(7)
    crop = rng.integers(30, 220, (40, 80, 3), dtype=np.uint8)
    parts = [PartDetection.from_source_class(index, .9, box) for index, box in ((0, (15, 5, 65, 35)), (1, (0, 5, 20, 35)), (2, (60, 5, 80, 35)))]
    engine = WeightedGradingEngine(GradingConfig())
    result = engine.evaluate(1, crop, parts, stabilize=False, texture_mask=np.ones((40, 80), bool))
    timing = engine.last_feature_timings
    assert timing["color_processing_seconds"] == engine.last_hsv_processing_seconds > 0
    assert timing["texture_processing_seconds"] > 0
    assert timing["feature_processing_seconds"] == timing["color_processing_seconds"] + timing["texture_processing_seconds"]
    assert timing["context"]["hsv_conversions"] == timing["context"]["lab_lightness_conversions"] == 1
    assert timing["context"]["color_computations"] == 4
    assert result.weighted_scores == {"Class A": .9, "Class B": 0., "Class C": 0., "Rejected": 0.}
    assert result.adjustments == ()


def test_estimated_or_uncertain_foreground_changes_provenance_not_raw_texture_values():
    rng = np.random.default_rng(3)
    crop = rng.integers(0, 256, (15, 23, 3), np.uint8)
    mask = np.ones(crop.shape[:2], bool)
    baseline = _texture_payload(crop, mask)
    estimated = _texture_payload(crop, mask, {"sampling": {"estimated": True}})
    uncertain = _texture_payload(crop, mask, {"sampling": {"estimated": True},
        "parent_isolation_reliable": False, "parent_isolation_reasons": ["overlap"]})
    equal_features(baseline["values"], estimated["values"])
    equal_features(baseline["values"], uncertain["values"])
    assert estimated["foreground_estimated"] is True
    assert estimated["reliability"] == "Estimated foreground support"
    assert uncertain["reliability"] == "Unreliable parent isolation"
    assert uncertain["parent_isolation_reasons"] == ["overlap"]
    assert "reliability" not in baseline
