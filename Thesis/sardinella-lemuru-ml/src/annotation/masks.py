"""Lossless COCO masks, independent of optional training/Roboflow packages."""
from __future__ import annotations

import math
import cv2
import numpy as np


def mask_to_rle(mask: np.ndarray) -> dict:
    """Encode COCO's column-major uncompressed RLE, retaining holes/islands."""
    binary = (np.asarray(mask) != 0).astype(np.uint8)
    if binary.ndim != 2:
        raise ValueError("A mask must be two dimensional.")
    flat = binary.reshape(-1, order="F")
    changes = np.flatnonzero(np.diff(flat)) + 1
    runs = np.diff(np.concatenate(([0], changes, [flat.size]))).tolist()
    if flat.size and flat[0]:
        runs.insert(0, 0)
    return {"size": list(binary.shape), "counts": runs}


def _compressed_counts(value: str) -> list[int]:
    # COCO maskApi.c rleFrString, including signed delta coding.
    runs, index = [], 0
    while index < len(value):
        number, shift, more = 0, 0, True
        while more:
            if index >= len(value):
                raise ValueError("Truncated compressed COCO RLE.")
            char = ord(value[index]) - 48
            index += 1
            if not 0 <= char <= 63 or shift > 60:
                raise ValueError("Invalid compressed COCO RLE.")
            number |= (char & 31) << shift
            more = bool(char & 32)
            shift += 5
            if not more and char & 16:
                number |= -1 << shift
        if len(runs) > 2:
            number += runs[-2]
        runs.append(number)
    return runs


def segmentation_to_mask(segmentation, height: int, width: int) -> np.ndarray:
    """Decode real segmentation only; bounding boxes are never substituted."""
    if height <= 0 or width <= 0 or height * width > 64_000_000:
        raise ValueError("Invalid or excessively large mask dimensions.")
    mask = np.zeros((height, width), dtype=np.uint8)
    if isinstance(segmentation, dict):
        if segmentation.get("size") != [height, width]:
            raise ValueError("Mask RLE dimensions do not match the original image.")
        counts = segmentation.get("counts")
        if isinstance(counts, str):
            counts = _compressed_counts(counts)
        if not isinstance(counts, list) or not counts:
            raise ValueError("Mask RLE counts must be a nonempty list.")
        if any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in counts):
            raise ValueError("Mask RLE counts must be nonnegative integers.")
        if sum(counts) != height * width:
            raise ValueError("Mask RLE counts do not cover the image exactly.")
        flat, cursor = mask.reshape(-1, order="F"), 0
        for index, count in enumerate(counts):
            if index % 2:
                flat[cursor:cursor + count] = 1
            cursor += count
        return np.ascontiguousarray(flat.reshape((height, width), order="F"))
    if not isinstance(segmentation, list) or not segmentation:
        raise ValueError("An actual nonempty segmentation mask is required.")
    for polygon in segmentation:
        if not isinstance(polygon, list) or len(polygon) < 6 or len(polygon) % 2:
            raise ValueError("A polygon needs at least three x/y coordinate pairs.")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in polygon):
            raise ValueError("Polygon coordinates must be finite numbers.")
        points = np.asarray(polygon, dtype=np.float64).reshape(-1, 2)
        if np.any(points < 0) or np.any(points[:, 0] > width) or np.any(points[:, 1] > height):
            raise ValueError("Polygon coordinates lie outside the original image.")
        if np.array_equal(points[0], points[-1]):
            points = points[:-1]
        if len(points) < 3 or len(np.unique(points, axis=0)) < 3:
            raise ValueError("Polygon requires at least three distinct vertices.")
        signed_area = np.dot(points[:, 0], np.roll(points[:, 1], -1)) - np.dot(points[:, 1], np.roll(points[:, 0], -1))
        if abs(float(signed_area)) < 1e-8:
            raise ValueError("Polygon is degenerate or has zero area.")
        # Reject crossing nonadjacent edges. A self-crossing ring is ambiguous;
        # accepting a rasterizer's fill rule would invent an annotation boundary.
        def cross(a, b, c):
            return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        def touches(a, b, c):
            return abs(cross(a, b, c)) < 1e-9 and min(a[0], b[0]) - 1e-9 <= c[0] <= max(a[0], b[0]) + 1e-9 and min(a[1], b[1]) - 1e-9 <= c[1] <= max(a[1], b[1]) + 1e-9
        n = len(points)
        for first in range(n):
            a, b = points[first], points[(first + 1) % n]
            if np.array_equal(a, b):
                raise ValueError("Polygon has a zero-length edge.")
            for second in range(first + 2, n):
                if first == 0 and second == n - 1:
                    continue
                c, d = points[second], points[(second + 1) % n]
                if max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]) or max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]):
                    continue
                if (cross(a, b, c) * cross(a, b, d) < 0 and cross(c, d, a) * cross(c, d, b) < 0) or touches(a, b, c) or touches(a, b, d) or touches(c, d, a) or touches(c, d, b):
                    raise ValueError("Polygon boundary intersects itself.")
        points[:, 0] = np.minimum(points[:, 0], width - 1)
        points[:, 1] = np.minimum(points[:, 1], height - 1)
        cv2.fillPoly(mask, [np.rint(points).astype(np.int32)], 1)
    return mask


