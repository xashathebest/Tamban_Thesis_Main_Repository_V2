"""Real CPU models + SAM + HTTP + Chrome, then explicit synthetic display truth.

Uses an isolated database, browser profile and ephemeral API port. It never
restarts the ordinary application or claims synthetic defects are real fish.
"""
import base64
import json
import tempfile

import cv2
import numpy as np

import sam_preview_browser_smoke as browser

browser.OUTPUT = browser.ROOT/"results/qa/surface_features/browser"
browser.SERVER = browser.SERVER.replace("m = importlib.import_module", "os.environ['SEGMENTATION_BACKEND']='mobilesam_experimental'\nm = importlib.import_module")
browser.SERVER = browser.SERVER.replace("uvicorn.run(m.app", r'''
@m.app.get('/__qa/surface-fixture')
def surface_fixture():
    import sys, base64
    sys.path.insert(0, str(__import__('pathlib').Path.cwd()/'tests'))
    from test_fish_surface import scene, provider
    from src.inference.surface_evidence import measure_owned_surface
    first, a, _ = scene('branch')
    second, b, _ = scene('spot', brightness=120, contrast=85)
    image = np.hstack((first, second))
    masks = {1:np.pad(a,((0,0),(0,320))), 2:np.pad(b,((0,0),(320,0)))}
    boxes = {identity: list(cv2.boundingRect(mask.astype(np.uint8))) for identity,mask in masks.items()}
    boxes = {identity:[x,y,x+w,y+h] for identity,(x,y,w,h) in boxes.items()}
    fixture_provider = provider(image,masks,boxes=boxes)
    fish=[]
    for identity,mask in masks.items():
        analysis=measure_owned_surface(fixture_provider,identity)
        analysis['surface_damage'].pop('overlay_mask',None)
        contours,_=cv2.findContours(mask.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        overlay={'coordinate_space':'original_frame','frame_id':'source-frame','frame_width_px':640,
                 'frame_height_px':160,'contours':[c.reshape(-1,2).tolist() for c in contours]}
        fish.append({'id':identity,'bbox':boxes[identity],'parts':[],'analysis':analysis,
            'segmentation':{'preview_usable':True,'parent_track_id':identity,'ownership_status':'checks_passed_unvalidated',
                            'engineering_checks_passed':True,'mask_overlay':overlay}})
    ok,encoded=cv2.imencode('.png',cv2.cvtColor(image,cv2.COLOR_RGB2BGR));assert ok
    return {'status':'generated','generated_masks':2,'review_required_masks':0,'fish':fish,
            'source':{'frame_id':'source-frame','frame_width_px':640,'frame_height_px':160},
            'preview_image':'data:image/png;base64,'+base64.b64encode(encoded).decode(),
            'performance':{'segmentation_ms':0.},'fixture_scope':'Controlled synthetic display fixture; not model accuracy evidence'}
uvicorn.run(m.app''').replace("import hashlib, importlib, json, os, cv2, torch, uvicorn", "import hashlib, importlib, json, os, cv2, torch, uvicorn, numpy as np")

