"""Clicks on displayed fish open inspection using the recorded source frame."""
import pytest

from test_coloredfish_ui import specimen
from test_sam_preview_ui import HARNESS, INCLUDE, node


CLICK = INCLUDE + HARNESS + r'''
include("selectMaskPreviewPoint");
elements.maskPreviewCanvas.getBoundingClientRect=()=>({left:10,top:20,width:1000,height:600});
elements.maskPreviewMasks={checked:true};elements.maskPreviewBoxes={checked:false};
elements.maskPreviewCracks={checked:false};
elements.maskPreviewModel1.checked=false;
const opens=[],selections=[],candidatePanels=[];
global.openMaskPreviewFishZoom=entry=>{opens.push(entry.id);};
global.selectInspectionFish=(id,options)=>selections.push({id,revealCard:options?.revealCard});
global.showCrackCandidate=(entry,candidate)=>candidatePanels.push({fish:entry.id,candidate:candidate.id});
'''


@pytest.mark.parametrize("mode,x,y", [("masks", 125, 85), ("boxes", 20, 40)])
def test_click_fish_in_mask_or_box_canvas_opens_zoom_after_native_css_mapping(mode, x, y):
    actual = node(CLICK + r'''
const input=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.data=input.payload;uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
elements.maskPreviewMasks.checked=input.mode==="masks";elements.maskPreviewBoxes.checked=input.mode==="boxes";
selectMaskPreviewPoint({clientX:10+input.x*2,clientY:20+input.y*2});
console.log(JSON.stringify({opens,selections,candidatePanels}));
''', {"payload": specimen(), "mode": mode, "x": x, "y": y})
    assert actual["opens"] == [1]
    assert actual["candidatePanels"] == []


@pytest.mark.parametrize("mode", ["masks", "boxes"])
def test_background_click_does_not_open_a_fish_modal(mode):
    actual = node(CLICK + r'''
const input=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.data=input.payload;
elements.maskPreviewMasks.checked=input.mode==="masks";elements.maskPreviewBoxes.checked=input.mode==="boxes";
selectMaskPreviewPoint({clientX:10+450*2,clientY:20+250*2});
console.log(JSON.stringify({opens,selections,candidatePanels}));
''', {"payload": specimen(), "mode": mode})
    assert actual == {"opens": [], "selections": [], "candidatePanels": []}


def test_mask_mode_does_not_open_from_empty_space_inside_the_parent_bbox():
    actual = node(CLICK + r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));
selectMaskPreviewPoint({clientX:10+20*2,clientY:20+40*2});
console.log(JSON.stringify({opens,selections}));
''', specimen())
    assert actual == {"opens": [], "selections": []}


def test_visible_model1_box_remains_clickable_outside_its_shaded_mask():
    actual = node(CLICK + r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));elements.maskPreviewModel1.checked=true;
selectMaskPreviewPoint({clientX:10+20*2,clientY:20+40*2});
console.log(JSON.stringify({opens}));
''', specimen())
    assert actual["opens"] == [1]


def test_crack_candidate_click_keeps_priority_over_fish_zoom():
    actual = node(CLICK + r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));elements.maskPreviewCracks.checked=true;
selectMaskPreviewPoint({clientX:10+110*2,clientY:20+70*2});
console.log(JSON.stringify({opens,selections,candidatePanels}));
''', specimen())
    assert actual["opens"] == []
    assert actual["candidatePanels"] == [{"fish": 1, "candidate": "1:0"}]


def test_highlighted_fish_filter_is_respected_by_canvas_zoom_clicks():
    actual = node(CLICK + r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));elements.maskPreviewFish.value="2";
selectMaskPreviewPoint({clientX:10+125*2,clientY:20+85*2});
console.log(JSON.stringify({opens,selections}));
''', specimen())
    assert actual == {"opens": [], "selections": []}


