"""Exercise real frontend DOM/canvas in Chrome using recorded software fixtures.

No application server, detector, segmentation model, or inference endpoint is
started. Only the API polling bootstrap is omitted; UI code and handlers are
served unchanged. This verifies display behavior, not anatomical accuracy.
Run explicitly from the project root with Python and Chrome installed.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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

from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_anatomical_debug_ui import specimen


OUTPUT = ROOT / "results/qa/additional/ui"
BOOTSTRAP = "initializeLanSecurity(); void loadModelSelector(); void loadResultsDashboard(); setInterval(getStatus, 900); setInterval(loadResultsDashboard, 2500);"


class StaticFrontend(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        files = {"/": ("index.html", "text/html"), "/assets/app.js": ("app.js", "text/javascript"),
                 "/assets/styles.css": ("styles.css", "text/css")}
        if path not in files:
            self.send_error(404); return
        name, mime = files[path]
        source = (ROOT / "frontend" / name).read_text(encoding="utf-8")
        if name == "app.js":
            assert source.count(BOOTSTRAP) == 1, "Frontend bootstrap changed; update isolated UI smoke"
            source = source.replace(BOOTSTRAP, "/* API polling disabled in isolated model-free UI smoke. */")
        value = source.encode("utf-8")
        self.send_response(200); self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(value))); self.end_headers(); self.wfile.write(value)

    def log_message(self, *_args):
        pass


EXERCISE = r'''(async()=>{
const checks={},fixture=window.__associationFixture,delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let requests=0;window.fetch=async()=>{requests++;throw new Error('No API calls allowed in display-only smoke');};
const source=document.createElement('canvas');source.width=500;source.height=300;const pen=source.getContext('2d');
pen.fillStyle='#f1f4f5';pen.fillRect(0,0,500,300);pen.fillStyle='#adb8c4';
for(const x of [15,265]){pen.beginPath();pen.ellipse(x+105,75,105,30,0,0,2*Math.PI);pen.fill();}
fixture.preview_image=source.toDataURL();const file=new File(['software fixture'],'recorded-ui-fixture.png',{type:'image/png'});
toggleUpload(true);selectedUpload=file;elements.uploadImage.src=fixture.preview_image;
elements.uploadImage.classList.remove('hidden');elements.uploadVideo.classList.add('hidden');
const fish=fixture.fish.map(item=>({...structuredClone(item),quality:'Class B',analysis:{...structuredClone(item.analysis||{}),
 segmentation:structuredClone(item.segmentation),final_grade:'Class B',weighted_scores:{'Class B':.8}}}));
resultsSource='upload';renderResultsDashboard(fish,{source:'upload',complete:true,scope:'association-ui-fixture',metadata:{source_name:'Software UI fixture'}});
mountResultsDashboard(true);elements.uploadResults.classList.remove('hidden');
await acceptAutomaticMaskPreview({fish,segmentation_preview:fixture},file);
const before=JSON.stringify(resultDatasets.upload.rows),original=elements.uploadImage.src,canvas=elements.maskPreviewCanvas;
checks.defaultUnchanged=elements.maskPreviewBoxes.checked&&!elements.maskPreviewMasks.checked&&!elements.maskPreviewAssociation.checked
 &&!elements.uploadImage.classList.contains('hidden')&&elements.maskPreviewViewport.classList.contains('hidden');
checks.allControlsRemain=['upload-mask-opacity','upload-mask-fish','upload-mask-zoom','upload-mask-model1','upload-mask-model2','upload-mask-show','upload-mask-cracks','upload-mask-legend','upload-mask-loading','upload-mask-cancel'].every(id=>document.getElementById(id));
elements.maskPreviewAssociation.click();await delay(20);
checks.highlightRequired=elements.maskPreviewAssociationStatus.textContent.includes('Highlight one Fish ID');
selectInspectionFish(1,{revealCard:true});await delay(30);const diagnostic=canvas.toDataURL();
checks.debugInMainViewer=elements.uploadMediaStage.contains(canvas)&&!elements.maskPreviewViewport.classList.contains('hidden')&&elements.uploadImage.classList.contains('hidden');
const card=elements.resultsGroups.querySelector('details[data-inspection-fish-id="1"]');
const section=[...card.querySelectorAll('details')].find(item=>item.querySelector('summary')?.textContent==='Anatomical Association Debug View');
section.open=true;section.dispatchEvent(new Event('toggle'));await delay(30);
checks.perFishReasons=section.textContent.includes('part_not_contained')&&section.textContent.includes('competing_parent_scores')&&section.textContent.includes('candidate only here');
checks.debugLegend=elements.maskPreviewAssociationLegend.children.length===4&&!elements.maskPreviewAssociationLegend.classList.contains('hidden');
elements.maskPreviewAssociation.click();await delay(20);
checks.originalRestored=elements.uploadImage.src===original&&!elements.uploadImage.classList.contains('hidden')&&elements.maskPreviewViewport.classList.contains('hidden');
elements.maskPreviewMasks.click();await delay(30);const masks=canvas.toDataURL();
checks.maskToggleStillWorks=!elements.maskPreviewViewport.classList.contains('hidden')&&elements.maskPreviewMasks.checked&&!elements.maskPreviewBoxes.checked&&masks!==diagnostic;
elements.maskPreviewOpacity.value='20';elements.maskPreviewOpacity.dispatchEvent(new Event('input'));checks.opacityStillWorks=canvas.toDataURL()!==masks;
elements.maskPreviewZoom.value='2';elements.maskPreviewZoom.dispatchEvent(new Event('input'));checks.zoomStillWorks=canvas.style.width==='200%';
elements.maskPreviewOpacity.value='40';elements.maskPreviewOpacity.dispatchEvent(new Event('input'));
elements.maskPreviewModel1.checked=false;elements.maskPreviewModel1.dispatchEvent(new Event('input'));const noBoxes=canvas.toDataURL();
elements.maskPreviewModel1.checked=true;elements.maskPreviewModel1.dispatchEvent(new Event('input'));checks.model1StillWorks=canvas.toDataURL()!==noBoxes;
const noParts=canvas.toDataURL();elements.maskPreviewModel2.checked=true;elements.maskPreviewModel2.dispatchEvent(new Event('input'));checks.model2StillWorks=canvas.toDataURL()!==noParts;
const noCracks=canvas.toDataURL();elements.maskPreviewCracks.checked=true;elements.maskPreviewCracks.dispatchEvent(new Event('input'));checks.structuralControlStillWorks=canvas.toDataURL()!==noCracks;
const visibleMasks=canvas.toDataURL();elements.maskPreviewShow.checked=false;elements.maskPreviewShow.dispatchEvent(new Event('input'));checks.maskVisibilityStillWorks=canvas.toDataURL()!==visibleMasks;
elements.maskPreviewShow.checked=true;elements.maskPreviewShow.dispatchEvent(new Event('input'));selectInspectionFish(2,{revealCard:true});
checks.highlightStillWorks=canvas.toDataURL()!==visibleMasks;
selectInspectionFish(1,{revealCard:true});await delay(40);
checks.staleDisclosureDoesNotChangeSelection=elements.maskPreviewFish.value==='1';
checks.reviewIndicators=elements.maskPreviewLegend.children.length===2;
const NativeImage=window.Image;
window.Image=class extends NativeImage{set src(value){setTimeout(()=>{super.src=value;},300);}get src(){return super.src;}};
uploadMaskPreview.image=null;const preparing=setMainViewerMode('masks');await delay(140);
checks.loadingStillWorks=!elements.maskPreviewLoading.classList.contains('hidden')&&elements.maskPreview.getAttribute('aria-busy')==='true'&&/Preparing.*[0-9]+\.[0-9]s/.test(elements.maskPreviewStatus.textContent);
await preparing;window.Image=NativeImage;
checks.preparedViewAutoDisplays=!elements.maskPreviewViewport.classList.contains('hidden')&&elements.maskPreviewLoading.classList.contains('hidden');
checks.noGradingMutation=JSON.stringify(resultDatasets.upload.rows)===before;
checks.noFetch=requests===0;
elements.maskPreviewZoom.value='1';elements.maskPreviewZoom.dispatchEvent(new Event('input'));
selectInspectionFish(1);elements.maskPreviewAssociation.click();
window.__debugScreenshot=()=>{elements.maskPreview.scrollIntoView({block:'start'});return true;};
window.__clearDebugForNewAnalysis=()=>{clearMaskPreview();return !elements.maskPreviewAssociation.checked&&uploadMaskPreview.data===null&&elements.maskPreviewCanvas.width===0;};
return {checks,fetch_calls:requests,scope:'Real Chrome frontend/DOM/canvas with synthetic native-pixel fixtures; no neural models or API inference; not an anatomical-accuracy test'};
})()'''


def main():
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.is_file():
        raise RuntimeError("Chrome is unavailable")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), StaticFrontend)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); cdp_port = sock.getsockname()[1]
    hidden = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix="tamban_anatomical_ui_", ignore_cleanup_errors=True) as directory:
            args = [str(chrome), "--headless=new", "--disable-gpu", "--no-first-run",
                    f"--user-data-dir={directory}", f"--remote-debugging-port={cdp_port}",
                    "--remote-allow-origins=*", "--window-size=1440,1100"]
            if os.getenv("TAMBAN_CHROME_NO_SANDBOX", "").lower() in {"1", "true", "yes", "on"}:
                args.append("--no-sandbox")
            process = subprocess.Popen([*args, f"http://127.0.0.1:{server.server_port}/"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
            deadline = time.monotonic() + 20
            while True:
                try:
                    with urlopen(f"http://127.0.0.1:{cdp_port}/json", timeout=1) as response:
                        page = next(item for item in json.load(response) if item.get("type") == "page")
                    break
                except (OSError, StopIteration):
                    if time.monotonic() > deadline: raise RuntimeError("Chrome debug page did not start")
                    time.sleep(.1)
            with connect(page["webSocketDebuggerUrl"], open_timeout=5, max_size=8 * 1024 * 1024) as websocket:
                counter = 0

                def call(method, params=None):
                    nonlocal counter
                    counter += 1
                    websocket.send(json.dumps({"id": counter, "method": method, "params": params or {}}))
                    while True:
                        response = json.loads(websocket.recv(timeout=30))
                        if response.get("id") != counter: continue
                        if "error" in response: raise AssertionError(response["error"])
                        if "exceptionDetails" in response["result"]: raise AssertionError(response["result"]["exceptionDetails"])
                        return response["result"]

                def evaluate(script):
                    return call("Runtime.evaluate", {"expression": script, "returnByValue": True,
                                                     "awaitPromise": True})["result"].get("value")

                for _ in range(100):
                    if evaluate("typeof renderAnatomicalAssociationDebug==='function'&&typeof elements!=='undefined'"): break
                    time.sleep(.1)
                else: raise AssertionError("Frontend did not initialize")
                fixture = deepcopy(specimen())
                fixture["fish"][0]["analysis"]["surface_damage"] = {
                    "status": "suspected", "coordinate_space": "original_frame", "frame_id": "native-source",
                    "parent_track_id": 1, "locations": [{"x": 60, "y": 82, "width": 60, "height": 4}]}
                evaluate("window.__associationFixture=" + json.dumps(fixture) + ";true")
                result = evaluate(EXERCISE)
                (OUTPUT / "anatomical_debug_browser.partial.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                assert all(result["checks"].values()), result["checks"]
                evaluate("window.__debugScreenshot()")
                screenshot = call("Page.captureScreenshot", {"format": "png"})
                (OUTPUT / "anatomical_debug_desktop.png").write_bytes(base64.b64decode(screenshot["data"]))
                call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
                evaluate("window.__debugScreenshot()")
                mobile = evaluate("({width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth})")
                screenshot = call("Page.captureScreenshot", {"format": "png"})
                (OUTPUT / "anatomical_debug_mobile.png").write_bytes(base64.b64decode(screenshot["data"]))
                result["checks"]["mobileNoHorizontalOverflow"] = mobile["scrollWidth"] <= mobile["width"] + 2
                result["checks"]["newAnalysisClearsDebug"] = evaluate("window.__clearDebugForNewAnalysis()")
                result["mobile"] = mobile
                result["chrome"] = call("Browser.getVersion")["product"]
                assert all(result["checks"].values()), result["checks"]
                (OUTPUT / "anatomical_debug_browser.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                print(json.dumps(result, indent=2))
            process.terminate(); process.wait(timeout=15); process = None
    finally:
        if process is not None:
            process.terminate(); process.wait(timeout=15)
        server.shutdown(); server.server_close(); thread.join(timeout=3)


if __name__ == "__main__":
    main()
