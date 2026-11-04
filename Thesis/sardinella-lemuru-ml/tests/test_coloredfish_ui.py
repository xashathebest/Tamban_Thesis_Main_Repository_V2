"""Source-bound measurement/crack overlays exercise recorded evidence only."""
from copy import deepcopy
from pathlib import Path

import pytest

from test_sam_preview_ui import HARNESS, INCLUDE, node, payload


ROOT = Path(__file__).resolve().parents[1]

EVIDENCE = INCLUDE + r'''
for(const name of ["inspectionFishEvidenceEntry","inspectionEvidenceScope","measurementOverlayEvidence","crackOverlayEvidence"])include(name);
'''

MEASURE = EVIDENCE + r'''
const value=JSON.parse(fs.readFileSync(0,"utf8")),before=JSON.stringify(value);
const entry=maskPreviewEntries(value)[0],sourceFrame=maskPreviewSource(value);
console.log(JSON.stringify({result:measurementOverlayEvidence(entry,sourceFrame),unchanged:before===JSON.stringify(value)}));
'''

CRACKS = EVIDENCE + r'''
const value=JSON.parse(fs.readFileSync(0,"utf8")),before=JSON.stringify(value);
const entry=maskPreviewEntries(value)[0],sourceFrame=maskPreviewSource(value);
console.log(JSON.stringify({result:crackOverlayEvidence(entry,sourceFrame),unchanged:before===JSON.stringify(value)}));
'''


def specimen():
    """Synthetic display fixture; these values are not anatomical labels."""
    value = payload()
    fish = value["fish"][0]
    fish["segmentation"].update(
        ownership_status="checks_passed_unvalidated", engineering_checks_passed=True
    )
    fish["analysis"] = {
        "fish_geometry": {
            "status": "unreliable", "measurement_validated": False,
            "used_for_grading": False,
            "reasons": ["experimental_mask_requires_ownership_validation"],
            "candidate_measurements": {
                "fish_length_px": 186., "max_body_width_px": 42.,
                "representative_body_width_px": 38., "relative_width_ratio": .2258,
            },
            "candidate_visualization": {
                "coordinate_space": "original_frame", "status": "estimated", "measured": False,
                "frame_id": "native-source", "frame_width_px": 500, "frame_height_px": 300,
                "parent_track_id": 1, "source_parent_id": 1,
                "principal_axis": [[35., 55.], [215., 100.]],
                "length_path": [[35., 55.], [125., 78.], [215., 100.]],
                "width_axis": [[130., 55.], [120., 95.]],
                "representative_width_axis": [[170., 65.], [161., 102.]],
                "representative_width_axis_value_px": 39.,
                "representative_width_axis_method": "Observed section nearest median",
                "reasons": ["experimental_mask_requires_ownership_validation"],
            },
        },
        "body_width": {"classification": "unavailable", "score_contributed": False,
                       "reason": "No calibrated anatomical width reference."},
        "surface_damage": {
            "status": "suspected", "coordinate_space": "crop_local_native_pixels",
            "frame_id": "native-source", "frame_width_px": 500, "frame_height_px": 300,
            "parent_track_id": 1, "source_parent_id": 1, "crop_bounds": [15, 30, 235, 120],
            "validation_status": "unvalidated", "severity": "unassessed",
            "used_for_grading": False,
            "reason": "Localized evidence requires expert review; severity is unassessed.",
            "locations": [{"x": 70., "y": 38., "width": 50., "height": 4.,
                           "estimated_length_px": 50., "area_px": 100,
                           "contours": [[[70., 38.], [119., 38.], [119., 41.], [70., 41.]]]}],
        },
    }
    return value


def test_measurement_and_crack_controls_preserve_existing_viewer_controls():
    html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    for name in ("upload-mask-measurements", "upload-mask-cracks"):
        control = html.split(f'id="{name}"', 1)[1].split(">", 1)[0]
        assert 'type="checkbox"' in control
        assert "checked" not in control
    assert "Show Measurements" in html and "Show Cracks" in html
    for name in ("upload-display-boxes", "upload-display-masks", "upload-mask-opacity",
                 "upload-mask-fish", "upload-mask-zoom", "upload-mask-model1",
                 "upload-mask-model2", "upload-mask-show", "upload-association-debug"):
        assert f'id="{name}"' in html


