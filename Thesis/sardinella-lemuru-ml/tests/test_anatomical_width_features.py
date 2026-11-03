"""Synthetic software fixtures exercise geometry and review gates, not accuracy."""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.evaluation.anatomical_width_reference import evaluate_reference, main, review_template
from src.inference.association import ParentAnchor
from src.inference.body_width import BodyWidthConfig, analyze_anatomical_body_width
from src.inference.fish_geometry import measure_fish_geometry
from src.inference.geometric_support import integrate_geometric_support
from src.inference.grading_policy import FishGradingInput, GradingPolicy, grade_fish
from src.inference.mask_ownership import validate_candidate_masks
from src.inference.part_types import PartDetection


def fixture(angle=0, body_half_width=20):
    mask = np.zeros((240,240), np.uint8)
    cv2.ellipse(mask, (120,120), (85,28), 0, 0, 360, 1, -1)
    body = np.zeros_like(mask); body[120-body_half_width:121+body_half_width,90:161] = 1
    transform = cv2.getRotationMatrix2D((120,120), -angle, 1.)
    mask = cv2.warpAffine(mask, transform, (240,240), flags=cv2.INTER_NEAREST)
    body = cv2.warpAffine(body, transform, (240,240), flags=cv2.INTER_NEAREST).astype(bool)
    ys,xs = np.nonzero(body); part = PartDetection.from_source_class(0,.95,(xs.min(),ys.min(),xs.max()+1,ys.max()+1))
    ys,xs = np.nonzero(mask)
    kwargs = {"parent_bbox": (xs.min()+97,ys.min()+97,xs.max()+104,ys.max()+104),
              "crop_bounds": (100,100,340,340), "frame_shape": (500,500,3), "association_reliable": True,
              "body_mask": body, "body_mask_metadata": {"validated": True,"body_region_validated":True,"validation_provenance":"Synthetic reviewed-pixel test fixture","parent_track_id":7},
              "mask_metadata": {"measurement_validated":True,"ownership_validated":True,
                  "expected_parent_id":7,"parent_track_id":7,"validation_provenance":"Synthetic whole-mask review fixture"},
              "source_context":"fixture-camera-plane"}
    return mask,[part],kwargs


def calibrated(**changes):
    return replace(BodyWidthConfig(scoring_enabled=True, calibration_validated=True, calibration_id="synthetic-software-only",
        validation_sample_count=3, normal_reference_min=.1,normal_reference_max=.2,extreme_reference=.4,
        reference_metric="body_width_to_fish_length_ratio",reference_source_id="fixture-camera-plane",
        reference_review_provenance="Synthetic fixture, not real fish calibration",reference_distribution=(.15,.18),
        reference_sample_ids=("fixture-1","fixture-2")),**changes)


@pytest.mark.parametrize("angle", [0,30,45,75,90,135])
def test_body_pixels_follow_fish_orientation_and_exclude_wider_whole_silhouette(angle):
    mask,parts,kwargs=fixture(angle)
    result=measure_fish_geometry(mask,parts,**kwargs)
    assert result["status"]=="measured",result
    assert result["fish_length_px"]==pytest.approx(171,abs=4)
    assert result["max_body_width_px"]==pytest.approx(41,abs=3)
    assert result["representative_body_width_px"]==pytest.approx(41,abs=3)
    assert result["whole_fish_max_width_px"] > result["max_body_width_px"]
    assert result["body_profile_length_px"]==pytest.approx(71,abs=4)
    assert result["body_width_to_length_ratio"]==pytest.approx(41/71,abs=.05)
    assert result["relative_width_ratio"]==pytest.approx(41/171,abs=.03)
    assert result["measurement_validated"] and result["body_region_validated"] and result["ownership_validated"]
    assert result["body_region_source"]=="reviewed_body_pixel_support"
    assert result["units"]["ratios"]=="dimensionless"
    assert result["fish_length_cm"] is None and not result["used_for_grading"]
    json.dumps(result,allow_nan=False)