browser.EXERCISE = r'''(async()=>{
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const until=async(fn,message)=>{const started=performance.now();while(!fn()){if(performance.now()-started>120000)throw new Error(message);await delay(40);}};
const checks={},rawFetch=window.fetch;let realAnalysis;
window.fetch=async(url,options={})=>{const response=await rawFetch(url,options);if(String(url)==='/api/analyze-image'&&response.ok)realAnalysis=await response.clone().json();return response;};
const bytes=Uint8Array.from(atob(window.__realFishBytes),c=>c.charCodeAt(0));
toggleUpload(true);setUploadSelection(new File([bytes],window.__realFishName,{type:'image/jpeg'}));elements.analyze.click();
await until(()=>!uploadInFlight&&uploadMaskPreview.data,'Real analysis/SAM did not finish: '+elements.uploadStatus.textContent);
const payload=uploadMaskPreview.data,analysis=realAnalysis,entries=maskPreviewEntries(payload);
const measured=entries.filter(e=>e.analysis.brightness?.status==='measured');
checks.realMasksAndBrightness=measured.length>0;
const labels=uploadMaskPreview.brightnessLabels||[];
checks.everyFishHasImageLabel=entries.every(entry=>labels.some(label=>label.id===entry.id));
checks.imageLabelsDoNotOverlap=labels.every((a,i)=>labels.every((b,j)=>i===j||a.x>=b.x+b.width||b.x>=a.x+a.width||a.y>=b.y+b.height||b.y>=a.y+a.height));
checks.everyEligibleBrightnessVisible=[...elements.surfaceFeatureMonitor.querySelectorAll('article')].length===entries.length&&measured.every(e=>elements.surfaceFeatureMonitor.textContent.includes(e.analysis.brightness.mean_brightness.toFixed(1)+'%'));
checks.rootAndPreviewAgree=analysis.fish.every(f=>{const preview=payload.fish.find(p=>p.id===f.id);return JSON.stringify(f.analysis.brightness)===JSON.stringify(preview.analysis.brightness)&&JSON.stringify(f.analysis.surface_damage)===JSON.stringify(preview.analysis.surface_damage);});
checks.gradingUnchanged=analysis.fish.every(f=>f.analysis.brightness.used_for_grading===false&&f.analysis.surface_damage.used_for_grading===false);
const diagnosticsBefore=await (await rawFetch('/__qa/diagnostics')).json();
const actualDesktop=elements.maskPreviewCanvas.toDataURL();
const fixture=await (await rawFetch('/__qa/surface-fixture')).json();
setUploadSelection(new File(['controlled software fixture'],'controlled-surface.png',{type:'image/png'}));
await acceptAutomaticMaskPreview({segmentation_preview:fixture},selectedUpload);
resultDatasets.upload.rows=fixture.fish;elements.maskPreviewFish.value='all';renderMaskPreview();
checks.syntheticBothFishVisible=elements.surfaceFeatureMonitor.querySelectorAll('article').length===2;
const canvas=elements.maskPreviewCanvas,context=canvas.getContext('2d');
const plain=document.createElement('canvas');plain.width=640;plain.height=160;plain.getContext('2d').drawImage(uploadMaskPreview.image,0,0,640,160);
const original=plain.toDataURL(),boxOnly=canvas.toDataURL();
elements.brightnessView.value='grayscale';renderMaskPreview();await delay(120);renderMaskPreview();
const grayscale=canvas.toDataURL();checks.grayscaleChangesView=grayscale!==boxOnly;
elements.brightnessView.value='original';elements.maskPreviewCracks.checked=true;elements.maskPreviewFish.value='1';renderMaskPreview();
let pixels=context.getImageData(0,0,canvas.width,canvas.height).data,white=0,invalid=0,outside=0;
const one=fixture.fish[0],owned=one.analysis.brightness.owned_mask,ownedBounds=one.analysis.brightness.crop_bounds;
const ownership=new Uint8Array(640*160);for(const [row,start,length]of owned.runs)for(let x=start;x<start+length;x++)ownership[(ownedBounds[1]+row)*640+ownedBounds[0]+x]=1;
for(let i=0;i<pixels.length;i+=4){if(pixels[i]===255)white++;if(![0,255].includes(pixels[i])||pixels[i]!==pixels[i+1]||pixels[i]!==pixels[i+2]||pixels[i+3]!==255)invalid++;if(pixels[i]&&!ownership[i/4])outside++;}
checks.binaryExactlyBlackWhite=invalid===0&&white>0;
checks.binaryMatchesBackendArea=white===one.analysis.surface_damage.crack_area_px;
checks.binaryOutsideOwnerBlack=outside===0;
checks.originalComparisonVisible=!elements.crackOriginalFigure.classList.contains('hidden');
const selectedFirst=canvas.toDataURL(),comparison=elements.crackOriginalCanvas.toDataURL();
const candidateButton=elements.maskPreviewEvidence.querySelector('.crack-candidate-button');candidateButton.click();
checks.candidateClassificationAndReliabilityVisible=elements.maskPreviewCrackDetails.textContent.includes('crack or split')&&elements.maskPreviewCrackDetails.textContent.includes('heuristic strength');
elements.maskPreviewFish.value='2';renderMaskPreview();pixels=context.getImageData(0,0,canvas.width,canvas.height).data;
checks.darkSpotNotWhite=[...pixels].every((v,i)=>i%4===3?v===255:v===0);
checks.rejectedVisible=elements.surfaceFeatureMonitor.textContent.includes('Rejected false-positive hypotheses')&&elements.maskPreviewEvidence.textContent.includes('dark spot');
const selectedSecond=canvas.toDataURL();
elements.maskPreviewFish.value='1';elements.maskPreviewCracks.checked=false;elements.crackRedOverlay.checked=true;
elements.crackRedOverlay.dispatchEvent(new Event('input',{bubbles:true}));
checks.redControlActivatesCrackView=elements.maskPreviewCracks.checked;
pixels=context.getImageData(0,0,canvas.width,canvas.height).data;let red=0;for(let i=0;i<pixels.length;i+=4)if(pixels[i]>pixels[i+1]+50&&pixels[i]>pixels[i+2]+50)red++;
checks.redOverlayLocalized=red>0&&red<=one.analysis.surface_damage.crack_area_px;
const redOverlay=canvas.toDataURL(),csvRows=surfaceEvidenceExportRows(fixture.fish);
elements.brightnessView.value='grayscale';elements.brightnessView.dispatchEvent(new Event('input',{bubbles:true}));
checks.grayscaleControlSwitchesOffCrackView=!elements.maskPreviewCracks.checked;
elements.brightnessView.value='original';
checks.csvMatchesUI=csvRows[0].mean_brightness===one.analysis.brightness.mean_brightness&&csvRows[0].crack_area===one.analysis.surface_damage.candidates[0].area_px;
const diagnosticsAfter=await(await rawFetch('/__qa/diagnostics')).json();
checks.controlsDoNotRerunModels=JSON.stringify(diagnosticsBefore.counts)===JSON.stringify(diagnosticsAfter.counts)&&diagnosticsBefore.sam_encoder_calls===diagnosticsAfter.sam_encoder_calls;
checks.checkpointUnchanged=JSON.stringify(diagnosticsAfter.checkpoint_before)===JSON.stringify(diagnosticsAfter.checkpoint_after);
checks.cpuOnly=!diagnosticsAfter.cuda_initialized;
elements.crackRedOverlay.checked=false;elements.maskPreviewCracks.checked=true;renderMaskPreview();elements.maskPreview.scrollIntoView({block:'start'});
window.__realSamArtifacts={original,boxOnly,shaded:grayscale,selectedFirst,selectedSecond};
return {checks,payload,analysis,diagnosticsBefore,diagnosticsAfter,fixture,csvRows,
  surface_artifacts:{actual_inspection:actualDesktop,brightness_grayscale:grayscale,binary_cracks:selectedFirst,original_comparison:comparison,red_overlay:redOverlay,dark_spot_binary:selectedSecond}};
})()'''

