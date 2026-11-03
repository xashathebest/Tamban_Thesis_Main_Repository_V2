"""Actual automatic inspection and colored-mask toggle in real Chrome."""
import json
from pathlib import Path

import sam_preview_browser_smoke as browser


browser.OUTPUT = browser.ROOT / "results/qa/sam_features"
browser.EXERCISE = r'''(async()=>{
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const until=async(fn,message)=>{const started=performance.now();while(!fn()){if(performance.now()-started>90000)throw new Error(message);await delay(40);}};
const checks={},requests=[],rawFetch=window.fetch,payloads=[];
window.fetch=async(url,options={})=>{if(String(url)==='/api/analyze-image'||String(url)==='/api/segmentation/preview'){
requests.push({path:String(url),method:options.method});const response=await rawFetch(url,options);
if(String(url)==='/api/analyze-image'&&response.ok)payloads.push(await response.clone().json());return response;}return rawFetch(url,options);};
const bytes=Uint8Array.from(atob(window.__realFishBytes),c=>c.charCodeAt(0));
window.__automaticPhoto=()=>new File([bytes],window.__realFishName,{type:'image/jpeg'});
toggleUpload(true);setUploadSelection(window.__automaticPhoto());elements.analyze.click();
await until(()=>!uploadInFlight&&uploadMaskPreview.data,'Automatic masks did not appear: '+elements.uploadStatus.textContent);
const analysis=payloads.at(-1),payload=uploadMaskPreview.data;
const before=await (await rawFetch('/__qa/diagnostics')).json();
const rows=JSON.stringify(resultDatasets.upload.rows),entries=maskPreviewEntries(payload);
checks.oneAnalysisRequest=requests.filter(r=>r.path==='/api/analyze-image').length===1;
checks.noSeparatePreviewRequest=!requests.some(r=>r.path==='/api/segmentation/preview');
checks.oneDetectorAndPartPass=before.counts.model1_calls===1&&before.counts.model2_calls===1;
checks.zeroGrabcut=before.counts.grabcut_calls===0;
checks.oneSharedEmbedding=before.sam_encoder_calls===1;
checks.realNonemptyMasks=payload.generated_masks>0&&entries.filter(e=>e.contours.length).length===payload.generated_masks;
checks.originalSource=payload.source.image_sha256===window.__realFishSha;
checks.widthAndStructuralUncalibrated=analysis.fish.every(f=>!f.analysis.body_width.score_contributed&&f.analysis.feature_fusion.contributions_applied.length===0);
checks.originalWeightedGradePreserved=analysis.fish.every(f=>f.analysis.feature_fusion.original_grade===f.analysis.feature_fusion.final_grade);
const canvas=elements.maskPreviewCanvas,ctx=canvas.getContext('2d');
const originalMainSource=elements.uploadImage.src;
checks.canvasIsInMainViewer=elements.uploadMediaStage.contains(canvas);
checks.boundingBoxesShowOriginalImage=!elements.uploadImage.classList.contains('hidden')&&elements.maskPreviewViewport.classList.contains('hidden');
elements.maskPreviewBoxes.click();renderMaskPreview();const boxOnly=canvas.toDataURL();
const baseline=ctx.getImageData(0,0,canvas.width,canvas.height).data;
elements.maskPreviewMasks.click();await delay(40);
const colored=ctx.getImageData(0,0,canvas.width,canvas.height).data;let changed=0;
for(let i=0;i<colored.length;i+=4)if(Math.abs(colored[i]-baseline[i])+Math.abs(colored[i+1]-baseline[i+1])+Math.abs(colored[i+2]-baseline[i+2])>15)changed++;
checks.visibleColoredSilhouettes=changed/(canvas.width*canvas.height)>.02;
checks.exclusiveToggle=elements.maskPreviewMasks.checked&&!elements.maskPreviewBoxes.checked;
checks.distinctFishColors=new Set(entries.filter(e=>e.contours.length).map(e=>e.color)).size>1;
checks.opacity40=elements.maskPreviewOpacity.value==='40';
checks.readableColorToggle=document.querySelector('label[title="Show the colored fish silhouettes from this analysis"]').textContent.includes('Fish Masks');
checks.masksReplaceImageInSameViewer=elements.uploadMediaStage.contains(canvas)&&!elements.maskPreviewViewport.classList.contains('hidden')&&elements.uploadImage.classList.contains('hidden');
checks.allOverlayControlsRemain=['upload-mask-show','upload-mask-model1','upload-mask-model2','upload-mask-opacity','upload-mask-fish','upload-mask-zoom','upload-mask-legend'].every(id=>document.getElementById(id));
const shaded=canvas.toDataURL();
const plain=document.createElement('canvas');plain.width=canvas.width;plain.height=canvas.height;plain.getContext('2d').drawImage(uploadMaskPreview.image,0,0,plain.width,plain.height);
selectInspectionFish(entries[0].id,{revealCard:true});const selectedFirst=canvas.toDataURL();
selectInspectionFish(entries[1].id,{revealCard:true});const selectedSecond=canvas.toDataURL();
checks.fishSelectionChangesMask=selectedFirst!==selectedSecond;
checks.selectedCardSynchronized=Boolean(elements.resultsGroups.querySelector(`details[data-inspection-fish-id="${entries[1].id}"]`)?.open);
elements.maskPreviewOpacity.value='20';elements.maskPreviewOpacity.dispatchEvent(new Event('input',{bubbles:true}));
checks.opacityChangesPixels=canvas.toDataURL()!==selectedSecond;
elements.maskPreviewOpacity.value='40';selectInspectionFish(null);elements.maskPreviewBoxes.click();
checks.originalAnnotatedImageRestored=elements.uploadImage.src===originalMainSource&&!elements.uploadImage.classList.contains('hidden')&&elements.maskPreviewViewport.classList.contains('hidden');
elements.maskPreviewMasks.click();await delay(100);
elements.maskPreviewModel1.checked=false;elements.maskPreviewModel2.checked=false;elements.maskPreviewShow.checked=true;renderMaskPreview();
const colorOnly=canvas.toDataURL();elements.maskPreviewShow.checked=false;elements.maskPreviewShow.dispatchEvent(new Event('input',{bubbles:true}));
checks.maskVisibilityControlWorks=canvas.toDataURL()!==colorOnly;
elements.maskPreviewShow.checked=true;elements.maskPreviewModel1.checked=true;renderMaskPreview();
checks.model1VisibilityControlWorks=canvas.toDataURL()!==colorOnly;
const withoutParts=canvas.toDataURL();elements.maskPreviewModel2.checked=true;elements.maskPreviewModel2.dispatchEvent(new Event('input',{bubbles:true}));
checks.model2VisibilityControlWorks=canvas.toDataURL()!==withoutParts;
elements.maskPreviewModel2.checked=false;elements.maskPreviewZoom.value='1.5';elements.maskPreviewZoom.dispatchEvent(new Event('input',{bubbles:true}));
checks.zoomStillWorks=canvas.style.width==='150%';elements.maskPreviewZoom.value='1';elements.maskPreviewZoom.dispatchEvent(new Event('input',{bubbles:true}));
checks.fitImageStillWorks=canvas.style.width==='100%';
checks.reviewIndicatorsRemain=elements.maskPreviewLegend.children.length===entries.length;
const NativeImage=window.Image;
window.Image=class extends NativeImage{set src(value){setTimeout(()=>{super.src=value;},450);}get src(){return super.src;}};
uploadMaskPreview.image=null;
const preparing=setMainViewerMode('masks');await delay(220);
const loadingText=elements.maskPreviewStatus.textContent;
checks.visiblePreparationIndicator=!elements.maskPreviewLoading.classList.contains('hidden')&&elements.maskPreview.getAttribute('aria-busy')==='true';
checks.preparationElapsedTime=/Preparing.*[0-9]+\.[0-9]s/.test(loadingText);
await preparing;window.Image=NativeImage;
checks.autoDisplaysWhenPrepared=!elements.maskPreviewViewport.classList.contains('hidden')&&elements.maskPreviewLoading.classList.contains('hidden');
const cachedAnalysis=uploadMaskPreview.analysis;
uploadMaskPreview.analysis={...cachedAnalysis,segmentation_preview:{...cachedAnalysis.segmentation_preview,preview_image:'data:image/png;base64,broken'}};
uploadMaskPreview.image=null;await setMainViewerMode('masks');
checks.visibleImageError=/failed|could not/i.test(elements.maskPreviewStatus.textContent)&&elements.maskPreviewLoading.classList.contains('hidden');
checks.failedMaskViewRestoresBoxes=elements.maskPreviewBoxes.checked&&!elements.uploadImage.classList.contains('hidden')&&elements.maskPreviewViewport.classList.contains('hidden');
uploadMaskPreview.analysis=cachedAnalysis;await setMainViewerMode('masks');
const legacyAnalysis={...analysis};delete legacyAnalysis.segmentation_preview;
uploadMaskPreview.analysis=legacyAnalysis;uploadMaskPreview.image=null;uploadMaskPreview.data=null;
await setMainViewerMode('masks');
checks.recordedLegacyMasksLoadAfterUrlRevocation=!elements.maskPreviewViewport.classList.contains('hidden')&&maskPreviewEntries(uploadMaskPreview.data).filter(e=>e.contours.length).length>0;
const after=await (await rawFetch('/__qa/diagnostics')).json();
checks.toggleNeverRerunsModels=JSON.stringify(before.counts)===JSON.stringify(after.counts)&&before.sam_encoder_calls===after.sam_encoder_calls;
checks.displayNeverMutatesGrades=rows===JSON.stringify(resultDatasets.upload.rows);
checks.checkpointUnchanged=JSON.stringify(after.checkpoint_before)===JSON.stringify(after.checkpoint_after);
checks.cpuOnly=!after.cuda_initialized;
window.__realSamArtifacts={original:plain.toDataURL(),boxOnly,shaded,selectedFirst,selectedSecond};
return {checks,payload,analysis,requests,loadingText,cardDebug:{source:resultsSource,filter:resultsFilter,cards:[...elements.resultsGroups.querySelectorAll('details[data-inspection-fish-id]')].map(c=>({id:c.dataset.inspectionFishId,open:c.open}))},status:elements.maskPreviewStatus.textContent,diagnosticsBefore:before,diagnosticsAfter:after,
 changedPixelFraction:changed/(canvas.width*canvas.height),successfulEntryCount:entries.filter(e=>e.contours.length).length};
})()'''

