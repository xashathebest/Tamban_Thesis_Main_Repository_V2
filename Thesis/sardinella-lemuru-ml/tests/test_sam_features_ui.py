"""Automatic mask results are a local, exclusive display of recorded evidence."""
from copy import deepcopy
import csv
from io import BytesIO, StringIO
import json
from pathlib import Path

from openpyxl import load_workbook
import pytest

from src.api.export import DEFAULT_EXPORT_FIELDS, EXPORT_FIELDS, inspection_row, make_csv, make_xlsx
from test_sam_preview_ui import INCLUDE, HARNESS, node, payload


ROOT = Path(__file__).resolve().parents[1]


AUTOMATIC = INCLUDE + HARNESS + r'''
for(const name of ["acceptAutomaticMaskPreview","selectInspectionFish"])include(name);
elements.maskPreviewBoxes=new Element();elements.maskPreviewMasks=new Element();elements.maskPreviewCracks=new Element();
elements.maskPreviewBoxes.checked=true;elements.maskPreviewMasks.checked=false;elements.maskPreviewCracks.checked=false;
elements.uploadMediaStage=new Element();
global.networkCalls=0;global.fetch=async()=>{networkCalls++;throw new Error("Display controls must not rerun analysis");};
'''


def test_completed_analysis_automatically_displays_recorded_result_without_new_request():
    specimen = payload(); specimen["performance"]["segmentation_ms"] = 734.
    actual = node(AUTOMATIC + r'''
const preview=JSON.parse(fs.readFileSync(0,"utf8"));const before=JSON.stringify(preview);
(async()=>{const accepted=await acceptAutomaticMaskPreview({segmentation_preview:preview},selectedUpload);
console.log(JSON.stringify({accepted,networkCalls,width:elements.maskPreviewCanvas.width,height:elements.maskPreviewCanvas.height,
  visible:!elements.maskPreview.hidden,originalHidden:elements.uploadMediaStage.hidden,draws,status:elements.maskPreviewStatus.textContent,unchanged:before===JSON.stringify(preview)}));})();
''', specimen)
    assert actual["accepted"] and actual["visible"] and actual["originalHidden"]
    assert actual["networkCalls"] == 0 and actual["unchanged"]
    assert (actual["width"], actual["height"]) == (500, 300)
    assert sum(row[0] == "box" for row in actual["draws"]) == 2
    assert not any(row[0] == "fill" for row in actual["draws"])
    assert "Segmentation 0.73s" in actual["status"]


def test_boxes_masks_toggle_is_exclusive_and_never_calls_network_or_regrades():
    actual = node(AUTOMATIC + r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
renderMaskPreview();const boxes=draws.splice(0);elements.maskPreviewBoxes.checked=false;elements.maskPreviewMasks.checked=true;
renderMaskPreview();const masks=draws.splice(0);elements.maskPreviewBoxes.checked=true;elements.maskPreviewMasks.checked=false;
renderMaskPreview();console.log(JSON.stringify({boxes,masks,back:draws,networkCalls}));
''', payload())
    assert actual["networkCalls"] == 0
    for key in ("boxes", "back"):
        assert sum(row[0] == "box" for row in actual[key]) == 2
        assert not any(row[0] == "fill" for row in actual[key])
    assert sum(row[0] == "fill" for row in actual["masks"]) == 2
    assert not any(row[0] == "box" for row in actual["masks"])


def test_selected_mask_and_result_card_remain_synchronized():
    actual = node(AUTOMATIC + r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
const cards=[1,2].map(id=>({dataset:{inspectionFishId:String(id)},open:false,classList:{toggle(_name,value){this.selected=value;}}}));
elements.resultsGroups={querySelectorAll:()=>cards};elements.maskPreviewMasks.checked=true;elements.maskPreviewBoxes.checked=false;
selectInspectionFish(2,{revealCard:true});console.log(JSON.stringify({value:elements.maskPreviewFish.value,cards,draws,networkCalls}));
''', payload())
    assert actual["value"] == "2" and actual["cards"][1]["open"]
    assert actual["cards"][1]["classList"]["selected"]
    assert not actual["cards"][0]["classList"]["selected"]
    assert sum(row[0] == "fill" for row in actual["draws"]) == 1
    assert actual["networkCalls"] == 0


