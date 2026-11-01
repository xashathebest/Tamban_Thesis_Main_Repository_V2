"""Complete reports preserve original weighted evidence and final geometry."""

import csv
from io import BytesIO, StringIO
import json

from openpyxl import load_workbook

from src.api.export import DEFAULT_EXPORT_FIELDS, EXPORT_FIELDS, inspection_row, make_csv, make_xlsx


def complete_fish():
    configuration = {"scoring_method": "post_weighted_v2", "scoring_enabled": True,
        "calibration_validated": True, "calibration_id": "synthetic-export-fixture"}
    width = {"whole_fish_width_px": 672, "whole_fish_height_px": 1511,
        "body_width_px": 583, "body_height_px": 678, "relative_width_proxy": 583 / 1511,
        "measurement_status": "Measured", "calibration_status": "Calibrated",
        "measurement_available": True, "reliable_for_scoring": True, "reliability": "Reliable proxy",
        "class_c_supporting_points": 8, "score_applied": True, "score_contributed": True,
        "threshold_configuration": configuration}
    geometric = {"original_grade": "Class B", "original_support": .54,
        "original_scores": {"Class A": 0, "Class B": .54, "Class C": .46, "Rejected": 0},
        "original_provisional_grade": "Class B", "original_provisional_support": .54,
        "final_grade": "Class C", "final_support": .54,
        "final_scores": {"Class A": 0, "Class B": .46, "Class C": .54, "Rejected": 0},
        "class_c_points": 8, "applied_score_shift": .08, "width_changed_classification": True,
        "score_scale": "normalized_combined_support",
        "scoring_method": "post_weighted_v2", "contribution_applied": True}
    values = {"mean_hue_deg": 45, "mean_saturation": .3, "mean_value": .8,
        "median_saturation": .25, "median_value": .75, "yellow_ratio_proxy": .05,
        "brown_ratio_proxy": .06, "dark_patch_ratio_proxy": .07,
        "discoloration_coverage_proxy": .08, "specular_ratio_proxy": .09}
    measured = {"status": "measured", "values": values,
        "frame_rois": [{"frame_id": 9, "crop_local_bbox": [10, 20, 593, 698]}]}
    return {"track_id": 2, "session_id": "session-1", "quality": "Class C",
        "bbox": [100, 100, 772, 1611], "timestamp": "2026-10-31T09:00:00-04:00",
        "parts": [{"region": "Body", "grade": "Class B", "confidence": .9, "bbox": [110, 120, 693, 798]},
                  {"region": "Head", "grade": "Class B", "confidence": .8, "bbox": [200, 1300, 500, 1500]}],
        "analysis": {"body_width": width, "geometric_support": geometric,
            "inspection_source": {"type": "uploaded_photo", "frame_width_px": 1920, "frame_height_px": 1920},
            "weighted_scores": geometric["final_scores"], "final_grade": "Class C", "final_score": .54,
            "grading_config": {"part_weights": {"Body": .5, "Head": .3, "Tail": .2}, "body_width": configuration},
            "supporting_image_measurements": {"regions": {"Body": measured}},
            "part_results": {"Body": {"present": True, "grade": "Class B", "grade_confidence": .9,
                "grade_evidence": {"Class B": .54, "Class C": .46}}}}}