def mask_bbox(mask: np.ndarray) -> list[int]:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise ValueError("Segmentation mask has no foreground pixels.")
    return [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)]


def coco_segmentation_to_mask(segmentation, height: int, width: int) -> np.ndarray:
    """Decode source COCO polygons with COCO's exact pixel convention.

    Integer polygon edges describe pixel boundaries in COCO; OpenCV's drawing
    tool instead includes both endpoint pixels. Keep this importer separate so
    existing interactive contour edits keep their established pixel convention.

    The 5x edge sampling algorithm follows cocodataset/cocoapi maskApi.c
    ``rleFrPoly`` (Piotr Dollar and Tsung-Yi Lin, BSD-2-Clause; COCO_LICENSE.txt).
    NumPy performs the edge sampling; pycocotools is not a runtime dependency.
    """
    if isinstance(segmentation, dict):
        return segmentation_to_mask(segmentation, height, width)
    if not isinstance(segmentation, list) or not segmentation:
        raise ValueError("An actual nonempty COCO segmentation is required.")
    if height <= 0 or width <= 0 or height * width > 64_000_000:
        raise ValueError("Invalid or excessively large mask dimensions.")
    result = np.zeros((height, width), dtype=np.uint8)
    for polygon in segmentation:
        if not isinstance(polygon, list) or len(polygon) < 6 or len(polygon) % 2:
            raise ValueError("A COCO polygon requires at least three x/y pairs.")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in polygon):
            raise ValueError("COCO polygon coordinates must be finite numbers.")
        points = np.asarray(polygon, dtype=np.float64).reshape(-1, 2)
        if (points < 0).any() or (points[:, 0] > width).any() or (points[:, 1] > height).any():
            raise ValueError("COCO polygon coordinates lie outside the original image.")
        quantized = np.trunc(points * 5 + .5).astype(np.int64)
        edges = []
        for start, end in zip(quantized, np.roll(quantized, -1, axis=0)):
            xs, ys = (int(v) for v in start)
            xe, ye = (int(v) for v in end)
            dx, dy = abs(xe - xs), abs(ye - ys)
            reverse = (dx >= dy and xs > xe) or (dx < dy and ys > ye)
            if reverse:
                xs, xe, ys, ye = xe, xs, ye, ys
            length = max(dx, dy)
            if not length:
                edges.append(np.array([[xs, ys]], dtype=np.int64))
                continue
            steps = np.arange(length + 1, dtype=np.int64)
            if reverse:
                steps = length - steps
            if dx >= dy:
                sampled = np.column_stack((xs + steps, np.trunc(ys + steps * ((ye - ys) / dx) + .5).astype(np.int64)))
            else:
                sampled = np.column_stack((np.trunc(xs + steps * ((xe - xs) / dy) + .5).astype(np.int64), ys + steps))
            edges.append(sampled)
        boundary = np.concatenate(edges)
        before, after = boundary[:-1], boundary[1:]
        changed = before[:, 0] != after[:, 0]
        before, after = before[changed], after[changed]
        x = (np.where(after[:, 0] < before[:, 0], after[:, 0], after[:, 0] - 1) + .5) / 5 - .5
        keep = (np.floor(x) == x) & (x >= 0) & (x <= width - 1)
        y = np.ceil(np.clip((np.minimum(after[:, 1], before[:, 1]) + .5) / 5 - .5, 0, height))
        offsets = np.sort(np.concatenate(((x[keep] * height + y[keep]).astype(np.int64), [height * width])))
        counts = np.diff(np.concatenate(([0], offsets))).tolist()
        # Repeated crossings toggle twice at the same pixel. Zero-length runs
        # carry that parity and our ordinary RLE decoder handles them exactly.
        decoded = segmentation_to_mask({"size": [height, width], "counts": counts}, height, width)
        result |= decoded
    return result


def yolo_polygon(mask: np.ndarray) -> list[float]:
    """One exact raster-equivalent contour; fail instead of bridging islands."""
    contours, hierarchy = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None or len(contours) != 1 or hierarchy[0][0][3] != -1:
        raise ValueError("YOLO segmentation cannot losslessly represent disconnected masks or holes; export COCO instead.")
    points = contours[0].reshape(-1, 2)
    if len(points) < 3:
        raise ValueError("YOLO segmentation cannot represent this tiny mask; export COCO instead.")
    restored = np.zeros(mask.shape, dtype=np.uint8)
    cv2.fillPoly(restored, [points.astype(np.int32)], 1)
    if not np.array_equal(restored != 0, mask != 0):
        raise ValueError("YOLO polygon would change mask pixels; export COCO instead.")
    height, width = mask.shape
    normalized = []
    for point in points:
        for pixel, dimension in zip(point, (width, height)):
            # Ultralytics reads normalized polygons as float32, scales them to
            # native pixels, then truncates to int32 for polygon2mask. Ordinary
            # p/dimension can round just below p and shift a boundary one pixel.
            # One upward float32 ULP is enough and round-trips through .12g.
            coordinate = np.nextafter(np.float32(int(pixel) / dimension), np.float32(np.inf))
            scaled = np.float32(coordinate * np.float32(dimension))
            if not int(pixel) <= float(scaled) < int(pixel) + 1 or not 0 <= coordinate <= 1:
                raise ValueError("YOLO float32 coordinates cannot retain this mask at its original resolution; export COCO instead.")
            normalized.append(float(coordinate))
    return normalized
