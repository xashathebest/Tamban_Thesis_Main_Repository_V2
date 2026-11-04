"""Exercise actual fish click handlers in Chrome with cached native-frame data."""
import anatomical_debug_browser_smoke as browser
from test_coloredfish_ui import specimen


browser.OUTPUT = browser.ROOT / "results/qa/fish_click_zoom"
browser.specimen = specimen
browser.EXERCISE = r'''(async()=>{
const checks={},fixture=window.__associationFixture,delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const until=async(predicate,message)=>{const start=performance.now();while(!predicate()){if(performance.now()-start>5000)throw new Error(message+'; '+elements.uploadStatus.textContent);await delay(20);}};
let requests=0,captures=0,objectUrls=0;
window.fetch=async()=>{requests++;throw new Error('Fish detail must reuse recorded analysis');};
fixture.fish[0].analysis.surface_damage={status:'suspected',coordinate_space:'original_frame',
 frame_id:'native-source',parent_track_id:1,validation_status:'unvalidated',severity:'unassessed',
 locations:[{x:85,y:68,width:50,height:4,estimated_length_px:50,
 contours:[[[85,68],[134,68],[134,71],[85,71]]]}]};
// This source is reduced to half native resolution, as real preview payloads
// are for large uploads. The cached metadata remains in original pixels.
const source=document.createElement('canvas');source.width=250;source.height=150;
const pen=source.getContext('2d');pen.fillStyle='#e9eff1';pen.fillRect(0,0,250,150);
pen.fillStyle='#9cabba';for(const x of [15,265]){pen.beginPath();pen.ellipse((x+105)/2,37.5,52.5,15,0,0,2*Math.PI);pen.fill();}
fixture.preview_image=source.toDataURL();
const overlapping=structuredClone(fixture.fish[1]);overlapping.id=3;overlapping.bbox=[70,35,250,125];overlapping.parts=[];overlapping.analysis={};
overlapping.segmentation.parent_track_id=3;overlapping.segmentation.mask_overlay.contours=[[[75,80],[120,50],[240,75],[180,110]]];
fixture.fish.push(overlapping);
const file=new File(['Invalid original bytes: cached image must be used'],'cached-source.png',{type:'image/png'});
toggleUpload(true);selectedUpload=file;elements.uploadImage.src=fixture.preview_image;
elements.uploadImage.classList.remove('hidden');elements.uploadVideo.classList.add('hidden');
const fish=fixture.fish.map(item=>({...structuredClone(item),quality:'Class B',analysis:{...structuredClone(item.analysis||{}),
 segmentation:structuredClone(item.segmentation),final_grade:'Class B',weighted_scores:{'Class B':.8},inspection_source:{frame_id:'other-grade-frame'}}}));
resultsSource='upload';renderResultsDashboard(fish,{source:'upload',complete:true,scope:'fish-click-ui-fixture',metadata:{source_name:'Cached click software fixture'}});
mountResultsDashboard(true);elements.uploadResults.classList.remove('hidden');
await acceptAutomaticMaskPreview({fish,segmentation_preview:fixture},file);
const before=JSON.stringify(resultDatasets.upload.rows),cachedImage=uploadMaskPreview.image;
checks.reducedCachedSource=cachedImage.naturalWidth===250&&fixture.source.frame_width_px===500;
captureFishZoomFrame=()=>{captures++;throw new Error('Do not recapture a recorded frame');};
URL.createObjectURL=()=>{objectUrls++;throw new Error('Use the decoded cached source');};
renderFishClickTargets('upload',fish);await delay(300);
const target=elements.uploadFishTargets.querySelector('[data-fish-id="1"]');
checks.originalBoxButtonExists=Boolean(target);
const rect=elements.uploadImage.getBoundingClientRect(),style=getComputedStyle(elements.uploadImage),buttonRect=target.getBoundingClientRect();
const insetX=parseFloat(style.borderLeftWidth)+parseFloat(style.paddingLeft),insetY=parseFloat(style.borderTopWidth)+parseFloat(style.paddingTop);
const width=rect.width-insetX-parseFloat(style.borderRightWidth)-parseFloat(style.paddingRight),height=rect.height-insetY-parseFloat(style.borderBottomWidth)-parseFloat(style.paddingBottom);
const scale=Math.min(width/500,height/300),left=rect.left+insetX+(width-500*scale)/2+15*scale,top=rect.top+insetY+(height-300*scale)/2+30*scale;
checks.originalBoxButtonAligned=Math.abs(buttonRect.left-left)<2&&Math.abs(buttonRect.top-top)<2;
target.click();await until(()=>fishZoom.detection?.id===1&&!elements.fishZoomModal.classList.contains('hidden'),'Original Bounding Boxes button did not open fish detail');
checks.originalBoxOpensZoom=true;
checks.zoomUsesCachedReducedImage=fishZoom.image===cachedImage&&fishZoom.nativeWidth===500&&fishZoom.nativeHeight===300&&fishZoom.frameId==='native-source';
checks.zoomUsesSnapshotBbox=JSON.stringify(fishZoom.detection.bbox)==='[15,30,235,120]'&&JSON.stringify(fishZoom.crop)==='[0,4,261,146]';
checks.overlapChoices=elements.fishZoomChoices.querySelectorAll('button').length===3;
elements.fishZoomClose.focus();elements.fishZoomModal.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}));
checks.tabStaysInZoom=elements.fishZoomModal.contains(document.activeElement)&&document.activeElement!==elements.fishZoomClose;
const choice=[...elements.fishZoomChoices.querySelectorAll('button')].find(button=>button.textContent.startsWith('Fish #3 '));
choice.click();await until(()=>fishZoom.detection?.id===3,'Overlapping fish choice failed');
checks.overlapChoiceRetainsSource=fishZoom.image===cachedImage&&fishZoom.frameId==='native-source'&&fishZoom.nativeWidth===500;
elements.fishZoomClose.click();
checks.closeButtonWorks=elements.fishZoomModal.classList.contains('hidden');
selectInspectionFish(null);elements.maskPreviewMasks.click();await delay(25);
elements.maskPreviewMeasurements.checked=true;elements.maskPreviewCracks.checked=true;elements.maskPreviewModel1.checked=false;
elements.maskPreviewModel2.checked=true;elements.maskPreviewOpacity.value='35';elements.maskPreviewZoom.value='1.5';renderMaskPreview();
const canvas=elements.maskPreviewCanvas;
const clickNative=(x,y)=>{const bounds=canvas.getBoundingClientRect();canvas.dispatchEvent(new MouseEvent('click',{bubbles:true,
 clientX:bounds.left+x/500*bounds.width,clientY:bounds.top+y/300*bounds.height}));};
clickNative(125,85);await until(()=>fishZoom.detection?.id===1&&!elements.fishZoomModal.classList.contains('hidden'),'Colored Fish Masks click did not open fish detail');
checks.maskClickOpensZoom=true;
checks.maskLayersInZoom=elements.fishZoomMask.checked&&elements.fishZoomMeasurements.checked&&elements.fishZoomCracks.checked&&elements.fishZoomModel2.checked;
checks.clickedIdSynchronized=elements.maskPreviewFish.value==='1';
elements.fishZoomIn.click();checks.zoomButtonWorks=fishZoom.scale>1;
elements.fishZoomReset.click();checks.resetButtonWorks=fishZoom.scale===1;
elements.fishZoomViewport.dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,deltaY:-100}));checks.wheelZoomWorks=fishZoom.scale>1;
const panBefore=fishZoom.panX;elements.fishZoomViewport.setPointerCapture=()=>{};elements.fishZoomViewport.releasePointerCapture=()=>{};
elements.fishZoomViewport.dispatchEvent(new PointerEvent('pointerdown',{pointerId:1,clientX:200,clientY:200,bubbles:true}));
elements.fishZoomViewport.dispatchEvent(new PointerEvent('pointermove',{pointerId:1,clientX:230,clientY:220,bubbles:true}));
elements.fishZoomViewport.dispatchEvent(new PointerEvent('pointerup',{pointerId:1,clientX:230,clientY:220,bubbles:true}));checks.panWorks=fishZoom.panX>panBefore;
elements.fishZoomModal.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await delay(20);
checks.escapeClosesOnlyZoom=elements.fishZoomModal.classList.contains('hidden')&&!elements.uploadWorkspace.classList.contains('hidden');
checks.mainControlsPreserved=elements.maskPreviewMasks.checked&&elements.maskPreviewMeasurements.checked&&elements.maskPreviewCracks.checked
 &&elements.maskPreviewModel2.checked&&elements.maskPreviewOpacity.value==='35'&&elements.maskPreviewZoom.value==='1.5';
clickNative(450,250);await delay(30);checks.backgroundDoesNotOpen=elements.fishZoomModal.classList.contains('hidden');
clickNative(110,70);await delay(30);checks.crackPriority=elements.fishZoomModal.classList.contains('hidden')&&!elements.maskPreviewCrackDetails.classList.contains('hidden');
elements.maskPreviewBoxes.click();await delay(20);renderMaskPreview();clickNative(20,40);
await until(()=>fishZoom.detection?.id===1&&!elements.fishZoomModal.classList.contains('hidden'),'Bounding Boxes canvas with overlays did not open detail');
checks.boxCanvasOpensZoom=true;elements.fishZoomClose.click();
// A recorded video snapshot uses the same cached decoded image and native
// metadata even though the current video element has no matching pixels.
selectedUpload=new File(['not a playable video'],'recorded.mp4',{type:'video/mp4'});
uploadMaskPreview.file=selectedUpload;uploadMaskPreview.analysisFile=selectedUpload;uploadMaskPreview.data.source.type='uploaded_video_snapshot';
elements.maskPreviewMasks.click();await delay(20);clickNative(125,85);
await until(()=>fishZoom.detection?.id===1&&!elements.fishZoomModal.classList.contains('hidden'),'Recorded video mask click did not open detail');
checks.videoSnapshotUsesCachedFrame=fishZoom.image===cachedImage&&fishZoom.frameId==='native-source'&&fishZoom.nativeWidth===500;
checks.noCaptureOrFileReload=captures===0&&objectUrls===0;
checks.noFetch=requests===0;checks.noGradeMutation=JSON.stringify(resultDatasets.upload.rows)===before;
window.__debugScreenshot=()=>{if(elements.fishZoomModal.classList.contains('hidden'))elements.maskPreviewViewport.scrollIntoView({block:'center'});return true;};
window.__clearDebugForNewAnalysis=()=>{closeFishZoom();clearMaskPreview();return uploadMaskPreview.data===null&&elements.maskPreviewCanvas.width===0;};
return {checks,targetGeometry:{actual:buttonRect.toJSON(),expected:{left,top},image:rect.toJSON(),style:{insetX,insetY,width,height,scale}},fetch_calls:requests,
 scope:'Real Chrome click handlers/DOM/canvas; reduced cached software snapshots; no inference or scientific accuracy validation'};
})()'''


if __name__ == "__main__":
    browser.main()
