"""Measure both ends of one fish from its centerline width profile.

The profile is already rotated onto the fish axis, so horizontal, vertical, and
diagonal fish use the same measurements. Thresholds come from configuration
calibrated on labeled silhouettes. They are not grade weights.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import yaml


@dataclass(frozen=True)
class HeadSilhouetteConfig:
    """Geometric gates for a severed anterior end versus a tail or snout."""

    minimum_profile_columns: int = 24
    representative_width_percentile: float = 90.0
    profile_samples: int = 21
    blunt_width_ratio: float = 0.90
    blunt_rise_fraction: float = 0.16
    slanted_rise_fraction: float = 0.30
    slanted_min_persistence: float = 0.55
    slanted_min_asymmetry: float = 0.18
    irregular_rise_fraction: float = 0.22
    irregular_min_discontinuity: float = 0.40
    irregular_min_persistence: float = 0.40
    posterior_narrow_ratio: float = 0.62
    posterior_window_start: float = 0.12
    posterior_window_stop: float = 0.22
    snout_max_persistence: float = 0.50
    snout_max_rise_fraction: float = 0.40
    discontinuity_window_fraction: float = 0.04
    discontinuity_search_fraction: float = 0.20
    near_width_fractions: tuple[float, ...] = (0.08, 0.14)
    flare_tip_start: float = 0.03
    flare_tip_stop: float = 0.08
    flare_peduncle_start: float = 0.14
    flare_peduncle_stop: float = 0.20
    flare_gain: float = 1.25
    flare_max_peduncle_ratio: float = 0.75
    flare_min_gain: float = 0.08
    rise_window_fraction: float = 0.03

    def __post_init__(self) -> None:
        if self.minimum_profile_columns < 16 or self.profile_samples < 5:
            raise ValueError("Head-silhouette profile length is too short.")
        fractions = (
            self.blunt_width_ratio, self.blunt_rise_fraction, self.slanted_rise_fraction,
            self.slanted_min_persistence, self.slanted_min_asymmetry, self.irregular_rise_fraction,
            self.irregular_min_discontinuity, self.irregular_min_persistence, self.posterior_narrow_ratio,
            self.posterior_window_start, self.posterior_window_stop, self.snout_max_persistence,
            self.snout_max_rise_fraction, self.discontinuity_window_fraction, self.discontinuity_search_fraction,
            self.flare_tip_start, self.flare_tip_stop, self.flare_peduncle_start, self.flare_peduncle_stop,
            self.flare_max_peduncle_ratio, self.flare_min_gain, self.rise_window_fraction,
        )
        if any(not math.isfinite(value) or value < 0 or value > 1 for value in fractions):
            raise ValueError("Head-silhouette fractions must be finite and between zero and one.")
        if not 50 <= self.representative_width_percentile <= 99:
            raise ValueError("representative_width_percentile must be between 50 and 99.")
        if self.flare_gain < 1 or not math.isfinite(self.flare_gain):
            raise ValueError("flare_gain must be at least one.")
        if not self.near_width_fractions or any(not 0 < value < 0.5 for value in self.near_width_fractions):
            raise ValueError("near_width_fractions must lie between zero and one half.")
        if not self.posterior_window_start < self.posterior_window_stop < 0.5:
            raise ValueError("The posterior window must sit near the end and stay in order.")
        if not self.blunt_rise_fraction <= self.irregular_rise_fraction <= self.slanted_rise_fraction:
            raise ValueError("Cut search windows must widen from blunt to irregular to slanted.")


def load_head_silhouette_config(path: str | Path | None = None) -> HeadSilhouetteConfig:
    """Load calibrated gates. Missing keys keep the dataclass defaults."""

    config_path = Path(path) if path else Path(__file__).resolve().parents[2] / "configs" / "head_integrity.yaml"
    with config_path.open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream) or {}
    if not isinstance(payload, Mapping):
        raise ValueError("Head integrity configuration must be a mapping.")
    section = payload.get("head_silhouette", {})
    if not isinstance(section, Mapping):
        raise ValueError("head_silhouette configuration must be a mapping.")
    values = dict(section)
    fractions = values.get("near_width_fractions")
    if isinstance(fractions, Sequence) and not isinstance(fractions, (str, bytes)):
        values["near_width_fractions"] = tuple(float(item) for item in fractions)
    known = {field for field in HeadSilhouetteConfig.__dataclass_fields__}
    return HeadSilhouetteConfig(**{key: value for key, value in values.items() if key in known})


def analyze_silhouette_ends(
    widths: np.ndarray,
    lower: np.ndarray | None = None,
    upper: np.ndarray | None = None,
    *,
    config: HeadSilhouetteConfig | None = None,
) -> dict[str, Any] | None:
    """Score the minimum-projection and maximum-projection ends.

    A severed end is blunt, slanted, or irregular. A posterior end keeps a narrow
    peduncle or a caudal flare. A snout widens and then flattens. Confirmation
    requires one severed end opposite one posterior end.
    """

    settings = config or load_head_silhouette_config()
    profile = np.asarray(widths, dtype=float)
    count = int(profile.size)
    if count < settings.minimum_profile_columns or not np.isfinite(profile).all():
        return None
    body = float(np.percentile(profile, settings.representative_width_percentile))
    if not math.isfinite(body) or body < 2:
        return None
    bounds = _boundaries(lower, upper, count)
    ends = [
        _describe_end(profile, bounds, body, reverse, settings)
        for reverse in (False, True)
    ]
    severed = [item for item in ends if item["role"] == "severed"]
    posteriors = [item for item in ends if item["role"] == "posterior"]
    snouts = [item for item in ends if item["role"] == "snout"]
    if len(severed) == 1 and len(posteriors) == 1:
        decision = "confirmed_anterior_cut"
        axis = severed[0]["axis"]
        character = severed[0]["character"]
    elif len(severed) == 1 and snouts:
        decision = "severed_tail"
        axis = None
        character = severed[0]["character"]
    else:
        decision = "ambiguous"
        axis = None
        character = None
    samples = np.linspace(0, count - 1, settings.profile_samples).astype(int)
    return {
        "cut_end_axis": axis,
        "cut_end_confirmed": decision == "confirmed_anterior_cut",
        "cut_character": character,
        "geometry_decision": decision,
        "representative_body_width_px": round(body, 4),
        "central_width_px": round(body, 4),
        "width_profile_ratio": [round(float(profile[index]) / body, 4) for index in samples],
        "terminal_width_ratios": {item["axis"]: item["terminal_width_ratio"] for item in ends},
        "body_taper": {item["axis"]: item["body_taper"] for item in ends},
        "ends": ends,
        "minimum_projection_blunt": ends[0]["character"] == "blunt",
        "maximum_projection_blunt": ends[1]["character"] == "blunt",
        "minimum_projection_narrow": ends[0]["role"] == "posterior",
        "maximum_projection_narrow": ends[1]["role"] == "posterior",
        "minimum_projection_rise_fraction": ends[0]["rise_fraction"],
        "maximum_projection_rise_fraction": ends[1]["rise_fraction"],
        "thresholds": {key: value for key, value in asdict(settings).items() if key != "near_width_fractions"},
    }


def _boundaries(lower: np.ndarray | None, upper: np.ndarray | None, count: int) -> tuple[np.ndarray, np.ndarray] | None:
    if lower is None or upper is None:
        return None
    low = np.asarray(lower, dtype=float)
    high = np.asarray(upper, dtype=float)
    if low.shape != (count,) or high.shape != (count,) or not np.isfinite(low).all() or not np.isfinite(high).all():
        return None
    return low, high


def _describe_end(widths: np.ndarray, bounds, body: float, reverse: bool, settings: HeadSilhouetteConfig) -> dict[str, Any]:
    rise, step = _first_rise(widths, body, settings.blunt_width_ratio, reverse, settings)
    persistence = _persistence(widths, step, reverse)
    discontinuity = _discontinuity(widths, body, reverse, settings)
    asymmetry = _asymmetry(widths, bounds, body, step, reverse)
    linearity = _linearity(widths, step, reverse)
    peduncle = _band_ratio(widths, body, settings.posterior_window_start, settings.posterior_window_stop, reverse)
    flare = _caudal_flare(widths, body, reverse, settings)
    near = {
        f"width_ratio_at_{int(round(fraction * 100))}pct": _round(_ratio_at(widths, body, fraction, reverse))
        for fraction in settings.near_width_fractions
    }
    series = widths[::-1] if reverse else widths
    terminal_span = min(len(series), max(3, int(round(len(series) * settings.rise_window_fraction))))
    terminal_ratio = float(np.median(series[:terminal_span])) / body
    taper_span = min(len(series), max(3, int(round(len(series) * settings.slanted_rise_fraction))))
    normalized_positions = np.arange(taper_span, dtype=float) / max(1, len(series) - 1)
    taper_slope = float(np.polyfit(normalized_positions, series[:taper_span] / body, 1)[0])
    blunt = rise is not None and rise <= settings.blunt_rise_fraction
    slanted = (
        rise is not None and rise <= settings.slanted_rise_fraction
        and persistence is not None and persistence >= settings.slanted_min_persistence
        and asymmetry is not None and asymmetry >= settings.slanted_min_asymmetry
    )
    irregular = (
        rise is not None and rise <= settings.irregular_rise_fraction
        and discontinuity >= settings.irregular_min_discontinuity
        and persistence is not None and persistence >= settings.irregular_min_persistence
    )
    character = "blunt" if blunt else "slanted" if slanted else "irregular" if irregular else None
    posterior = (peduncle is not None and peduncle <= settings.posterior_narrow_ratio) or flare
    if character is not None:
        role = "severed"
    elif posterior:
        role = "posterior"
    elif (
        character is None and persistence is not None and persistence < settings.snout_max_persistence
        and rise is not None and rise <= settings.snout_max_rise_fraction
    ):
        role = "snout"
    else:
        role = "ambiguous"
    return {
        "axis": "maximum_projection" if reverse else "minimum_projection",
        "role": role,
        "character": character,
        "rise_fraction": _round(rise),
        "slope_persistence": _round(persistence),
        "discontinuity": _round(discontinuity),
        "asymmetry": _round(asymmetry),
        "width_linearity": _round(linearity),
        "peduncle_ratio": _round(peduncle),
        "caudal_flare": flare,
        "near_end_width_ratios": near,
        "terminal_width_ratio": _round(terminal_ratio),
        "terminal_window_length_fraction": _round(terminal_span / len(series)),
        "abrupt_terminal_truncation": character is not None,
        "truncation_evidence": {
            "character": character,
            "rise_fraction": _round(rise),
            "discontinuity": _round(discontinuity),
            "slope_persistence": _round(persistence),
            "asymmetry": _round(asymmetry),
        },
        "body_taper": {
            "peduncle_width_ratio": _round(peduncle),
            "terminal_to_body_width_ratio": _round(terminal_ratio),
            "inward_width_slope": _round(taper_slope),
            "basis": "Width normalized by representative silhouette width and distance normalized by profile length; positive slope widens inward.",
        },
        "indicators": [name for name, active in (("blunt", blunt), ("slanted", slanted), ("irregular", irregular), ("posterior", posterior), ("caudal_flare", flare)) if active],
    }


def _first_rise(widths: np.ndarray, body: float, ratio: float, reverse: bool, settings: HeadSilhouetteConfig):
    count = len(widths)
    span = max(3, int(round(count * settings.rise_window_fraction)))
    limit = int(round(count * settings.slanted_rise_fraction))
    if limit <= span:
        return None, None
    series = widths[::-1] if reverse else widths
    for step in range(1, limit + 1):
        window = series[step:step + span]
        if len(window) < span:
            break
        if float(np.median(window)) >= ratio * body:
            return step / count, step
    return None, None


def _persistence(widths: np.ndarray, step: int | None, reverse: bool) -> float | None:
    if step is None:
        return None
    if step < 4:
        return 1.0
    series = widths[::-1] if reverse else widths

    def value(at: int) -> float:
        window = series[max(0, at - 1):at + 2]
        return float(np.median(window))

    gain_early = value(max(1, step // 2)) - value(1)
    gain_late = value(step) - value(max(1, step // 2))
    if gain_early <= 1e-6:
        return 1.0 if gain_late > 0 else 0.0
    return gain_late / gain_early


def _discontinuity(widths: np.ndarray, body: float, reverse: bool, settings: HeadSilhouetteConfig) -> float:
    count = len(widths)
    window = max(2, int(round(count * settings.discontinuity_window_fraction)))
    search = int(round(count * settings.discontinuity_search_fraction))
    series = widths[::-1] if reverse else widths
    peak = 0.0
    for start in range(0, max(1, search - window)):
        peak = max(peak, abs(float(series[start + window]) - float(series[start])) / body)
    return peak


def _asymmetry(widths: np.ndarray, bounds, body: float, step: int | None, reverse: bool) -> float | None:
    if bounds is None or step is None or step < 2:
        return None
    lower, upper = bounds
    centers = (lower + upper) / 2.0
    count = len(widths)
    axis = float(np.median(centers[count // 3:max(count // 3 + 1, 2 * count // 3)]))
    segment = centers[:step] if not reverse else centers[count - step:]
    if segment.size == 0 or not math.isfinite(axis):
        return None
    return float(np.max(np.abs(segment - axis)) / body)


def _linearity(widths: np.ndarray, step: int | None, reverse: bool) -> float | None:
    if step is None or step < 5:
        return None
    series = np.asarray(widths[::-1] if reverse else widths, dtype=float)
    sample = series[1:step]
    if sample.size < 4 or float(np.ptp(sample)) < 1:
        return None
    slope, intercept = np.polyfit(np.arange(sample.size, dtype=float), sample, 1)
    predicted = slope * np.arange(sample.size) + intercept
    residual = float(np.sum((sample - predicted) ** 2))
    total = float(np.sum((sample - float(sample.mean())) ** 2))
    if total <= 1e-9:
        return None
    return max(0.0, 1.0 - residual / total)


def _ratio_at(widths: np.ndarray, body: float, fraction: float, reverse: bool) -> float:
    count = len(widths)
    span = max(1, int(round(count * 0.015)))
    center = int(round((count - 1) * (1.0 - fraction if reverse else fraction)))
    window = widths[max(0, center - span):min(count, center + span + 1)]
    return float(np.median(window)) / body


def _band_ratio(widths: np.ndarray, body: float, start: float, stop: float, reverse: bool) -> float | None:
    count = len(widths)
    first = int(round(count * start))
    second = int(round(count * stop))
    segment = widths[count - second:count - first] if reverse else widths[first:second]
    if len(segment) < 3:
        return None
    return float(np.median(segment)) / body


def _caudal_flare(widths: np.ndarray, body: float, reverse: bool, settings: HeadSilhouetteConfig) -> bool:
    tip = _band_ratio(widths, body, settings.flare_tip_start, settings.flare_tip_stop, reverse)
    peduncle = _band_ratio(widths, body, settings.flare_peduncle_start, settings.flare_peduncle_stop, reverse)
    if tip is None or peduncle is None:
        return False
    return (
        peduncle <= settings.flare_max_peduncle_ratio
        and tip >= peduncle * settings.flare_gain
        and tip - peduncle >= settings.flare_min_gain
    )


def _round(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), 4)
