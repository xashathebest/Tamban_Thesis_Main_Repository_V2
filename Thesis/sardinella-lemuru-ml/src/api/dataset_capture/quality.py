"""Bounded descriptive quality checks. These warnings are never fish grades."""
from __future__ import annotations

import cv2
import numpy as np


QUALITY_CAVEAT = (
    "Focus, clipping, similarity and background changes are descriptive review aids; "
    "they do not establish fish grade, specimen identity or annotation quality."
)


def assess_quality(frame: np.ndarray, previous: dict | None = None,
                   thresholds: dict | None = None) -> dict:
    """Inspect a small derivative while leaving the native BGR frame untouched."""
    settings = {"focus_min": 35.0, "clipped_ratio": 0.30,
                "duplicate_distance": 3, "background_drift": 35.0}
    if thresholds:
        for key in settings:
            if key in thresholds:
                value = float(thresholds[key])
                if not np.isfinite(value) or value < 0 or value > 10000:
                    raise ValueError("Quality thresholds must be finite, nonnegative values.")
                settings[key] = value
    height, width = frame.shape[:2]
    scale = min(1.0, 512.0 / max(height, width))
    small = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))),
                       interpolation=cv2.INTER_AREA) if scale < 1 else frame
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    focus = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    low, high = float(np.mean(gray <= 5)), float(np.mean(gray >= 250))
    signature = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (signature[:, 1:] > signature[:, :-1]).reshape(-1)
    dhash = format(sum(int(value) << index for index, value in enumerate(bits)), "016x")
    background = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA).reshape(-1).tolist()
    warnings = []
    if focus < settings["focus_min"]:
        warnings.append("LOW_FOCUS_SCORE")
    if low > settings["clipped_ratio"]:
        warnings.append("UNDEREXPOSURE_OR_DARK_BACKGROUND")
    if high > settings["clipped_ratio"]:
        warnings.append("OVEREXPOSURE_OR_LIGHT_BACKGROUND")
    if min(height, width) < 480:
        warnings.append("LOW_RESOLUTION")
    similarity_distance, drift = None, None
    if previous:
        try:
            similarity_distance = (int(dhash, 16) ^ int(previous["dhash"], 16)).bit_count()
            if similarity_distance <= settings["duplicate_distance"]:
                warnings.append("NEAR_DUPLICATE_REVIEW")
            before = np.asarray(previous["background_signature"], dtype=np.float32)
            if before.size == 64:
                drift = float(np.abs(np.asarray(background, dtype=np.float32) - before).mean())
                if drift > settings["background_drift"]:
                    warnings.append("BACKGROUND_DRIFT_REVIEW")
        except (KeyError, ValueError, TypeError):
            pass
    return {"focus_score": round(focus, 3), "underexposed_ratio": round(low, 5),
            "overexposed_ratio": round(high, 5), "mean_luminance": round(float(gray.mean()), 3),
            "width": width, "height": height, "dhash": dhash,
            "background_signature": background, "similarity_distance": similarity_distance,
            "background_drift": drift, "warnings": warnings, "thresholds": settings,
            "caveat": QUALITY_CAVEAT}
