"""Experimental candidates stay scoped to their fish, source frame and exports."""
from copy import deepcopy
import csv
from io import BytesIO, StringIO
import json
from pathlib import Path
import shutil
import subprocess

from openpyxl import load_workbook
import pytest

from src.api.export import DEFAULT_EXPORT_FIELDS, EXPORT_FIELDS, inspection_row, make_csv, make_xlsx


ROOT = Path(__file__).resolve().parents[1]
FIELDS = (
    "segmentation_backend", "segmentation_status", "segmentation_ownership_status",
    "segmentation_validation_status", "segmentation_mask_score", "segmentation_reasons",
    "segmentation_checkpoint_sha256", "segmentation_frame_id", "segmentation_embedding_ms",
    "segmentation_prompt_ms", "segmentation_used_for_grading", "segmentation_shadow_association",
    "segmentation_candidate_evidence",
)


def event():
    return {"id": 7, "quality": "Class B", "quality_confidence": .8, "bbox": [5, 5, 55, 45],
        "parts": [{"bbox": [15, 10, 40, 35], "region": "Body", "grade": "Class B"}],
        "analysis": {"final_grade": "Class B", "weighted_scores": {"Class B": .8},
            "inspection_source": {"frame_id": "frame-old"},
            "segmentation": {"backend": "mobilesam_experimental", "experimental": True,
                "parent_track_id": 7, "status": "candidate", "ownership_status": "checks_passed_unvalidated",
                "validation_status": "validated", "used_for_grading": True,  # A forged claim must not promote it.
                "mask_score_unvalidated": .99, "checkpoint_sha256": "a" * 64,
                "reasons": ["No independently reviewed ownership labels"],
                "timings": {"embedding_ms": 12., "mask_decode_ms": 2.5},
                "shadow_association": {"applied": False, "required_body_owned": False},
                "source_parent_bbox": [10, 10, 60, 50],
                "source_parts": [{"bbox": [20, 15, 45, 40], "coordinate_space": "original_frame"}],
                "mask_overlay": {"coordinate_space": "original_frame", "frame_id": "frame-2",
                    "frame_width_px": 100, "frame_height_px": 80,
                    "contours": [[[10, 10], [60, 10], [60, 50], [10, 50]]],
                    "source_preview_image": "data:image/jpeg;base64,AA"}}}}


def test_candidate_exports_append_without_promoting_validation_or_changing_grade():
    specimen = event(); before = deepcopy(specimen)
    assert DEFAULT_EXPORT_FIELDS[-len(FIELDS):] == FIELDS
    row = inspection_row(specimen)
    assert row["grade"] == "Class B"
    assert row["segmentation_mask_score"] == .99
    assert row["segmentation_validation_status"] == "Not independently validated (experimental)"
    assert row["segmentation_used_for_grading"] == "No"
    evidence = json.loads(row["segmentation_candidate_evidence"])
    assert "source_preview_image" not in evidence["mask_overlay"]
    assert evidence["mask_overlay"]["source_preview_image_recorded"] is True
    assert evidence["used_for_grading"] is True  # The raw claim remains available for review.
    csv_row = next(csv.DictReader(StringIO(make_csv([specimen], FIELDS).decode("utf-8-sig"))))
    workbook = load_workbook(BytesIO(make_xlsx([specimen], FIELDS, {})), data_only=True)
    excel = dict(zip(FIELDS, list(workbook["Fish Inspections"].values)[1]))
    assert csv_row[EXPORT_FIELDS["segmentation_used_for_grading"]] == excel["segmentation_used_for_grading"] == "No"
    assert json.loads(csv_row[EXPORT_FIELDS["segmentation_candidate_evidence"]]) == json.loads(excel["segmentation_candidate_evidence"]) == evidence
    assert specimen == before


@pytest.mark.parametrize("score", [None, True, "0.99", 10**400])
def test_invalid_mask_scores_are_not_reported_as_confidence(score):
    specimen = event(); specimen["analysis"]["segmentation"]["mask_score_unvalidated"] = score
    assert inspection_row(specimen)["segmentation_mask_score"] == ""


@pytest.mark.parametrize("score", [float("nan"), float("inf")])
def test_nonfinite_raw_candidate_evidence_retains_strict_json_rejection(score):
    specimen = event(); specimen["analysis"]["segmentation"]["mask_score_unvalidated"] = score
    with pytest.raises(ValueError, match="JSON compliant"):
        inspection_row(specimen)


def node(script, payload=None):
    executable = shutil.which("node")
    if executable is None:
        pytest.skip("Node.js is required for candidate UI behavior")
    result = subprocess.run([executable, "-e", script], input=json.dumps(payload) if payload is not None else "",
                            text=True, cwd=ROOT, capture_output=True, check=True)
    return json.loads(result.stdout)


INCLUDE = r'''
const fs = require("fs"); const vm = require("vm");
const source = fs.readFileSync("frontend/app.js", "utf8");
function include(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`Missing ${name}`);
  const next = source.slice(start + 1).search(/\n(?:async )?function /);
  const beginning = source.slice(start - 6, start) === "async " ? start - 6 : start;
  vm.runInThisContext(source.slice(beginning, next < 0 ? source.length : start + 1 + next));
}
'''


