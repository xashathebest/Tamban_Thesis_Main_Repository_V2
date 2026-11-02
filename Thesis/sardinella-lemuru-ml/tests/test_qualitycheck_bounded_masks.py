"""Bounded CPU foreground estimates retain native ownership and honest units."""
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier

import cv2
import numpy as np
import pytest

from src.inference.fish_geometry import PhysicalCalibration, measure_fish_geometry
from src.inference.fish_geometry_pipeline import analyze_fish_geometry
from src.inference.part_types import PartDetection
from src.inference.preprocessing import (
    CropBounds, PreprocessingError, RuntimeMaskContext, RuntimeMaskSettings,
    generate_runtime_fish_mask, measurement_crop_bounds,
)


def scene(height=480, width=1280):
    image = np.full((height, width, 3), 25, np.uint8)
    cv2.ellipse(image, (width // 2, height // 2), (int(width * .39), int(height * .22)),
                0, 0, 360, (155, 175, 195), -1)
    return image


def legacy_mask(image):
    """Retained native algorithm as the numerical-preservation oracle."""
    height, width = image.shape[:2]
    border = max(1, min(height, width) // 24)
    initial = np.zeros((height, width), np.uint8)
    cv2.grabCut(image, initial, (border, border, width - 2 * border, height - 2 * border),
                np.zeros((1, 65)), np.zeros((1, 65)), 3, cv2.GC_INIT_WITH_RECT)
    raw = np.logical_or(initial == cv2.GC_FGD, initial == cv2.GC_PR_FGD)
    rows, columns = np.nonzero(raw)
    contact = bool(rows.size and (columns.min() <= border + 1 or columns.max() >= width - border - 2
                                 or rows.min() <= border + 1 or rows.max() >= height - border - 2))
    raw = cv2.morphologyEx(raw.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    raw = cv2.morphologyEx(raw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    _, labels, stats, _ = cv2.connectedComponentsWithStats(raw, 8)
    return labels == int(np.argmax(stats[1:, cv2.CC_STAT_AREA]) + 1), contact


@pytest.mark.parametrize("settings", (RuntimeMaskSettings(), RuntimeMaskSettings.native()))
def test_small_native_path_preserves_the_original_pixels(settings):
    image = scene(120, 240)
    cv2.setRNGSeed(0)
    expected, expected_contact = legacy_mask(image)
    cv2.setRNGSeed(0)
    actual, metadata = generate_runtime_fish_mask(image, settings=settings)
    np.testing.assert_array_equal(actual, expected)
    assert metadata["foreground_touches_initialization_boundary"] == expected_contact
    assert metadata["sampling"]["mode"] == "native"
    assert metadata["sampling"]["estimated"] is False
    assert metadata["sampling"]["scale_to_native"] == [1, 1]


@pytest.mark.parametrize("height,width,settings", [
    (397, 1301, RuntimeMaskSettings()),
    (480, 1280, RuntimeMaskSettings(maximum_dimension=320, maximum_pixels=80_000)),
    (900, 1000, RuntimeMaskSettings(maximum_dimension=640, maximum_pixels=100_000)),
])
def test_working_grid_is_bounded_and_returns_the_exact_native_shape(height, width, settings):
    image = scene(height, width)
    original = image.copy()
    mask, metadata = generate_runtime_fish_mask(image, settings=settings)
    assert mask is not None and mask.dtype == np.bool_
    assert mask.shape == (height, width)
    sampling = metadata["sampling"]
    assert sampling["estimated"] is True and sampling["mode"] == "bounded_working_grid"
    work_h, work_w = sampling["working_shape"]
    assert max(work_h, work_w) <= settings.maximum_dimension
    assert work_h * work_w <= settings.maximum_pixels
    assert sampling["scale_to_native"] == [width / work_w, height / work_h]
    assert sampling["native_output_shape"] == [height, width]
    assert sampling["native_boundary_validated"] is False
    assert metadata["measurement_validated"] is metadata["mask_validated_for_cracks"] is False
    assert metadata["segmentation_backend"] == "opencv_cpu_grabcut"
    assert metadata["foreground_pixels"] == int(mask.sum())
    assert set(metadata["stage_timings_ms"]) == {"source_resize", "grabcut", "raw_components", "morphology", "final_components", "native_lift", "total"}
    assert all(value >= 0 for value in metadata["stage_timings_ms"].values())
    np.testing.assert_array_equal(image, original)
    json.dumps(metadata, allow_nan=False)


def test_each_context_captures_its_settings_and_native_masks_have_a_separate_cache_entry(monkeypatch):
    image = scene(180, 780)
    bounds = CropBounds(0, 0, 780, 180)
    monkeypatch.setenv("FISH_MASK_MAX_DIMENSION", "320")
    context = RuntimeMaskContext(image, frame_id="owned-frame")
    bounded, bounded_metadata = context.get(7, bounds)
    monkeypatch.setenv("FISH_MASK_MAX_DIMENSION", "0")
    cached, cached_metadata = context.get(7, bounds)
    native, native_metadata = context.get(7, bounds, settings=RuntimeMaskSettings.native())
    other_parent, other_metadata = context.get(8, bounds)
    assert np.shares_memory(bounded, cached)
    assert bounded_metadata["sampling"]["estimated"] and cached_metadata["cache_hit"]
    assert other_metadata["sampling"]["estimated"]
    assert native_metadata["sampling"]["estimated"] is False
    assert native is not None and other_parent is not None
    assert context.diagnostics()["segmentation_calls"] == 3
    assert context.diagnostics()["cache_misses"] == 3
    assert context.diagnostics()["cache_hits"] == 1
    assert context.diagnostics()["downsized_calls"] == 2
    assert RuntimeMaskContext(image).get(7, bounds)[1]["sampling"]["estimated"] is False


def test_native_opt_out_and_explicit_calibration_share_the_same_effective_policy(monkeypatch):
    monkeypatch.setenv("FISH_MASK_MAX_DIMENSION", "0")
    image = scene(120, 240)
    context = RuntimeMaskContext(image)
    bounds = CropBounds(0, 0, 240, 120)
    first, _ = context.get(7, bounds)
    second, metadata = context.get(7, bounds, settings=RuntimeMaskSettings.native())
    assert np.shares_memory(first, second) and metadata["cache_hit"]
    assert context.diagnostics()["segmentation_calls"] == 1
    assert RuntimeMaskSettings(0, 200_000) == RuntimeMaskSettings.native()


def test_grabcut_execution_counter_excludes_hits_and_survives_postprocessing_errors(monkeypatch):
    calls = []
    def fake_grabcut(image, initial, rect, background, foreground, iterations, mode):
        calls.append(image.shape)
        cv2.ellipse(initial, (initial.shape[1] // 2, initial.shape[0] // 2),
                    (initial.shape[1] // 3, initial.shape[0] // 5), 0, 0, 360, cv2.GC_PR_FGD, -1)
    monkeypatch.setattr(cv2, "grabCut", fake_grabcut)
    context = RuntimeMaskContext(scene(180, 5000))
    bounds = CropBounds(0, 0, 240, 120)
    mask, first = context.get(7, bounds)
    context.get(7, bounds)
    assert mask is not None and first["grabcut_invocations"] == 1
    def fail_morphology(*args):
        raise RuntimeError("Synthetic post-GrabCut failure")
    monkeypatch.setattr(cv2, "morphologyEx", fail_morphology)
    failed, metadata = context.get(8, bounds)
    assert failed is None and metadata["error_type"] == "RuntimeError"
    assert metadata["grabcut_invocations"] == 1
    assert len(calls) == context.diagnostics()["grabcut_executions"] == 2
    assert context.diagnostics()["segmentation_calls"] == 2
    assert context.diagnostics()["cache_hits"] == 1
    assert context.diagnostics()["generation_failures"] == 1


def test_underresolved_sampling_counts_an_attempt_without_grabcut_or_working_pixel_processing():
    context = RuntimeMaskContext(scene(24, 5000))
    mask, metadata = context.get(7, CropBounds(0, 0, 5000, 24))
    assert mask is None and metadata["sampling"]["working_shape"][0] < 12
    assert metadata["grabcut_invocations"] == metadata["working_pixel_count"] == 0
    assert context.diagnostics()["segmentation_calls"] == 1
    assert context.diagnostics()["grabcut_executions"] == 0
    assert context.diagnostics()["working_pixels_processed"] == 0


def test_settings_are_thread_local_when_contexts_use_different_working_grids(monkeypatch):
    barrier = Barrier(2)
    observed = []
    def fake_grabcut(image, initial, rect, background, foreground, iterations, mode):
        observed.append(image.shape[:2])
        barrier.wait(timeout=5)
        cv2.ellipse(initial, (initial.shape[1] // 2, initial.shape[0] // 2),
                    (initial.shape[1] // 3, initial.shape[0] // 5), 0, 0, 360, cv2.GC_PR_FGD, -1)
    monkeypatch.setattr(cv2, "grabCut", fake_grabcut)
    image = scene(180, 780)
    bounds = CropBounds(0, 0, 780, 180)
    contexts = [RuntimeMaskContext(image, settings=RuntimeMaskSettings(maximum_dimension=320)),
                RuntimeMaskContext(image, settings=RuntimeMaskSettings.native())]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda context: context.get(7, bounds), contexts))
    assert sorted(observed) == [(73, 320), (180, 780)]
    assert results[0][1]["sampling"]["estimated"] is True
    assert results[1][1]["sampling"]["estimated"] is False


def test_projected_foreground_keeps_sampling_provenance_and_exact_crop_origin():
    image = scene(384, 1536)
    source = CropBounds(0, 0, 1536, 384)
    target = CropBounds(80, 20, 1456, 364)
    context = RuntimeMaskContext(image, frame_id="projected")
    mask, metadata = context.get_projected(11, source, target, frame=image,
                                           target_crop=image[target.y1:target.y2, target.x1:target.x2])
    assert mask.shape == (target.height, target.width)
    assert metadata["source"] == "runtime_grabcut_padded_projection"
    assert metadata["parent_track_id"] == 11
    assert metadata["crop_bounds"] == [80, 20, 1456, 364]
    assert metadata["sampling"]["estimated"] is True
    assert metadata["sampling"]["native_shape"] == [384, 1536]
    assert metadata["sampling"]["native_output_shape"] == [target.height, target.width]
    assert metadata["projection"]["resized"] is False
    assert metadata["source_mask_metadata"]["sampling"]["scale_to_native"] == metadata["sampling"]["scale_to_native"]
    assert context.diagnostics()["segmentation_calls"] == 1


def test_bounded_segmentation_does_not_hide_a_second_foreground_component():
    image = np.full((480, 1280, 3), 25, np.uint8)
    cv2.ellipse(image, (360, 240), (220, 80), 0, 0, 360, (150, 175, 195), -1)
    cv2.ellipse(image, (950, 240), (200, 90), 0, 0, 360, (150, 175, 195), -1)
    mask, metadata = generate_runtime_fish_mask(image)
    assert mask is not None
    assert metadata["raw_component_count"] >= 2
    assert metadata["raw_second_component_fraction"] > .2
    assert metadata["component_evidence_resolution"] == "working_grid"


def test_clipped_foreground_retains_its_initialization_boundary_warning():
    image = scene()
    cv2.ellipse(image, (20, 240), (500, 110), 0, 0, 360, (155, 175, 195), -1)
    _, metadata = generate_runtime_fish_mask(image)
    assert metadata["foreground_touches_initialization_boundary"] is True
    assert metadata["sampling"]["estimated"] is True


@pytest.mark.parametrize("image", (np.full((480, 1280, 3), 25, np.uint8), scene(24, 5000)))
def test_uninformative_or_underresolved_foreground_has_a_clear_failure_state(image):
    mask, metadata = generate_runtime_fish_mask(image)
    assert mask is None
    assert metadata["status"] == "unavailable" and metadata["reason"]
    assert metadata["mask_validated_for_cracks"] is False
    assert metadata["measurement_validated"] is False
    assert metadata["segmentation_backend"] == "opencv_cpu_grabcut"
    assert metadata["stage_timings_ms"]["total"] >= 0


def geometry_case():
    image = scene(480, 1440)
    parent = (120, 120, 1320, 360)
    bounds = CropBounds(*parent)
    parts = [PartDetection.from_source_class(0, .95, (300, 10, 900, 230))]
    return image, parent, bounds, parts


def test_resampled_geometry_retains_native_pixel_estimates_without_claiming_reliable_or_physical_results():
    image, parent, bounds, parts = geometry_case()
    context = RuntimeMaskContext(image)
    crop = image[bounds.y1:bounds.y2, bounds.x1:bounds.x2]
    result = analyze_fish_geometry(crop, parts, parent_bbox=parent, crop_bounds=bounds, frame_shape=image.shape,
                                   association_reliable=True, measurement_frame=image, mask_context=context, parent_id=4)
    assert result["sampling"]["estimated"] is True
    assert result["status"] == "unreliable"
    assert "resampled_foreground_requires_native_validation" in result["reasons"]
    assert result["candidate_measurements"]["fish_length_px"] > 1000
    assert result["candidate_measurements"]["max_body_width_px"] > 150
    assert result["fish_length_px"] is result["max_body_width_px"] is result["relative_width_ratio"] is None
    assert result["fish_length_cm"] is result["max_body_width_cm"] is None
    assert result["used_for_grading"] is result["physical_calibration"]["applied"] is False
    assert not result.get("visualization")


def test_validated_physical_configuration_requests_native_segmentation_instead_of_reusing_scaled_masks():
    image, parent, bounds, parts = geometry_case()
    context = RuntimeMaskContext(image)
    measurement_bounds = measurement_crop_bounds(image, parent)
    _, previous = context.get(4, measurement_bounds)
    assert previous["sampling"]["estimated"]
    calibration = PhysicalCalibration(True, "synthetic-software-only", 100., (1440, 480), "synthetic-plane")
    result = analyze_fish_geometry(image[bounds.y1:bounds.y2, bounds.x1:bounds.x2], parts,
                                   parent_bbox=parent, crop_bounds=bounds, frame_shape=image.shape,
                                   association_reliable=True, measurement_frame=image, mask_context=context, parent_id=4,
                                   physical_calibration=calibration, source_context="synthetic-plane")
    assert result["sampling"]["estimated"] is False
    assert result["mask_metadata"]["segmentation_settings"]["maximum_dimension"] == 0
    assert "resampled_foreground_requires_native_validation" not in result["reasons"]
    assert context.diagnostics()["segmentation_calls"] == 2
    if result["status"] == "measured":
        assert result["fish_length_cm"] == pytest.approx(result["fish_length_px"] / 100, abs=1e-6)


def test_a_direct_scaled_mask_cannot_apply_centimeters_even_with_a_valid_physical_scale():
    image, parent, bounds, parts = geometry_case()
    crop = image[bounds.y1:bounds.y2, bounds.x1:bounds.x2]
    mask, metadata = generate_runtime_fish_mask(crop)
    result = measure_fish_geometry(mask, parts, parent_bbox=parent, crop_bounds=bounds, frame_shape=image.shape,
                                  association_reliable=True, mask_metadata=metadata,
                                  physical_calibration=PhysicalCalibration(True, "synthetic", 100., (1440, 480), "plane"),
                                  source_context="plane")
    assert result["sampling"]["estimated"] is True
    assert result["fish_length_cm"] is result["max_body_width_cm"] is None
    assert result["physical_calibration"]["status"] == "Not applied"
    assert result["physical_calibration"]["applied"] is False


@pytest.mark.parametrize("setting", ({"maximum_dimension": True}, {"maximum_dimension": 10}, {"maximum_pixels": -1}))
def test_invalid_explicit_sampling_settings_are_rejected(setting):
    with pytest.raises(PreprocessingError):
        RuntimeMaskSettings(**setting)


def test_invalid_environment_limits_fall_back_explicitly_and_do_not_break_grading_context(monkeypatch):
    monkeypatch.setenv("FISH_MASK_MAX_DIMENSION", "not-a-size")
    monkeypatch.setenv("FISH_MASK_MAX_PIXELS", "-5")
    settings = RuntimeMaskSettings.from_environment()
    assert settings.maximum_dimension == 640 and settings.maximum_pixels == 200_000
    assert len(settings.configuration_warnings) == 2
    context = RuntimeMaskContext(scene(120, 240))
    mask, metadata = context.get(2, CropBounds(0, 0, 240, 120))
    assert mask is not None and metadata["segmentation_settings"]["configuration_warnings"]
    assert context.diagnostics()["settings_fallbacks"] == 1
