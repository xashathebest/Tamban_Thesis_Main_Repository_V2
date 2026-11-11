"""Model-free skeleton, native transects and provisional terminal-plane evidence.

Scores are engineering evidence, never probabilities. Numeric decision limits
are explicitly provisional until independently labeled masks are available.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import heapq
import math

import cv2
import numpy as np

from src.features.morphology import zhang_suen_skeleton
from src.inference.anatomical_measurements import _binary, _region_pixels, _selected
from src.inference.fish_geometry import FishGeometryConfig


METHOD = "skeleton_native_terminal_plane_v1"
FEATURES = ("anterior_to_body_width_ratio", "anterior_taper_ratio", "endpoint_flatness",
            "contour_curvature", "abrupt_body_termination", "normalized_anterior_shape_deviation")


@dataclass(frozen=True)
class ProvisionalHeadGeometryConfig:
    skeleton_max_dimension: int = 1024
    skeleton_max_iterations: int = 256
    profile_samples: int = 101
    native_ray_step_px: float = .5
    anterior_window_fraction: float = .30
    minimum_front_coverage: float = .90
    maximum_front_flatness: float = .025
    minimum_termination_jump: float = .90
    maximum_branch_fraction: float = .25
    plane_offset_body_fraction: float = .05
    score_threshold: float = 1.0


def _path(skeleton, scales):
    points = np.argwhere(skeleton)
    nodes = {tuple(p) for p in points.tolist()}
    if not nodes:
        return None, 0
    offsets = [(dy, dx, math.hypot(dx * scales[0], dy * scales[1]))
               for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy]

    def farthest(start):
        distances, previous, queue = {start: 0.}, {}, [(0., start)]
        while queue:
            distance, node = heapq.heappop(queue)
            if distance != distances[node]:
                continue
            for dy, dx, cost in offsets:
                other = node[0] + dy, node[1] + dx
                candidate = distance + cost
                if other in nodes and candidate < distances.get(other, float("inf")):
                    distances[other], previous[other] = candidate, node
                    heapq.heappush(queue, (candidate, other))
        end = max(distances, key=distances.get)
        return end, previous, distances

    end, _, _ = farthest(tuple(points[0]))
    other, previous, distances = farthest(end)
    ordered = [other]
    while ordered[-1] != end:
        ordered.append(previous[ordered[-1]])
    xy = np.asarray([(x * scales[0], y * scales[1]) for y, x in ordered], dtype=float)
    return xy, len(distances)


def _inside(mask, xy):
    points = np.rint(xy).astype(np.int64)
    valid = ((points[:, 0] >= 0) & (points[:, 0] < mask.shape[1])
             & (points[:, 1] >= 0) & (points[:, 1] < mask.shape[0]))
    result = np.zeros(len(points), bool)
    result[valid] = mask[points[valid, 1], points[valid, 0]] > 0
    return result


def _resample(path, count):
    distances = np.r_[0., np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
    positions = np.linspace(0, distances[-1], count)
    return np.column_stack([np.interp(positions, distances, path[:, dim]) for dim in (0, 1)])


def _extend(mask, point, direction, step):
    ray = np.arange(0, max(mask.shape) * 1.5, step)
    present = _inside(mask, point + ray[:, None] * direction)
    absent = np.flatnonzero(~present)
    last = max(0, int(absent[0]) - 1) if len(absent) else len(ray) - 1
    return point + ray[last] * direction


def measure_mathematical_head_geometry(mask, parts=(), *, anatomy=None, config=None,
                                        minimum_part_confidence=.25, geometry_config=None):
    cfg, rules = config or ProvisionalHeadGeometryConfig(), geometry_config or FishGeometryConfig()
    result = {"method": METHOD, "status": "unavailable", "reasons": [], "features": {key: None for key in FEATURES},
              "centerline_px": [], "width_profile": [], "orientation_reliable": False,
              "orientation_source": None, "provisional": True, "calibrated": False,
              "score": None, "score_threshold": cfg.score_threshold, "supports_head_removal": False,
              "thresholds": asdict(cfg), "threshold_basis": "Conservative provisional engineering limits; not fitted to these images.",
              "used_for_grading": False, "native_pixels_modified": False,
              "feature_definitions": {
                  "endpoint_flatness": "RMS residual of a terminal front-line fit divided by median interior width; permits slanted planes.",
                  "contour_curvature": "Median dimensionless second derivative of the observed terminal front contour.",
                  "abrupt_body_termination": "Foreground occupancy jump across the fitted terminal plane.",
                  "normalized_anterior_shape_deviation": "Mean absolute width-profile difference from an ideal smooth zero-tip ellipse, normalized by Body width; a geometric surrogate, not an intact-fish reference."}}
    binary = _binary(mask)
    if binary is None or binary.sum() < rules.minimum_mask_pixels:
        result["reasons"].append("insufficient_native_mask_support")
        return result
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    native = (labels == largest).astype(np.uint8)
    secondary = 1 - int(native.sum()) / int(binary.sum())
    if secondary > rules.maximum_secondary_component_fraction:
        result["reasons"].append("fragmented_native_mask")
    x, y, width, height = cv2.boundingRect(native)
    local = np.pad(native[y:y + height, x:x + width], 2)
    scale = min(1., cfg.skeleton_max_dimension / max(local.shape))
    work = cv2.resize(local, (max(3, round(local.shape[1] * scale)), max(3, round(local.shape[0] * scale))),
                      interpolation=cv2.INTER_NEAREST)
    scales = local.shape[1] / work.shape[1], local.shape[0] / work.shape[0]
    skeleton, converged, iterations = zhang_suen_skeleton(work, cfg.skeleton_max_iterations)
    path, reached = _path(skeleton, scales)
    result["skeleton"] = {"method": "zhang_suen_weighted_geodesic_diameter", "converged": converged,
        "iterations": iterations, "working_shape": list(work.shape), "scale_to_native": list(scales),
        "resampled": scale < 1., "pixels": int(skeleton.sum()), "reachable_pixels": reached}
    if not converged or path is None or len(path) < 3:
        result["reasons"].append("skeleton_not_resolved")
        return result
    branch_fraction = 1 - len(path) / max(1, int(skeleton.sum()))
    result["skeleton"]["branch_fraction"] = round(branch_fraction, 6)
    if branch_fraction > cfg.maximum_branch_fraction:
        result["reasons"].append("branched_skeleton_uncertain")
    path += np.array((x - 2, y - 2))
    path = _resample(path, cfg.profile_samples)
    smooth = path.copy()
    for index in range(2, len(path) - 2):
        smooth[index] = path[index - 2:index + 3].mean(axis=0)
    for end, other in ((0, 4), (-1, -5)):
        direction = smooth[end] - smooth[other]
        norm = np.linalg.norm(direction)
        if norm <= 0:
            result["reasons"].append("degenerate_centerline_tangent")
            return result
        smooth[end] = _extend(native, smooth[end], direction / norm, cfg.native_ray_step_px)
    path = _resample(smooth, cfg.profile_samples)
    # PCA assists consistency/polarity; it does not decide which image side is Head.
    ys, xs = np.nonzero(native)
    covariance = np.cov(np.column_stack((xs, ys)), rowvar=False)
    values, vectors = np.linalg.eigh(covariance)
    axis = vectors[:, -1]
    supplied = (anatomy or {}).get("orientation_axis_vector")
    if supplied is not None and np.dot(axis, supplied) < 0:
        axis = -axis
    axis_ratio = math.sqrt(max(values[-1], 0) / max(values[0], 1e-9))
    result["pca"] = {"axis": np.round(axis, 6).tolist(), "axis_ratio": round(axis_ratio, 6)}
    if axis_ratio < rules.minimum_axis_ratio:
        result["reasons"].append("pca_orientation_uncertain")
    tail_parts = _selected(parts, "Tail", minimum_part_confidence)
    head_parts = _selected(parts, "Head", minimum_part_confidence)
    anterior_first = None
    if len(tail_parts) == 1:
        pixels = _region_pixels(tail_parts[0], native.shape, native)
        if pixels is not None and pixels.any():
            ty, tx = np.nonzero(pixels)
            tail_index = int(np.argmin(np.linalg.norm(path - (tx.mean(), ty.mean()), axis=1)))
            tail_position = tail_index / (len(path) - 1)
            result["tail_centerline_position"] = round(tail_position, 6)
            if abs(tail_position - .5) >= .18:
                anterior_first = tail_position > .5
                result["orientation_source"] = "owned_model2_tail_and_skeleton"
    if anterior_first is None and not tail_parts and (anatomy or {}).get("anatomical_orientation_reliable"):
        cut = (anatomy or {}).get("cut_end_axis")
        if cut in {"minimum_projection", "maximum_projection"}:
            minimum_first = np.dot(path[0], axis) < np.dot(path[-1], axis)
            anterior_first = minimum_first == (cut == "minimum_projection")
            result["orientation_source"] = "existing_silhouette_polarity_and_skeleton"
    if len(tail_parts) > 1:
        result["reasons"].append("multiple_tail_detections")
    if anterior_first is None:
        result["reasons"].append("anterior_posterior_not_resolved")
    elif not anterior_first:
        path = path[::-1].copy()
    result["orientation_reliable"] = anterior_first is not None and axis_ratio >= rules.minimum_axis_ratio
    if head_parts:
        result["reasons"].append("accepted_head_detection_present")
    distances = np.r_[0., np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
    length = float(distances[-1])
    result["fish_length_px"] = round(length, 4)
    tangents = np.gradient(path, axis=0)
    tangents /= np.maximum(np.linalg.norm(tangents, axis=1)[:, None], 1e-9)
    normals = np.column_stack((-tangents[:, 1], tangents[:, 0]))
    widths = []
    for point, normal in zip(path, normals):
        ends = [_extend(native, point, sign * normal, cfg.native_ray_step_px) for sign in (-1, 1)]
        widths.append(float(np.linalg.norm(ends[1] - ends[0]) + 1.))
    widths = np.asarray(widths)
    body_width = float(np.median(widths[30:71]))
    result.update(status="measured", centerline_px=np.round(path, 4).tolist(), body_width_px=round(body_width, 4),
        coordinate_space="crop_local_native_pixels", width_profile=[{"position": round(float(t), 4),
        "width_px": round(float(w), 4), "width_to_body_ratio": round(float(w / max(body_width, 1)), 6)}
        for t, w in zip(np.linspace(0, 1, len(widths)), widths)])
    if body_width < rules.minimum_transverse_pixels or length <= body_width:
        result["reasons"].append("insufficient_anatomical_resolution")
        return result
    terminal = float(np.median(widths[:3])) / body_width
    near = float(np.median(widths[8:15])) / body_width
    result["features"]["anterior_to_body_width_ratio"] = round(terminal, 6)
    result["features"]["anterior_taper_ratio"] = round(terminal / max(near, 1e-9), 6)
    result["posterior_width_ratio"] = round(float(np.median(widths[78:89])) / body_width, 6)
    if not result["orientation_reliable"]:
        return result
    tangent = path[4] - path[0]
    tangent /= max(np.linalg.norm(tangent), 1e-9)
    normal = np.array((-tangent[1], tangent[0]))
    transverse = np.linspace(-.45, .45, 61) * body_width
    ray = np.arange(-body_width, cfg.anterior_window_fraction * length, cfg.native_ray_step_px)
    hits, accepted_t = [], []
    for offset in transverse:
        present = _inside(native, path[0] + normal * offset + ray[:, None] * tangent)
        indices = np.flatnonzero(present)
        if len(indices):
            hits.append(float(ray[indices[0]])); accepted_t.append(float(offset))
    coverage = len(hits) / len(transverse)
    result["terminal_front_coverage"] = round(coverage, 6)
    if len(hits) < 3:
        result["reasons"].append("terminal_front_not_resolved")
        return result
    hits, accepted_t = np.asarray(hits), np.asarray(accepted_t)
    slope, intercept = np.polyfit(accepted_t, hits, 1)
    predicted = slope * accepted_t + intercept
    flatness = float(np.sqrt(np.mean((hits - predicted) ** 2))) / body_width
    curvature = float(np.median(np.abs(np.diff(hits / body_width, n=2)))) / max((.9 / 60) ** 2, 1e-9)
    plane = path[0] + accepted_t[:, None] * normal + predicted[:, None] * tangent
    delta = cfg.plane_offset_body_fraction * body_width * tangent
    before, after = float(_inside(native, plane - delta).mean()), float(_inside(native, plane + delta).mean())
    jump = after - before
    u = np.linspace(0, 1, 31)
    ideal = np.sqrt(np.maximum(0, 2 * u - u * u))
    deviation = float(np.mean(np.abs(widths[:31] / body_width - ideal)))
    result["features"].update(endpoint_flatness=round(flatness, 6), contour_curvature=round(curvature, 6),
        abrupt_body_termination=round(jump, 6), normalized_anterior_shape_deviation=round(deviation, 6))
    result["terminal_plane"] = {"slope": round(float(slope), 6), "intercept_px": round(float(intercept), 4),
        "occupancy_before": before, "occupancy_after": after,
        "contour_samples": [[round(float(t / body_width), 6), round(float(h / body_width), 6)]
                            for t, h in zip(accepted_t, hits)]}
    indicators = {"resolved_front": coverage >= cfg.minimum_front_coverage,
        "flat_or_slanted_plane": flatness <= cfg.maximum_front_flatness,
        "abrupt_termination": jump >= cfg.minimum_termination_jump,
        "posterior_taper": result["posterior_width_ratio"] <= .62}
    result["indicators"] = indicators
    result["score"] = sum(indicators.values()) / len(indicators)
    result["supports_head_removal"] = (result["score"] >= cfg.score_threshold and not result["reasons"]
        and result["orientation_source"] == "owned_model2_tail_and_skeleton")
    result["reasons"] += [name + "_not_confirmed" for name, passed in indicators.items() if not passed]
    return result