def test_candidate_overlay_checks_identity_dimensions_and_source_frame():
    script = INCLUDE + r'''
for (const name of ["fishZoomId", "segmentationEvidenceRows", "segmentationOverlayEvidence", "segmentationSnapshotObservation"]) include(name);
const fish = JSON.parse(fs.readFileSync(0,"utf8"));
const cases = [fish];
for (const patch of [{parent_track_id:8}, {mask_overlay:{frame_id:"other"}}, {mask_overlay:{frame_width_px:99}},
  {mask_overlay:{coordinate_space:"crop_local"}}, {mask_overlay:{contours:[[[0,0],[101,0],[0,10]]]}},
  {mask_overlay:{contours:[[[0,0],["50",0],[0,10]]]}}]) {
  const changed = structuredClone(fish);
  if (patch.mask_overlay) Object.assign(changed.analysis.segmentation.mask_overlay, patch.mask_overlay);
  else Object.assign(changed.analysis.segmentation, patch);
  cases.push(changed);
}
console.log(JSON.stringify({evidence:segmentationEvidenceRows(fish), overlays:cases.map(item=>segmentationOverlayEvidence(item,"frame-2",100,80)),
  unknown:segmentationOverlayEvidence(fish,null,100,80), snapshot:segmentationSnapshotObservation(fish,"frame-2"), raw:fish}));
'''
    specimen = event(); actual = node(script, specimen)
    assert len(actual["overlays"][0]["contours"]) == 1
    assert all(not item["contours"] for item in actual["overlays"][1:])
    assert actual["unknown"]["frame_matches"] is False
    assert "withheld" in actual["unknown"]["reason"]
    evidence = dict(actual["evidence"])
    assert evidence["Validation"] == "Not independently validated (experimental)"
    assert "not fish-ownership confidence" in evidence["Model mask score"]
    assert evidence["Mask effect on grading"].startswith("None")
    assert actual["snapshot"]["bbox"] == [10, 10, 60, 50]
    assert actual["snapshot"]["parts"] == specimen["analysis"]["segmentation"]["source_parts"]
    assert actual["raw"] == specimen


def test_snapshot_never_borrows_best_grade_parts_from_another_frame():
    specimen = event(); del specimen["analysis"]["segmentation"]["source_parts"]
    del specimen["analysis"]["segmentation"]["source_parent_bbox"]
    actual = node(INCLUDE + r'''
include("segmentationSnapshotObservation"); const fish=JSON.parse(fs.readFileSync(0,"utf8"));
console.log(JSON.stringify(segmentationSnapshotObservation(fish,"frame-2")));
''', specimen)
    assert actual["bbox"] is None and actual["parts"] == []
    assert actual["quality"] == "Class B" and actual["quality_confidence"] == .8


def test_primary_completion_status_does_not_hide_failed_or_unreliable_masks():
    actual = node(INCLUDE + r'''
include("segmentationCompletionNote");
console.log(JSON.stringify([segmentationCompletionNote([]),segmentationCompletionNote([{analysis:{segmentation:{status:"unavailable"}}}]),
segmentationCompletionNote([{analysis:{segmentation:{status:"candidate",ownership_status:"unreliable"}}}]),
segmentationCompletionNote([{analysis:{segmentation:{status:"candidate",ownership_status:"checks_passed_unvalidated"}}}])]));
''')
    assert "no fish detected" in actual[0]
    assert "MobileSAM unavailable" in actual[1]
    assert "ownership review" in actual[2]
    assert "unvalidated" in actual[3] and "do not change grades" in actual[3]


def test_explicit_request_header_is_off_by_default_and_captured_per_analysis():
    script = INCLUDE + r'''
const marker='elements.analyze.addEventListener("click", async () => {';
let listener; const calls=[]; const status={textContent:""};
global.elements={analyze:{addEventListener(_name,fn){listener=fn;},classList:{add(){},remove(){}},textContent:""}, uploadStatus:status, segmentationExperiment:{checked:false}};
global.selectedUpload={name:"fish.jpg",type:"image/jpeg"}; global.uploadInFlight=false;global.uploadRequestVersion=0;global.uploadController=null;
for(const name of ["setUploadSelection","closeFishZoom","startUploadTimer","stopUploadTimer","updateUploadTimer","updateUploadControls"]) global[name]=()=>{};
global.isVideoUpload=()=>false;global.uploadElapsedSeconds=()=>1.2;
global.fetch=async(_url,options)=>{calls.push(options.headers);return {ok:false,status:409,json:async()=>({detail:"Test response before inference"})};};
const start=source.indexOf(marker); const end=source.indexOf("function pixelBox(",start);
vm.runInThisContext(source.slice(start,end));
(async()=>{await listener();elements.segmentationExperiment.checked=true;await listener();console.log(JSON.stringify(calls));})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    actual = node(script)
    assert "X-Segmentation-Backend" not in actual[0]
    assert actual[1]["X-Segmentation-Backend"] == "mobilesam_experimental"
    html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    toggle = html.split('id="upload-mobilesam"', 1)[1].split(">", 1)[0]
    assert "checked" not in toggle


def test_closing_zoom_cancels_pending_old_source_image():
    script = INCLUDE + r'''
for(const name of ["fishZoomAnalysis","openFishZoom","closeFishZoom"])include(name);
const fish=JSON.parse(fs.readFileSync(0,"utf8"));let resolve;
global.fishZoomRequestVersion=0;global.fishZoom={image:{old:true},detection:fish,previousFocus:null};global.selectedUpload=null;
global.fishZoomMedia=()=>({});global.fishZoomImage=()=>new Promise(done=>{resolve=done;});
global.elements={fishZoomCanvas:{width:50,height:50},fishZoomModal:{classList:{add(){}}}};
global.document={body:{classList:{remove(){}}}};
(async()=>{const pending=openFishZoom("upload",[fish],fish);closeFishZoom();resolve({naturalWidth:100,naturalHeight:80});await pending;
console.log(JSON.stringify({image:fishZoom.image,detection:fishZoom.detection,frameId:fishZoom.frameId,canvasWidth:elements.fishZoomCanvas.width}));})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    actual = node(script, event())
    assert actual == {"image": None, "detection": None, "frameId": None, "canvasWidth": 0}
