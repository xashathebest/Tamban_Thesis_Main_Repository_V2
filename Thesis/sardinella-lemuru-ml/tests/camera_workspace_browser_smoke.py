"""Actual Chrome/CDP regression checks for the camera-first workspaces.

Serves the repository frontend with its API polling bootstrap disabled. A real
local MJPEG stream and cached synthetic fish evidence exercise display behavior
without a webcam, trained models, grading, or inference. Run explicitly; this is
not an accuracy or hardware-camera test.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from threading import Thread
import time
from urllib.request import urlopen

from PIL import Image, ImageDraw
from websockets.sync.client import connect

import anatomical_debug_browser_smoke as existing
from test_coloredfish_ui import specimen


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "frontend"
OUTPUT = ROOT / "results/qa/camera_workspace"
STREAM = {"connections": 0, "frames": 0}


class Frontend(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/fixture-stream.mjpg":
            STREAM["connections"] += 1
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                for frame in range(1200):
                    image = Image.new("RGB", (640, 480), "#d4e5e7")
                    draw = ImageDraw.Draw(image)
                    draw.ellipse((80, 155, 420, 300), fill="#7f9ba5", outline="#175cba", width=4)
                    draw.line((320, 0, 320, 480), fill="#ff9e2d", width=3)
                    draw.text((20, 25), f"Synthetic MJPEG preview / frame {frame}", fill="#153644")
                    draw.text((80, 135), "Fish #1 / Class B", fill="#175cba")
                    encoded = io.BytesIO()
                    image.save(encoded, format="JPEG")
                    payload = encoded.getvalue()
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(payload)).encode() + b"\r\n\r\n" + payload + b"\r\n")
                    self.wfile.flush()
                    STREAM["frames"] += 1
                    time.sleep(.08)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            return
        name = "index.html" if path == "/" else path.removeprefix("/assets/")
        if name not in {"index.html", "app.js", "styles.css", "inspection-layout.css",
                        "inspection-evidence.css", "session-workspace.css", "session-workspace.js",
                        "camera-workspace.css", "analytics-workspace.js", "analytics-workspace.css"}:
            self.send_error(404)
            return
        source_path = SOURCE_DIR / name
        if not source_path.is_file():
            self.send_error(404)
            return
        source = source_path.read_text(encoding="utf-8")
        if name == "app.js":
            assert source.count(existing.BOOTSTRAP) == 1, "Update isolated bootstrap contract"
            source = source.replace(existing.BOOTSTRAP, "/* API bootstrap omitted in isolated UI regression. */")
        mime = "text/html" if name.endswith(".html") else "text/css" if name.endswith(".css") else "text/javascript"
        value = source.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(value)))
        self.end_headers()
        self.wfile.write(value)

    def log_message(self, *_args):
        pass


SETUP = r'''(async()=>{
window.__qa={requests:[],sourceNode:elements.video};
window.fetch=async(...args)=>{window.__qa.requests.push(String(args[0]));throw new Error('No inference or API calls in display-only checks');};
window.__qa.box=element=>{const b=element.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height,right:b.right,bottom:b.bottom};};
const fixture=window.__associationFixture,source=document.createElement('canvas');source.width=500;source.height=300;
const pen=source.getContext('2d');pen.fillStyle='#e7f0f2';pen.fillRect(0,0,500,300);
pen.fillStyle='#91a9af';for(const x of [15,265]){pen.beginPath();pen.ellipse(x+105,75,105,30,0,0,2*Math.PI);pen.fill();}
fixture.preview_image=source.toDataURL();
const bytes=Uint8Array.from(atob(fixture.preview_image.split(',')[1]),char=>char.charCodeAt(0));
window.__qa.file=new File([bytes],'workspace-fixture.png',{type:'image/png'});
toggleUpload(true);
const transfer=new DataTransfer();transfer.items.add(window.__qa.file);
elements.uploadDropZone.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}));
await new Promise(resolve=>setTimeout(resolve,80));
const fish=fixture.fish.map((item,i)=>({...structuredClone(item),quality:'Class C',ai_final_grade:i?'Class B':'Class A',
analysis:{...structuredClone(item.analysis||{}),segmentation:structuredClone(item.segmentation),
final_grade:i?'Class B':'Class A',weighted_scores:{[i?'Class B':'Class A']:.8}}}));
fixture.fish=fish;
renderResultsDashboard(fish,{source:'upload',complete:true,scope:'camera-workspace-fixture',metadata:{source_name:window.__qa.file.name}});
resultsSource='upload';resultsFilter='All';renderResultsDashboard(null,{renderOnly:true});
mountResultsDashboard(true);elements.uploadResults.classList.remove('hidden');
await acceptAutomaticMaskPreview({fish,segmentation_preview:fixture},window.__qa.file);
window.__qa.rowsBefore=JSON.stringify(resultDatasets.upload.rows);
window.__qa.snapshot=kind=>{const media=fishZoomMedia(kind),stage=kind==='live'?elements.liveMediaStage:elements.uploadMediaStage;
const target=stage.querySelector('.fish-click-target');return {stage:window.__qa.box(stage),media:window.__qa.box(media),
fit:getComputedStyle(media).objectFit,natural:[media.naturalWidth||media.videoWidth,media.naturalHeight||media.videoHeight],
target:target?window.__qa.box(target):null,canvas:window.__qa.box(elements.maskPreviewCanvas),
viewport:window.__qa.box(elements.maskPreviewViewport),fullscreen:document.fullscreenElement?.id||null};};
window.__qa.alignment=(kind,box)=>{const media=fishZoomMedia(kind),stage=kind==='live'?elements.liveMediaStage:elements.uploadMediaStage;
const target=stage.querySelector('.fish-click-target'),b=media.getBoundingClientRect(),t=target?.getBoundingClientRect();
if(!t)return {maxError:1e9,inverseError:1e9};
const w=media.naturalWidth||media.videoWidth,h=media.naturalHeight||media.videoHeight;
const scale=(getComputedStyle(media).objectFit==='cover'?Math.max:Math.min)(b.width/w,b.height/h);
const left=b.x+(b.width-w*scale)/2,top=b.y+(b.height-h*scale)/2;
const expected=[left+box[0]*scale,top+box[1]*scale,(box[2]-box[0])*scale,(box[3]-box[1])*scale];
const inverse=fishZoomPoint({clientX:t.x+t.width/2,clientY:t.y+t.height/2},media,stage);
return {maxError:Math.max(...[t.x,t.y,t.width,t.height].map((v,i)=>Math.abs(v-expected[i]))),
inverseError:Math.max(Math.abs(inverse[0]-(box[0]+box[2])/2),Math.abs(inverse[1]-(box[1]+box[3])/2))};};
return {dropped:selectedUpload===window.__qa.file,selected:elements.uploadDropZone.classList.contains('is-selected'),
controlsInside:elements.uploadMediaStage.contains(document.getElementById('upload-fullscreen-button'))&&elements.liveMediaStage.contains(document.getElementById('live-fullscreen-button')),
filename:elements.uploadFileName.textContent,uploadToolbarHeight:elements.uploadDropZone.getBoundingClientRect().height};
})()'''


def main():
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.is_file():
        raise RuntimeError("Chrome is unavailable")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    result = {"checks": {}, "viewports": {}, "scope": "Real Chrome DOM/canvas, trusted input and local MJPEG; cached synthetic fish evidence; no webcam, models, inference or accuracy claims", "limitations": ["Hardware camera/driver and real model FPS were not exercised."]}
    server = ThreadingHTTPServer(("127.0.0.1", 0), Frontend)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        cdp_port = sock.getsockname()[1]
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix="tamban_camera_workspace_", ignore_cleanup_errors=True) as directory:
            args = [str(chrome), "--headless=new", "--disable-gpu", "--no-first-run",
                    f"--user-data-dir={directory}", f"--remote-debugging-port={cdp_port}",
                    "--remote-allow-origins=*", "--window-size=1366,768"]
            if os.getenv("TAMBAN_CHROME_NO_SANDBOX", "").lower() in {"1", "true", "yes", "on"}:
                args.append("--no-sandbox")
            process = subprocess.Popen([*args, f"http://127.0.0.1:{server.server_port}/"], stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            deadline = time.monotonic() + 20
            while True:
                try:
                    with urlopen(f"http://127.0.0.1:{cdp_port}/json", timeout=1) as response:
                        page = next(item for item in json.load(response) if item.get("type") == "page")
                    break
                except (OSError, StopIteration):
                    if time.monotonic() > deadline:
                        raise RuntimeError("Chrome debug page did not start")
                    time.sleep(.1)
            with connect(page["webSocketDebuggerUrl"], open_timeout=5, max_size=16 * 1024 * 1024) as websocket:
                counter = 0
                runtime_errors = []

                def call(method, params=None):
                    nonlocal counter
                    counter += 1
                    websocket.send(json.dumps({"id": counter, "method": method, "params": params or {}}))
                    while True:
                        response = json.loads(websocket.recv(timeout=30))
                        if response.get("method") == "Runtime.exceptionThrown":
                            runtime_errors.append(response.get("params", {}))
                        if response.get("id") != counter:
                            continue
                        if "error" in response:
                            raise AssertionError(response["error"])
                        if "exceptionDetails" in response["result"]:
                            raise AssertionError(response["result"]["exceptionDetails"])
                        return response["result"]

                def evaluate(script):
                    return call("Runtime.evaluate", {"expression": script, "returnByValue": True,
                                                     "awaitPromise": True})["result"].get("value")

                def wait_for(script, timeout=5):
                    until = time.monotonic() + timeout
                    while not evaluate(script):
                        if time.monotonic() > until:
                            result["failure_state"] = evaluate("({uploadHidden:elements.uploadWorkspace.classList.contains('hidden'),fullscreen:document.fullscreenElement?.id,body:document.body.className,errors:window.__qa?.requests})")
                            screenshot("failure.png")
                            raise AssertionError(f"Timed out waiting for {script}")
                        time.sleep(.06)

                def click(selector):
                    point = evaluate("(()=>{const e=document.querySelector(" + json.dumps(selector)
                                     + ");if(!e)throw new Error('Missing click target');e.scrollIntoView({block:'nearest',behavior:'instant'});const b=e.getBoundingClientRect();return {x:b.x+b.width/2,y:b.y+b.height/2};})()")
                    call("Input.dispatchMouseEvent", {"type": "mousePressed", "button": "left", "clickCount": 1, **point})
                    call("Input.dispatchMouseEvent", {"type": "mouseReleased", "button": "left", "clickCount": 1, **point})
                    time.sleep(.12)

                def key(name, code):
                    call("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": name, "code": name, "windowsVirtualKeyCode": code})
                    call("Input.dispatchKeyEvent", {"type": "keyUp", "key": name, "code": name, "windowsVirtualKeyCode": code})
                    time.sleep(.14)

                def choose(identifier, value):
                    evaluate("(()=>{const e=document.getElementById(" + json.dumps(identifier)
                             + ");e.value=" + json.dumps(value) + ";e.dispatchEvent(new Event('change',{bubbles:true}));e.dispatchEvent(new Event('input',{bubbles:true}));return true;})()")
                    time.sleep(.12)

                def screenshot(name):
                    encoded = call("Page.captureScreenshot", {"format": "png"})
                    (OUTPUT / name).write_bytes(base64.b64decode(encoded["data"]))

                def viewport(width, height):
                    call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
                    time.sleep(.16)

                call("Runtime.enable")
                viewport(1366, 768)
                wait_for("typeof renderMaskPreview==='function'&&typeof elements!=='undefined'")
                fixture = deepcopy(specimen())
                evaluate("window.__associationFixture=" + json.dumps(fixture) + ";true")
                status_checks = evaluate(r'''(()=>{
const previous={attached:streamAttached,ready:streamReady};streamAttached=true;streamReady=true;
const base={inspection_status:'running',camera_status:'connected',model_status:'ready',segmenter_status:'ready',
model_info:{detector:{device:'cpu'},quality:{status:'ready'}},active_tracks:[],
live_frame_status:{camera_state:'active',ai_state:'running',capture_fps:29.2,processing_fps:4.8,capture_resolution:[640,480]}};
window.__qaLiveStatus=structuredClone(base);
renderCamera(base);
const running=elements.liveBadge.textContent==='INSPECTING'&&elements.feedFps.textContent.includes('29.2')&&elements.feedFps.textContent.includes('4.8');
base.live_frame_status.ai_state='paused';renderCamera(base);
const paused=elements.liveBadge.textContent==='PREVIEW'&&elements.feedFps.textContent.includes('AI: 0.0 FPS')&&elements.inspectionState.textContent.includes('paused');
base.live_frame_status.camera_state='stalled';base.live_frame_status.ai_state='waiting';renderCamera(base);
const stale=elements.liveBadge.textContent==='CAMERA STALLED'&&elements.feedFps.textContent.includes('Camera: 0.0 FPS')&&elements.placeholderCopy.textContent.includes('Stop inspection');
base.inspection_status='stopped';base.camera_status='disconnected';base.live_frame_status.camera_state='disconnected';base.live_frame_status.ai_state='stopped';renderCamera(base);
const stopped=elements.liveBadge.textContent==='STOPPED'&&elements.start.textContent==='Start inspection';
streamAttached=previous.attached;streamReady=previous.ready;
return {cameraAndAiRatesDistinct:running,previewDoesNotClaimInspection:paused,staleFramesShowRecoveryAndZeroRates:stale,stoppedCameraShowsStartAction:stopped};
})()''')
                result["checks"].update(status_checks)
                setup = evaluate(SETUP)
                checks = result["checks"]
                checks["dragDropSelectsMedia"] = setup["dropped"]
                checks["uploadCollapsesAfterSelection"] = setup["selected"] and setup["uploadToolbarHeight"] < 110
                checks["fullscreenControlsInsideActualViewers"] = setup["controlsInside"]
                checks["selectedFileVisible"] = setup["filename"] == "workspace-fixture.png"
                checks["selectedMediaHasThumbnail"] = evaluate("(()=>{const t=document.getElementById('upload-thumbnail');return !!t&&!t.classList.contains('hidden')&&t.src.startsWith('blob:');})()")
                time.sleep(.2)
                geometry = evaluate("window.__qa.snapshot('upload')")
                result["initial_upload"] = geometry
                split = evaluate("(()=>{const l=document.getElementById('upload-viewer-panel').getBoundingClientRect(),r=document.getElementById('upload-workspace-results').getBoundingClientRect();return {ratio:l.width/(l.width+r.width),viewerWidth:l.width,viewerHeight:elements.uploadMediaStage.clientHeight,rightLeft:r.left,leftRight:l.right};})()")
                result["initial_split"] = split
                checks["desktopViewerGetsAbout70Percent"] = .64 <= split["ratio"] <= .76
                checks["largeDesktopMediaViewer"] = split["viewerWidth"] >= 600 and split["viewerHeight"] >= 250
                checks["resultsBesideViewer"] = split["rightLeft"] >= split["leftRight"]

                click('#upload-fish-targets [data-fish-id="1"]')
                checks["imageSelectionOpensCorrectEvidence"] = evaluate("elements.maskPreviewFish.value==='1'&&elements.resultsGroups.querySelector('details[data-inspection-fish-id=\"1\"]').open")
                click('.result-grade-group[data-grade="Class B"] > summary')
                click('details[data-inspection-fish-id="2"] > summary')
                checks["resultSelectionHighlightsCorrectFish"] = evaluate("elements.maskPreviewFish.value==='2'&&elements.uploadFishTargets.dataset.selection==='2'")

                before_width = evaluate("document.getElementById('upload-viewer-panel').clientWidth")
                evaluate("document.getElementById('upload-workspace-splitter').focus();true")
                key("ArrowLeft", 37)
                after_width = evaluate("document.getElementById('upload-viewer-panel').clientWidth")
                checks["keyboardResizesPanels"] = after_width < before_width - 2
                point = evaluate("(()=>{const b=document.getElementById('upload-workspace-splitter').getBoundingClientRect();return {x:b.x+b.width/2,y:b.y+b.height/2};})()")
                call("Input.dispatchMouseEvent", {"type": "mousePressed", "button": "left", "clickCount": 1, **point})
                call("Input.dispatchMouseEvent", {"type": "mouseMoved", "button": "left", "buttons": 1, "x": point["x"] + 65, "y": point["y"]})
                call("Input.dispatchMouseEvent", {"type": "mouseReleased", "button": "left", "clickCount": 1, "x": point["x"] + 65, "y": point["y"]})
                time.sleep(.15)
                checks["pointerResizesPanels"] = evaluate("document.getElementById('upload-viewer-panel').clientWidth") > after_width + 20

                click('label:has(> #upload-display-masks)')
                wait_for("!elements.maskPreviewViewport.classList.contains('hidden')")
                fit = evaluate("window.__qa.snapshot('upload')")
                checks["fitShowsWholeUndistortedMaskImage"] = fit["canvas"]["width"] <= fit["stage"]["width"] + 2 and fit["canvas"]["height"] <= fit["stage"]["height"] + 2 and abs(fit["canvas"]["width"] / fit["canvas"]["height"] - 5 / 3) < .015
                choose("upload-viewer-fit-mode", "cover")
                fill = evaluate("window.__qa.snapshot('upload')")
                checks["fillCoversWithoutDistortion"] = fill["canvas"]["width"] >= fill["stage"]["width"] - 2 and fill["canvas"]["height"] >= fill["stage"]["height"] - 2 and abs(fill["canvas"]["width"] / fill["canvas"]["height"] - 5 / 3) < .015
                checks["maskViewerHasNoInternalScrollbars"] = evaluate("getComputedStyle(elements.maskPreviewViewport).overflow==='hidden'")
                choose("upload-mask-zoom", "2")
                pan_before = evaluate("({x:viewerTransforms.upload.x,y:viewerTransforms.upload.y})")
                point = evaluate("(()=>{const b=elements.uploadMediaStage.getBoundingClientRect();return {x:b.x+b.width*.5,y:b.y+b.height*.7};})()")
                call("Input.dispatchMouseEvent", {"type": "mousePressed", "button": "left", "clickCount": 1, **point})
                call("Input.dispatchMouseEvent", {"type": "mouseMoved", "button": "left", "buttons": 1, "x": point["x"] + 45, "y": point["y"] - 30})
                call("Input.dispatchMouseEvent", {"type": "mouseReleased", "button": "left", "clickCount": 1, "x": point["x"] + 45, "y": point["y"] - 30})
                pan_after = evaluate("({x:viewerTransforms.upload.x,y:viewerTransforms.upload.y,canvas:window.__qa.box(elements.maskPreviewCanvas),stage:window.__qa.box(elements.uploadMediaStage)})")
                checks["zoomedMaskCanvasPans"] = abs(pan_after["x"] - pan_before["x"]) > 20 and abs(pan_after["y"] - pan_before["y"]) > 15
                # Click a native source point projected through the actual canvas rectangle.
                # This exercises inverse hit testing after Fill, zoom and pan.
                native = evaluate("(()=>{const b=elements.maskPreviewCanvas.getBoundingClientRect();return {x:b.x+125/500*b.width,y:b.y+75/300*b.height,visible:b.y+75/300*b.height>=elements.uploadMediaStage.getBoundingClientRect().y};})()")
                if native["visible"]:
                    call("Input.dispatchMouseEvent", {"type": "mousePressed", "button": "left", "clickCount": 1, "x": native["x"], "y": native["y"]})
                    call("Input.dispatchMouseEvent", {"type": "mouseReleased", "button": "left", "clickCount": 1, "x": native["x"], "y": native["y"]})
                    time.sleep(.1)
                    checks["maskSelectionStaysAlignedAfterZoomPan"] = evaluate("elements.maskPreviewFish.value==='1'")
                else:
                    # At very wide stages the upper fish can be outside the crop;
                    # move it into view before testing the same inverse transform.
                    evaluate("viewerTransforms.upload.y=150;applyViewerTransform('upload');true")
                    native = evaluate("(()=>{const b=elements.maskPreviewCanvas.getBoundingClientRect();return {x:b.x+125/500*b.width,y:b.y+75/300*b.height};})()")
                    call("Input.dispatchMouseEvent", {"type": "mousePressed", "button": "left", "clickCount": 1, **native})
                    call("Input.dispatchMouseEvent", {"type": "mouseReleased", "button": "left", "clickCount": 1, **native})
                    time.sleep(.1)
                    checks["maskSelectionStaysAlignedAfterZoomPan"] = evaluate("elements.maskPreviewFish.value==='1'")
                result["mask_pan_selection"] = evaluate("({selected:elements.maskPreviewFish.value,canvas:window.__qa.box(elements.maskPreviewCanvas),stage:window.__qa.box(elements.uploadMediaStage),pan:viewerTransforms.upload})")
                result["mask_pan_selection"]["click"] = native
                screenshot("mask_zoom_pan_selection.png")
                click('#upload-fit-button')
                choose("upload-viewer-fit-mode", "contain")
                evaluate("elements.maskPreviewMeasurements.checked=true;elements.maskPreviewCracks.checked=true;elements.maskPreviewModel2.checked=true;elements.maskPreviewOpacity.value='25';renderMaskPreview();true")
                canvas_before = evaluate("elements.maskPreviewCanvas.toDataURL()")
                click('#upload-fullscreen-button')
                wait_for("document.fullscreenElement?.id==='upload-media-stage'")
                full = evaluate("({stage:window.__qa.box(elements.uploadMediaStage),width:innerWidth,height:innerHeight,unrelated:elements.uploadMediaStage.contains(document.elementFromPoint(10,10)),toolbar:window.__qa.box(document.getElementById('upload-fullscreen-button'))})")
                result["upload_fullscreen"] = full
                checks["actualViewerUsesNativeFullscreen"] = True
                checks["fullscreenOccupiesViewport"] = abs(full["stage"]["width"] - full["width"]) < 2 and abs(full["stage"]["height"] - full["height"]) < 2
                checks["fullscreenHidesUnrelatedUI"] = full["unrelated"]
                checks["fullscreenPreservesNativeOverlayPixels"] = evaluate("elements.maskPreviewCanvas.toDataURL()") == canvas_before
                checks["fullscreenPreservesInspectionControls"] = evaluate("elements.maskPreviewMeasurements.checked&&elements.maskPreviewCracks.checked&&elements.maskPreviewModel2.checked&&elements.maskPreviewOpacity.value==='25'")
                key("Tab", 9)
                checks["keyboardFocusRemainsInFullscreenViewer"] = evaluate("elements.uploadMediaStage.contains(document.activeElement)")
                screenshot("upload_fullscreen.png")
                key("Escape", 27)
                time.sleep(.25)
                checks["escapeExitsFullscreenKeepsWorkspace"] = evaluate("!document.fullscreenElement&&!elements.uploadWorkspace.classList.contains('hidden')")
                if evaluate("!!document.fullscreenElement"):
                    evaluate("document.exitFullscreen()")
                click('#upload-fullscreen-button')
                wait_for("document.fullscreenElement?.id==='upload-media-stage'")
                click('#upload-fullscreen-button')
                wait_for("!document.fullscreenElement")
                checks["minimizeRestoresLayout"] = evaluate("!elements.uploadWorkspace.classList.contains('hidden')&&document.getElementById('upload-workspace-results').getBoundingClientRect().width>0")

                for width, height in [(1366, 768), (1920, 1080), (1024, 700), (768, 1024), (390, 844)]:
                    viewport(width, height)
                    evaluate("elements.uploadWorkspace.scrollTop=0;true")
                    data = evaluate("({width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth,workspace:window.__qa.box(elements.uploadWorkspace),stage:window.__qa.box(elements.uploadMediaStage),results:window.__qa.box(document.getElementById('upload-workspace-results'))})")
                    result["viewports"][f"{width}x{height}"] = data
                    checks[f"responsive_{width}x{height}"] = data["scrollWidth"] <= data["width"] + 2 and data["stage"]["width"] > 200 and data["stage"]["height"] >= 160 and data["workspace"]["right"] <= width + 2
                    screenshot(f"upload_{width}x{height}.png")

                viewport(1366, 768)
                evaluate("toggleUpload(false);elements.placeholder.classList.add('hidden');elements.video.classList.remove('hidden');elements.video.src='/fixture-stream.mjpg';elements.liveMediaStage.classList.remove('hidden');true")
                wait_for("elements.video.naturalWidth===640")
                evaluate("latestStatus=structuredClone(window.__qaLiveStatus);latestStatus.active_tracks=[{track_id:1,bbox:[80,155,420,300],ai_final_grade:'Class B'}];latestStatus.live_frame_status.ai_state='paused';streamAttached=true;streamReady=true;renderCamera(latestStatus);true")
                source_before = evaluate("elements.video.getAttribute('src')")
                connections_before, frames_before = STREAM["connections"], STREAM["frames"]
                click('#live-fullscreen-button')
                wait_for("document.fullscreenElement?.id==='live-media-stage'")
                time.sleep(.35)
                checks["liveFullscreenKeepsStreamNodeAndSource"] = evaluate("elements.video===window.__qa.sourceNode&&elements.video.getAttribute('src')===" + json.dumps(source_before))
                checks["liveStreamNeverReconnectsOnFullscreen"] = STREAM["connections"] == connections_before
                checks["liveStreamFramesContinueInFullscreen"] = STREAM["frames"] > frames_before + 2
                live_fit = evaluate("window.__qa.snapshot('live')")
                result["live_fullscreen_fit"] = live_fit
                alignment = evaluate("window.__qa.alignment('live',[80,155,420,300])")
                checks["live640FitOverlayCoordinatesAligned"] = alignment["maxError"] < 2 and alignment["inverseError"] < 2
                choose("live-viewer-fit-mode", "cover")
                live_fill = evaluate("window.__qa.snapshot('live')")
                result["live_fullscreen_fill"] = live_fill
                checks["liveFitFillAvailable"] = live_fit["fit"] == "contain" and live_fill["fit"] == "cover"
                alignment = evaluate("window.__qa.alignment('live',[80,155,420,300])")
                checks["live640FillOverlayCoordinatesAligned"] = alignment["maxError"] < 2 and alignment["inverseError"] < 2
                screenshot("live_fullscreen_fill.png")
                key("Escape", 27)
                time.sleep(.2)
                checks["liveEscapeRestoresLayout"] = evaluate("!document.fullscreenElement")
                if evaluate("!!document.fullscreenElement"):
                    evaluate("document.exitFullscreen()")
                click('#live-fit-button')
                choose("live-viewer-zoom", "2")
                evaluate("viewerTransforms.live.x=45;viewerTransforms.live.y=30;applyViewerTransform('live');true")
                alignment = evaluate("window.__qa.alignment('live',[80,155,420,300])")
                checks["liveZoomPanOverlayCoordinatesAligned"] = alignment["maxError"] < 2 and alignment["inverseError"] < 2
                click('#live-fit-button')
                screenshot("live_1366x768.png")

                evaluate("(()=>{const c=document.createElement('canvas');c.width=1280;c.height=720;const p=c.getContext('2d');p.fillStyle='#cadfe2';p.fillRect(0,0,1280,720);p.fillStyle='#5f94a3';p.fillRect(260,220,600,180);latestStatus.active_tracks=[{track_id:1,bbox:[260,220,860,400],ai_final_grade:'Class B'}];elements.video.src=c.toDataURL();return true;})()")
                wait_for("elements.video.naturalWidth===1280")
                for fit_mode in ["contain", "cover"]:
                    choose("live-viewer-fit-mode", fit_mode)
                    alignment = evaluate("window.__qa.alignment('live',[260,220,860,400])")
                    checks[f"highResolution_{fit_mode}_OverlayAligned"] = alignment["maxError"] < 2 and alignment["inverseError"] < 2

                evaluate("window.__qa.settingsLoads=0;loadCameraCalibration=()=>{window.__qa.settingsLoads++;};true")
                click('#live-fullscreen-button')
                wait_for("document.fullscreenElement?.id==='live-media-stage'")
                click('#open-camera-controls')
                wait_for("!document.fullscreenElement&&elements.cameraCalibrationDrawer.classList.contains('open')")
                checks["cameraSettingsShortcutExitsFullscreenAndOpensControls"] = evaluate("window.__qa.settingsLoads===1")
                time.sleep(.25)  # Let the drawer's entrance transition settle before a trusted click.
                click('#close-camera-calibration-button')
                wait_for("!activePanel&&!elements.shell.inert")

                evaluate("window.__qa.actions=[];postControl=endpoint=>{window.__qa.actions.push(endpoint);};latestStatus.inspection_status='stopped';elements.start.disabled=false;true")
                click('#start-button')
                evaluate("latestStatus.inspection_status='running';true")
                click('#start-button')
                evaluate("window.confirm=()=>true;elements.reset.disabled=false;true")
                click('#reset-button')
                checks["startStopResetRouteToExistingEndpoints"] = evaluate("JSON.stringify(window.__qa.actions)===JSON.stringify(['/api/inspection/start','/api/inspection/stop','/api/session/reset'])")
                result["control_actions"] = evaluate("window.__qa.actions")

                click('#upload-mode-button')
                checks["analyzeMediaSecondaryActionOpensWorkspace"] = evaluate("!elements.uploadWorkspace.classList.contains('hidden')")
                checks["cachedEvidenceSurvivesFullscreenAndResponsiveChanges"] = evaluate("JSON.stringify(resultDatasets.upload.rows)===window.__qa.rowsBefore")
                checks["displayChangesNeverRunInference"] = evaluate("window.__qa.requests.length===0")
                checks["workingFeatureControlsPreserved"] = evaluate("['upload-display-boxes','upload-display-masks','upload-mask-opacity','upload-mask-fish','upload-mask-model1','upload-mask-model2','upload-mask-measurements','upload-mask-cracks','upload-association-debug','preview-mode-button','reset-button','start-button','open-camera-controls','live-camera-select','live-model-selector'].every(id=>document.getElementById(id))")
                video = evaluate(r'''(async()=>{
const c=document.createElement('canvas');c.width=1280;c.height=720;const p=c.getContext('2d'),stream=c.captureStream(12),parts=[];
const recording=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'});
recording.ondataavailable=e=>parts.push(e.data);const finished=new Promise(resolve=>recording.onstop=resolve);recording.start();
for(let frame=0;frame<12;frame++){p.fillStyle='#cbe0e5';p.fillRect(0,0,1280,720);p.fillStyle='#398a9e';p.fillRect(120+frame*15,230,640,190);await new Promise(resolve=>setTimeout(resolve,85));}
recording.stop();await finished;stream.getTracks().forEach(track=>track.stop());
setUploadSelection(new File(parts,'preview-fixture.webm',{type:'video/webm'}));
await new Promise(resolve=>elements.uploadVideo.readyState>=2?resolve():elements.uploadVideo.addEventListener('loadeddata',resolve,{once:true}));
elements.uploadVideo.loop=true;await elements.uploadVideo.play();return {width:elements.uploadVideo.videoWidth,height:elements.uploadVideo.videoHeight};
})()''')
                checks["videoMediaPreviewsAtNativeResolution"] = video == {"width": 1280, "height": 720}
                time_before = evaluate("elements.uploadVideo.currentTime")
                click('#upload-fullscreen-button')
                wait_for("document.fullscreenElement?.id==='upload-media-stage'")
                time.sleep(.18)
                checks["videoPlaybackContinuesInFullscreen"] = evaluate("!elements.uploadVideo.paused&&elements.uploadVideo.currentTime!==" + str(time_before))
                choose("upload-viewer-fit-mode", "cover")
                checks["videoFillMaintainsAspectMode"] = evaluate("getComputedStyle(elements.uploadVideo).objectFit==='cover'")
                screenshot("video_fullscreen.png")
                key("Escape", 27)
                checks["videoEscapeKeepsMediaSelected"] = evaluate("!document.fullscreenElement&&selectedUpload.name==='preview-fixture.webm'")
                checks["videoDisplayDoesNotRunInference"] = evaluate("window.__qa.requests.length===0")
                result["chrome"] = call("Browser.getVersion")["product"]
                result["stream"] = dict(STREAM)
                result["requests"] = evaluate("window.__qa.requests")
                result["runtime_errors"] = runtime_errors
                checks["noRuntimeExceptions"] = not runtime_errors
                (OUTPUT / "camera_workspace_browser.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                print(json.dumps(result, indent=2))
                assert all(checks.values()), {key: value for key, value in checks.items() if not value}
            process.terminate()
            process.wait(timeout=15)
            process = None
    except Exception:
        (OUTPUT / "camera_workspace_browser.partial.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        raise
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=15)
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    main()
