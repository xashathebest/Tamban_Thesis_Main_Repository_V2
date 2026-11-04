"""Real Chrome canvas/DOM checks using recorded software evidence, without models.

Reuses the static frontend harness, which disables only API polling bootstrap.
No fish accuracy or crack validation claim is made by these display fixtures.
"""
import anatomical_debug_browser_smoke as browser
from test_coloredfish_ui import specimen


browser.OUTPUT = browser.ROOT / "results/qa/coloredfish"
browser.specimen = specimen
browser.EXERCISE = r'''(async()=>{
const checks={},fixture=window.__associationFixture,delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let requests=0;window.fetch=async()=>{requests++;throw new Error('Display-only controls must not call an API');};
// The shared runner supplies a legacy bounding-box candidate. Add its actual
// component contour here so this smoke also exercises the new contour renderer.
fixture.fish[0].analysis.surface_damage={status:'suspected',coordinate_space:'original_frame',
 frame_id:'native-source',frame_width_px:500,frame_height_px:300,parent_track_id:1,
 severity:'unassessed',validation_status:'unvalidated',used_for_grading:false,
 reason:'Software display fixture: this candidate requires expert review.',
 locations:[{x:85,y:68,width:50,height:4,estimated_length_px:50,area_px:100,
 contours:[[[85,68],[134,68],[134,71],[85,71]]]}]};
const source=document.createElement('canvas');source.width=500;source.height=300;
const pen=source.getContext('2d');pen.fillStyle='#f1f4f5';pen.fillRect(0,0,500,300);
pen.fillStyle='#adb8c4';for(const x of [15,265]){pen.beginPath();pen.ellipse(x+105,75,105,30,0,0,2*Math.PI);pen.fill();}
fixture.preview_image=source.toDataURL();const file=new File(['software fixture'],'coloredfish-fixture.png',{type:'image/png'});
toggleUpload(true);selectedUpload=file;elements.uploadImage.src=fixture.preview_image;
elements.uploadImage.classList.remove('hidden');elements.uploadVideo.classList.add('hidden');
const fish=fixture.fish.map(item=>({...structuredClone(item),quality:'Class B',analysis:{...structuredClone(item.analysis||{}),
 segmentation:structuredClone(item.segmentation),final_grade:'Class B',weighted_scores:{'Class B':.8}}}));
resultsSource='upload';renderResultsDashboard(fish,{source:'upload',complete:true,scope:'coloredfish-ui-fixture',metadata:{source_name:'Software UI fixture'}});
mountResultsDashboard(true);elements.uploadResults.classList.remove('hidden');
await acceptAutomaticMaskPreview({fish,segmentation_preview:fixture},file);
const before=JSON.stringify(resultDatasets.upload.rows),canvas=elements.maskPreviewCanvas;
const measurements=document.getElementById('upload-mask-measurements'),cracks=document.getElementById('upload-mask-cracks');
checks.controlsExist=Boolean(measurements&&cracks);
checks.defaultOff=Boolean(measurements&&!measurements.checked&&cracks&&!cracks.checked);
elements.maskPreviewMasks.click();await delay(25);elements.maskPreviewModel1.checked=false;
elements.maskPreviewModel2.checked=false;renderMaskPreview();
const shaded=canvas.toDataURL();measurements.click();await delay(20);const measured=canvas.toDataURL();
checks.measurementsChangeCanvas=measured!==shaded;
checks.measurementsIndependent=measurements.checked&&!cracks.checked;
cracks.click();await delay(20);const damaged=canvas.toDataURL();
checks.cracksChangeCanvas=damaged!==measured;
checks.cracksIndependent=measurements.checked&&cracks.checked;
measurements.click();await delay(20);checks.measurementsHideIndependently=canvas.toDataURL()!==damaged&&cracks.checked;
measurements.click();selectInspectionFish(1,{revealCard:true});await delay(25);
checks.estimatedEvidence=elements.maskPreviewEvidence.textContent.includes('Estimated');
checks.noAbsenceClaim=!/\bNo cracks\b/i.test(elements.maskPreviewEvidence.textContent);
selectInspectionFish(2);await delay(20);
checks.unavailableEvidence=elements.maskPreviewEvidence.textContent.includes('Unavailable');
selectInspectionFish(1);elements.maskPreviewZoom.value='2';elements.maskPreviewZoom.dispatchEvent(new Event('input'));
checks.zoomStillWorks=canvas.style.width==='200%';
// Click the candidate's real original-frame location after CSS zoom.
const bounds=canvas.getBoundingClientRect();
canvas.dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:bounds.left+110/500*bounds.width,clientY:bounds.top+69.5/300*bounds.height}));
await delay(20);
const candidatePanel=elements.maskPreviewCrackDetails;
checks.candidateClickDetails=!candidatePanel.classList.contains('hidden')
 &&candidatePanel.textContent.includes('Original image (85, 68) to (135, 72)')
 &&candidatePanel.textContent.includes('50 × 4 px candidate bounds')
 &&candidatePanel.textContent.includes('Estimated candidate; not validated as a crack');
checks.selectedFishPreserved=elements.maskPreviewFish.value==='1';
checks.controlsRemain=['upload-display-boxes','upload-display-masks','upload-mask-opacity','upload-mask-fish',
 'upload-mask-zoom','upload-mask-model1','upload-mask-model2','upload-mask-show','upload-association-debug'].every(id=>document.getElementById(id));
elements.maskPreviewOpacity.value='20';elements.maskPreviewOpacity.dispatchEvent(new Event('input'));
checks.opacityStillWorks=elements.maskPreviewOpacityValue.textContent==='20%';
checks.noGradingMutation=JSON.stringify(resultDatasets.upload.rows)===before;
checks.noFetch=requests===0;
// Real completed analyses commonly retain diagnostic numbers while withholding
// source endpoints and Body-supported crack evidence. Controls must explain
// that state immediately even though their canvas pixels cannot change.
const cachedData=uploadMaskPreview.data,unavailableData=structuredClone(cachedData);
delete unavailableData.fish[0].analysis.fish_geometry.candidate_visualization;
unavailableData.fish[0].analysis.fish_geometry.reasons=['experimental_mask_requires_ownership_validation'];
unavailableData.fish[0].analysis.surface_damage={status:'unavailable',coordinate_space:'original_frame',
 frame_id:'native-source',parent_track_id:1,locations:[],
 reason:'A reviewed, correctly owned Body pixel mask is unavailable; MobileSAM candidates do not establish Body anatomy.'};
uploadMaskPreview.data=unavailableData;renderMaskPreview();
const unavailableNotice=elements.maskPreviewOverlayStatus;
checks.unavailableFeedbackAtControls=!unavailableNotice.classList.contains('hidden')
 &&/measurements/i.test(unavailableNotice.textContent)&&/cracks/i.test(unavailableNotice.textContent)
 &&/endpoints/i.test(unavailableNotice.textContent)&&/Body/.test(unavailableNotice.textContent);
checks.unavailableFeedbackDoesNotRerun=requests===0&&JSON.stringify(resultDatasets.upload.rows)===before;
uploadMaskPreview.data=cachedData;renderMaskPreview();
elements.maskPreviewZoom.value='1';elements.maskPreviewZoom.dispatchEvent(new Event('input'));
window.__debugScreenshot=()=>{elements.maskPreviewViewport.scrollIntoView({block:'center'});return true;};
window.__clearDebugForNewAnalysis=()=>{clearMaskPreview();return uploadMaskPreview.data===null&&elements.maskPreviewCanvas.width===0;};
return {checks,fetch_calls:requests,scope:'Real Chrome frontend DOM/canvas; synthetic native coordinates only; no models or crack validation'};
})()'''


if __name__ == "__main__":
    browser.main()
