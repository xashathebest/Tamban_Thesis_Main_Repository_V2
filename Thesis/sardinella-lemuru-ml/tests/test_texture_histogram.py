"""Exact feature equivalence for the optimized masked co-occurrence histogram."""

import numpy as np
import pytest

from src.features.texture import _paired_slices, masked_glcm


def reference_glcm(gray, mask, levels, distance):
    # Former production implementation retained as an independent count oracle.
    quantized = np.minimum((np.clip(gray, 0.0, 1.0) * levels).astype(np.int32), levels - 1)
    counts = np.zeros((levels, levels), dtype=np.float64)
    pairs = 0
    for dr, dc in ((0, distance), (distance, 0), (distance, distance), (-distance, distance)):
        source, target = _paired_slices(mask.shape, dr, dc)
        valid = mask[source] & mask[target]
        if not valid.any():
            continue
        left, right = quantized[source][valid], quantized[target][valid]
        np.add.at(counts, (left, right), 1.0)
        np.add.at(counts, (right, left), 1.0)
        pairs += int(valid.sum())
    if counts.sum():
        counts /= counts.sum()
    return counts, pairs


@pytest.mark.parametrize("shape,distance,levels", [((1, 3), 5, 4), ((7, 11), 1, 16), ((31, 19), 3, 256), ((80, 100), 5, 32)])
def test_histogram_is_exact_for_irregular_masks_large_distances_and_levels(shape, distance, levels):
    rng = np.random.default_rng(103)
    gray = rng.uniform(-0.1, 1.1, shape)
    mask = rng.random(shape) > 0.3
    expected, expected_pairs = reference_glcm(gray, mask, levels, distance)
    actual, actual_pairs = masked_glcm(gray, mask, levels=levels, distance=distance)
    assert actual_pairs == expected_pairs
    np.testing.assert_array_equal(actual, expected)
