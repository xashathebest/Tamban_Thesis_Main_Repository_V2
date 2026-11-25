"""Guard evaluation matching, count semantics, pairing, and regression decisions."""
from copy import deepcopy

import numpy as np

from src.evaluation.compare_model1_versions import (
    count_metrics, match_counts, paired_bootstrap, promotion_gate,
)


def test_duplicates_are_false_positives_and_threshold_applies_before_matching():
    boxes = [[0, 0, 10, 10], [0, 0, 10, 10], [30, 0, 40, 10]]
    scores = [.8, .9, .4]
    truth = [[0, 0, 10, 10], [30, 0, 40, 10]]
    assert match_counts(boxes, scores, truth, .5) == (1, 1, 1)
    assert match_counts(boxes, scores, truth, .85) == (1, 0, 1)


def test_matching_is_invariant_to_input_order_and_uses_descending_confidence():
    boxes = [[0, 0, 10, 10], [2, 0, 12, 10]]
    scores = [.9, .8]
    truth = [[0, 0, 10, 10], [-3, 0, 7, 10]]
    # The higher-confidence exact box takes target 0; target 1 remains unmatched.
    assert match_counts(boxes, scores, truth, .5) == (1, 1, 1)
    assert match_counts(boxes[::-1], scores[::-1], truth, .5) == (1, 1, 1)


def test_empty_predictions_and_empty_background_images():
    assert match_counts([], [], [[0, 0, 10, 10]], .5) == (0, 0, 1)
    assert match_counts([[0, 0, 10, 10]], [.8], [], .5) == (0, 1, 0)
    assert match_counts([], [], [], .5) == (0, 0, 0)


def test_correct_count_does_not_imply_correct_localization():
    metrics = count_metrics(np.asarray([[2, 1, 1], [0, 0, 1]]))
    assert metrics["exact_count_accuracy"] == .5
    assert metrics["perfect_detection_image_rate"] == 0
    assert metrics["precision"] == 2 / 3
    assert metrics["recall"] == .5
    assert metrics["f1"] == 4 / 7


def test_paired_bootstrap_keeps_identical_predictions_identical():
    counts = np.asarray([[3, 0, 1], [2, 1, 2], [4, 0, 0]])
    intervals = paired_bootstrap(counts, counts.copy(), repeats=100)
    assert all(interval == {"lower": 0., "upper": 0.} for interval in intervals.values())


def passing_summary():
    baseline = {"map50_95": .7, "thresholds": {t: {"f1": .75, "precision": .9} for t in ("0.50", "0.70")}}
    candidate = {"map50_95": .75, "thresholds": {t: {"f1": .8, "precision": .91} for t in ("0.50", "0.70")}}
    return {name: {"models": {"v2": deepcopy(baseline), "v3": deepcopy(candidate)},
                   "paired_intervals": {t: {"f1": {"lower": .01, "upper": .1}} for t in ("0.50", "0.70")}}
            for name in ("development", "legacy")}


def test_development_gain_cannot_hide_legacy_regression():
    summary = passing_summary()
    assert promotion_gate(summary)["candidate_supported"]
    summary["legacy"]["models"]["v3"]["map50_95"] = .65
    gate = promotion_gate(summary)
    assert not gate["candidate_supported"]
    assert not gate["checks"]["legacy_map50_95_loss_at_most_2pp"]


def test_missing_legacy_evidence_or_uncertain_f1_blocks_gate():
    summary = passing_summary()
    del summary["legacy"]
    assert not promotion_gate(summary)["candidate_supported"]
    summary = passing_summary()
    summary["development"]["paired_intervals"]["0.50"]["f1"]["lower"] = -.01
    assert not promotion_gate(summary)["candidate_supported"]