def test_complete_csv_retains_stage_scores_raw_detections_dimensions_and_all_features():
    event = complete_fish()
    values = inspection_row(event)
    assert set(EXPORT_FIELDS) <= set(values)
    rows = list(csv.DictReader(StringIO(make_csv([event], DEFAULT_EXPORT_FIELDS).decode("utf-8-sig"))))
    assert len(rows) == 1
    row = rows[0]
    assert row[EXPORT_FIELDS["original_weighted_grade"]] == "Class B"
    assert row[EXPORT_FIELDS["final_combined_grade"]] == "Class C"
    assert row[EXPORT_FIELDS["class_b_original_weighted_score"]] == "54.0"
    assert row[EXPORT_FIELDS["class_c_final_combined_score"]] == "54.0"
    assert row[EXPORT_FIELDS["geometric_class_c_points"]] == "8.0"
    assert "not percent" in EXPORT_FIELDS["geometric_class_c_points"]
    assert row[EXPORT_FIELDS["geometric_applied_score_shift"]] == "0.08"
    assert row[EXPORT_FIELDS["score_scale"]] == "normalized_combined_support"
    assert "Final Competing Support" in EXPORT_FIELDS["class_c_weighted_score"]
    assert row[EXPORT_FIELDS["body_width_score_applied"]] == "Yes"
    assert row[EXPORT_FIELDS["body_width_reliable_for_scoring"]] == "Yes"
    assert row[EXPORT_FIELDS["body_bbox_width_px"]] == "583.0"
    assert row[EXPORT_FIELDS["head_bbox_width_px"]] == "300.0"
    assert row[EXPORT_FIELDS["tail_bbox_width_px"]] == ""
    assert row[EXPORT_FIELDS["body_brown_ratio"]] == "6.0"
    assert row[EXPORT_FIELDS["body_mean_hue"]] == "45.0"
    assert row[EXPORT_FIELDS["body_mean_value"]] == "80.0"
    assert row[EXPORT_FIELDS["body_dark_area_ratio"]] == "7.0"
    assert row[EXPORT_FIELDS["body_discoloration_ratio"]] == "8.0"
    assert row[EXPORT_FIELDS["body_highlight_ratio"]] == "9.0"
    assert json.loads(row[EXPORT_FIELDS["part_detections"]]) == event["parts"]
    assert json.loads(row[EXPORT_FIELDS["complete_analysis"]]) == event["analysis"]
    assert json.loads(row[EXPORT_FIELDS["body_measurement_rois"]])[0]["frame_id"] == 9
    assert row[EXPORT_FIELDS["inspection_source_type"]] == "uploaded_photo"
    assert row[EXPORT_FIELDS["source_frame_width_px"]] == "1920.0"
    assert json.loads(row[EXPORT_FIELDS["complete_fish_event"]]) == event


def test_xlsx_rules_and_rows_preserve_exact_calibration_snapshot():
    event = complete_fish()
    fields = ("original_weighted_grade", "final_combined_grade", "geometric_support", "grading_configuration")
    rules = event["analysis"]["grading_config"]
    workbook = load_workbook(BytesIO(make_xlsx([event], fields, {}, grading_rules=rules)), data_only=True)
    values = list(workbook["Fish Inspections"].values)[1]
    assert values[:2] == ("Class B", "Class C")
    assert json.loads(values[2]) == event["analysis"]["geometric_support"]
    assert json.loads(values[3]) == rules
    rule_values = {row[0]: row[1] for row in list(workbook["Grade Calculation Rules"].values)[1:]}
    assert rule_values["Geometric scoring method"] == "post_weighted_v2"
    assert json.loads(rule_values["Complete width configuration"]) == rules["body_width"]


def test_raw_unreliable_measurement_is_exported_without_support_points():
    event = complete_fish()
    width = event["analysis"]["body_width"]
    width.update(measurement_status="Unreliable", reliability="Unreliable", reliable_for_scoring=False,
                 class_c_supporting_points=None, score_applied=False, score_contributed=False)
    event["analysis"].pop("geometric_support")
    row = inspection_row(event)
    assert row["relative_body_width_proxy"] > 0
    assert row["body_width_measurement_status"] == "Unreliable"
    assert row["body_width_class_c_points"] == ""
    assert row["body_width_reliable_for_scoring"] == "No"
    assert row["original_weighted_grade"] == ""


def test_best_model2_evidence_retains_original_class_when_geometry_changes_final_grade():
    event = complete_fish()
    event["analysis"].update(provisional_grade="Class C", provisional_score=.54,
                             best_evidence_class="Class B", best_evidence_score=.54)
    row = inspection_row(event)
    assert row["best_evidence_class"] == "Class B"
    assert row["best_evidence_score"] == 54
    assert row["original_weighted_grade"] == "Class B"
    assert row["final_combined_grade"] == "Class C"
    # Explicit original evidence also remains authoritative for older payloads
    # without the detailed geometry snapshot.
    del event["analysis"]["geometric_support"]
    assert inspection_row(event)["best_evidence_class"] == "Class B"


def test_historical_missing_geometry_never_fabricates_original_grade_or_measurements():
    row = inspection_row({"quality": "Class B", "analysis": {"weighted_scores": {"Class B": .6}, "final_score": .6}})
    assert row["original_weighted_grade"] == ""
    assert row["final_combined_grade"] == "Class B"
    assert row["final_combined_support"] == 60
    assert row["body_width_measurement_status"] == "Unavailable"
    assert row["whole_fish_bbox_width_px"] == ""
    assert row["body_brown_ratio"] == ""
