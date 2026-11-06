"""Real Chrome workbench checks; cached synthetic evidence, no camera or models."""
import anatomical_debug_browser_smoke as browser
from test_coloredfish_ui import specimen


browser.OUTPUT = browser.ROOT / "results/qa/inspection_workspace"
browser.specimen = specimen
browser.EXERCISE = r'''(async()=>{
const checks={},fixture=window.__associationFixture,delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let requests=0;
window.fetch=async()=>{requests++;throw new Error('Display changes must reuse the cached analysis');};
const source=document.createElement('canvas');source.width=500;source.height=300;
const pen=source.getContext('2d');pen.fillStyle='#e9f0f4';pen.fillRect(0,0,500,300);
pen.fillStyle='#adb8c4';for(const x of [15,265]){pen.beginPath();pen.ellipse(x+105,75,105,30,0,0,2*Math.PI);pen.fill();}
fixture.preview_image=source.toDataURL();
const bytes=Uint8Array.from(atob(fixture.preview_image.split(',')[1]),char=>char.charCodeAt(0));
const file=new File([bytes],'inspection.png',{type:'image/png'});
toggleUpload(true);
const dropped=new DataTransfer();dropped.items.add(file);
elements.uploadDropZone.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dropped}));
checks.dragAndDrop=selectedUpload===file&&elements.uploadImage.src.startsWith('blob:');
elements.uploadImage.src=fixture.preview_image;
checks.uploadSelection=elements.uploadFileName.textContent==='inspection.png'
 &&!document.getElementById('remove-upload-button').classList.contains('hidden');
const fish=fixture.fish.map((item,i)=>({...structuredClone(item),quality:'Class C',ai_final_grade:i?'Class B':'Class A',
 analysis:{...structuredClone(item.analysis||{}),segmentation:structuredClone(item.segmentation),
 final_grade:i?'Class B':'Class A',weighted_scores:{[i?'Class B':'Class A']:.8}}}));
for(let i=0;i<fish.length;i++)fixture.fish[i]={...fixture.fish[i],...fish[i]};
renderResultsDashboard(fish,{source:'upload',complete:true,scope:'inspection-workspace-fixture',metadata:{source_name:file.name}});
resultsSource='upload';resultsFilter='All';renderResultsDashboard(null,{renderOnly:true});
mountResultsDashboard(true);elements.uploadResults.classList.remove('hidden');
await acceptAutomaticMaskPreview({fish,segmentation_preview:fixture},file);
await delay(100);
const before=JSON.stringify(resultDatasets.upload.rows);
checks.twoPanels=document.getElementById('upload-workspace-results').contains(elements.resultsDashboard)
 &&document.getElementById('upload-viewer-panel').contains(elements.uploadMediaStage);
const layout=document.querySelector('.upload-inspection-layout').getBoundingClientRect(),left=document.getElementById('upload-viewer-panel').getBoundingClientRect(),right=document.getElementById('upload-workspace-results').getBoundingClientRect();
checks.desktopSideBySide=right.left>=left.right-2&&layout.height>150;
checks.engineGrade=fishZoomGrade(fish[0])==='Class A'&&resultGrade(fish[0])==='Class A';
checks.gradeLegend=document.querySelectorAll('#upload-viewer-panel .grade-color-legend li').length===5;
elements.maskPreviewMasks.click();await delay(50);renderMaskPreview();
const canvas=elements.maskPreviewCanvas,viewport=elements.maskPreviewViewport;
const cv=canvas.getBoundingClientRect(),vp=viewport.getBoundingClientRect();
checks.fitWholeImage=cv.width<=vp.width+2&&cv.height<=vp.height+2&&Math.abs(cv.width/cv.height-500/300)<.03;
const entries=maskPreviewEntries(uploadMaskPreview.data);
checks.maskIdentityColors=entries[0].color!==entries[1].color;
const bounds=canvas.getBoundingClientRect();
canvas.dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:bounds.left+30/500*bounds.width,clientY:bounds.top+50/300*bounds.height}));
await delay(40);
const card=elements.resultsGroups.querySelector('details[data-inspection-fish-id="1"]');
checks.selectionSynchronizes=elements.maskPreviewFish.value==='1'&&card?.open
 &&elements.fishZoomModal.classList.contains('hidden');
checks.evidenceTogether=['Overview','Geometry','Crack Detection','Mask Reliability','Grading Explanation'].every(title=>card.textContent.includes(title));
checks.gradeSeparateFromReliability=card.textContent.includes('Class A')&&/Estimated|Review|Unavailable/i.test(card.textContent);
elements.maskPreviewMeasurements.click();elements.maskPreviewCracks.click();
elements.maskPreviewOpacity.value='25';elements.maskPreviewOpacity.dispatchEvent(new Event('input'));
elements.maskPreviewZoom.value='2';elements.maskPreviewZoom.dispatchEvent(new Event('input'));
await toggleViewerFullscreen(elements.uploadWorkspace);await delay(50);
checks.fullscreen=Boolean(document.fullscreenElement===elements.uploadMediaStage||elements.uploadMediaStage.classList.contains('viewer-fullscreen-fallback'));
checks.fullscreenKeepsLayers=elements.maskPreviewMeasurements.checked&&elements.maskPreviewCracks.checked
 &&elements.maskPreviewOpacity.value==='25'&&elements.maskPreviewFish.value==='1';
await toggleViewerFullscreen(elements.uploadWorkspace);document.getElementById('upload-fit-button').click();await delay(40);
checks.fitButton=elements.maskPreviewZoom.value==='1';
checks.noInferenceRequests=requests===0;
checks.gradingUnchanged=JSON.stringify(resultDatasets.upload.rows)===before;
toggleUpload(false);
const liveSource=elements.video.getAttribute('src'),livePanel=document.getElementById('live-viewer-panel');
document.getElementById('live-viewer-zoom').value='2';document.getElementById('live-viewer-zoom').dispatchEvent(new Event('change'));
checks.liveZoom=elements.video.style.transform.includes('scale(2)');
await toggleViewerFullscreen(livePanel);await delay(30);
checks.liveFullscreen=Boolean(document.fullscreenElement===elements.liveMediaStage||elements.liveMediaStage.classList.contains('viewer-fullscreen-fallback'))
 &&elements.video.getAttribute('src')===liveSource;
await toggleViewerFullscreen(livePanel);document.getElementById('live-fit-button').click();
checks.liveFit=elements.video.style.transform==='';
toggleUpload(true);await delay(300);
checks.cachedResultsSurviveClose=resultDatasets.upload.scope==='inspection-workspace-fixture'
 &&resultDatasets.upload.rows.length===2&&selectedUpload===file;
checks.analyticsNavigation=Boolean(document.querySelector('[data-view="analytics"]')&&document.getElementById('view-analytics'));
checks.noInferenceRequests=requests===0;
window.__debugScreenshot=()=>{elements.uploadWorkspace.scrollTop=0;return true;};
window.__clearDebugForNewAnalysis=()=>{elements.removeUpload.click();return uploadMaskPreview.data===null&&resultDatasets.upload.rows.length===0&&!selectedUpload;};
return {checks,fetch_calls:requests,scope:'Real Chrome DOM/canvas; synthetic cached evidence; no inference or accuracy claims'};
})()'''


if __name__ == "__main__":
    browser.main()