def test_late_automatic_source_decode_cannot_restore_a_previous_analysis():
    actual = node(AUTOMATIC + r'''
const preview=JSON.parse(fs.readFileSync(0,"utf8"));let finish;
global.Image=class{constructor(){this.naturalWidth=250;this.naturalHeight=150;}set src(_value){finish=()=>this.onload();}};
(async()=>{const pending=acceptAutomaticMaskPreview({segmentation_preview:preview},selectedUpload);clearMaskPreview();selectedUpload={name:"new.jpg"};finish();
console.log(JSON.stringify({accepted:await pending,data:uploadMaskPreview.data,draws,width:elements.maskPreviewCanvas.width}));})();
''', payload())
    assert actual == {"accepted": False, "data": None, "draws": [], "width": 0}


@pytest.mark.parametrize("scope", ["matching", "wrong_frame", "wrong_parent", "out_of_frame"])
def test_structural_locations_draw_only_on_matching_parent_source_pixels(scope):
    specimen = payload()
    damage = {"status": "suspected", "frame_id": "native-source", "parent_track_id": 1,
              "coordinate_space": "crop_local_native_pixels", "crop_bounds": [15,30,235,120],
              "locations": [{"x": 70., "y": 30., "width": 40., "height": 3.}]}
    if scope == "wrong_frame": damage["frame_id"] = "old-frame"
    if scope == "wrong_parent": damage["parent_track_id"] = 2
    if scope == "out_of_frame": damage["locations"][0]["x"] = 1000.
    specimen["fish"][0]["analysis"] = {"surface_damage": damage}
    actual = node(AUTOMATIC + r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
elements.maskPreviewCracks.checked=true;renderMaskPreview();console.log(JSON.stringify({draws}));
''', specimen)
    crack_boxes = [row for row in actual["draws"] if row[0] == "box" and row[1] == 85.]
    assert len(crack_boxes) == (1 if scope == "matching" else 0)
    if crack_boxes: assert crack_boxes[0][1:] == [85.,60.,40.,3.]


def test_live_mode_changes_only_mutually_exclusive_display_settings():
    actual = node(INCLUDE + r'''
include("setLiveVisualizationMode");global.elements={liveDisplayBoxes:{checked:true},liveDisplayMasks:{checked:false}};
const calls=[];global.postSettings=value=>calls.push(value);setLiveVisualizationMode("masks");const first=structuredClone(elements);
setLiveVisualizationMode("boxes");console.log(JSON.stringify({calls,first,last:elements}));
''')
    assert actual["calls"] == [{"display_settings": {"outlines": False,"fish_masks": True}},
                                {"display_settings": {"outlines": True,"fish_masks": False}}]
    assert actual["first"]["liveDisplayMasks"]["checked"]
    assert not actual["last"]["liveDisplayMasks"]["checked"]


def test_primary_dom_has_one_exclusive_mode_and_no_manual_sam_button():
    source = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    assert 'id="upload-display-boxes" type="radio" name="upload-display-mode"' in source
    assert 'id="upload-display-masks" type="radio" name="upload-display-mode"' in source
    for old in ('id="upload-mask-show"', 'id="upload-mask-model1"', 'id="inspect-upload-masks"', 'id="upload-mobilesam"'):
        assert old not in source


def specimen(*, estimated=False, confirmed=False):
    geometry = {"status": "measured", "representative_body_width_px": 38., "whole_fish_max_width_px": 55.,
        "whole_fish_length_to_width_ratio": 5., "body_profile_length_px": 110., "body_width_to_length_ratio": .4,
        "body_width_profile_cv": .07, "body_region_validated": True, "ownership_validated": True,
        "units": {"length": "px", "ratios": "dimensionless"}}
    if estimated:
        geometry.update(sampling={"mode": "mobilesam_candidate", "estimated": True}, candidate_measurements={"representative_body_width_px": 38.})
    structural = {"status": "confirmed", "severity": "major", "severity_validated": confirmed, "source_bound": confirmed,
        "validation_provenance": {"reviewer": "synthetic software fixture"}, "used_for_grading": True,
        "calibration_status": "Calibrated" if confirmed else "Not calibrated", "score_shift": .05,
        "contribution_reason": "reviewed_major_rule" if confirmed else "candidate_only"}
    fusion = {"structural": structural, "eligibility": {"rule_applied": True, "class_a_eligible": False, "policy_id": "fixture"},
              "original_grade": "Class A", "final_grade": "Class B" if confirmed else "Class A", "structural_changed_classification": True}
    return {"id": 1, "bbox": [1,1,300,100], "quality": fusion["final_grade"], "analysis": {"final_grade": fusion["final_grade"],
            "fish_geometry": geometry, "feature_fusion": fusion}}


@pytest.mark.parametrize("estimated,confirmed", [(False,True),(True,False)])
def test_csv_xlsx_append_anatomical_fusion_fields_without_promoting_estimates(estimated, confirmed):
    value = specimen(estimated=estimated, confirmed=confirmed); before = deepcopy(value)
    fields = ("representative_body_width_px", "anatomical_geometry_estimates", "structural_severity",
              "structural_used_for_grading", "class_a_eligibility_restricted", "feature_fusion_original_grade", "feature_fusion_final_grade")
    row = inspection_row(value)
    assert row["representative_body_width_px"] == ("" if estimated else 38.)
    if estimated: assert json.loads(row["anatomical_geometry_estimates"])["representative_body_width_px"] == 38.
    assert row["structural_severity"] == ("major" if confirmed else "Unassessed")
    assert row["class_a_eligibility_restricted"] == row["structural_used_for_grading"] == ("Yes" if confirmed else "No")
    assert row["feature_fusion_original_grade"] == "Class A"
    assert row["feature_fusion_final_grade"] == ("Class B" if confirmed else "Class A")
    csv_row = next(csv.DictReader(StringIO(make_csv([value], fields).decode("utf-8-sig"))))
    workbook = load_workbook(BytesIO(make_xlsx([value], fields, {})), data_only=True)
    excel = dict(zip(fields, list(workbook["Fish Inspections"].values)[1]))
    for field in fields[2:]: assert csv_row[EXPORT_FIELDS[field]] == str(excel[field])
    assert value == before


def test_estimated_geometry_explanation_keeps_body_measurement_units_and_uncertainty():
    value = specimen(estimated=True)
    actual = node(INCLUDE + r'''
include("geometryStructuralRows");console.log(JSON.stringify(geometryStructuralRows(JSON.parse(fs.readFileSync(0,"utf8")))));
''', value)
    rows = dict(actual)
    assert rows["Representative central Body width (px)"] == "38 (estimate; unvalidated)"
    assert rows["Body-region validation"] == "Body anatomy not independently validated"
    assert "dimensionless" in rows["Units"] and rows["Normal reference range"] == "Not calibrated"


@pytest.mark.parametrize("final_grade,support", [("Class B", .81), ("Ungraded", None)])
def test_final_exports_and_ui_use_structural_eligibility_result_after_geometric_stage(final_grade, support):
    value = specimen(confirmed=True)
    value["quality"] = "Class A"  # An earlier stage is deliberately retained.
    value["analysis"]["geometric_support"] = {"original_grade": "Class A", "final_grade": "Class A", "final_support": .95,
        "original_scores": {"Class A": .95}, "final_scores": {"Class A": .95, "Class B": .05}}
    fusion = value["analysis"]["feature_fusion"]
    fusion.update(schema_version="feature_fusion_v1", final_grade=final_grade, final_support=support,
                  final_scores={"Class A": .19, "Class B": .81})
    value["analysis"]["final_grade"] = final_grade
    row = inspection_row(value)
    assert row["grade"] == row["final_combined_grade"] == final_grade
    assert row["final_combined_support"] == ("" if support is None else 81.)
    assert json.loads(row["final_combined_scores"])["Class B"] == .81
    assert json.loads(row["geometric_support"])["final_grade"] == "Class A"
    actual = node(INCLUDE + r'''
for(const name of ["eventValue","analysisFor","weightedFinalSupport","aiFinalGrade"])include(name);
const fish=JSON.parse(fs.readFileSync(0,"utf8"));console.log(JSON.stringify({grade:aiFinalGrade(fish),support:weightedFinalSupport(fish)}));
''', value)
    assert actual == {"grade": final_grade, "support": support}