def test_estimated_lines_use_actual_rotated_native_geometry_and_observed_section():
    value = specimen()
    actual = node(MEASURE, value)
    result = actual["result"]
    assert actual["unchanged"] and result["status"] == "Estimated"
    lines = {line["key"]: line for line in result["lines"]}
    visualization = value["fish"][0]["analysis"]["fish_geometry"]["candidate_visualization"]
    assert lines["length"]["points"] == visualization["length_path"]
    assert lines["maximum"]["points"] == visualization["width_axis"]
    assert lines["representative"]["points"] == visualization["representative_width_axis"]
    assert lines["representative"]["value"] == 39.
    assert result["values"]["representative_body_width_px"] == 38.
    assert "experimental mask requires ownership validation" in result["reason"]


@pytest.mark.parametrize("fault", ["frame", "parent", "dimensions", "space", "withheld", "identity"])
def test_measurement_lines_withheld_for_unmatched_or_unavailable_native_evidence(fault):
    value = specimen()
    fish = value["fish"][0]
    visualization = fish["analysis"]["fish_geometry"]["candidate_visualization"]
    if fault == "frame": visualization["frame_id"] = "previous-frame"
    elif fault == "parent": visualization.update(parent_track_id=2, source_parent_id=2)
    elif fault == "dimensions": visualization["frame_width_px"] = 1000
    elif fault == "space": visualization["coordinate_space"] = "crop_local_pixels"
    elif fault == "withheld": visualization["status"] = "unavailable"
    else: fish["segmentation"]["source_detection_id"] = 9
    actual = node(MEASURE, value)
    assert actual["unchanged"]
    assert actual["result"]["status"] == "Unavailable"
    assert actual["result"]["lines"] == []
    assert actual["result"]["reason"]


def test_numeric_values_cannot_invent_axes_from_the_parent_box():
    value = specimen()
    geometry = value["fish"][0]["analysis"]["fish_geometry"]
    for key in ("principal_axis", "length_path", "width_axis", "representative_width_axis"):
        geometry["candidate_visualization"].pop(key)
    actual = node(MEASURE, value)["result"]
    assert actual["status"] == "Unavailable" and actual["lines"] == []
    assert actual["values"]["fish_length_px"] == 186.
    assert "Values alone cannot locate an overlay" in actual["reason"]


@pytest.mark.parametrize("metadata", [
    {"frame_id": "previous-frame"},
    {"parent_track_id": 2, "source_parent_id": 2},
    {"frame_width_px": 1000},
    {"frame_height_px": 600},
])
def test_matching_visualization_cannot_overwrite_conflicting_geometry_provenance(metadata):
    value = specimen()
    geometry = value["fish"][0]["analysis"]["fish_geometry"]
    geometry.update(metadata)
    result = node(MEASURE, value)["result"]
    assert result["status"] == "Unavailable" and result["lines"] == []


def test_missing_body_geometry_preserves_real_length_without_guessing_width_lines():
    value = specimen()
    geometry = value["fish"][0]["analysis"]["fish_geometry"]
    for key in ("width_axis", "representative_width_axis"):
        geometry["candidate_visualization"].pop(key)
    geometry["candidate_measurements"].update(max_body_width_px=None, representative_body_width_px=None, relative_width_ratio=None)
    geometry["reasons"] = ["body_association_unreliable"]
    actual = node(MEASURE, value)["result"]
    assert [line["key"] for line in actual["lines"]] == ["length"]
    assert actual["status"] == "Estimated" and "body association unreliable" in actual["reason"]


def test_reviewed_geometry_is_distinguished_from_an_engineering_estimate():
    value = specimen()
    geometry = value["fish"][0]["analysis"]["fish_geometry"]
    geometry.update(geometry["candidate_measurements"])
    geometry.update(status="measured", measurement_validated=True, ownership_validated=True,
                    body_region_validated=True, validation_provenance={"reviewer": "software fixture"})
    geometry["visualization"] = deepcopy(geometry.pop("candidate_visualization"))
    geometry["visualization"]["status"] = "validated"
    actual = node(MEASURE, value)["result"]
    assert actual["status"] == "Validated"
    geometry["measurement_validated"] = False
    assert node(MEASURE, value)["result"]["status"] == "Estimated"


def test_detected_crack_contour_translates_crop_origin_once_and_stays_unvalidated():
    actual = node(CRACKS, specimen())
    candidates = actual["result"]["candidates"]
    assert actual["unchanged"] and len(candidates) == 1
    assert candidates[0]["bbox"] == [85., 68., 135., 72.]
    assert candidates[0]["contours"] == [[[85., 68.], [134., 68.], [134., 71.], [85., 71.]]]
    assert candidates[0]["status"] == "Estimated" and candidates[0]["severity"] == "Unassessed"


