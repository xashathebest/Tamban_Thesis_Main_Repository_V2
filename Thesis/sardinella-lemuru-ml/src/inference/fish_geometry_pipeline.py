"""Prepare native-pixel, individual-fish masks independently of grade evidence."""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Sequence

import numpy as np

from src.inference.fish_geometry import (
    FishGeometryConfig, PhysicalCalibration, measure_fish_geometry,
)
from src.inference.part_types import PartDetection
from src.inference.preprocessing import (
    CropBounds, RuntimeMaskContext, generate_runtime_fish_mask,
    measurement_crop_bounds, measurement_roi_padding, RuntimeMaskSettings,
)


def analyze_fish_geometry(
    crop: np.ndarray, parts: Sequence[PartDetection], *,
    parent_bbox=None, crop_bounds=None, frame_shape=None,
    overlapping: bool = False, association_reliable: bool = False,
    fish_mask: np.ndarray | None = None, fish_mask_metadata: Mapping | None = None,
    measurement_frame: np.ndarray | None = None,
    mask_context: RuntimeMaskContext | None = None, parent_id: int | str | None = None,
    config: FishGeometryConfig | None = None,
    physical_calibration: PhysicalCalibration | None = None, source_context=None,
) -> dict:
    """Use a provided instance mask or segment a padded original-frame ROI.

    The separate measurement ROI never replaces the image, parts, or mask used
    by the existing grading engine. Masks retain native output dimensions;
    bounded working grids retain explicit estimated-boundary provenance.
    Validated physical calibration requests native segmentation explicitly.
    """
    metadata = dict(fish_mask_metadata or {})
    parent_context = {key: metadata[key] for key in (
        "expected_parent_id", "context_reliability_reasons", "clipped", "mask_clipped",
    ) if key in metadata}
    mask = fish_mask
    measurement_parts = list(parts)
    measurement_bounds = crop_bounds
    source = str(metadata.get("source", ""))
    provided_instance = mask is not None and bool(source) and not source.startswith("runtime_")
    native_required = (
        physical_calibration.validated if isinstance(physical_calibration, PhysicalCalibration)
        else isinstance(physical_calibration, Mapping) and physical_calibration.get("validated") is True
    )
    native_settings = RuntimeMaskSettings.native() if native_required else None

    def segment(image, bounds=None):
        if mask_context is not None and parent_id is not None and bounds is not None and mask_context.is_for_frame(measurement_frame):
            return (mask_context.get(parent_id, bounds, settings=native_settings)
                    if native_settings is not None else mask_context.get(parent_id, bounds))
        return (generate_runtime_fish_mask(image, settings=native_settings)
                if native_settings is not None else generate_runtime_fish_mask(image))
    frame_matches = (
        isinstance(measurement_frame, np.ndarray) and measurement_frame.ndim == 3
        and measurement_frame.shape[2] == 3 and measurement_frame.dtype == np.uint8
        and frame_shape is not None and tuple(measurement_frame.shape[:2]) == tuple(frame_shape[:2])
    )
    if frame_matches and parent_bbox is not None and crop_bounds is not None and not provided_instance:
        # GrabCut initializes a background ring. Include real background beyond
        # the detector box so that ring cannot silently cut off a fish's tips.
        # Known overlap is already decisive; preserve a supplied mask but avoid
        # spending another segmentation on an unresolvable overlapping ROI.
        if not overlapping:
            padding = measurement_roi_padding(parent_bbox)
            measurement_bounds = measurement_crop_bounds(measurement_frame, parent_bbox)
            measurement_crop = measurement_frame[
                measurement_bounds.y1:measurement_bounds.y2,
                measurement_bounds.x1:measurement_bounds.x2,
            ]
            mask, metadata = segment(measurement_crop, measurement_bounds)
            original_x, original_y = (
                crop_bounds.origin if isinstance(crop_bounds, CropBounds) else crop_bounds[:2]
            )
            offset_x, offset_y = original_x - measurement_bounds.x1, original_y - measurement_bounds.y1
            measurement_parts = [replace(
                part,
                bbox=(part.bbox[0] + offset_x, part.bbox[1] + offset_y,
                      part.bbox[2] + offset_x, part.bbox[3] + offset_y),
                mask=tuple((x + offset_x, y + offset_y) for x, y in part.mask) if part.mask else None,
            ) for part in parts]
            metadata = {**metadata, "measurement_padding_px": padding, "dedicated_measurement_crop": True}
    elif mask is None:
        mask, metadata = segment(crop, crop_bounds)
    elif (native_required and not provided_instance and isinstance(metadata.get("sampling"), Mapping)
          and metadata["sampling"].get("estimated") is True):
        mask, metadata = segment(crop, crop_bounds)
    elif not source:
        metadata.update(source="provided_instance_mask_unverified", measurement_validated=False)
    metadata.update(parent_context)

    geometry = measure_fish_geometry(
        mask, measurement_parts, parent_bbox=parent_bbox,
        crop_bounds=measurement_bounds, frame_shape=frame_shape,
        overlapping=overlapping, association_reliable=association_reliable,
        mask_metadata=metadata, config=config,
        physical_calibration=physical_calibration, source_context=source_context,
    )
    geometry["mask_metadata"] = metadata
    geometry["coordinate_space"] = "native_original_frame_pixels" if measurement_bounds is not None else "unverified_crop"
    geometry["mask_crop_bounds"] = (
        [measurement_bounds.x1, measurement_bounds.y1, measurement_bounds.x2, measurement_bounds.y2]
        if isinstance(measurement_bounds, CropBounds) else list(measurement_bounds) if measurement_bounds is not None else None
    )
    geometry["used_for_grading"] = False
    return geometry