@pytest.mark.parametrize("video", [False, True], ids=["photo", "recorded-video-snapshot"])
def test_cached_zoom_helper_preserves_source_native_dimensions_layers_and_snapshot_bbox(video):
    actual = node(CLICK + r'''
include("openMaskPreviewFishZoom");
const input=JSON.parse(fs.readFileSync(0,"utf8")),before=JSON.stringify(input.payload);
uploadMaskPreview.data=input.payload;uploadMaskPreview.image={naturalWidth:250,naturalHeight:150};
if(input.video)selectedUpload={name:"recorded.mp4",type:"video/mp4"};
uploadMaskPreview.file=selectedUpload;
elements.maskPreviewShow.checked=true;elements.maskPreviewMeasurements={checked:true};elements.maskPreviewCracks.checked=true;
elements.maskPreviewModel1.checked=false;elements.maskPreviewModel2.checked=true;elements.maskPreviewOpacity.value="35";
global.resultDatasets={upload:{rows:input.payload.fish.map(fish=>({...fish,quality:"Class B",analysis:{...fish.analysis,segmentation:fish.segmentation}}))}};
let opened=null;global.openFishZoom=(kind,detections,selected,options)=>{opened={kind,detections,selected,
 sameImage:options.source.image===uploadMaskPreview.image,source:{...options.source,image:undefined},layers:options.layers};};
global.captureFishZoomFrame=()=>{throw new Error("Recorded snapshots must not recapture video");};
global.URL={createObjectURL:()=>{throw new Error("Cached source must not reopen a file");}};
openMaskPreviewFishZoom(maskPreviewEntries(input.payload)[0]);
console.log(JSON.stringify({opened,selections,unchanged:before===JSON.stringify(input.payload)}));
''', {"payload": specimen(), "video": video})
    opened = actual["opened"]
    assert actual["unchanged"] and opened["kind"] == "upload" and opened["sameImage"]
    assert opened["source"] == {"frameId": "native-source", "width": 500, "height": 300}
    assert opened["selected"]["id"] == 1
    assert opened["selected"]["bbox"] == [15, 30, 235, 120]
    assert opened["selected"]["analysis"]["segmentation"]["source_parent_bbox"] == [15, 30, 235, 120]
    assert opened["layers"] == {"mask": True, "boxes": False, "parts": True, "measurements": True, "cracks": True, "opacity": .35}


def test_original_box_targets_use_native_coordinates_inside_image_padding():
    actual = node(CLICK + r'''
for(const name of ["fishZoomBox","fishZoomGeometry","fishZoomPoint","fishZoomHits","renderFishClickTargets"])include(name);
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.file=selectedUpload;
uploadMaskPreview.image={naturalWidth:250,naturalHeight:150};
const media={naturalWidth:250,naturalHeight:150,classList:{contains:()=>false},
 getBoundingClientRect:()=>({left:110,top:216,width:1018,height:618})};
elements.uploadMediaStage={getBoundingClientRect:()=>({left:100,top:200,width:1000,height:600})};
elements.uploadFishTargets=new Element();
Element.prototype.addEventListener=function(name,handler){(this.listeners??={})[name]=handler;};
global.fishZoomMedia=()=>media;
global.getComputedStyle=()=>({borderLeftWidth:"1px",borderRightWidth:"1px",borderTopWidth:"1px",borderBottomWidth:"1px",
 paddingLeft:"8px",paddingRight:"8px",paddingTop:"8px",paddingBottom:"8px"});
let stopped=false;
renderFishClickTargets("upload",uploadMaskPreview.data.fish);
const target=elements.uploadFishTargets.children[0];target.listeners.click({stopPropagation:()=>stopped=true});
const hits=fishZoomHits({clientX:369,clientY:395},"upload",uploadMaskPreview.data.fish).map(fish=>fish.id);
console.log(JSON.stringify({style:target.style,opens,stopped,hits}));
''', specimen())
    assert actual["style"] == {"left": "49px", "top": "85px", "width": "440px", "height": "180px"}
    assert actual["opens"] == [1] and actual["stopped"]
    assert actual["hits"] == [1]