@pytest.mark.parametrize("fault", ["frame", "parent", "dimensions", "space", "negative_local", "outside_crop", "no_candidates"])
def test_cracks_require_real_locations_bound_to_this_source_and_fish(fault):
    value = specimen()
    damage = value["fish"][0]["analysis"]["surface_damage"]
    if fault == "frame": damage["frame_id"] = "previous-frame"
    elif fault == "parent": damage.update(parent_track_id=2, source_parent_id=2)
    elif fault == "dimensions": damage["frame_height_px"] = 301
    elif fault == "space": damage["coordinate_space"] = "resized_crop"
    elif fault == "negative_local": damage["locations"][0]["x"] = -1.
    elif fault == "outside_crop": damage["locations"][0]["width"] = 200.
    else: damage.update(status="not_detected", locations=[])
    actual = node(CRACKS, value)
    assert actual["unchanged"] and actual["result"]["candidates"] == []
    assert actual["result"]["reason"]


def test_unvalidated_severity_does_not_color_or_reclassify_a_candidate():
    value = specimen()
    damage = value["fish"][0]["analysis"]["surface_damage"]
    damage["severity"] = "major"
    damage["locations"][0]["severity"] = "minor"
    actual = node(CRACKS, value)["result"]["candidates"][0]
    assert actual["severity"] == "Unassessed" and actual["status"] == "Estimated"


def test_reviewed_fish_level_severity_is_not_borrowed_by_individual_candidates():
    value = specimen()
    damage = value["fish"][0]["analysis"]["surface_damage"]
    damage.update(validation_status="validated", mask_validated_for_cracks=True,
                  validation_provenance={"reviewer": "software fixture"}, severity="major", severity_validated=True)
    candidate = node(CRACKS, value)["result"]["candidates"][0]
    assert candidate["status"] == "Validated" and candidate["severity"] == "Unassessed"
    damage["locations"][0].update(severity="minor", severity_validated=True)
    assert node(CRACKS, value)["result"]["candidates"][0]["severity"] == "minor"


def test_candidate_click_hits_the_contour_instead_of_empty_space_inside_its_box():
    result = node(INCLUDE + r'''
include("crackCandidateAtPoint");
const candidates=[{id:"triangular-support",bbox:[10,10,100,100],contours:[[[10,10],[100,10],[10,100]]]}];
console.log(JSON.stringify({inside:crackCandidateAtPoint(candidates,20,20)?.id||null,
 emptyCorner:crackCandidateAtPoint(candidates,90,90),nearOutline:crackCandidateAtPoint(candidates,56,56,3)?.id||null}));
''')
    assert result == {"inside": "triangular-support", "emptyCorner": None, "nearOutline": "triangular-support"}


def test_overlay_toggles_zoom_and_selection_use_only_cached_results():
    actual = node(EVIDENCE + HARNESS + r'''
for(const name of ["drawInspectionMeasurements","drawInspectionCracks"])include(name);
elements.maskPreviewMeasurements=new Element();elements.maskPreviewMeasurements.checked=false;
elements.maskPreviewCracks=new Element();elements.maskPreviewCracks.checked=false;
elements.maskPreviewMasks=new Element();elements.maskPreviewMasks.checked=true;
elements.maskPreviewBoxes=new Element();elements.maskPreviewBoxes.checked=false;
const value=JSON.parse(fs.readFileSync(0,"utf8")),before=JSON.stringify(value);
uploadMaskPreview.data=value;uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
let networkCalls=0;global.fetch=async()=>{networkCalls++;throw new Error("Overlay controls must not rerun inference");};
context.lineTo=(...point)=>draws.push(["line",...point]);
renderMaskPreview();draws.length=0;
elements.maskPreviewMeasurements.checked=true;elements.maskPreviewCracks.checked=true;elements.maskPreviewZoom.value="3";
renderMaskPreview();const first=draws.splice(0);
elements.maskPreviewFish.value="2";renderMaskPreview();
console.log(JSON.stringify({first,second:draws,networkCalls,unchanged:before===JSON.stringify(value),width:elements.maskPreviewCanvas.width,
 zoom:elements.maskPreviewCanvas.style.width}));
''', specimen())
    assert actual["networkCalls"] == 0 and actual["unchanged"]
    assert actual["width"] == 500 and actual["zoom"] == "300%"
    assert any(row == ["point", 35., 55.] for row in actual["first"])
    assert any(row == ["line", 125., 78.] for row in actual["first"])
    assert not any(row[0] == "text" and ("Length:" in row[1] or "Candidate 1" in row[1]) for row in actual["second"])


