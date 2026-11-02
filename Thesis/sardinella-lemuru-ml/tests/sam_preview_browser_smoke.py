"""Real CPU Model 1/Model 2 -> HTTP -> MobileSAM -> visible Chrome canvas.

Run explicitly from the project root. This is not a scientific mask-accuracy
test. It starts only an isolated ephemeral server and hides all CUDA devices.
The ordinary application on port 8000 is never restarted or reconfigured.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen

import cv2
import numpy as np
from websockets.sync.client import connect

from dashboard_status_smoke import free_port, wait_json


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "results/qa/sam_preview"
SOURCE = ROOT / "Dried Fish Quality Grading.v7i.coco-segmentation/test/WIN_20260823_21_45_11_Pro_jpg.rf.01a0867ea638f10c1ffa3acd30d37830.jpg"


SERVER = r'''
import hashlib, importlib, json, os, cv2, torch, uvicorn
torch.set_num_threads(1)
cv2.setNumThreads(1)
m = importlib.import_module('src.api.app')
assert m.model.load(), m.model.error
assert m.quality_model.model is not None, m.quality_model.error
counts = {'model1_calls':0, 'model2_calls':0, 'grabcut_calls':0}
detect = m.model.detect
infer = m.quality_model._infer_parts
grabcut = cv2.grabCut
def detect_count(*args, **kwargs):
    counts['model1_calls'] += 1
    return detect(*args, **kwargs)
def infer_count(*args, **kwargs):
    counts['model2_calls'] += 1
    return infer(*args, **kwargs)
def grabcut_count(*args, **kwargs):
    counts['grabcut_calls'] += 1
    return grabcut(*args, **kwargs)
m.model.detect, m.quality_model._infer_parts, cv2.grabCut = detect_count, infer_count, grabcut_count
paths = {'model1':m.model.weights_path, 'model2':m.quality_model.weights_path}
def hashes():
    return {name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in paths.items()}
before = hashes()
@m.app.get('/__qa/diagnostics')
def diagnostics():
    from src.inference.mobilesam_backend import get_mobilesam_service
    sam = get_mobilesam_service()
    engine = sam._engine
    return {'counts':dict(counts), 'sam_status':sam.status(),
        'sam_encoder_calls':getattr(engine,'encoder_forward_calls',0),
        'cuda_initialized':torch.cuda.is_initialized(), 'device':'cpu',
        'checkpoint_before':before, 'checkpoint_after':hashes()}
uvicorn.run(m.app, host='127.0.0.1', port=int(os.environ['SAM_QA_PORT']), lifespan='off', log_level='warning')
'''


EXERCISE = r'''(async () => {
  const delay = milliseconds => new Promise(resolve => setTimeout(resolve,milliseconds));
  const until = async (predicate, message, timeout=90000) => {
    const start=performance.now();
    while(!predicate()) {if(performance.now()-start>timeout)throw new Error(message);await delay(40);}
  };
  const checks={}; const requests=[]; const payloads=[];
  const rawFetch=window.fetch;
  window.fetch=async (url, options={})=>{
    const path=String(url);
    if(path==='/api/segmentation/preview') {
      requests.push({path,headers:options.headers,bodySize:options.body?.size});
      const response=await rawFetch(url,options);
      payloads.push({httpStatus:response.status,payload:await response.clone().json()});
      return response;
    }
    return rawFetch(url,options);
  };
  const bytes=Uint8Array.from(atob(window.__realFishBytes),char=>char.charCodeAt(0));
  const photo=new File([bytes],window.__realFishName,{type:'image/jpeg'});
  toggleUpload(true);setUploadSelection(photo);
  await until(()=>uploadAnalysisAvailable(),'Real CPU upload analyzer unavailable');
  checks.optionalOff=!elements.segmentationExperiment.checked;
  checks.previewAvailableBeforeAnalysis=!elements.inspectMasks.disabled;
  elements.segmentationOptions.open=true;
  elements.analyze.click();
  await until(()=>!uploadInFlight,'Actual Model1/Model2 photo analysis timed out');
  checks.realDetectorAnalysis=resultDatasets.upload.rows.length>=2;
  const gradesBefore=JSON.stringify(resultDatasets.upload.rows);
  const diagnosticsBefore=await (await rawFetch('/__qa/diagnostics')).json();
  elements.inspectMasks.click();
  await until(()=>payloads.length>0,'Inspect fish masks did not make a real API call');
  await until(()=>uploadMaskPreview.image && !uploadMaskPreview.inFlight,'Real mask preview did not render');
  await delay(180);
  const payload=payloads[0].payload;
  const canvas=document.getElementById('upload-mask-canvas');
  const status=document.getElementById('upload-mask-status');
  const masks=document.getElementById('upload-mask-show');
  const boxes=document.getElementById('upload-mask-model1');
  const anatomy=document.getElementById('upload-mask-model2');
  const opacity=document.getElementById('upload-mask-opacity');
  const choice=document.getElementById('upload-mask-fish');
  const diagnosticsAfter=await (await rawFetch('/__qa/diagnostics')).json();
  checks.realPreviewRequest=requests[0]?.bodySize===bytes.length && requests[0]?.headers?.['X-Filename']===window.__realFishName;
  checks.actualCheckpointLoaded=diagnosticsAfter.sam_status.loaded===true && diagnosticsAfter.sam_status.checkpoint_integrity==='verified';
  checks.generatedRealCandidates=payload.status==='generated' && payload.generated_masks>=2;
  checks.oneSharedEmbedding=diagnosticsAfter.sam_encoder_calls-diagnosticsBefore.sam_encoder_calls===1;
  checks.existingModel1BoxesReused=diagnosticsAfter.counts.model1_calls===diagnosticsBefore.counts.model1_calls;
  checks.noModel2Rerun=diagnosticsAfter.counts.model2_calls===diagnosticsBefore.counts.model2_calls;
  checks.noDuplicateGrabcut=diagnosticsAfter.counts.grabcut_calls===diagnosticsBefore.counts.grabcut_calls;
  checks.noGradeMutation=JSON.stringify(resultDatasets.upload.rows)===gradesBefore;
  checks.nativeCanvas=canvas.width===payload.source.frame_width_px && canvas.height===payload.source.frame_height_px;
  checks.originalSource=canvas.width===640 && canvas.height===640 && payload.source.image_sha256===window.__realFishSha;
  checks.realTime=typeof payload.performance.segmentation_ms==='number' && payload.performance.segmentation_ms>0 && /\d+(?:\.\d+)?s|seconds/.test(status.textContent);
  checks.reviewFlags=payload.review_required_masks>0 && /review|unreliable|overlap|unvalidated/i.test(document.getElementById('upload-mask-preview').textContent);
  checks.defaultOpacity=Number(opacity.value)===40;
  checks.unassignedAnnotationsOff=!anatomy.checked;
  const entries=maskPreviewEntries(payload);
  const successful=entries.filter(item=>item.contours?.length || item.segmentation?.mask_overlay?.contours?.length || item.fish?.segmentation?.mask_overlay?.contours?.length);
  checks.allSerializedMasksReceived=successful.length===payload.generated_masks;
  checks.distinctMaskColors=new Set(entries.map(item=>item.color)).size===entries.length;
  checks.actualSilhouetteVertices=entries.some(item=>item.contours.some(polygon=>polygon.length>8));
  const change=control=>{control.dispatchEvent(new Event('input',{bubbles:true}));control.dispatchEvent(new Event('change',{bubbles:true}));};
  const set=(control,value)=>{control.checked=value;change(control);};
  set(masks,false);set(boxes,false);set(anatomy,false);choice.value='all';change(choice);
  await delay(50);
  const original=canvas.toDataURL('image/png');
  const originalPixels=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
  set(boxes,true);await delay(50);const boxOnly=canvas.toDataURL('image/png');
  set(boxes,false);set(masks,true);await delay(50);const shaded=canvas.toDataURL('image/png');
  const shadedPixels=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
  let different=0;for(let i=0;i<originalPixels.length;i+=4)if(Math.abs(originalPixels[i]-shadedPixels[i])+Math.abs(originalPixels[i+1]-shadedPixels[i+1])+Math.abs(originalPixels[i+2]-shadedPixels[i+2])>15)different++;
  checks.visibleShadedPixels=different>canvas.width*canvas.height*.03;
  checks.boxesDistinct=boxOnly!==original && shaded!==boxOnly;
  const choices=[...choice.options].filter(option=>option.value!=='all');
  checks.perFishChoices=choices.length===payload.fish.length && choices.length>=2;
  choice.value=choices[0].value;change(choice);await delay(35);const selectedFirst=canvas.toDataURL('image/png');
  choice.value=choices[1].value;change(choice);await delay(35);const selectedSecond=canvas.toDataURL('image/png');
  checks.differentFishDifferentMasks=selectedFirst!==selectedSecond && selectedFirst!==shaded && selectedSecond!==shaded;
  opacity.value='15';opacity.dispatchEvent(new Event('input',{bubbles:true}));await delay(35);const faint=canvas.toDataURL('image/png');
  opacity.value='70';opacity.dispatchEvent(new Event('input',{bubbles:true}));await delay(35);
  checks.opacityChangesPixels=faint!==canvas.toDataURL('image/png');
  opacity.value='40';opacity.dispatchEvent(new Event('input',{bubbles:true}));choice.value='all';change(choice);set(boxes,true);
  await delay(50);
  window.__realSamArtifacts={original,boxOnly,shaded,selectedFirst,selectedSecond,requests,payload,diagnosticsBefore,diagnosticsAfter};
  return {checks,status:status.textContent,changedPixelFraction:different/(canvas.width*canvas.height),successfulEntryCount:successful.length,
    fishChoices:choices.map(item=>({value:item.value,text:item.textContent})),requests,diagnosticsBefore,diagnosticsAfter,payload};
})()'''


LIFECYCLE = r'''(async()=>{
  const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));const checks={};
  const canvas=document.getElementById('upload-mask-canvas');
  const bytes=Uint8Array.from(atob(window.__realFishBytes),char=>char.charCodeAt(0));
  const photo=()=>new File([bytes],window.__realFishName,{type:'image/jpeg'});
  const old=canvas.toDataURL('image/png');
  setUploadSelection(photo());await delay(60);
  checks.newSelectionClears=uploadMaskPreview.image===null && !uploadMaskPreview.data && resultDatasets.upload.rows.length===0;
  const before=await (await fetch('/__qa/diagnostics')).json();
  await inspectUploadMasks();
  const standalone=uploadMaskPreview.data;
  const after=await (await fetch('/__qa/diagnostics')).json();
  checks.standaloneBeforeAnalysisWorks=standalone?.status==='generated' && standalone.generated_masks>=2 && resultDatasets.upload.rows.length===0;
  checks.standaloneCallsModel1Once=after.counts.model1_calls-before.counts.model1_calls===1;
  checks.standaloneNoModel2OrGrabcut=after.counts.model2_calls===before.counts.model2_calls && after.counts.grabcut_calls===before.counts.grabcut_calls;
  checks.standaloneOneEmbedding=after.sam_encoder_calls-before.sam_encoder_calls===1;
  setUploadSelection(new File(['video'],'different.mp4',{type:'video/mp4'}));await delay(25);
  checks.videoSwitchClears=uploadMaskPreview.image===null && !uploadMaskPreview.data && elements.inspectMasks.disabled;
  setUploadSelection(new File(['not an image'],'bad.jpg',{type:'image/jpeg'}));
  await inspectUploadMasks();await delay(25);
  checks.realDecodeFailureVisible=/failed|decode|invalid|image/i.test(document.getElementById('upload-mask-status').textContent) && !uploadMaskPreview.data;
  const errorMessage=document.getElementById('upload-mask-status').textContent;
  setUploadSelection(photo());
  const pending=inspectUploadMasks();await delay(15);setUploadSelection(new File(['video'],'cancel.mp4',{type:'video/mp4'}));await pending;await delay(50);
  checks.cancelCannotRestoreOldMasks=uploadMaskPreview.image===null && !uploadMaskPreview.data && elements.inspectMasks.disabled;
  return {checks,errorMessage,oldCanvasRecorded:Boolean(old),standalonePerformance:standalone?.performance,
    standaloneGenerated:standalone?.generated_masks};
})()'''


def local_status():
    result = {}
    for path in ("/api/segmentation/status", "/api/status/live"):
        try:
            with urlopen("http://127.0.0.1:8000" + path, timeout=2) as response:
                data = json.load(response)
            result[path] = {key: data.get(key) for key in ("default_backend", "runtime_mode", "inspection_status", "system_status") if key in data}
            if "mobilesam" in data:
                result[path]["mobilesam"] = data["mobilesam"]
        except (OSError, URLError) as error:
            result[path] = {"error": str(error)}
    return result


def main():
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.is_file() or not SOURCE.is_file():
        raise RuntimeError("Actual source image or Chrome is unavailable")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source_bytes = SOURCE.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    api_port, cdp_port = free_port(), free_port()
    running_service = local_status()
    with tempfile.TemporaryDirectory(prefix="tamban_real_sam_preview_") as tmp:
        env = dict(os.environ, SAM_QA_PORT=str(api_port), FISH_INSPECTION_DB_PATH=str(Path(tmp)/"qa.sqlite3"),
            FISH_DETECTOR_DEVICE="cpu", FISH_QUALITY_DEVICE="cpu", MOBILESAM_DEVICE="cpu", SEGMENTATION_BACKEND="grabcut",
            YOLO_CONFIG_DIR=tmp, PYTHONDONTWRITEBYTECODE="1", CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
        hidden = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with (OUTPUT/"actual_cpu_server.log").open("w",encoding="utf-8") as log:
            server=subprocess.Popen([sys.executable,"-B","-c",SERVER],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=hidden)
            browser=None
            try:
                wait_json(f"http://127.0.0.1:{api_port}/__qa/diagnostics",server,timeout=90)
                args=["--headless=new","--disable-gpu","--no-first-run",f"--user-data-dir={Path(tmp)/'chrome'}",
                    f"--remote-debugging-port={cdp_port}","--remote-allow-origins=*","--window-size=1440,1100"]
                if os.getenv("TAMBAN_CHROME_NO_SANDBOX","").lower() in {"1","true","yes","on"}:args.append("--no-sandbox")
                browser=subprocess.Popen([str(chrome),*args,f"http://127.0.0.1:{api_port}/"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=hidden)
                page=next(p for p in wait_json(f"http://127.0.0.1:{cdp_port}/json",browser) if p.get("type")=="page")
                with connect(page["webSocketDebuggerUrl"],open_timeout=5,max_size=32*1024*1024) as ws:
                    counter=0
                    def call(method,params=None):
                        nonlocal counter
                        counter+=1;ws.send(json.dumps({"id":counter,"method":method,"params":params or {}}))
                        while True:
                            response=json.loads(ws.recv(timeout=180))
                            if response.get("id")==counter:
                                if "error" in response:raise AssertionError(response["error"])
                                if "exceptionDetails" in response["result"]:raise AssertionError(response["result"]["exceptionDetails"])
                                return response["result"]
                    def evaluate(script):
                        return call("Runtime.evaluate",{"expression":script,"returnByValue":True,"awaitPromise":True})["result"].get("value")
                    for _ in range(150):
                        if evaluate("typeof inspectUploadMasks==='function' && typeof latestStatus!=='undefined' && latestStatus!==null"):break
                        time.sleep(.1)
                    else:raise AssertionError("New mask preview UI did not load")
                    evaluate("window.__realFishBytes="+json.dumps(base64.b64encode(source_bytes).decode())+";window.__realFishName="+json.dumps(SOURCE.name)+";window.__realFishSha="+json.dumps(source_sha)+";true")
                    result=evaluate(EXERCISE)
                    (OUTPUT/"actual_e2e_partial.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
                    assert all(result["checks"].values()),result["checks"]
                    for key,name in (("original","original.png"),("boxOnly","model1_boxes.png"),("shaded","mobilesam_shaded.png"),("selectedFirst","selected_fish_1.png"),("selectedSecond","selected_fish_2.png")):
                        data=evaluate(f"window.__realSamArtifacts.{key}")
                        (OUTPUT/name).write_bytes(base64.b64decode(data.split(",",1)[1]))
                    screenshot=call("Page.captureScreenshot",{"format":"png","captureBeyondViewport":False})
                    (OUTPUT/"actual_preview_desktop.png").write_bytes(base64.b64decode(screenshot["data"]))
                    call("Emulation.setDeviceMetricsOverride",{"width":390,"height":844,"deviceScaleFactor":1,"mobile":True})
                    evaluate("document.getElementById('upload-mask-preview').scrollIntoView({block:'center'});true")
                    time.sleep(.2)
                    mobile=evaluate("({width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth,canvas:document.getElementById('upload-mask-canvas').getBoundingClientRect().width})")
                    result["mobile"]=mobile
                    assert mobile["scrollWidth"]<=mobile["width"]+2,mobile
                    screenshot=call("Page.captureScreenshot",{"format":"png","captureBeyondViewport":False})
                    (OUTPUT/"actual_preview_mobile.png").write_bytes(base64.b64decode(screenshot["data"]))
                    result["lifecycle"]=evaluate(LIFECYCLE)
                    assert all(result["lifecycle"]["checks"].values()),result["lifecycle"]
                    assert result["diagnosticsAfter"]["cuda_initialized"] is False
                    assert result["diagnosticsAfter"]["checkpoint_before"]==result["diagnosticsAfter"]["checkpoint_after"]
                    result.update(scope="Real unchanged CPU Model1+Model2 analysis and MobileSAM checkpoint, actual HTTP and real Chrome canvas; no expert mask accuracy ground truth",
                        source={"path":str(SOURCE),"sha256":source_sha},running_service_before=running_service,
                        chrome_version=call("Browser.getVersion")["product"],peak_gpu_memory_bytes=None,
                        gpu_memory_reason="CPU-only, CUDA not initialized; separate running GPU service untouched")
                    (OUTPUT/"actual_e2e.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
                    tiles=[cv2.imread(str(OUTPUT/name)) for name in ("original.png","model1_boxes.png","mobilesam_shaded.png")]
                    cv2.imwrite(str(OUTPUT/"original_boxes_masks.comparison.png"),np.hstack(tiles))
                    print(json.dumps({"checks":result["checks"],"lifecycle":result["lifecycle"],"mobile":mobile,
                        "performance":result["payload"]["performance"],"generated_masks":result["payload"]["generated_masks"],
                        "review_required_masks":result["payload"]["review_required_masks"],"output":str(OUTPUT)},indent=2))
            finally:
                for process in (browser,server):
                    if process is not None:
                        process.terminate();process.wait(timeout=15)


if __name__=="__main__":main()
