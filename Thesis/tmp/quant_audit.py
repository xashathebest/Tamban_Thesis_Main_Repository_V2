from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1] / "sardinella-lemuru-ml" / "dataset" / "raw"
OUT = Path(__file__).resolve().parent / "quant_audit"
CLASSES = ["Class_A", "Class_B", "Class_C", "Rejected"]
EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
MAX_DIM = 1280
RNG = np.random.default_rng(20260904)


def safe_div(a: float, b: float) -> float:
    return float(a / b) if b else float("nan")


def resize_for_analysis(image: np.ndarray) -> tuple[np.ndarray, float]:
    h, w = image.shape[:2]
    scale = min(1.0, MAX_DIM / max(h, w))
    if scale < 1.0:
        image = cv2.resize(image, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    return image, scale


def fill_external_contours(binary: np.ndarray) -> np.ndarray:
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(binary)
    cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
    return filled


def segment_foreground(image: np.ndarray) -> tuple[np.ndarray, dict[str, float]]:
    """Segment bright/chromatic fish from the dark conveyor using per-image Otsu."""
    h, w = image.shape[:2]
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lightness = lab[:, :, 0]
    blurred = cv2.GaussianBlur(lightness, (7, 7), 0)
    threshold, raw = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Relative kernels make the cleanup stable after all images are resized to a common ceiling.
    close_size = max(3, int(round(min(h, w) * 0.008)) | 1)
    open_size = max(3, int(round(min(h, w) * 0.0025)) | 1)
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_size, close_size))
    open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_size, open_size))
    cleaned = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, close_kernel)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, open_kernel)
    cleaned = fill_external_contours(cleaned)

    # Remove conveyor texture/debris. This is a segmentation noise floor, not a class rule.
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(cleaned, 8)
    min_keep = max(64, int(round(h * w * 0.00010)))
    mask = np.zeros((h, w), np.uint8)
    kept = 0
    for label in range(1, n_labels):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area >= min_keep:
            mask[labels == label] = 255
            kept += 1

    return mask, {
        "otsu_L8": float(threshold),
        "seg_min_keep_px": float(min_keep),
        "seg_kept_raw_components": float(kept),
    }


