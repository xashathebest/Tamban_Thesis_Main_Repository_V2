"""Browser logic for actual on-demand mask requests and native-frame drawing."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def payload():
    fish = []
    for identity, left in ((1, 15), (2, 265)):
        fish.append({"id": identity, "bbox": [left, 30, left + 220, 120],
            "parts": [{"region": "Body", "bbox": [left + 60, 50, left + 150, 95],
                       "parent_track_id": identity, "coordinate_space": "original_frame"}],
            "segmentation": {"backend": "mobilesam_experimental", "preview_usable": True,
                "parent_track_id": identity, "ownership_status": "ambiguous", "engineering_checks_passed": False,
                "used_for_grading": False, "reasons": ["candidate_ownership_unvalidated"],
                "mask_overlay": {"coordinate_space": "original_frame", "frame_id": "native-source",
                    "frame_width_px": 500, "frame_height_px": 300,
                    "contours": [[[left + 5, 75], [left + 80, 45], [left + 200, 70], [left + 150, 105]]],
                    "conflict_contours": []}}})
    return {"status": "generated", "source": {"frame_id": "native-source", "frame_width_px": 500,
            "frame_height_px": 300}, "preview_image": "data:image/jpeg;base64,software-fixture",
            "fish": fish, "performance": {"segmentation_ms": 625.5}}


INCLUDE = r'''
const fs=require("fs"), vm=require("vm");
const source=fs.readFileSync("frontend/app.js","utf8");
vm.runInThisContext(source.match(/^const gradeColors = .*;$/m)[0]);
function include(name) {
  const start=source.indexOf(`function ${name}(`);
  if(start<0)throw new Error(`Missing ${name}`);
  const next=source.slice(start+1).search(/\n(?:async )?function /);
  const beginning=source.slice(start-6,start)==="async "?start-6:start;
  vm.runInThisContext(source.slice(beginning,next<0?source.length:start+1+next));
}
for(const name of ["fishZoomId","fishZoomGrade","aiFinalGrade","segmentationOverlayEvidence","maskPreviewColor","maskPreviewSource","maskPreviewEntries"])include(name);
'''


HARNESS = r'''
class Element {
  constructor(){this.children=[];this.dataset={};this.style={};this.value="";this.checked=true;this.width=0;this.height=0;this.textContent="";this.hidden=true;this.attributes={};this.classList={add:()=>{this.hidden=true;},remove:()=>{this.hidden=false;},toggle:()=>{}};}
  replaceChildren(...items){this.children=items;}
  append(...items){this.children.push(...items);}
  setAttribute(key,value){this.attributes[key]=value;}
}
global.document={createElement:()=>new Element()};global.draws=[];
const context={setTransform:(...args)=>draws.push(["transform",...args]),drawImage:(...args)=>draws.push(["image",...args.slice(1)]),save(){},restore(){},beginPath(){},closePath(){},moveTo:(...args)=>draws.push(["point",...args]),lineTo(){},fill:()=>draws.push(["fill"]),stroke(){},setLineDash(){},strokeRect:(...args)=>draws.push(["box",...args]),fillRect(){},measureText:text=>({width:text.length*8}),fillText:(text)=>draws.push(["text",text])};
global.elements={};
for(const key of ["maskPreview","maskPreviewCanvas","maskPreviewStatus","maskPreviewLoading","maskPreviewShow","maskPreviewModel1","maskPreviewModel2","maskPreviewOpacity","maskPreviewOpacityValue","maskPreviewFish","maskPreviewZoom","maskPreviewCancel","maskPreviewLegend"])elements[key]=new Element();
elements.maskPreviewCanvas.getContext=()=>context;elements.maskPreviewOpacity.value="40";elements.maskPreviewFish.value="all";elements.maskPreviewZoom.value="1";elements.maskPreviewModel2.checked=false;
global.selectedUpload={name:"actual-fish.jpg",type:"image/jpeg"};global.uploadInFlight=false;
global.uploadMaskPreview={data:null,image:null,file:null,version:0,controller:null,inFlight:false,timer:null,startedAt:0,analysisToken:"existing-analysis",analysisFile:selectedUpload};
global.controlsUpdated=0;global.updateUploadControls=()=>controlsUpdated++;
global.isVideoUpload=file=>Boolean(file?.type.startsWith("video/"));
global.setInterval=()=>1;global.clearInterval=()=>{};
global.Image=class{constructor(){this.naturalWidth=250;this.naturalHeight=150;}set src(value){queueMicrotask(()=>this.onload());}};
for(const name of ["inspectionEvidenceScope","measurementOverlayEvidence","crackOverlayEvidence","drawInspectionMeasurements","crackCandidateAtPoint","drawInspectionCracks","maskPreviewPolygons","renderMaskPreview","rememberMaskPreviewAnalysis","setMaskViewBusy","restoreOriginalUploadView","stopMaskPreparationTimer","prepareRecordedMaskPreview","stopMaskPreviewTimer","clearMaskPreview","cancelMaskPreview","maskPreviewLegend","inspectUploadMasks"])include(name);
'''


def node(script, value=None):
    executable = shutil.which("node")
    if executable is None:
        pytest.skip("Node.js required for preview request/drawing regression")
    result = subprocess.run([executable, "-e", script], input=json.dumps(value), text=True, encoding="utf-8",
                            cwd=ROOT, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_preview_entries_require_exact_parent_frame_and_native_dimensions():
    specimen = payload()
    cases = [specimen]
    for patch in ({"parent_track_id": 2}, {"preview_usable": False}, {"mask_overlay": {"frame_id": "stale"}},
                  {"mask_overlay": {"frame_width_px": 1000}}, {"mask_overlay": {"coordinate_space": "crop_local"}},
                  {"mask_overlay": {"contours": [[[10, 10], [501, 10], [40, 50]]]}}):
        changed = deepcopy(specimen)
        if "mask_overlay" in patch:
            changed["fish"][0]["segmentation"]["mask_overlay"].update(patch["mask_overlay"])
        else:
            changed["fish"][0]["segmentation"].update(patch)
        cases.append(changed)
    actual = node(INCLUDE + r'''
const cases=JSON.parse(fs.readFileSync(0,"utf8"));
console.log(JSON.stringify(cases.map(value=>maskPreviewEntries(value).map(entry=>({id:entry.id,contours:entry.contours,color:entry.color,review:entry.review})))));
''', cases)
    assert len(actual[0][0]["contours"]) == len(actual[0][1]["contours"]) == 1
    assert actual[0][0]["color"] != actual[0][1]["color"]
    assert all(case[0]["contours"] == [] for case in actual[1:])
    assert all(entry["review"] for entry in actual[0])


def test_preview_rejects_unassigned_neighbor_parts_without_losing_raw_record():
    specimen = payload()
    specimen["fish"][0]["parts"] += [
        {"region": "Head", "bbox": [10, 20, 50, 50], "parent_track_id": 2},
        {"region": "Tail", "bbox": [100, 20, 120, 70], "association_status": "UNASSIGNED"},
        {"region": "Body", "bbox": [100, 20, 120, 70], "coordinate_space": "crop_local"},
    ]
    result = node(INCLUDE + r'''
const data=JSON.parse(fs.readFileSync(0,"utf8"));const before=JSON.stringify(data);
console.log(JSON.stringify({parts:maskPreviewEntries(data)[0].parts,unchanged:before===JSON.stringify(data)}));
''', specimen)
    assert len(result["parts"]) == 1
    assert result["parts"][0]["region"] == "Body"
    assert result["unchanged"]


def test_inspect_performs_real_preview_request_reusing_analysis_token_and_original_file():
    actual = node(INCLUDE + HARNESS + r'''
const payload=JSON.parse(fs.readFileSync(0,"utf8"));let request;
global.fetch=async(url,options)=>{request={url,headers:options.headers,originalFile:options.body===selectedUpload,signal:!!options.signal};return {ok:true,json:async()=>payload};};
(async()=>{await inspectUploadMasks();console.log(JSON.stringify({request,status:elements.maskPreviewStatus.textContent,data:!!uploadMaskPreview.data,visible:!elements.maskPreview.hidden,opacity:elements.maskPreviewOpacityValue.textContent,draws,inFlight:uploadMaskPreview.inFlight}));})();
''', payload())
    assert actual["request"]["url"] == "/api/segmentation/preview"
    assert actual["request"]["headers"]["X-Preview-Analysis-Token"] == "existing-analysis"
    assert actual["request"]["originalFile"] and actual["request"]["signal"]
    assert actual["data"] and actual["visible"] and not actual["inFlight"]
    assert actual["opacity"] == "40%"
    assert "Generated 2 candidate masks" in actual["status"]
    assert "Segmentation 0.63s" in actual["status"]
    assert "Grading is unchanged" in actual["status"]
    assert sum(item[0] == "fill" for item in actual["draws"]) == 2


def test_selecting_fish_draws_only_its_own_native_mask_and_toggles_preserve_original():
    actual = node(INCLUDE + HARNESS + r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
elements.maskPreviewFish.value="2";renderMaskPreview();const selected=draws.slice();draws.length=0;
elements.maskPreviewShow.checked=false;elements.maskPreviewModel1.checked=false;renderMaskPreview();
console.log(JSON.stringify({selected,hidden:draws,width:elements.maskPreviewCanvas.width,height:elements.maskPreviewCanvas.height}));
''', payload())
    assert actual["width"] == 500 and actual["height"] == 300
    assert sum(item[0] == "fill" for item in actual["selected"]) == 1
    assert [item[1] for item in actual["selected"] if item[0] == "text"] == ["Fish #2 " + chr(183) + " Ungraded", "⚠"]
    assert all(item[1] >= 265 for item in actual["selected"] if item[0] == "point")
    assert any(item[0] == "image" for item in actual["hidden"])
    assert not any(item[0] in {"fill", "box", "text"} for item in actual["hidden"])


@pytest.mark.parametrize("failure", ["unavailable", "no_contours", "wrong_source"])
def test_no_success_for_empty_unavailable_or_mismatched_preview(failure):
    specimen = payload()
    if failure == "unavailable":
        specimen.update(status="unavailable", message="MobileSAM checkpoint checksum mismatch", setup_command="python -m src.evaluation.download_mobilesam_checkpoint")
    elif failure == "no_contours":
        for fish in specimen["fish"]:
            fish["segmentation"]["mask_overlay"]["contours"] = []
    else:
        specimen["source"]["frame_height_px"] = 450
    actual = node(INCLUDE + HARNESS + r'''
const payload=JSON.parse(fs.readFileSync(0,"utf8"));global.fetch=async()=>({ok:true,json:async()=>payload});
(async()=>{await inspectUploadMasks();console.log(JSON.stringify({status:elements.maskPreviewStatus.textContent,data:uploadMaskPreview.data,width:elements.maskPreviewCanvas.width,draws}));})();
''', specimen)
    assert actual["data"] is None and actual["width"] == 0
    assert "Generated 2" not in actual["status"]
    assert "No masks were applied" in actual["status"]
    assert not actual["draws"]
    if failure == "unavailable":
        assert "checksum mismatch" in actual["status"]
        assert "python -m src.evaluation.download_mobilesam_checkpoint" in actual["status"]


def test_new_selection_prevents_late_network_result_from_restoring_old_masks():
    actual = node(INCLUDE + HARNESS + r'''
const payload=JSON.parse(fs.readFileSync(0,"utf8"));let resolve;global.fetch=()=>new Promise(done=>resolve=done);
(async()=>{const pending=inspectUploadMasks();const controller=uploadMaskPreview.controller;clearMaskPreview();selectedUpload={name:"new.jpg",type:"image/jpeg"};resolve({ok:true,json:async()=>payload});await pending;
console.log(JSON.stringify({data:uploadMaskPreview.data,image:uploadMaskPreview.image,aborted:controller.signal.aborted,hidden:elements.maskPreview.hidden,width:elements.maskPreviewCanvas.width,draws}));})();
''', payload())
    assert actual == {"data": None, "image": None, "aborted": True, "hidden": True, "width": 0, "draws": []}


def test_cancel_or_stale_image_decode_cannot_redraw_the_previous_source():
    actual = node(INCLUDE + HARNESS + r'''
const payload=JSON.parse(fs.readFileSync(0,"utf8"));let lateLoad;
global.Image=class{constructor(){this.naturalWidth=250;this.naturalHeight=150;}set src(value){lateLoad=()=>this.onload();}};
global.fetch=async()=>({ok:true,json:async()=>payload});
(async()=>{const pending=inspectUploadMasks();await new Promise(resolve=>setImmediate(resolve));cancelMaskPreview();lateLoad();await pending;
console.log(JSON.stringify({data:uploadMaskPreview.data,width:elements.maskPreviewCanvas.width,status:elements.maskPreviewStatus.textContent,draws}));})();
''', payload())
    assert actual["data"] is None and actual["width"] == 0 and not actual["draws"]
    assert "canceled" in actual["status"]


def test_video_never_posts_video_bytes_to_the_still_mask_endpoint():
    result = node(INCLUDE + HARNESS + r'''
selectedUpload={name:"fish.mp4",type:"video/mp4"};let requests=0;global.fetch=async()=>{requests++;throw new Error("must not request");};
(async()=>{await inspectUploadMasks();console.log(JSON.stringify({requests,data:uploadMaskPreview.data}));})();
''')
    assert result == {"requests": 0, "data": None}


def test_regular_fish_zoom_does_not_paint_unassigned_model2_debug_boxes():
    result = node(INCLUDE + r'''
include("drawFishZoomOverlay");
global.elements={fishZoomAnnotations:{checked:true},fishZoomModel1:{checked:false},fishZoomModel2:{checked:true},fishZoomMask:{checked:false},fishZoomCracks:{checked:false}};
global.fishZoomAnalysis=fish=>fish.analysis;global.fishZoomRelativeBox=box=>box;global.gradeColors={};global.fishZoom={};
const boxes=[];const context={strokeRect:(...args)=>boxes.push(args),setLineDash(){}};
drawFishZoomOverlay(context,{bbox:[0,0,200,100],parts:[{region:"Body",bbox:[20,20,100,70]}],analysis:{model2_debug:{unassigned_detections:[{region:"Head",bbox:[130,10,170,50]}]}}},[0,0,200,100],200,100);
console.log(JSON.stringify(boxes));
''')
    assert result == [[20, 20, 80, 50]]
