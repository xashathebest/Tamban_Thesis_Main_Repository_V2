"""Before/after Chrome evidence for the Analyze Media refinement.

The before phase serves an immutable source snapshot taken before edits. Both
phases exercise real frontend layout with cached synthetic source-bound evidence;
no application server, neural model, inference or grading endpoint is started.
"""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from threading import Thread
import time
from urllib.request import urlopen

from websockets.sync.client import connect

import camera_workspace_browser_smoke as browser
from test_coloredfish_ui import specimen


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "results/qa/analyze_refinement"
LONG_NAME = "tamban_inspection_original_photo_batch_2026-11-04_fish_quality_assurance_reference_frame_000001_with_full_anatomical_evidence.png"
VIEWPORTS = [(1366, 768), (1920, 1080), (1024, 700), (768, 1024), (390, 844)]

METRICS = r'''(()=>{
const box=e=>{if(!e)return null;const b=e.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height,right:b.right,bottom:b.bottom};};
const stage=elements.uploadMediaStage,tools=stage.querySelector('.viewer-floating-tools'),full=document.getElementById('upload-fullscreen-button'),
panel=document.getElementById('upload-workspace-results'),layout=document.querySelector('.upload-inspection-layout'),name=elements.uploadFileName;
const img=elements.uploadImage,rect=img.getBoundingClientRect(),s=stage.getBoundingClientRect();
const imageStyle=getComputedStyle(img),inset=name=>parseFloat(imageStyle[name])||0;
const contentWidth=rect.width-inset('paddingLeft')-inset('paddingRight')-inset('borderLeftWidth')-inset('borderRightWidth'),
contentHeight=rect.height-inset('paddingTop')-inset('paddingBottom')-inset('borderTopWidth')-inset('borderBottomWidth');
const scale=img.naturalWidth?Math.min(contentWidth/img.naturalWidth,contentHeight/img.naturalHeight):0;
const controls=[...tools.querySelectorAll('button,select')].filter(e=>e.getBoundingClientRect().width).map(e=>({id:e.id,box:box(e)}));
return {viewport:{width:innerWidth,height:innerHeight,clientWidth:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth},
workspace:box(elements.uploadWorkspace),upload:box(elements.uploadDropZone),stage:box(stage),tools:box(tools),controls,
toolbarOverflow:tools.scrollWidth>tools.clientWidth+1,fullscreen:box(full),fullscreenIcon:box(full.querySelector('svg')),fullscreenText:full.textContent.trim(),
fullscreenLabel:full.getAttribute('aria-label'),fullscreenTitle:full.getAttribute('title'),filename:{box:box(name),title:name.title,text:name.textContent,scrollWidth:name.scrollWidth,clientWidth:name.clientWidth,textOverflow:getComputedStyle(name).textOverflow,whiteSpace:getComputedStyle(name).whiteSpace,overflow:getComputedStyle(name).overflow},
results:box(panel),resultsVisible:!panel.hidden&&getComputedStyle(panel).display!=='none'&&panel.getBoundingClientRect().width>0,
splitterVisible:getComputedStyle(document.getElementById('upload-workspace-splitter')).display!=='none',
layout:box(layout),natural:[img.naturalWidth,img.naturalHeight],fit:getComputedStyle(img).objectFit,
renderedMedia:{x:rect.x+inset('paddingLeft')+inset('borderLeftWidth')+(contentWidth-img.naturalWidth*scale)/2,
y:rect.y+inset('paddingTop')+inset('borderTopWidth')+(contentHeight-img.naturalHeight*scale)/2,
width:img.naturalWidth*scale,height:img.naturalHeight*scale},maskViewport:box(elements.maskPreviewViewport),
imageHidden:img.classList.contains('hidden'),file:selectedUpload?.name||null,
maskViewportOverflow:getComputedStyle(elements.maskPreviewViewport).overflow,
bodyLocked:document.body.classList.contains('panel-open'),htmlOverflow:getComputedStyle(document.documentElement).overflow};
})()'''

