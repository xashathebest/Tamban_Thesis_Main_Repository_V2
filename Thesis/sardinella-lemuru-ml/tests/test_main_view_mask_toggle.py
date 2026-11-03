"""Main-view switching preserves the original result and existing controls."""
from html.parser import HTMLParser
from pathlib import Path

from test_sam_features_ui import AUTOMATIC, node, payload


MAIN = AUTOMATIC + r'''
for (const key of ["maskPreviewViewport","uploadImage","uploadVideo","uploadFishTargets"]) {
  elements[key]=new Element();
  elements[key].classList.contains=()=>elements[key].hidden;
}
elements.uploadImage.hidden=false;elements.uploadVideo.hidden=true;
elements.uploadImage.src="existing-annotated-image";
elements.maskPreviewViewport.hidden=true;
elements.maskPreviewModel1.checked=true;
'''


def test_toggle_uses_main_area_and_restores_identical_annotated_image_without_requests():
    actual=node(MAIN+r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
renderMaskPreview();const boxes={imageHidden:elements.uploadImage.hidden,maskHidden:elements.maskPreviewViewport.hidden,src:elements.uploadImage.src};
elements.maskPreviewBoxes.checked=false;elements.maskPreviewMasks.checked=true;renderMaskPreview();
const masks={imageHidden:elements.uploadImage.hidden,maskHidden:elements.maskPreviewViewport.hidden,mainHidden:elements.uploadMediaStage.hidden};
elements.maskPreviewBoxes.checked=true;elements.maskPreviewMasks.checked=false;renderMaskPreview();
console.log(JSON.stringify({boxes,masks,restored:{imageHidden:elements.uploadImage.hidden,maskHidden:elements.maskPreviewViewport.hidden,src:elements.uploadImage.src},networkCalls}));
''',payload())
    assert actual["boxes"]==actual["restored"]=={"imageHidden":False,"maskHidden":True,"src":"existing-annotated-image"}
    assert actual["masks"]=={"imageHidden":True,"maskHidden":False,"mainHidden":False}
    assert actual["networkCalls"]==0


def test_secondary_visibility_controls_opacity_highlight_and_zoom_stay_independent():
    actual=node(MAIN+r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
elements.maskPreviewBoxes.checked=false;elements.maskPreviewMasks.checked=true;
elements.maskPreviewModel1.checked=false;elements.maskPreviewShow.checked=false;renderMaskPreview();const hidden=draws.splice(0);
elements.maskPreviewShow.checked=true;elements.maskPreviewFish.value="2";elements.maskPreviewOpacity.value="40";elements.maskPreviewZoom.value="2";
renderMaskPreview();const shaded=draws.splice(0);
elements.maskPreviewModel1.checked=true;elements.maskPreviewModel2.checked=true;renderMaskPreview();
console.log(JSON.stringify({hidden,shaded,annotated:draws,zoom:elements.maskPreviewCanvas.style.width,opacity:elements.maskPreviewOpacityValue.textContent,
  settings:{show:elements.maskPreviewShow.checked,model1:elements.maskPreviewModel1.checked,model2:elements.maskPreviewModel2.checked,fish:elements.maskPreviewFish.value},networkCalls}));
''',payload())
    assert not any(row[0] in {"fill","box"} for row in actual["hidden"])
    assert sum(row[0]=="fill" for row in actual["shaded"])==1
    assert not any(row[0]=="box" for row in actual["shaded"])
    assert sum(row[0]=="box" for row in actual["annotated"])==2
    assert actual["zoom"]=="200%" and actual["opacity"]=="40%"
    assert actual["settings"]=={"show":True,"model1":True,"model2":True,"fish":"2"}
    assert actual["networkCalls"]==0


def test_new_analysis_resets_mode_and_canvas_without_removing_overlay_preferences():
    actual=node(MAIN+r'''
uploadMaskPreview.data=JSON.parse(fs.readFileSync(0,"utf8"));uploadMaskPreview.image={};uploadMaskPreview.file=selectedUpload;
elements.maskPreviewMasks.checked=true;elements.maskPreviewBoxes.checked=false;elements.maskPreviewOpacity.value="25";
renderMaskPreview();clearMaskPreview();
console.log(JSON.stringify({data:uploadMaskPreview.data,canvas:elements.maskPreviewCanvas.width,masksHidden:elements.maskPreviewViewport.hidden,
  boxes:elements.maskPreviewBoxes.checked,masks:elements.maskPreviewMasks.checked,opacity:elements.maskPreviewOpacity.value,networkCalls}));
''',payload())
    assert actual=={"data":None,"canvas":0,"masksHidden":True,"boxes":True,"masks":False,"opacity":"25","networkCalls":0}


def test_unavailable_masks_keep_original_image_and_explain_missing_overlay():
    actual=node(MAIN+r'''
elements.maskPreviewBoxes.checked=false;elements.maskPreviewMasks.checked=true;renderMaskPreview();
console.log(JSON.stringify({imageHidden:elements.uploadImage.hidden,maskHidden:elements.maskPreviewViewport.hidden,status:elements.maskPreviewStatus.textContent,networkCalls}));
''')
    assert not actual["imageHidden"] and actual["maskHidden"]
    assert "unavailable" in actual["status"] and actual["networkCalls"]==0


def test_existing_per_fish_masks_are_reused_without_a_new_preview_endpoint_request():
    actual=node(MAIN+r'''
const fixture=JSON.parse(fs.readFileSync(0,"utf8"));global.uploadPreviewUrl=fixture.preview_image;
const existing={fish:fixture.fish.map(row=>({id:row.id,bbox:row.bbox,parts:row.parts,analysis:{segmentation:row.segmentation}}))};
const before=JSON.stringify(existing);
(async()=>{const accepted=await acceptAutomaticMaskPreview(existing,selectedUpload);elements.maskPreviewBoxes.checked=false;elements.maskPreviewMasks.checked=true;renderMaskPreview();
console.log(JSON.stringify({accepted,networkCalls,unchanged:before===JSON.stringify(existing),masks:uploadMaskPreview.data.fish.length,visible:!elements.maskPreviewViewport.hidden}));})();
''',payload())
    assert actual=={"accepted":True,"networkCalls":0,"unchanged":True,"masks":2,"visible":True}


def test_canvas_is_inside_original_main_view_and_all_control_ids_are_retained():
    class Structure(HTMLParser):
        def __init__(self):super().__init__();self.stack=[];self.ancestors={}
        def handle_starttag(self,tag,attrs):
            data=dict(attrs)
            if data.get("id"):self.ancestors[data["id"]]=list(self.stack)
            if tag not in {"input","img","br","hr","meta","link","use","path"}:self.stack.append(data.get("id") or tag)
        def handle_endtag(self,tag):
            if tag not in {"input","img","br","hr","meta","link","use","path"} and self.stack:self.stack.pop()
    parser=Structure();parser.feed((Path(__file__).resolve().parents[1]/"frontend/index.html").read_text(encoding="utf-8"))
    assert "upload-media-stage" in parser.ancestors["upload-mask-canvas"]
    assert "upload-mask-preview" not in parser.ancestors["upload-mask-canvas"]
    assert {"upload-display-boxes","upload-display-masks","upload-mask-show","upload-mask-model1","upload-mask-model2",
            "upload-mask-opacity","upload-mask-fish","upload-mask-zoom","upload-mask-legend"} <= parser.ancestors.keys()