@pytest.mark.parametrize("gate", ["whole_review", "ownership", "body_review", "body_extent", "body_parent", "experimental"])
def test_foreground_success_cannot_validate_itself_or_score_width(gate):
    mask,parts,kwargs=fixture()
    if gate=="whole_review":kwargs["mask_metadata"]["measurement_validated"]=False
    elif gate=="ownership":kwargs["mask_metadata"]["ownership_validated"]=False
    elif gate=="body_review":kwargs["body_mask_metadata"]["validated"]=False
    elif gate=="body_extent":kwargs["body_mask_metadata"]["body_region_validated"]=False
    elif gate=="body_parent":kwargs["body_mask_metadata"]["parent_track_id"]=8
    else:kwargs["mask_metadata"].update(experimental=True,sampling={"mode":"mobilesam_candidate","estimated":True})
    geometry=measure_fish_geometry(mask,parts,**kwargs)
    width=analyze_anatomical_body_width(geometry,config=calibrated())
    assert geometry["measurement_validated"] is False
    assert width["reliable_for_scoring"] is False and width["class_c_supporting_points"] is None
    assert not width["score_contributed"]


def test_body_mask_containing_neighbor_pixels_is_withheld_without_changing_raw_mask():
    mask,parts,kwargs=fixture(); body=kwargs["body_mask"]
    body[30:55,20:50]=True; before=body.copy()
    geometry=measure_fish_geometry(mask,parts,**kwargs)
    assert "body_segmentation_not_associated_with_fish" in geometry["reasons"]
    assert geometry["max_body_width_px"] is None
    np.testing.assert_array_equal(body,before)


def test_tight_crop_is_not_a_false_image_boundary_when_native_pixels_are_complete():
    mask,parts,kwargs=fixture(); ys,xs=np.nonzero(mask)
    left,top,right,bottom=int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)
    native_box=[left+100,top+100,right+100,bottom+100]
    tight=mask[top:bottom,left:right]
    part=replace(parts[0],bbox=(parts[0].bbox[0]-left,parts[0].bbox[1]-top,parts[0].bbox[2]-left,parts[0].bbox[3]-top))
    kwargs.update(crop_bounds=native_box,parent_bbox=native_box,body_mask=kwargs["body_mask"][top:bottom,left:right])
    kwargs["mask_metadata"].update(candidate_provenance={"coordinate_space":"original_frame","mask_shape":[500,500]},
        full_frame_foreground_bbox=native_box,full_frame_foreground_pixels=int(mask.sum()))
    accepted=measure_fish_geometry(tight,[part],**kwargs)
    assert "silhouette_touches_crop_boundary" not in accepted["reasons"]
    assert accepted["status"]=="measured"
    kwargs["mask_metadata"]["full_frame_foreground_pixels"]+=1
    rejected=measure_fish_geometry(tight,[part],**kwargs)
    assert "silhouette_touches_crop_boundary" in rejected["reasons"]


def test_native_parent_padding_can_touch_frame_without_foreground_clipping():
    shape=(120,320); mask=np.zeros(shape,np.uint8);cv2.ellipse(mask,(140,60),(110,20),0,0,360,1,-1)
    parent=ParentAnchor(1,(0,25,270,95));part=PartDetection.from_source_class(0,.9,(90,45,190,75))
    head=PartDetection.from_source_class(1,.9,(35,48,65,72))
    value={"status":"candidate","parent_id":1,"mask":mask.astype(bool),"provenance":{"backend":"mobilesam_experimental",
        "parent_id":1,"original_bbox_global":list(parent.bbox),"prompt_bbox_global":list(parent.bbox),
        "coordinate_space":"original_frame","mask_shape":list(shape)}}
    result=validate_candidate_masks({1:value},[parent],[part,head],frame_shape=shape)[1]
    assert result["metrics"]["parent_bbox_touches_frame_boundary"]
    assert not result["metrics"]["mask_touches_frame_boundary"]
    assert "parent_touches_frame_boundary" not in result["reasons"]
    assert result["ownership_validated"] is False
    mask[:,0]=1;value["mask"]=mask.astype(bool)
    result=validate_candidate_masks({1:value},[parent],[part,head],frame_shape=shape)[1]
    assert "mask_touches_frame_boundary" in result["reasons"]


def test_reviewed_anatomical_width_scoring_is_continuous_and_reference_specific():
    mask,parts,kwargs=fixture(); geometry=measure_fish_geometry(mask,parts,**kwargs)
    result=analyze_anatomical_body_width(geometry,config=calibrated())
    assert result["score_status"]=="Calibrated"
    assert result["class_c_supporting_points"]==pytest.approx(10*(41/171-.2)/.2,abs=.01)
    assert result["measurement_method"]=="anatomical_mask_profile"
    assert not result["score_contributed"]  # Only the existing final fusion can consume points.
    assert result["reviewed_reference_percentile"]==1.
    for config,reason in ((calibrated(reference_metric="axis_aligned_bounding_box_proxy"),"calibration_metric_mismatch"),
                          (calibrated(reference_source_id="another-plane"),"calibration_context_mismatch")):
        blocked=analyze_anatomical_body_width(geometry,config=config)
        assert blocked["contribution_reason"]==reason and blocked["class_c_supporting_points"] is None