def component_geometry(component_mask: np.ndarray, image_area: int) -> dict[str, float] | None:
    contours, _ = cv2.findContours(component_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    area = float(np.count_nonzero(component_mask))
    perimeter = float(cv2.arcLength(contour, True))
    hull = cv2.convexHull(contour)
    hull_area = float(cv2.contourArea(hull))
    hull_perimeter = float(cv2.arcLength(hull, True))
    (_, _), (rect_w, rect_h), _ = cv2.minAreaRect(contour)
    rect_long = float(max(rect_w, rect_h))
    rect_short = float(min(rect_w, rect_h))

    ys, xs = np.nonzero(component_mask)
    coords = np.column_stack((xs, ys)).astype(np.float64)
    centered = coords - coords.mean(axis=0, keepdims=True)
    covariance = np.cov(centered, rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    major = eigenvectors[:, int(np.argmax(eigenvalues))]
    minor = np.array([-major[1], major[0]])
    longitudinal = centered @ major
    transverse = centered @ minor
    lo, hi = np.percentile(longitudinal, [0.5, 99.5])
    pca_length = float(max(hi - lo, 1.0))

    positions = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    widths: list[float] = []
    half_window = max(1.5, pca_length * 0.015)
    for position in positions:
        target = lo + position * pca_length
        section = transverse[np.abs(longitudinal - target) <= half_window]
        if len(section) >= 5:
            width = float(np.percentile(section, 99) - np.percentile(section, 1))
        else:
            width = float("nan")
        widths.append(width / pca_length)

    # Orient the profile consistently by treating the broader end as the approximate head side.
    if np.nanmean(widths[:2]) < np.nanmean(widths[-2:]):
        widths = widths[::-1]

    h, w = component_mask.shape
    touches_border = bool(
        np.any(component_mask[0, :])
        or np.any(component_mask[-1, :])
        or np.any(component_mask[:, 0])
        or np.any(component_mask[:, -1])
    )

    result = {
        "area_px": area,
        "area_fraction": area / image_area,
        "perimeter_px": perimeter,
        "solidity": safe_div(area, hull_area),
        "contour_irregularity": safe_div(perimeter, hull_perimeter),
        "circularity": safe_div(4.0 * math.pi * area, perimeter * perimeter),
        "rect_length_px": rect_long,
        "rect_width_px": rect_short,
        "rect_width_length": safe_div(rect_short, rect_long),
        "rect_extent": safe_div(area, rect_long * rect_short),
        "pca_length_px": pca_length,
        "normalized_area": safe_div(area, pca_length * pca_length),
        "touches_border": float(touches_border),
    }
    for pos, width in zip(positions, widths):
        result[f"w{round(pos * 100)}_length"] = width
    middle = np.array(widths[1:-1], dtype=float)
    result["middle_width_length"] = float(np.nanmean(middle))
    result["profile_max_width_length"] = float(np.nanmax(widths))
    result["profile_width_cv"] = safe_div(float(np.nanstd(middle)), float(np.nanmean(middle)))
    result["end_width_asymmetry"] = safe_div(abs(widths[0] - widths[-1]), np.nanmean(widths))
    return result


def glcm_features(gray: np.ndarray, mask: np.ndarray, levels: int = 16) -> dict[str, float]:
    quantized = np.minimum(gray.astype(np.int32) * levels // 256, levels - 1)
    matrix = np.zeros((levels, levels), dtype=np.float64)
    shifts = [(0, 1), (1, 0), (1, 1), (1, -1)]
    for dy, dx in shifts:
        if dx >= 0:
            x1 = slice(0, gray.shape[1] - dx if dx else None)
            x2 = slice(dx, None)
        else:
            x1 = slice(-dx, None)
            x2 = slice(0, dx)
        y1 = slice(0, gray.shape[0] - dy if dy else None)
        y2 = slice(dy, None)
        valid = (mask[y1, x1] > 0) & (mask[y2, x2] > 0)
        a = quantized[y1, x1][valid]
        b = quantized[y2, x2][valid]
        if len(a):
            matrix += np.bincount(a * levels + b, minlength=levels * levels).reshape(levels, levels)
    total = matrix.sum()
    if total <= 0:
        return {name: float("nan") for name in ["glcm_contrast", "glcm_homogeneity", "glcm_energy", "glcm_entropy"]}
    probability = matrix / total
    i, j = np.indices(probability.shape)
    nonzero = probability > 0
    return {
        "glcm_contrast": float(np.sum(probability * (i - j) ** 2)),
        "glcm_homogeneity": float(np.sum(probability / (1.0 + np.abs(i - j)))),
        "glcm_energy": float(np.sum(probability**2)),
        "glcm_entropy": float(-np.sum(probability[nonzero] * np.log2(probability[nonzero]))),
    }


def lbp_entropy(gray: np.ndarray, mask: np.ndarray) -> float:
    center = gray[1:-1, 1:-1]
    valid = mask[1:-1, 1:-1] > 0
    neighbors = [
        gray[:-2, :-2], gray[:-2, 1:-1], gray[:-2, 2:], gray[1:-1, 2:],
        gray[2:, 2:], gray[2:, 1:-1], gray[2:, :-2], gray[1:-1, :-2],
    ]
    code = np.zeros_like(center, dtype=np.uint8)
    for bit, neighbor in enumerate(neighbors):
        code |= ((neighbor >= center).astype(np.uint8) << bit)
    values = code[valid]
    if not len(values):
        return float("nan")
    histogram = np.bincount(values, minlength=256).astype(float)
    probability = histogram[histogram > 0] / histogram.sum()
    return float(-np.sum(probability * np.log2(probability)))


def robust_stats(values: np.ndarray, prefix: str) -> dict[str, float]:
    values = values[np.isfinite(values)]
    if not len(values):
        return {f"{prefix}_{name}": float("nan") for name in ["mean", "median", "std", "p10", "p90"]}
    return {
        f"{prefix}_mean": float(np.mean(values)),
        f"{prefix}_median": float(np.median(values)),
        f"{prefix}_std": float(np.std(values)),
        f"{prefix}_p10": float(np.percentile(values, 10)),
        f"{prefix}_p90": float(np.percentile(values, 90)),
    }


def sample_values(values: np.ndarray, count: int = 2500) -> np.ndarray:
    if len(values) <= count:
        return values.copy()
    indices = RNG.choice(len(values), size=count, replace=False)
    return values[indices]


def aggregate_components(component_records: list[dict[str, float]], row: dict[str, float]) -> None:
    if not component_records:
        return
    comp = pd.DataFrame(component_records)
    nonborder = comp.loc[comp["touches_border"] == 0]
    usable = nonborder if len(nonborder) else comp
    row["analysis_blob_count"] = float(len(comp))
    row["nonborder_blob_count"] = float(len(nonborder))
    row["border_blob_fraction"] = float(comp["touches_border"].mean())
    for column in [
        "area_fraction", "solidity", "contour_irregularity", "circularity",
        "rect_width_length", "rect_extent", "normalized_area", "middle_width_length",
        "profile_max_width_length", "profile_width_cv", "end_width_asymmetry",
        "w20_length", "w30_length", "w40_length", "w50_length", "w60_length",
        "w70_length", "w80_length",
    ]:
        row[f"blob_{column}_median"] = float(usable[column].median())
        row[f"blob_{column}_iqr"] = float(usable[column].quantile(0.75) - usable[column].quantile(0.25))


def analyze_image(path: Path, label: str, image_index: int) -> tuple[dict[str, float | str], list[dict[str, float | str]], dict[str, np.ndarray], tuple[np.ndarray, np.ndarray]]:
    original = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if original is None:
        raise ValueError(f"OpenCV could not decode {path}")
    original_h, original_w = original.shape[:2]
    image, resize_scale = resize_for_analysis(original)
    h, w = image.shape[:2]
    mask, seg = segment_foreground(image)
    foreground = mask > 0
    foreground_count = int(foreground.sum())
    if foreground_count == 0:
        raise ValueError(f"No foreground segmented in {path}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    lab8 = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lstar = lab8[:, :, 0].astype(np.float32) * (100.0 / 255.0)
    astar = lab8[:, :, 1].astype(np.float32) - 128.0
    bstar = lab8[:, :, 2].astype(np.float32) - 128.0
    saturation = hsv[:, :, 1].astype(np.float32) / 255.0
    value = hsv[:, :, 2].astype(np.float32) / 255.0
    chroma = np.sqrt(astar * astar + bstar * bstar)

    fg_l = lstar[foreground]
    fg_a = astar[foreground]
    fg_b = bstar[foreground]
    fg_s = saturation[foreground]
    fg_v = value[foreground]
    fg_chroma = chroma[foreground]
    background = ~foreground

    row: dict[str, float | str] = {
        "class": label,
        "filename": path.name,
        "path": str(path),
        "image_index": float(image_index),
        "original_width": float(original_w),
        "original_height": float(original_h),
        "analysis_width": float(w),
        "analysis_height": float(h),
        "resize_scale": float(resize_scale),
        "file_bytes": float(path.stat().st_size),
        "foreground_fraction": float(foreground.mean()),
        **seg,
        **robust_stats(fg_l, "Lstar"),
        **robust_stats(fg_a, "astar"),
        **robust_stats(fg_b, "bstar"),
        **robust_stats(fg_chroma, "chroma"),
        **robust_stats(fg_s, "saturation"),
        **robust_stats(fg_v, "value"),
    }
    row["image_gray_mean"] = float(gray.mean())
    row["background_Lstar_median"] = float(np.median(lstar[background])) if np.any(background) else float("nan")
    row["background_Lstar_p90"] = float(np.percentile(lstar[background], 90)) if np.any(background) else float("nan")
    row["foreground_background_L_contrast"] = float(row["Lstar_median"] - row["background_Lstar_median"])

    erode_size = max(3, int(round(min(h, w) * 0.003)) | 1)
    eroded = cv2.erode(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode_size, erode_size)))
    inner = eroded > 0
    if not np.any(inner):
        inner = foreground
        eroded = mask
    sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(sobel_x, sobel_y)
    laplacian = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    row.update(robust_stats(gradient[inner], "gradient"))
    row["laplacian_abs_mean"] = float(np.mean(np.abs(laplacian[inner])))
    row["laplacian_variance"] = float(np.var(laplacian[inner]))
    histogram = np.bincount(gray[inner], minlength=256).astype(float)
    probability = histogram[histogram > 0] / histogram.sum()
    row["gray_entropy"] = float(-np.sum(probability * np.log2(probability)))
    row["lbp_entropy"] = lbp_entropy(gray, eroded)
    row.update(glcm_features(gray, eroded))

    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    image_area = h * w
    fragment_floor = max(64, int(round(image_area * 0.00025)))
    analysis_floor = max(128, int(round(image_area * 0.00100)))
    component_areas = [int(stats[i, cv2.CC_STAT_AREA]) for i in range(1, n_labels) if int(stats[i, cv2.CC_STAT_AREA]) >= fragment_floor]
    row["foreground_blob_count"] = float(len(component_areas))
    row["fragmentation_index"] = float(1.0 - max(component_areas) / sum(component_areas)) if component_areas else float("nan")
    row["largest_blob_foreground_share"] = float(max(component_areas) / sum(component_areas)) if component_areas else float("nan")
    row["component_area_cv"] = safe_div(float(np.std(component_areas)), float(np.mean(component_areas))) if component_areas else float("nan")

    component_rows: list[dict[str, float | str]] = []
    geometry_rows: list[dict[str, float]] = []
    for component_id in range(1, n_labels):
        area = int(stats[component_id, cv2.CC_STAT_AREA])
        if area < analysis_floor:
            continue
        component_mask = (labels == component_id).astype(np.uint8) * 255
        geometry = component_geometry(component_mask, image_area)
        if geometry is None:
            continue
        geometry_rows.append(geometry)
        component_rows.append({
            "class": label,
            "filename": path.name,
            "component_id": float(component_id),
            **geometry,
        })
    aggregate_components(geometry_rows, row)

    samples = {
        "Lstar": sample_values(fg_l),
        "astar": sample_values(fg_a),
        "bstar": sample_values(fg_b),
        "saturation": sample_values(fg_s),
        "value": sample_values(fg_v),
        "gradient": sample_values(gradient[inner]),
    }
    return row, component_rows, samples, (image, mask)


def rank_auc(values: np.ndarray, positive: np.ndarray) -> float:
    valid = np.isfinite(values)
    values = values[valid]
    positive = positive[valid].astype(bool)
    n_pos = int(positive.sum())
    n_neg = int((~positive).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = pd.Series(values).rank(method="average").to_numpy()
    return float((ranks[positive].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def eta_squared(frame: pd.DataFrame, feature: str) -> float:
    valid = frame[["class", feature]].dropna()
    if len(valid) < 2:
        return float("nan")
    values = valid[feature].to_numpy(float)
    grand = values.mean()
    total = float(np.sum((values - grand) ** 2))
    between = 0.0
    for _, group in valid.groupby("class"):
        between += len(group) * (float(group[feature].mean()) - grand) ** 2
    return safe_div(between, total)


def cliffs_delta(x: np.ndarray, y: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    y = y[np.isfinite(y)]
    if not len(x) or not len(y):
        return float("nan")
    # Broadcasting is modest here (at most a few hundred image-level observations).
    differences = x[:, None] - y[None, :]
    return float((np.count_nonzero(differences > 0) - np.count_nonzero(differences < 0)) / differences.size)


def median_iqr(series: pd.Series) -> str:
    series = series.dropna().astype(float)
    if not len(series):
        return "NA"
    return f"{series.median():.4g} [{series.quantile(0.25):.4g}, {series.quantile(0.75):.4g}]"


def add_empirical_ratios(rows: list[dict[str, float | str]], samples_by_image: list[dict[str, np.ndarray]]) -> dict[str, float]:
    pooled = {key: np.concatenate([sample[key] for sample in samples_by_image]) for key in samples_by_image[0]}
    thresholds = {
        "L10": float(np.percentile(pooled["Lstar"], 10)),
        "L50": float(np.percentile(pooled["Lstar"], 50)),
        "L90": float(np.percentile(pooled["Lstar"], 90)),
        "b75": float(np.percentile(pooled["bstar"], 75)),
        "b90": float(np.percentile(pooled["bstar"], 90)),
        "S25": float(np.percentile(pooled["saturation"], 25)),
        "G75": float(np.percentile(pooled["gradient"], 75)),
    }
    for row, sample in zip(rows, samples_by_image):
        lstar = sample["Lstar"]
        bstar = sample["bstar"]
        saturation = sample["saturation"]
        gradient = sample["gradient"]
        warm = bstar >= thresholds["b75"]
        row["warm_chroma_ratio_pooled_q75"] = float(np.mean(warm))
        row["strong_warm_ratio_pooled_q90"] = float(np.mean(bstar >= thresholds["b90"]))
        row["yellow_proxy_ratio"] = float(np.mean(warm & (lstar >= thresholds["L50"])))
        row["brown_proxy_ratio"] = float(np.mean(warm & (lstar < thresholds["L50"])))
        row["dark_ratio_pooled_q10"] = float(np.mean(lstar <= thresholds["L10"]))
        row["specular_proxy_ratio"] = float(np.mean((lstar >= thresholds["L90"]) & (saturation <= thresholds["S25"])))
        row["high_gradient_ratio_pooled_q75"] = float(np.mean(gradient >= thresholds["G75"]))
    return thresholds


def make_qc_montage(qc_images: dict[str, list[tuple[np.ndarray, np.ndarray, str]]]) -> None:
    tiles: list[np.ndarray] = []
    for label in CLASSES:
        for image, mask, filename in qc_images[label]:
            target_w = 480
            scale = target_w / image.shape[1]
            tile = cv2.resize(image, (target_w, round(image.shape[0] * scale)), interpolation=cv2.INTER_AREA)
            tile_mask = cv2.resize(mask, (tile.shape[1], tile.shape[0]), interpolation=cv2.INTER_NEAREST)
            contours, _ = cv2.findContours(tile_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            overlay = tile.copy()
            cv2.drawContours(overlay, contours, -1, (0, 255, 0), 2)
            cv2.putText(overlay, f"{label}: {filename}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 2, cv2.LINE_AA)
            tiles.append(overlay)
    max_h = max(tile.shape[0] for tile in tiles)
    padded = [cv2.copyMakeBorder(tile, 0, max_h - tile.shape[0], 0, 0, cv2.BORDER_CONSTANT) for tile in tiles]
    rows = [np.hstack(padded[index:index + 4]) for index in range(0, len(padded), 4)]
    montage = np.vstack(rows)
    cv2.imwrite(str(OUT / "segmentation_qc.jpg"), montage, [cv2.IMWRITE_JPEG_QUALITY, 90])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    paths: list[tuple[str, Path]] = []
    for label in CLASSES:
        label_paths = sorted(path for path in (ROOT / label).iterdir() if path.is_file() and path.suffix.lower() in EXTENSIONS)
        paths.extend((label, path) for path in label_paths)
    print(f"Found {len(paths)} decodable candidates: " + ", ".join(f"{label}={sum(1 for x, _ in paths if x == label)}" for label in CLASSES), flush=True)

    rows: list[dict[str, float | str]] = []
    component_rows: list[dict[str, float | str]] = []
    samples_by_image: list[dict[str, np.ndarray]] = []
    failures: list[dict[str, str]] = []
    qc_candidates: dict[str, list[tuple[np.ndarray, np.ndarray, str]]] = defaultdict(list)
    counts = {label: sum(1 for x, _ in paths if x == label) for label in CLASSES}
    class_seen = defaultdict(int)
    qc_indices = {label: {0, counts[label] // 2, counts[label] - 1} for label in CLASSES}

    for index, (label, path) in enumerate(paths):
        local_index = class_seen[label]
        class_seen[label] += 1
        try:
            row, comps, samples, qc = analyze_image(path, label, index)
            rows.append(row)
            component_rows.extend(comps)
            samples_by_image.append(samples)
            if local_index in qc_indices[label]:
                qc_candidates[label].append((qc[0], qc[1], path.name))
        except Exception as exc:
            failures.append({"class": label, "path": str(path), "error": repr(exc)})
        if (index + 1) % 50 == 0 or index + 1 == len(paths):
            print(f"Processed {index + 1}/{len(paths)}; failures={len(failures)}", flush=True)

    thresholds = add_empirical_ratios(rows, samples_by_image)
    frame = pd.DataFrame(rows)
    components = pd.DataFrame(component_rows)
    frame.to_csv(OUT / "image_features.csv", index=False)
    components.to_csv(OUT / "connected_blob_features.csv", index=False)
    (OUT / "failures.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")
    (OUT / "empirical_pixel_thresholds.json").write_text(json.dumps(thresholds, indent=2), encoding="utf-8")
    make_qc_montage(qc_candidates)

    excluded = {
        "image_index", "original_width", "original_height", "analysis_width", "analysis_height",
        "resize_scale", "seg_min_keep_px", "seg_kept_raw_components",
    }
    numeric_features = [
        column for column in frame.select_dtypes(include=[np.number]).columns
        if column not in excluded and frame[column].nunique(dropna=True) > 1
    ]
    effects: list[dict[str, float | str]] = []
    for feature in numeric_features:
        values = frame[feature].to_numpy(float)
        record: dict[str, float | str] = {"feature": feature, "eta_squared": eta_squared(frame, feature)}
        for label in CLASSES:
            positive = frame["class"].eq(label).to_numpy()
            auc = rank_auc(values, positive)
            record[f"{label}_auc"] = auc
            record[f"{label}_separation_auc"] = max(auc, 1.0 - auc) if np.isfinite(auc) else float("nan")
            record[f"{label}_direction"] = "higher" if auc >= 0.5 else "lower"
        effects.append(record)
    effect_frame = pd.DataFrame(effects).sort_values("eta_squared", ascending=False)
    effect_frame.to_csv(OUT / "feature_effects.csv", index=False)

    selected = [
        "foreground_fraction", "foreground_blob_count", "fragmentation_index", "largest_blob_foreground_share",
        "border_blob_fraction", "blob_rect_width_length_median", "blob_normalized_area_median",
        "blob_middle_width_length_median", "blob_solidity_median", "blob_contour_irregularity_median",
        "Lstar_median", "bstar_median", "bstar_p90", "warm_chroma_ratio_pooled_q75",
        "strong_warm_ratio_pooled_q90", "yellow_proxy_ratio", "brown_proxy_ratio",
        "dark_ratio_pooled_q10", "specular_proxy_ratio", "gradient_mean",
        "high_gradient_ratio_pooled_q75", "gray_entropy", "lbp_entropy", "glcm_contrast",
        "glcm_homogeneity", "background_Lstar_median", "foreground_background_L_contrast",
    ]
    selected = [feature for feature in selected if feature in frame.columns]
    summary_lines = []
    for feature in selected:
        item = {"feature": feature}
        for label in CLASSES:
            item[label] = median_iqr(frame.loc[frame["class"] == label, feature])
        item["eta_squared"] = eta_squared(frame, feature)
        summary_lines.append(item)
    selected_summary = pd.DataFrame(summary_lines)
    selected_summary.to_csv(OUT / "selected_class_summary.csv", index=False)

    comparisons = [
        ("Class_A", "Class_B"), ("Class_A", "Class_C"), ("Class_A", "Rejected"),
        ("Class_B", "Class_C"), ("Class_B", "Rejected"), ("Class_C", "Rejected"),
    ]
    delta_records = []
    for feature in selected:
        for first, second in comparisons:
            x = frame.loc[frame["class"] == first, feature].to_numpy(float)
            y = frame.loc[frame["class"] == second, feature].to_numpy(float)
            delta_records.append({
                "feature": feature,
                "first": first,
                "second": second,
                "cliffs_delta_first_minus_second": cliffs_delta(x, y),
            })
    pd.DataFrame(delta_records).to_csv(OUT / "selected_pairwise_cliffs_delta.csv", index=False)

    print("\nEMPIRICAL PIXEL CUTS (pooled foreground, class-blind):")
    print(json.dumps(thresholds, indent=2))
    print("\nSELECTED MEDIAN [Q1, Q3] BY CLASS:")
    print(selected_summary.to_string(index=False))
    print("\nTOP 25 IMAGE-LEVEL EFFECTS BY ETA-SQUARED:")
    show_columns = ["feature", "eta_squared"] + [f"{label}_separation_auc" for label in CLASSES] + [f"{label}_direction" for label in CLASSES]
    print(effect_frame[show_columns].head(25).to_string(index=False))
    print("\nCONNECTED-BLOB COUNTS:")
    print(components.groupby("class").agg(blobs=("filename", "size"), images=("filename", "nunique"), median_area_fraction=("area_fraction", "median"), border_fraction=("touches_border", "mean")).to_string())
    print(f"\nFailures: {len(failures)}")
    if failures:
        print(json.dumps(failures[:20], indent=2))
    print(f"Artifacts: {OUT}")


if __name__ == "__main__":
    main()
