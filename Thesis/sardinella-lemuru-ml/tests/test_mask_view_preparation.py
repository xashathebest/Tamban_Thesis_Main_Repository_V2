"""Mask mode has a bounded, visible preparation path without duplicate work."""
from test_main_view_mask_toggle import MAIN
from test_sam_preview_ui import node, payload


PREPARE = MAIN + r'''
include("setMainViewerMode");
'''


def test_loading_shows_elapsed_time_then_automatically_reveals_cached_masks_once():
    actual=node(PREPARE+r'''
const data=JSON.parse(fs.readFileSync(0,"utf8"));let finish,tick,images=0,clock=0;
global.performance={now:()=>clock};global.setInterval=fn=>{tick=fn;return 1;};
global.Image=class{constructor(){images++;this.naturalWidth=250;this.naturalHeight=150;}set src(value){finish=()=>this.onload();}};
(async()=>{
 const automatic=acceptAutomaticMaskPreview({segmentation_preview:data},selectedUpload);
 const selected=setMainViewerMode("masks");clock=750;tick();
 const loading={visible:!elements.maskPreviewLoading.hidden,text:elements.maskPreviewStatus.textContent,busy:elements.maskPreview.attributes['aria-busy']};
 finish();await Promise.all([automatic,selected]);
 console.log(JSON.stringify({loading,images,networkCalls,ready:!elements.maskPreviewViewport.hidden,spinnerHidden:elements.maskPreviewLoading.hidden,busy:elements.maskPreview.attributes['aria-busy'],status:elements.maskPreviewStatus.textContent}));
})();
''',payload())
    assert actual["loading"]["visible"] and actual["loading"]["busy"]=="true"
    assert "0.8s" in actual["loading"]["text"]
    assert actual["images"]==1 and actual["networkCalls"]==0
    assert actual["ready"] and actual["spinnerHidden"] and actual["busy"]=="false"
    assert "Showing 2 cached" in actual["status"]


def test_switching_back_during_preparation_is_immediate_and_does_not_flip_back_later():
    actual=node(PREPARE+r'''
const data=JSON.parse(fs.readFileSync(0,"utf8"));let finish;
elements.uploadImage.hidden=true;uploadMaskPreview.mainMedia="image";
global.Image=class{constructor(){this.naturalWidth=250;this.naturalHeight=150;}set src(value){finish=()=>this.onload();}};
(async()=>{const automatic=acceptAutomaticMaskPreview({segmentation_preview:data},selectedUpload);
 const selected=setMainViewerMode("masks");await setMainViewerMode("boxes");const boxesImmediately=elements.maskPreviewBoxes.checked&&!elements.uploadImage.hidden;
 finish();await Promise.all([automatic,selected]);
 console.log(JSON.stringify({boxesImmediately,boxes:elements.maskPreviewBoxes.checked,masks:elements.maskPreviewMasks.checked,maskHidden:elements.maskPreviewViewport.hidden,networkCalls}));})();
''',payload())
    assert actual=={"boxesImmediately":True,"boxes":True,"masks":False,"maskHidden":True,"networkCalls":0}


def test_decode_failure_is_visible_and_clears_spinner_without_discarding_original():
    actual=node(PREPARE+r'''
uploadMaskPreview.analysis={segmentation_preview:JSON.parse(fs.readFileSync(0,"utf8"))};uploadMaskPreview.analysisFile=selectedUpload;
global.Image=class{constructor(){this.naturalWidth=250;this.naturalHeight=150;}set src(value){queueMicrotask(()=>this.onerror());}};
(async()=>{await setMainViewerMode("masks");console.log(JSON.stringify({status:elements.maskPreviewStatus.textContent,spinnerHidden:elements.maskPreviewLoading.hidden,original:elements.uploadImage.src,networkCalls}));})();
''',payload())
    assert "could not be displayed" in actual["status"]
    assert actual["spinnerHidden"] and actual["original"]=="existing-annotated-image" and actual["networkCalls"]==0


def test_revoked_upload_url_does_not_prevent_reusing_recorded_per_fish_masks():
    actual=node(PREPARE+r'''
const data=JSON.parse(fs.readFileSync(0,"utf8"));global.uploadPreviewUrl=null;let created=0,revoked=0;
global.URL={createObjectURL(file){created++;return 'blob:fresh-current-file';},revokeObjectURL(value){if(value==='blob:fresh-current-file')revoked++;}};
const recorded={fish:data.fish.map(f=>({id:f.id,bbox:f.bbox,parts:f.parts,analysis:{segmentation:f.segmentation}}))};
(async()=>{await acceptAutomaticMaskPreview(recorded,selectedUpload);await setMainViewerMode("masks");console.log(JSON.stringify({created,revoked,networkCalls,ready:!elements.maskPreviewViewport.hidden}));})();
''',payload())
    assert actual=={"created":1,"revoked":1,"networkCalls":0,"ready":True}


def test_missing_masks_request_generation_once_reuses_snapshot_and_keeps_requested_mode():
    actual=node(PREPARE+r'''
const data=JSON.parse(fs.readFileSync(0,"utf8"));let requests=0,token;
global.fetch=async(url,options)=>{requests++;token=options.headers['X-Preview-Analysis-Token'];return {ok:true,json:async()=>data};};
(async()=>{await setMainViewerMode("masks");await setMainViewerMode("boxes");await setMainViewerMode("masks");
console.log(JSON.stringify({requests,token,masks:elements.maskPreviewMasks.checked,ready:!elements.maskPreviewViewport.hidden,spinnerHidden:elements.maskPreviewLoading.hidden}));})();
''',payload())
    assert actual=={"requests":1,"token":"existing-analysis","masks":True,"ready":True,"spinnerHidden":True}


def test_preparation_from_an_old_analysis_cannot_paint_after_new_selection():
    actual=node(PREPARE+r'''
const data=JSON.parse(fs.readFileSync(0,"utf8"));let finish;
global.Image=class{constructor(){this.naturalWidth=250;this.naturalHeight=150;}set src(value){finish=()=>this.onload();}};
(async()=>{const pending=acceptAutomaticMaskPreview({segmentation_preview:data},selectedUpload);clearMaskPreview();selectedUpload={name:'another.png',type:'image/png'};finish();await pending;
console.log(JSON.stringify({data:uploadMaskPreview.data,spinnerHidden:elements.maskPreviewLoading.hidden,width:elements.maskPreviewCanvas.width,hidden:elements.maskPreviewViewport.hidden}));})();
''',payload())
    assert actual=={"data":None,"spinnerHidden":True,"width":0,"hidden":True}
