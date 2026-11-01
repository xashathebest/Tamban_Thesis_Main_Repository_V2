"""Conservative surface-damage evidence from an existing fish mask.

This is an evidence feature, not a validated grading model. It deliberately
reports suspected damage and never emits a final class.
"""

from __future__ import annotations

import cv2
import numpy as np

from src.features.texture import TextureSettings, extract_texture_features
from src.preprocessing.scientific_image_utils import PreprocessingError


def analyze_surface_damage(
    image_rgb: np.ndarray,
    mask: np.ndarray,
    *,
    mask_source: str = "feature_mask",
) -> dict[str, object]:
    """Return conservative crack-like evidence and a local overlay mask."""

    image = np.asarray(image_rgb)
    binary = np.asarray(mask, dtype=bool)
    if image.ndim != 3 or image.shape[:2] != binary.shape:
        raise PreprocessingError("Surface damage analysis requires an aligned RGB image and mask.")
    if not binary.any():
        return {
            "status": "unavailable",
            "label": "Suspected Damage",
            "confidence": None,
            "estimated_length_px": 0.0,
            "locations": [],
            "mask_source": mask_source,
            "mask_validated_for_cracks": False,
            "reason": "The fish feature mask is empty.",
            "overlay_mask": np.zeros(binary.shape, dtype=np.uint8),
        }

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    denoised = cv2.GaussianBlur(gray, (5, 5), 0)
    clean_mask = cv2.morphologyEx(binary.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    clean_mask = cv2.morphologyEx(clean_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
    interior = cv2.erode(clean_mask.astype(np.uint8), np.ones((5, 5), np.uint8), iterations=1).astype(bool)
    edges = cv2.Canny(denoised, 45, 125) > 0
    original_edges = cv2.Canny(gray, 45, 125) > 0
    candidates = cv2.morphologyEx((edges & original_edges & interior).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(candidates, 8)
    locations: list[dict[str, object]] = []
    overlay = np.zeros(binary.shape, dtype=np.uint8)
    for index in range(1, component_count):
        x, y, width, height, area = (int(value) for value in stats[index])
        length = float(max(width, height))
        if area < 5 or length < 8:
            continue
        component = labels == index
        overlay[component] = 255
        locations.append({
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "estimated_length_px": round(length, 2),
            "area_px": area,
        })

    texture = extract_texture_features(image, clean_mask, TextureSettings())
    edge_density = float(texture.get("edge_density_proxy", 0.0) or 0.0)
    signal = min(1.0, len(locations) / 5.0 + edge_density)
    confidence = round(min(0.89, 0.35 + signal * 0.45), 3) if locations else None
    status = "suspected" if locations and confidence is not None and confidence >= 0.55 else "not_detected"
    severity = "moderate" if len(locations) >= 3 or sum(item["area_px"] for item in locations) > binary.sum() * 0.02 else "low"
    return {
        "status": status,
        "label": "Suspected Damage",
        "confidence": confidence,
        "severity": severity if status == "suspected" else "none",
        "estimated_length_px": round(max((item["estimated_length_px"] for item in locations), default=0.0), 2),
        "locations": locations,
        "mask_source": mask_source,
        "mask_validated_for_cracks": False,
        "reason": "Conservative texture discontinuity evidence; not validated as a crack classifier.",
        "overlay_mask": overlay,
    }
