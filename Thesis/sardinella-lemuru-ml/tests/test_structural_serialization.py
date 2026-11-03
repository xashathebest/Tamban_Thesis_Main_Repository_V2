"""Post-structural grades and each earlier evidence stage survive boundaries."""
from copy import deepcopy
from io import BytesIO, StringIO
import csv
import json

import numpy as np
from openpyxl import load_workbook
import pytest

from src.api.export import EXPORT_FIELDS, inspection_row, make_csv, make_xlsx
from src.api.image_analysis import complete_inspection_payload
from src.inference.feature_fusion import StructuralFusionConfig
from src.inference.grading_engine import GradingConfig, WeightedGradingEngine
from src.inference.inspection_results import normalize_inspection_result
from src.inference.part_types import PartDetection


PROVENANCE = {"review_id":"synthetic-review","reviewer":"software-test-only","reference_set_id":"synthetic-reference"}
SOURCE = {"source_id":"synthetic-serialization","frame_pixels_sha256":"a"*64}


def specimen(alternative=True):
    cfg=StructuralFusionConfig(enabled=True,calibration_validated=True,policy_id="synthetic-policy",
        reference_set_id=PROVENANCE["reference_set_id"],validation_sample_count=1,policy_review_provenance=PROVENANCE)
    engine=WeightedGradingEngine(GradingConfig(grading_mode="tail_optional_v1",image_diagnostics_enabled=False),structural_config=cfg)
    detections=[PartDetection.from_source_class(i,.9,(10+20*i,10,25+20*i,40)) for i in range(3)]
    if alternative:detections += [PartDetection.from_source_class(3+i,.6,(10+20*i,10,25+20*i,40)) for i in range(3)]
    reviewed={"fish_id":7,"parent_track_id":7,"frame_id":"fixture-frame",**SOURCE,"reviewed":True,"status":"confirmed",
        "severity":"major","severity_reviewed":True,"region":"Body","ownership_validated":True,
        "body_mask_validated":True,"measurement_validated":True,"validation_provenance":PROVENANCE,
        "coordinate_space":"original_frame","locations":[{"x":25,"y":20,"width":12,"height":3}],
        "clipped":False,"overlapping":False,"ownership_ambiguous":False,"partial_silhouette":False}
    verdict=engine.evaluate(7,np.full((60,100,3),100,np.uint8),detections,stabilize=False,frame_id="fixture-frame",
                            structural_evidence=reviewed,source_context=SOURCE)
    analysis=verdict.to_dict()
    analysis.update(inspection_source={"frame_id":"fixture-frame","frame_width_px":100,"frame_height_px":60},
                    model1_detection={"bbox":[5,5,85,50]},quality_inference={"mode":"full_frame","crop_bounds":[5,5,85,50]})
    return {"id":7,"track_id":7,"quality":verdict.final_grade or "Ungraded","quality_confidence":verdict.final_score,
            "bbox":[5,5,85,50],"parts":[p.to_dict() for p in detections],"analysis":analysis}


@pytest.mark.parametrize("alternative,expected",[(True,"Class B"),(False,"Ungraded")])
def test_normalization_and_api_completion_keep_each_structural_stage(alternative,expected):
    event=specimen(alternative);before=deepcopy(event)
    actual=normalize_inspection_result(event,frame_shape=(60,100,3))
    api=complete_inspection_payload({"fish":[event],"analyzed_at":"2026-11-02T00:00:00Z"},frame_shape=(60,100,3))["fish"][0]
    for value in (actual,api):
        assert value["quality"] == value["analysis"]["final_grade"] == expected
        assert value["analysis"]["feature_fusion"] == event["analysis"]["feature_fusion"]
        assert value["analysis"]["geometric_support"] == event["analysis"]["geometric_support"]
        assert value["analysis"]["feature_fusion"]["primary_anatomical"]["grade"] == "Class A"
        assert value["analysis"]["feature_fusion"]["eligibility"]["class_a_eligible"] is False
        assert value["analysis"]["weighted_scores"] == event["analysis"]["weighted_scores"]
    assert event == before


@pytest.mark.parametrize("alternative,expected",[(True,"Class B"),(False,"Ungraded")])
def test_csv_and_xlsx_export_actual_final_grade_not_prestructural_geometry(alternative,expected):
    event=specimen(alternative);before=deepcopy(event)
    fields=("grade","original_weighted_grade","original_weighted_support","final_combined_grade","final_combined_support")
    row=inspection_row(event)
    csv_values=next(csv.DictReader(StringIO(make_csv([event],fields).decode("utf-8-sig"))))
    workbook=load_workbook(BytesIO(make_xlsx([event],fields,{})),data_only=True)
    excel=dict(zip(fields,list(workbook["Fish Inspections"].values)[1]))
    for values in (row,excel):
        assert values["grade"] == values["final_combined_grade"] == expected
        assert values["original_weighted_grade"] == "Class A"
    assert csv_values[EXPORT_FIELDS["grade"]] == csv_values[EXPORT_FIELDS["final_combined_grade"]] == expected
    assert csv_values[EXPORT_FIELDS["original_weighted_grade"]] == "Class A"
    assert event == before


def test_raw_forged_fusion_does_not_override_normalized_recorded_grade():
    event=specimen()
    event["quality"]="Class A";event["analysis"]["final_grade"]="Class A"
    forged=deepcopy(event["analysis"]["feature_fusion"]);forged.update(final_grade="Rejected",final_support=1.)
    forged["eligibility"].update(rule_applied=True,class_a_eligible=False)
    event["analysis"]["feature_fusion"]=forged
    actual=normalize_inspection_result(event,frame_shape=(60,100,3))
    assert actual["quality"] == actual["analysis"]["final_grade"] == "Class A"
