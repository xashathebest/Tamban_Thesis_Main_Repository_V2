"""Adaptive tail policy: evidence, safeguards, provenance, and replay."""

import math
import csv
import io
import unittest

import numpy as np

from src.api.export import inspection_row, make_csv, make_xlsx
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine, load_grading_config
from src.inference.grading_policy import FishGradingInput, GradingPolicy, grade_fish
from src.inference.part_types import PartDetection
from src.evaluation.fish_level_validation import EvaluationRules, recompute_final_verdict


IDS = {"Class A": (0, 1, 2), "Class B": (3, 4, 5), "Class C": (6, 7, 8), "Rejected": (9, 10, 11)}
BOXES = ((20, 5, 45, 25), (2, 5, 20, 25), (45, 5, 60, 25))
IMAGE = np.full((32, 64, 3), 100, dtype=np.uint8)


def part(region, grade, confidence):
    index = {"Body": 0, "Head": 1, "Tail": 2}[region]
    return PartDetection.from_source_class(IDS[grade][index], confidence, BOXES[index])


def engine(**settings):
    return WeightedGradingEngine(GradingConfig(grading_mode="tail_optional_v1", image_diagnostics_enabled=False, **settings))


class TailOptionalPolicyTests(unittest.TestCase):
    def test_runtime_config_selects_versioned_tail_optional_policy(self):
        config = load_grading_config()
        self.assertEqual(config.grading_mode, "tail_optional_v1")
        self.assertEqual(config.config_version, "4.0")

    def test_three_parts_and_absent_or_weak_tail(self):
        body, head = part("Body", "Class A", .87), part("Head", "Class A", .79)
        full = engine().evaluate(1, IMAGE, [body, head, part("Tail", "Class A", .9)], stabilize=False).to_dict()
        absent = engine().evaluate(2, IMAGE, [body, head], stabilize=False).to_dict()
        weak = engine().evaluate(3, IMAGE, [body, head, part("Tail", "Class A", .24)], stabilize=False).to_dict()
        self.assertAlmostEqual(full["weighted_scores"]["Class A"], .852)
        self.assertEqual(full["weighting_method"], "three_part")
        self.assertEqual(full["tail_status"], "evaluated")
        for result in (absent, weak):
            self.assertAlmostEqual(result["weighted_scores"]["Class A"], .84)
            self.assertAlmostEqual(result["effective_weights"]["Body"], .625)
            self.assertAlmostEqual(result["effective_weights"]["Head"], .375)
            self.assertAlmostEqual(sum(result["weights_used"].values()), 1.0)
            self.assertEqual(result["weighting_method"], "head_body_only")
            self.assertEqual(result["original_weight_coverage"], .8)
        self.assertEqual(absent["tail_status"], "not_detected")
        self.assertEqual(weak["tail_status"], "below_threshold")
        self.assertIsNone(absent["part_results"]["Tail"]["physical_missing"])
        exported = inspection_row({"track_id": 2, "quality": absent["final_grade"], "analysis": absent})
        self.assertEqual(exported["weighting_method"], "head_body_only")
        self.assertEqual(exported["tail_evaluation_status"], "not_detected")

    def test_reliable_rejected_tail_is_retained(self):
        result = engine().evaluate(1, IMAGE, [part("Body", "Class A", .9), part("Head", "Class A", .9), part("Tail", "Rejected", .95)], stabilize=False).to_dict()
        self.assertEqual(result["tail_status"], "evaluated")
        self.assertAlmostEqual(result["effective_weights"]["Tail"], .2)
        self.assertAlmostEqual(result["weighted_scores"]["Rejected"], .19)

    def test_csv_and_excel_preserve_weighting_metadata(self):
        from openpyxl import load_workbook

        result = engine().evaluate(1, IMAGE, [part("Body", "Class A", .9), part("Head", "Class A", .8)], stabilize=False).to_dict()
        event = {"track_id": 1, "quality": result["final_grade"], "analysis": result}
        fields = ["weighting_method", "tail_evaluation_status", "body_effective_weight", "head_effective_weight", "tail_effective_weight"]
        csv_row = next(csv.DictReader(io.StringIO(make_csv([event], fields).decode("utf-8-sig"))))
        self.assertEqual(csv_row["Weighting Method"], "head_body_only")
        self.assertEqual(csv_row["Tail Evaluation Status"], "not_detected")
        self.assertAlmostEqual(float(csv_row["Body Effective Weight"]), .625)
        workbook = load_workbook(io.BytesIO(make_xlsx([event], fields, {})), data_only=True)
        values = list(workbook["Fish Inspections"].values)
        self.assertEqual(values[1][:2], ("head_body_only", "not_detected"))
        self.assertEqual(values[1][2:], (.625, .375, 0))

    def test_missing_mandatory_part_and_temporal_recovery(self):
        for parts in ([part("Body", "Class A", .9), part("Tail", "Class A", .9)], [part("Head", "Class A", .9), part("Tail", "Class A", .9)]):
            result = engine().evaluate(1, IMAGE, parts, stabilize=False)
            self.assertIsNone(result.final_grade)
            self.assertIn("UG_MISSING_PART_EVIDENCE", result.reason_codes)
        live = engine()
        pair = [part("Body", "Class A", .9), part("Head", "Class A", .9)]
        self.assertIsNone(live.evaluate(1, IMAGE, pair, stabilize=True, frame_id=1).final_grade)
        self.assertIsNone(live.evaluate(1, IMAGE, [], stabilize=True, frame_id=2).final_grade)
        self.assertEqual(live.evaluate(1, IMAGE, pair, stabilize=True, frame_id=3).final_grade, "Class A")

    def test_mandatory_region_matrix_and_zero_confidence(self):
        detections = {region: part(region, "Class A", .9) for region in ("Body", "Head", "Tail")}
        for regions in ((), ("Body",), ("Body", "Tail"), ("Head", "Tail")):
            with self.subTest(regions=regions):
                result = engine().evaluate(1, IMAGE, [detections[region] for region in regions], stabilize=False)
                self.assertIsNone(result.final_grade)
                self.assertIn("UG_MISSING_PART_EVIDENCE", result.reason_codes)
        valid = engine().evaluate(2, IMAGE, [detections["Body"], detections["Head"]], stabilize=False)
        self.assertEqual(valid.final_grade, "Class A")
        self.assertNotIn("UG_MISSING_PART_EVIDENCE", valid.reason_codes)
        zero = grade_fish(
            FishGradingInput(part_scores={}, presence_confidence={"Body": 0., "Head": 0.}),
            GradingPolicy(grading_mode="tail_optional_v1", minimum_part_confidence=0.),
        )
        self.assertEqual(zero.observed_regions, ())
        self.assertIsNone(zero.final_grade)
        self.assertIn("UG_MISSING_PART_EVIDENCE", zero.reason_codes)

    def test_equal_support_obeys_configured_grade_margin(self):
        evidence = FishGradingInput(
            part_scores={region: {"Class A": .8, "Class B": .8} for region in ("Body", "Head")},
            presence_confidence={"Body": .8, "Head": .8},
        )
        default_margin = grade_fish(evidence, GradingPolicy(grading_mode="tail_optional_v1"))
        required_margin = grade_fish(evidence, GradingPolicy(grading_mode="tail_optional_v1", minimum_grade_margin=.01))
        self.assertEqual(default_margin.final_grade, "Class A")
        self.assertIsNone(required_margin.final_grade)
        self.assertIn("UG_LOW_MARGIN", required_margin.reason_codes)

    def test_grade_thresholds_and_all_class_labels(self):
        for grade in IDS:
            with self.subTest(grade=grade):
                accepted = engine().evaluate(1, IMAGE, [part("Body", grade, .5), part("Head", grade, .5)], stabilize=False)
                self.assertEqual(accepted.final_grade, grade)
                self.assertAlmostEqual(accepted.final_score, .5)
                below = engine().evaluate(2, IMAGE, [part("Body", grade, .499), part("Head", grade, .499)], stabilize=False)
                self.assertIsNone(below.final_grade)
                self.assertIn("UG_LOW_GRADE_SUPPORT", below.reason_codes)

    def test_legacy_mode_and_invalid_adaptive_configuration(self):
        values = FishGradingInput(part_scores={"Body": {"Class A": .87}, "Head": {"Class A": .79}}, presence_confidence={"Body": .87, "Head": .79})
        self.assertAlmostEqual(grade_fish(values, GradingPolicy()).weighted_scores["Class A"], .672)
        self.assertAlmostEqual(grade_fish(values, GradingPolicy(grading_mode="tail_optional_v1")).weighted_scores["Class A"], .84)
        for kwargs in ({"minimum_regions_observed": 3}, {"minimum_original_weight_coverage": .81}, {"body_weight": 0., "head_weight": .8}, {"require_body": False}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                GradingPolicy(grading_mode="tail_optional_v1", **kwargs)

    def test_distinct_fish_and_offline_replay(self):
        live = engine()
        a = [part("Body", "Class A", .9), part("Head", "Class A", .8)]
        b = [part("Body", "Class B", .8), part("Head", "Class B", .9), part("Tail", "Class B", .7)]
        for frame in (1, 2):
            first = live.evaluate(1, IMAGE, a, stabilize=True, frame_id=frame)
            second = live.evaluate(2, IMAGE, b, stabilize=True, frame_id=frame)
        self.assertEqual((first.final_grade, second.final_grade), ("Class A", "Class B"))
        self.assertTrue(math.isclose(first.effective_weights["Body"], .625))
        self.assertTrue(math.isclose(second.effective_weights["Body"], .5))
        replay = recompute_final_verdict({"analysis": first.to_dict()}, EvaluationRules(grading_mode="tail_optional_v1"))
        self.assertEqual(replay["final_grade"], first.final_grade)
        self.assertAlmostEqual(replay["final_support"], first.final_score)


if __name__ == "__main__":
    unittest.main()