def test_measurement_labels_stay_separate_when_measurement_endpoints_are_close():
    actual = node(EVIDENCE + HARNESS + r'''
include("drawInspectionMeasurements");
const value=JSON.parse(fs.readFileSync(0,"utf8"));
const evidence=measurementOverlayEvidence(maskPreviewEntries(value)[0],maskPreviewSource(value));
const backgrounds=[];context.fillRect=(...args)=>backgrounds.push(args);context.measureText=text=>({width:text.length*4});
drawInspectionMeasurements(context,evidence,maskPreviewSource(value),1.5,12);
console.log(JSON.stringify({backgrounds}));
''', specimen())
    boxes = actual["backgrounds"]
    assert len(boxes) == 3
    for index, (left, top, width, height) in enumerate(boxes):
        for other_left, other_top, other_width, other_height in boxes[index + 1:]:
            assert (left + width <= other_left or other_left + other_width <= left
                    or top + height <= other_top or other_top + other_height <= top)


def test_large_image_downsampling_applies_canvas_transform_to_native_measurement_points():
    value = specimen()
    value["source"].update(frame_width_px=5000, frame_height_px=3000)
    fish = value["fish"][0]
    fish["bbox"] = [coordinate * 10 for coordinate in fish["bbox"]]
    visualization = fish["analysis"]["fish_geometry"]["candidate_visualization"]
    visualization.update(frame_width_px=5000, frame_height_px=3000)
    for key in ("principal_axis", "length_path", "width_axis", "representative_width_axis"):
        visualization[key] = [[coordinate * 10 for coordinate in point] for point in visualization[key]]
    actual = node(EVIDENCE + HARNESS + r'''
include("drawInspectionMeasurements");
elements.maskPreviewMeasurements=new Element();elements.maskPreviewMeasurements.checked=true;
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
renderMaskPreview();console.log(JSON.stringify({draws,width:elements.maskPreviewCanvas.width,height:elements.maskPreviewCanvas.height}));
''', value)
    assert (actual["width"], actual["height"]) == (2048, 1229)
    transform = next(row for row in actual["draws"] if row[0] == "transform")
    assert transform[1:] == [2048 / 5000, 0, 0, 1229 / 3000, 0, 0]
    assert ["point", 350., 550.] in actual["draws"]


@pytest.mark.parametrize("blocked", [False, True])
def test_zoom_candidate_click_inverts_css_scale_native_crop_and_pan(blocked):
    actual = node(INCLUDE + r'''
include("selectFishZoomCrackPoint");
include("crackCandidateAtPoint");
const blocked=JSON.parse(fs.readFileSync(0,"utf8"));
global.elements={fishZoomCracks:{checked:true},fishZoomCanvas:{getBoundingClientRect:()=>({left:10,top:20,width:500,height:300})}};
global.fishZoom={nativeWidth:1200,nativeHeight:900,frameId:"native-source",crop:[400,100,800,300],
 drawTransform:{x:50,y:60,scale:2,viewWidth:1000,viewHeight:600},detection:{id:1},selectedCrackId:null,suppressCrackClick:blocked};
let sourceSeen=null,redraws=0,detailRenders=0;
global.inspectionFishEvidenceEntry=fish=>fish;
global.crackOverlayEvidence=(entry,source)=>{sourceSeen=source;return {candidates:[{id:"real-candidate",bbox:[500,200,530,210],contours:[]}]};};
global.renderFishZoomDetails=()=>detailRenders++;
global.renderFishZoom=()=>redraws++;
selectFishZoomCrackPoint({clientX:150,clientY:155});
console.log(JSON.stringify({selected:fishZoom.selectedCrackId,sourceSeen,redraws,detailRenders}));
''', blocked)
    if blocked:
        assert actual == {"selected": None, "sourceSeen": None, "redraws": 0, "detailRenders": 0}
    else:
        assert actual == {
            "selected": "real-candidate", "sourceSeen": {"width": 1200, "height": 900, "frameId": "native-source"},
            "redraws": 1, "detailRenders": 1,
        }
