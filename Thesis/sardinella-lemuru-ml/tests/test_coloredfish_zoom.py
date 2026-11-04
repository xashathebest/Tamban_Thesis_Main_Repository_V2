"""Zoom inspection retains native evidence through CSS scaling, pan and DPR."""

import pytest

from test_sam_preview_ui import INCLUDE, node


ZOOM = INCLUDE + r'''
for(const name of ["inspectionFishEvidenceEntry","inspectionEvidenceScope","crackOverlayEvidence",
                   "crackCandidateAtPoint","renderFishZoom","selectFishZoomCrackPoint"])include(name);
global.networkCalls=0;global.fetch=()=>{networkCalls++;throw new Error("Overlays must reuse recorded evidence");};
const calls=[],context={setTransform:(...args)=>calls.push(["transform",...args]),fillRect(){},
  drawImage:(_image,...args)=>calls.push(["image",...args]),save(){},restore(){},
  translate:(...args)=>calls.push(["translate",...args]),scale:(...args)=>calls.push(["scale",...args])};
global.elements={fishZoomCanvas:{style:{},getContext:()=>context,
  getBoundingClientRect:()=>({left:40,top:25,width:400,height:250})},
  fishZoomViewport:{getBoundingClientRect:()=>({width:800,height:500})},
  fishZoomOriginal:{checked:true},fishZoomCracks:{checked:true},fishZoomLevel:{}};
global.fishZoom={image:{naturalWidth:1000,naturalHeight:500},nativeWidth:4000,nativeHeight:2000,
  frameId:"zoom-frame",crop:[1000,400,1800,800],scale:1.75,panX:27,panY:-11,
  detection:{id:1,bbox:[1000,400,1800,800],analysis:{surface_damage:{
    status:"suspected",coordinate_space:"original_frame",parent_track_id:1,
    frame_id:"zoom-frame",frame_width_px:4000,frame_height_px:2000,
    locations:[{x:1195,y:498,width:25,height:7,estimated_length_px:24,
      contours:[[[1195,498],[1220,498],[1220,505],[1195,505]]]}]}}},
  selectedCrackId:null,suppressCrackClick:false};
global.drawFishZoomOverlay=(_context,_fish,crop,width,height)=>calls.push(["overlay",crop,width,height]);
let detailRenders=0;global.renderFishZoomDetails=()=>detailRenders++;
'''


@pytest.mark.parametrize("dpr", [1, 2, 3])
def test_zoom_render_and_click_share_native_crop_transform_at_high_dpr(dpr):
    actual = node(ZOOM + r'''
global.window={devicePixelRatio:JSON.parse(fs.readFileSync(0,"utf8"))};
renderFishZoom();const first=calls.slice(),t=fishZoom.drawTransform;
// The displayed canvas is CSS-scaled to half its layout size. Click the native
// candidate at (1200,500), using the rendered pan and zoom transform.
selectFishZoomCrackPoint({clientX:40+(t.x+(1200-1000)*t.scale)*.5,
                         clientY:25+(t.y+(500-400)*t.scale)*.5});
console.log(JSON.stringify({first,transform:t,width:elements.fishZoomCanvas.width,
  height:elements.fishZoomCanvas.height,selected:fishZoom.selectedCrackId,detailRenders,networkCalls}));
''', dpr)
    assert actual["width"] == 800 * dpr and actual["height"] == 500 * dpr
    assert actual["first"][0] == ["transform", dpr, 0, 0, dpr, 0, 0]
    assert actual["first"][1] == ["image", 250, 100, 200, 100, -203, -76, 1260, 630]
    assert actual["first"][2] == ["translate", -203, -76]
    assert actual["first"][3] == ["scale", 1.575, 1.575]
    assert actual["first"][4] == ["overlay", [1000, 400, 1800, 800], 800, 400]
    assert actual["selected"] == "1:0" and actual["detailRenders"] == 1
    assert actual["networkCalls"] == 0


@pytest.mark.parametrize("mismatch", ["frame", "parent", "dimensions"])
def test_zoom_click_cannot_select_evidence_from_a_different_source(mismatch):
    actual = node(ZOOM + r'''
global.window={devicePixelRatio:2};
const mismatch=JSON.parse(fs.readFileSync(0,"utf8")),damage=fishZoom.detection.analysis.surface_damage;
if(mismatch==="frame")damage.frame_id="old-frame";
if(mismatch==="parent")damage.parent_track_id=2;
if(mismatch==="dimensions")damage.frame_width_px=2000;
renderFishZoom();const t=fishZoom.drawTransform;
selectFishZoomCrackPoint({clientX:40+(t.x+200*t.scale)*.5,clientY:25+(t.y+100*t.scale)*.5});
console.log(JSON.stringify({selected:fishZoom.selectedCrackId,detailRenders,networkCalls}));
''', mismatch)
    assert actual == {"selected": None, "detailRenders": 0, "networkCalls": 0}


def test_zoom_click_uses_detected_contour_rather_than_empty_candidate_box_corner():
    actual = node(ZOOM + r'''
global.window={devicePixelRatio:2};
const location=fishZoom.detection.analysis.surface_damage.locations[0];
location.height=60;location.contours=[[[1195,498],[1220,553],[1218,558],[1195,503]]];
renderFishZoom();const t=fishZoom.drawTransform;
// (1218,500) lies inside the candidate bounds but outside its slanted support.
selectFishZoomCrackPoint({clientX:40+(t.x+218*t.scale)*.5,clientY:25+(t.y+100*t.scale)*.5});
console.log(JSON.stringify({selected:fishZoom.selectedCrackId,detailRenders,networkCalls}));
''')
    assert actual == {"selected": None, "detailRenders": 0, "networkCalls": 0}


def test_zoom_unavailable_placement_keeps_numbers_explicitly_estimated_diagnostics():
    actual = node(INCLUDE + r'''
include("renderFishZoomDetails");
class Element{constructor(){this.children=[];}append(...items){this.children.push(...items);}replaceChildren(){this.children=[];}}
global.document={createElement:()=>new Element()};global.elements={fishZoomDetails:new Element()};
global.fishZoom={nativeWidth:500,nativeHeight:300,frameId:"zoom-frame",selectedCrackId:null};
global.fishZoomDetailRows=()=>[];global.fishZoomAnalysis=fish=>fish.analysis;
global.inspectionFishEvidenceEntry=fish=>fish;
global.measurementOverlayEvidence=()=>({status:"Unavailable",reason:"Ownership cannot be established",values:{fish_length_px:185}});
global.crackOverlayEvidence=()=>({candidates:[],reason:"No reliable crack evidence"});
renderFishZoomDetails({id:1,analysis:{}});
console.log(JSON.stringify(elements.fishZoomDetails.children.map(row=>row.children.map(cell=>cell.textContent))));
''')
    rows = dict(actual)
    assert rows["Geometry"] == "Unavailable"
    assert rows["Length (px)"] == "185 · Estimated diagnostic; overlay unavailable"
    assert rows["Maximum Body width (px)"] == "Unavailable"