def test_no_reference_values_are_fabricated_by_default():
    mask,parts,kwargs=fixture();geometry=measure_fish_geometry(mask,parts,**kwargs)
    result=analyze_anatomical_body_width(geometry)
    assert result["score_status"]=="Not calibrated" and result["class_c_supporting_points"] is None
    assert result["reference_distribution"]==[] and result["normal_reference_range"] is None
    assert calibrated().maximum_geometric_contribution<=.1


@pytest.mark.parametrize("tail",[True,False])
def test_reviewed_pixel_width_can_actively_change_class_through_existing_capped_fusion(tail):
    mask,parts,kwargs=fixture(body_half_width=27)
    geometry=measure_fish_geometry(mask,parts,**kwargs)
    config=calibrated()
    width=analyze_anatomical_body_width(geometry,config=config)
    regions=("Body","Head","Tail") if tail else ("Body","Head")
    scores={region:{"Class B":.54,"Class C":.46} for region in regions}
    policy=GradingPolicy(grading_mode="tail_optional_v1")
    original=grade_fish(FishGradingInput(scores,{region:.54 for region in regions}),policy)
    assert original.final_grade=="Class B"
    final,applied,evidence=integrate_geometric_support(original,width,config,policy,part_scores=scores)
    assert final.final_grade=="Class C",(geometry,width,evidence)
    assert evidence["original_grade"]=="Class B" and evidence["width_changed_classification"]
    assert 0<applied["applied_geometric_score_shift"]<=config.maximum_geometric_contribution
    assert final.effective_weights==original.effective_weights
    assert final.contributions==original.contributions
    if not tail:
        assert final.effective_weights["Body"]==pytest.approx(.625) and final.effective_weights["Head"]==pytest.approx(.375)


def records():
    rows=[]
    for index,(label,split,width) in enumerate((("normal","reference",20),("widened","reference",40),("normal","validation",22))):
        rows.append({"specimen_id":f"software-fixture-{index}","image_sha256":str(index)*64,"capture_session":f"capture-{index}",
            "source_id":"fixture-camera-plane","split":split,"reviewer":"Synthetic fixture reviewer","review_reference":"test-only",
            "measurement_validated":True,"ownership_validated":True,"body_region_validated":True,
            "fish_length_px":100,"max_body_width_px":width,"manual_width_label":label})
    return rows


def test_empty_reference_workflow_reports_missing_data_without_enabling_rules(tmp_path):
    path=tmp_path/"worksheet.json";main(["template","--output",str(path)])
    report=evaluate_reference(json.loads(path.read_text()))
    assert report["reviewed_configuration_proposal"] is None
    assert report["data_still_needed"] and not report["calibration_validated"]
    assert not report["thresholds_selected_by_program"] and not report["automatic_grading_enabled"]


def test_reviewed_reference_workflow_preserves_explicit_limits_and_remains_disabled():
    payload=review_template();payload["records"]=records()
    payload["calibration_review"]={"approved":True,"calibration_id":"software-fixture-only","source_id":"fixture-camera-plane",
        "reviewer":"Synthetic reviewer","review_reference":"fixture-review","held_out_grade_report":"fixture-grade-report",
        "normal_reference_min":.1,"normal_reference_max":.25,"extreme_reference":.45}
    report=evaluate_reference(payload);config=report["reviewed_configuration_proposal"]
    assert config["reference_distribution"]==(.2,)
    assert config["normal_reference_max"]==.25
    assert config["scoring_enabled"] is False and report["automatic_grading_enabled"] is False
    assert report["held_out_count"]==1


@pytest.mark.parametrize("gate",["duplicate","split_leakage","ownership","context"])
def test_unreviewed_or_leaking_reference_records_are_rejected(gate):
    payload=review_template();payload["records"]=records()
    if gate=="duplicate":payload["records"][1]["specimen_id"]=payload["records"][0]["specimen_id"]
    elif gate=="split_leakage":payload["records"][2]["capture_session"]=payload["records"][0]["capture_session"]
    elif gate=="ownership":payload["records"][0]["ownership_validated"]=False
    else:payload["records"][1]["source_id"]="another-camera"
    with pytest.raises(ValueError):evaluate_reference(payload)