browser.LIFECYCLE = r'''(async()=>{setUploadSelection(new File(['different'],'different.png',{type:'image/png'}));return {checks:{newFileClearsEvidence:!uploadMaskPreview.data&&elements.surfaceFeatureMonitor.children.length===0&&elements.maskPreviewCanvas.width===0}};})()'''


def main():
    # Some Windows user temp trees have stale restrictive ACLs from earlier QA.
    browser.OUTPUT.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(browser.OUTPUT.resolve())
    browser.main()
    path = browser.OUTPUT/"actual_e2e.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    frame = cv2.imread(str(browser.SOURCE))
    numerical_checks = []
    for fish in result["analysis"]["fish"]:
        brightness = fish["analysis"]["brightness"]
        if brightness["status"] != "measured": continue
        left,top,right,bottom = brightness["crop_bounds"]
        owned = np.zeros((bottom-top,right-left), bool)
        for row,start,length in brightness["owned_mask"]["runs"]: owned[row,start:start+length] = True
        expected = frame[top:bottom,left:right].max(axis=2)[owned].astype(float)*100/255
        error = abs(float(expected.mean())-brightness["mean_brightness"])
        assert error < 1e-10, (fish["id"],error)
        damage = fish["analysis"]["surface_damage"]
        prediction = np.zeros_like(owned)
        for row,start,length in damage.get("binary_mask",{}).get("runs",[]): prediction[row,start:start+length]=True
        assert not (prediction & ~owned).any()
        numerical_checks.append({"fish_id":fish["id"],"owned_pixel_count":int(owned.sum()),
            "mean_brightness":brightness["mean_brightness"],"brightness_error_percentage_points":error,
            "candidate_pixels_outside_owned_mask":int(np.count_nonzero(prediction & ~owned))})
    result["real_pixel_checks"] = numerical_checks
    for name, data in result.pop("surface_artifacts").items():
        (browser.OUTPUT/f"{name}.png").write_bytes(base64.b64decode(data.split(",",1)[1]))
    result["scope"] = "Actual CPU Model 1/Model 2/MobileSAM integration plus separately identified synthetic display truth. No expert real-fish crack labels."
    path.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"browser_checks":result["checks"],"real_pixel_checks":numerical_checks},indent=2))


if __name__ == "__main__": main()