browser.LIFECYCLE = r'''(async()=>{
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms)),checks={};
setUploadSelection(new File(['bad'],'bad.png',{type:'image/png'}));
checks.newFileClears=uploadMaskPreview.data===null&&elements.maskPreviewCanvas.width===0;
elements.analyze.click();const start=performance.now();while(uploadInFlight){if(performance.now()-start>30000)throw new Error('Failed request did not finish');await delay(30);}
checks.failedAnalysisCannotRestoreMasks=!uploadMaskPreview.data&&elements.maskPreviewCanvas.width===0;
checks.realDecodeFailureVisible=/image|decode|invalid/i.test(elements.uploadStatus.textContent);
setUploadSelection(new File(['video'],'clip.mp4',{type:'video/mp4'}));
checks.videoSelectionClears=uploadMaskPreview.data===null&&elements.maskPreviewCanvas.width===0;
return {checks,errorMessage:elements.uploadStatus.textContent};
})()'''


if __name__ == "__main__":
    browser.main()
    path=browser.OUTPUT/"actual_e2e.json"
    result=json.loads(path.read_text())
    result["scope"]="Actual CPU Model 1 + Model 2 + automatic MobileSAM in one analysis, real HTTP, colored Boxes/Masks browser toggle. No independent mask/feature accuracy labels."
    path.write_text(json.dumps(result,indent=2)+"\n")