SELECT_MEDIA = r'''(async()=>{
const c=document.createElement('canvas');c.width=500;c.height=300;const p=c.getContext('2d');
p.fillStyle='#e7f0f2';p.fillRect(0,0,500,300);p.fillStyle='#91a9af';
for(const x of [15,265]){p.beginPath();p.ellipse(x+105,75,105,30,0,0,2*Math.PI);p.fill();}
const bytes=Uint8Array.from(atob(c.toDataURL().split(',')[1]),v=>v.charCodeAt(0));
window.__refineFile=new File([bytes],window.__longName,{type:'image/png'});
setUploadSelection(window.__refineFile);await new Promise(resolve=>setTimeout(resolve,100));return true;
})()'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    args = parser.parse_args()
    phase_dir = OUTPUT / args.phase
    phase_dir.mkdir(parents=True, exist_ok=True)
    if args.phase == "before":
        browser.SOURCE_DIR = OUTPUT / "before_source"
        assert (browser.SOURCE_DIR / "app.js").is_file(), "Capture source snapshot before changing the frontend"
    result = {"phase": args.phase, "checks": {}, "viewports": {}, "sticky_controls": {}, "api_requests": [],
              "scope": "Real headless Chrome layout, screenshots and trusted browser input; cached synthetic fish evidence; no model/inference/accuracy claims"}
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    server = ThreadingHTTPServer(("127.0.0.1", 0), browser.Frontend)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix="tamban_refine_", ignore_cleanup_errors=True) as directory:
            command = [str(chrome), "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={directory}",
                       f"--remote-debugging-port={port}", "--remote-allow-origins=*", "--window-size=1366,768"]
            if os.getenv("TAMBAN_CHROME_NO_SANDBOX", "").lower() in {"1", "true", "yes", "on"}:
                command.append("--no-sandbox")
            process = subprocess.Popen([*command, f"http://127.0.0.1:{server.server_port}/"], stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            until = time.monotonic() + 20
            while True:
                try:
                    with urlopen(f"http://127.0.0.1:{port}/json", timeout=1) as response:
                        page = next(item for item in json.load(response) if item.get("type") == "page")
                    break
                except (OSError, StopIteration):
                    if time.monotonic() > until:
                        raise RuntimeError("Chrome did not start")
                    time.sleep(.1)
            with connect(page["webSocketDebuggerUrl"], open_timeout=5, max_size=16 * 1024 * 1024) as socket_client:
                counter = 0
                errors = []

                def call(method, params=None):
                    nonlocal counter
                    counter += 1
                    socket_client.send(json.dumps({"id": counter, "method": method, "params": params or {}}))
                    while True:
                        response = json.loads(socket_client.recv(timeout=30))
                        if response.get("method") == "Runtime.exceptionThrown":
                            errors.append(response.get("params"))
                        if response.get("id") != counter:
                            continue
                        if "error" in response:
                            raise AssertionError(response["error"])
                        if "exceptionDetails" in response["result"]:
                            raise AssertionError(response["result"]["exceptionDetails"])
                        return response["result"]

                def evaluate(script):
                    return call("Runtime.evaluate", {"expression": script, "returnByValue": True, "awaitPromise": True})["result"].get("value")

                def wait_for(script):
                    until = time.monotonic() + 5
                    while not evaluate(script):
                        if time.monotonic() > until:
                            raise AssertionError(f"Timed out: {script}")
                        time.sleep(.06)

                def screenshot(name):
                    picture = call("Page.captureScreenshot", {"format": "png"})
                    (phase_dir / name).write_bytes(base64.b64decode(picture["data"]))

                def click(selector):
                    location = evaluate("(()=>{const e=document.querySelector(" + json.dumps(selector)
                                        + ");e.scrollIntoView({block:'nearest',behavior:'instant'});const b=e.getBoundingClientRect();return {x:b.x+b.width/2,y:b.y+b.height/2};})()")
                    call("Input.dispatchMouseEvent", {"type": "mousePressed", "button": "left", "clickCount": 1, **location})
                    call("Input.dispatchMouseEvent", {"type": "mouseReleased", "button": "left", "clickCount": 1, **location})
                    time.sleep(.12)

                def key(name, code):
                    call("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": name, "code": name, "windowsVirtualKeyCode": code})
                    call("Input.dispatchKeyEvent", {"type": "keyUp", "key": name, "code": name, "windowsVirtualKeyCode": code})
                    time.sleep(.1)

                call("Runtime.enable")
                wait_for("typeof renderMaskPreview==='function'&&typeof elements!=='undefined'")
                evaluate("window.__longName=" + json.dumps(LONG_NAME) + ";window.__refineRequests=[];window.fetch=async(...args)=>{window.__refineRequests.push(String(args[0]));throw new Error('No inference in layout validation');};true")
                fixture = deepcopy(specimen())
                evaluate("window.__associationFixture=" + json.dumps(fixture) + ";true")
                for width, height in VIEWPORTS:
                    call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
                    evaluate("resetUploadWorkspace();toggleUpload(true);elements.uploadWorkspace.scrollTop=0;true")
                    time.sleep(.18)
                    states = {}
                    states["before_upload"] = evaluate(METRICS)
                    screenshot(f"before_upload_{width}x{height}.png")
                    evaluate(SELECT_MEDIA)
                    time.sleep(.15)
                    states["selected_preview"] = evaluate(METRICS)
                    screenshot(f"selected_preview_{width}x{height}.png")
                    evaluate(browser.SETUP.replace("'workspace-fixture.png'", "window.__longName"))
                    evaluate("selectInspectionFish(1,{revealCard:true});elements.uploadWorkspace.scrollTop=0;true")
                    time.sleep(.15)
                    states["analyzed_results"] = evaluate(METRICS)
                    screenshot(f"analyzed_results_{width}x{height}.png")
                    result["api_requests"].extend(evaluate("window.__qa.requests"))
                    result["viewports"][f"{width}x{height}"] = states
                    if args.phase == "after" and width <= 900:
                        evaluate("elements.uploadWorkspace.scrollTop=240;true")
                        time.sleep(.1)
                        sticky = evaluate("(()=>{const box=window.__qa.box;return {workspace:box(elements.uploadWorkspace),scrollTop:elements.uploadWorkspace.scrollTop,header:box(elements.uploadWorkspace.querySelector('.upload-modal-head')),upload:box(elements.uploadDropZone),controls:['close-upload-button','select-upload-button','remove-upload-button','analyze-button'].map(id=>({id,box:box(document.getElementById(id))}))};})()")
                        result["sticky_controls"][f"{width}x{height}"] = sticky
                        screenshot(f"sticky_controls_{width}x{height}.png")
                        evaluate("elements.uploadWorkspace.scrollTop=0;true")
                result["chrome"] = call("Browser.getVersion")["product"]
                result["runtime_errors"] = errors
                if args.phase == "after":
                    checks = result["checks"]
                    for dimensions, sticky in result["sticky_controls"].items():
                        bounds = sticky["workspace"]
                        checks[dimensions + "_actionsStayVisibleDuringLongResultsScroll"] = sticky["scrollTop"] >= 200 and all(control["box"]["y"] >= bounds["y"] and control["box"]["bottom"] <= bounds["bottom"] for control in sticky["controls"])
                        checks[dimensions + "_stickyHeaderAndUploaderDoNotOverlap"] = sticky["header"]["bottom"] <= sticky["upload"]["y"] + 1
                    for dimensions, states in result["viewports"].items():
                        width, height = map(int, dimensions.split("x"))
                        for state_name, metrics in states.items():
                            prefix = f"{dimensions}_{state_name}"
                            checks[prefix + "_noHorizontalOverflow"] = metrics["viewport"]["scrollWidth"] <= metrics["viewport"]["clientWidth"] + 1
                            checks[prefix + "_toolbarFitsViewer"] = not metrics["toolbarOverflow"] and metrics["tools"]["x"] >= metrics["stage"]["x"] - 1 and metrics["tools"]["right"] <= metrics["stage"]["right"] + 1
                            checks[prefix + "_fullscreenIconCompact"] = metrics["fullscreenText"] == "" and 14 <= metrics["fullscreenIcon"]["width"] <= 24 and 14 <= metrics["fullscreenIcon"]["height"] <= 24
                            checks[prefix + "_fullscreenAccessible"] = bool(metrics["fullscreenLabel"] and metrics["fullscreenTitle"])
                            checks[prefix + "_noToolbarControlsOverlap"] = all(a["box"]["right"] <= b["box"]["x"] + 1 for a, b in zip(metrics["controls"], metrics["controls"][1:]))
                        selected = states["selected_preview"]
                        analyzed = states["analyzed_results"]
                        filename = selected["filename"]
                        checks[dimensions + "_filenameOverflowUsesEllipsisAndFullTooltip"] = filename["title"] == LONG_NAME and filename["textOverflow"] == "ellipsis" and filename["whiteSpace"] == "nowrap" and filename["overflow"] == "hidden" and filename["box"]["right"] <= selected["upload"]["right"]
                        checks[dimensions + "_previewUsesUnusedResultsSpace"] = not selected["resultsVisible"] and selected["stage"]["width"] >= selected["layout"]["width"] - 6
                        checks[dimensions + "_fitContainsEntireImage"] = selected["fit"] == "contain" and selected["renderedMedia"]["width"] <= selected["stage"]["width"] + 1 and selected["renderedMedia"]["height"] <= selected["stage"]["height"] + 1
                        checks[dimensions + "_resultsRestoreAfterAnalysis"] = analyzed["resultsVisible"]
                        checks[dimensions + "_wholePreviewVisibleWithoutScrolling"] = selected["stage"]["bottom"] <= selected["workspace"]["bottom"] + 1
                        checks[dimensions + "_beforeUploadCompact"] = states["before_upload"]["upload"]["height"] <= (60 if width >= 1024 else 76)
                        if width >= 1024:
                            checks[dimensions + "_selectedUploadSingleCompactRow"] = selected["upload"]["height"] <= 58
                            ratio = analyzed["stage"]["width"] / analyzed["layout"]["width"]
                            checks[dimensions + "_analysisRestores7030Split"] = .65 <= ratio <= .75 and analyzed["splitterVisible"]
                        else:
                            checks[dimensions + "_selectedUploadCompact"] = selected["upload"]["height"] <= 90
                            if width <= 680:
                                checks[dimensions + "_toolbarDoesNotCoverSourcePhoto"] = selected["tools"]["bottom"] <= selected["renderedMedia"]["y"] + 1 and analyzed["tools"]["bottom"] <= analyzed["renderedMedia"]["y"] + 1
                    # Trusted native fullscreen with the initial icon; all previous
                    # measurements were captured before the first fullscreen sync.
                    click('label:has(> #upload-display-masks)')
                    wait_for("!elements.maskPreviewViewport.classList.contains('hidden')")
                    mobile_mask = evaluate("({stage:window.__qa.box(elements.uploadMediaStage),viewport:window.__qa.box(elements.maskPreviewViewport),canvas:window.__qa.box(elements.maskPreviewCanvas),tools:window.__qa.box(elements.uploadMediaStage.querySelector('.viewer-floating-tools'))})")
                    result["mobile_mask_fit"] = mobile_mask
                    checks["mobileMaskToolbarDoesNotCoverAnnotations"] = mobile_mask["tools"]["bottom"] <= mobile_mask["canvas"]["y"] + 1 and mobile_mask["viewport"]["y"] >= mobile_mask["stage"]["y"] + 40
                    checks["mobileMaskFitsCompleteFrame"] = mobile_mask["canvas"]["width"] <= mobile_mask["viewport"]["width"] + 1 and mobile_mask["canvas"]["height"] <= mobile_mask["viewport"]["height"] + 1 and abs(mobile_mask["canvas"]["width"] / mobile_mask["canvas"]["height"] - 5 / 3) < .015
                    screenshot("mobile_mask_fit.png")
                    evaluate("selectInspectionFish(2);elements.maskPreviewZoom.value='2';viewerTransforms.upload.x=20;viewerTransforms.upload.y=35;renderMaskPreview();applyViewerTransform('upload');true")
                    point = evaluate("(()=>{const b=elements.maskPreviewCanvas.getBoundingClientRect();return {x:b.x+b.width*125/500,y:b.y+b.height*75/300};})()")
                    call("Input.dispatchMouseEvent", {"type": "mousePressed", "button": "left", "clickCount": 1, **point})
                    call("Input.dispatchMouseEvent", {"type": "mouseReleased", "button": "left", "clickCount": 1, **point})
                    time.sleep(.12)
                    checks["mobileMaskZoomPanSelectionRemainsAligned"] = evaluate("elements.maskPreviewFish.value==='1'")
                    evaluate("resetViewerTransform('upload');true")
                    call("Emulation.setDeviceMetricsOverride", {"width": 1366, "height": 768, "deviceScaleFactor": 1, "mobile": False})
                    evaluate("elements.uploadWorkspace.scrollTop=0;true")
                    click('#upload-fullscreen-button')
                    wait_for("document.fullscreenElement?.id==='upload-media-stage'")
                    checks["trustedFullscreenStillUsesActualViewer"] = True
                    screenshot("native_fullscreen.png")
                    key("Escape", 27)
                    checks["escapeKeepsInspectionWorkspace"] = evaluate("!document.fullscreenElement&&!elements.uploadWorkspace.classList.contains('hidden')")
                    checks["existingOverlayControlsPreserved"] = evaluate("['upload-display-boxes','upload-display-masks','upload-mask-opacity','upload-mask-fish','upload-mask-model1','upload-mask-model2','upload-mask-measurements','upload-mask-cracks','upload-association-debug','upload-mask-zoom'].every(id=>document.getElementById(id))")
                    lifecycle = evaluate(r'''(async()=>{
const checks={},before=JSON.stringify(resultDatasets.upload.rows),scope=resultDatasets.upload.scope;
toggleUpload(false);toggleUpload(true);
checks.cachedCloseReopenPreservesResults=JSON.stringify(resultDatasets.upload.rows)===before&&resultDatasets.upload.scope===scope&&elements.uploadWorkspace.classList.contains('has-results');
setUploadSelection(new File([window.__qa.file],'replacement.png',{type:'image/png'}));
checks.replaceReturnsToWidePreview=!elements.uploadWorkspace.classList.contains('has-results')&&document.getElementById('upload-workspace-results').inert&&document.getElementById('upload-workspace-splitter').tabIndex===-1;
renderResultsDashboard([],{source:'upload',complete:true,scope:'completed-zero-fish',metadata:{source_name:'replacement.png'}});
resultsSource='upload';resultsFilter='All';renderResultsDashboard(null,{renderOnly:true});mountResultsDashboard(true);
checks.completedZeroFishShowsResults=elements.uploadWorkspace.classList.contains('has-results')&&!document.getElementById('upload-workspace-results').inert&&resultDatasets.upload.rows.length===0;
uploadInFlight=true;updateUploadControls();startUploadTimer();await new Promise(resolve=>setTimeout(resolve,350));
checks.processingElapsedTimeIsReal=uploadElapsedSeconds()>=.3&&uploadElapsedSeconds()<2&&/\d+\.\ds/.test(elements.uploadStatus.textContent)&&elements.uploadWorkspace.classList.contains('is-processing');
checks.processingKeepsFileActionsClear=elements.selectUpload.disabled&&elements.removeUpload.disabled;
stopUploadTimer();uploadInFlight=false;updateUploadControls();
resetUploadWorkspace();
checks.removeClearsWorkspaceState=!selectedUpload&&!elements.uploadWorkspace.classList.contains('has-media')&&!elements.uploadWorkspace.classList.contains('has-results')&&elements.uploadFileName.title==='';
return checks;
})()''')
                    checks.update(lifecycle)
                    # Restore analyzed evidence for the final visual screenshot.
                    evaluate(browser.SETUP.replace("'workspace-fixture.png'", "window.__longName"))
                    evaluate("selectInspectionFish(1,{revealCard:true});elements.uploadWorkspace.scrollTop=0;true")
                    evaluate("document.getElementById('upload-overlay-summary-status').closest('details').open=true;true")
                    key("Escape", 27)
                    checks["escapeClosesAdvancedControlsBeforeWorkspace"] = evaluate("!document.getElementById('upload-overlay-summary-status').closest('details').open&&!elements.uploadWorkspace.classList.contains('hidden')")
                    evaluate("document.getElementById('upload-overlay-summary-status').closest('details').open=true;true")
                    click('#upload-result-image')
                    checks["outsidePointerClosesAdvancedControls"] = evaluate("!document.getElementById('upload-overlay-summary-status').closest('details').open")
                    screenshot("final_analyzed_desktop.png")
                    checks["noRuntimeErrors"] = not errors
                    checks["noInferenceRequests"] = not result["api_requests"] and evaluate("window.__qa.requests.length===0&&window.__refineRequests.length===0")
                (phase_dir / "layout_metrics.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                print(json.dumps({"phase": args.phase, "checks": len(result["checks"]), "failed": [key for key, value in result["checks"].items() if not value], "viewports": list(result["viewports"])}, indent=2))
                assert all(result["checks"].values()), [key for key, value in result["checks"].items() if not value]
            process.terminate()
            process.wait(timeout=15)
            process = None
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=15)
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    main()
