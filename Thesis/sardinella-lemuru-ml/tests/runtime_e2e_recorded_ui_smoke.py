"""Replay the actual HTTP image/masks on the final frontend without inference."""
from copy import deepcopy
import json

import anatomical_debug_browser_smoke as browser


OUTPUT = browser.ROOT / "results/qa/runtime_e2e/ui/recorded"


EXERCISE = r'''(async()=>{
const checks={},fixture=window.__associationFixture,analysis=fixture._runtime_analysis,delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
delete fixture._runtime_analysis;
let requests=0;window.fetch=async()=>{requests++;throw new Error('Recorded actual-image replay must not call an API');};
for(const fish of fixture.fish)fish.analysis=structuredClone(analysis.fish.find(row=>row.id===fish.id).analysis);
const file=new File(['recorded source identity'],'actual-http-photo.jpg',{type:'image/jpeg'});
toggleUpload(true);selectedUpload=file;elements.uploadImage.src=analysis.annotated_image;
elements.uploadImage.classList.remove('hidden');elements.uploadVideo.classList.add('hidden');
resultsSource='upload';renderResultsDashboard(analysis.fish,{source:'upload',complete:true,scope:'actual-http-recorded',metadata:{analyzed_at:analysis.analyzed_at}});
mountResultsDashboard(true);elements.uploadResults.classList.remove('hidden');
await acceptAutomaticMaskPreview({fish:analysis.fish,segmentation_preview:fixture},file);
const before=JSON.stringify(resultDatasets.upload.rows),canvas=elements.maskPreviewCanvas,source=maskPreviewSource(fixture);
const entries=maskPreviewEntries(fixture),original=elements.uploadImage.src;
checks.realRecordedSource=source.width===640&&source.height===640&&entries.length===9;
checks.defaultBoxesAndDebugOff=elements.maskPreviewBoxes.checked&&!elements.maskPreviewMasks.checked&&!elements.maskPreviewAssociation.checked;
checks.sameNativeRawTrace=analysis.fish.every(f=>f.analysis.model2_debug.raw_detections.length===17);
checks.acceptedOverlaysMatchRealAssignments=entries.every(entry=>anatomicalAssociationOverlay(entry,source).filter(row=>row.kind==='accepted').length===entry.analysis.quality_inference.association.parts.filter(row=>row.status==='ASSIGNED'&&row.track_id===entry.id).length);
elements.maskPreviewMasks.click();await delay(30);const shaded=canvas.toDataURL();
checks.shadedMasksInMainViewer=!elements.maskPreviewViewport.classList.contains('hidden')&&elements.uploadImage.classList.contains('hidden');
checks.actualMaskReviewIndicators=elements.maskPreviewLegend.children.length===9;
selectInspectionFish(1,{revealCard:true});selectInspectionFish(2,{revealCard:true});await delay(30);
checks.correctHighlightAfterCardEvents=elements.maskPreviewFish.value==='2';
const selected=canvas.toDataURL();elements.maskPreviewOpacity.value='20';elements.maskPreviewOpacity.dispatchEvent(new Event('input'));
checks.opacityWorks=canvas.toDataURL()!==selected;
elements.maskPreviewZoom.value='2';elements.maskPreviewZoom.dispatchEvent(new Event('input'));checks.zoomWorks=canvas.style.width==='200%';
elements.maskPreviewAssociation.click();await delay(20);
checks.nativeDebugInMainViewer=!elements.maskPreviewViewport.classList.contains('hidden')&&elements.maskPreviewAssociationStatus.textContent.includes('recorded diagnostic overlays');
const card=elements.resultsGroups.querySelector('details[data-inspection-fish-id="2"]');
const section=[...card.querySelectorAll('details')].find(item=>item.querySelector('summary')?.textContent==='Anatomical Association Debug View');
section.open=true;section.dispatchEvent(new Event('toggle'));await delay(20);
const expectedReason=analysis.fish.find(f=>f.id===2).analysis.quality_inference.association.parts.find(row=>row.reason)?.reason;
checks.actualPerFishCandidateTable=section.querySelectorAll('tbody tr').length>=17&&Boolean(expectedReason)&&section.textContent.includes(expectedReason);
elements.maskPreviewAssociation.click();elements.maskPreviewBoxes.click();await delay(20);
checks.boxesRestoreOriginal=elements.uploadImage.src===original&&!elements.uploadImage.classList.contains('hidden')&&elements.maskPreviewViewport.classList.contains('hidden');
checks.gradingUnchanged=JSON.stringify(resultDatasets.upload.rows)===before;
checks.noApiOrInference=requests===0;
elements.maskPreviewOpacity.value='40';elements.maskPreviewZoom.value='1';selectInspectionFish(2);elements.maskPreviewMasks.click();elements.maskPreviewAssociation.click();
window.__debugScreenshot=()=>{elements.maskPreview.scrollIntoView({block:'start'});return true;};
window.__clearDebugForNewAnalysis=()=>{clearMaskPreview();return !elements.maskPreviewAssociation.checked&&!uploadMaskPreview.data&&canvas.width===0;};
return{checks,fetch_calls:requests,source_sha256:fixture.source.image_sha256,scope:'Final frontend in real Chrome with exact earlier actual CPU HTTP photo/mask/grade data; source/card/controls/diagnostics, no model or API calls and no expert-accuracy claim'};
})()'''


def main():
    result = json.loads((OUTPUT.parent / "actual_e2e.json").read_text(encoding="utf-8"))
    fixture = deepcopy(result["payload"])
    fixture["_runtime_analysis"] = deepcopy(result["analysis"])
    browser.specimen = lambda: fixture
    browser.OUTPUT = OUTPUT
    browser.EXERCISE = EXERCISE
    browser.main()


if __name__ == "__main__":
    main()
