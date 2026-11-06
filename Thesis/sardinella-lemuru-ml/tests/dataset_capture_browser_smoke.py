"""Real Chrome capture interactions against a synthetic, checkpoint-free API.

Run explicitly, never against a live camera/account. All files, browser profiles,
captures, screenshots and reports are written outside the repository.
"""
from __future__ import annotations

import argparse
import base64
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


EXERCISE = r'''(async()=>{
const $=id=>document.getElementById('dc-'+id),delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(test,label,timeout=15000){const end=Date.now()+timeout;while(!test()){if(Date.now()>end)throw new Error(label+' timed out: '+$('feedback').textContent);await delay(75);}}
const checks={};
await until(()=>$('create-session')&&!$('create-session').disabled,'Capture initialization');
checks.noAutoInitially=$('run-state').textContent==='idle'&&$('snapshot').disabled;
$('session-name').value='Synthetic browser collection';$('batch').value='batch-fixture';$('specimen').value='specimen-one';$('specimen-confirmed').checked=true;
$('metadata-form').requestSubmit();await until(()=>$('session-select').value&&$('feedback').textContent.includes('created'),'Create session');
$('camera-open').click();await until(()=>!$('snapshot').disabled,'Open synthetic camera');
await until(()=>$('preview').naturalWidth>0,'Raw preview');
checks.readbacksTruth=$('readback-size').textContent==='960 × 640 px'&&$('readback-device').textContent.includes('synthetic');
$('snapshot').click();await until(()=>$('count-manual').textContent==='1'&&!$('snapshot').disabled,'First manual photo');
$('snapshot').click();await until(()=>$('count-manual').textContent==='2'&&document.querySelectorAll('.dc-photo').length===2,'Second manual photo');
const id=encodeURIComponent($('session-select').value),initial=await(await fetch('/api/capture/sessions/'+id+'/items')).json();
checks.twoFreshManualPhotos=initial.items.length===2&&new Set(initial.items.map(item=>item.frame_id)).size===2&&new Set(initial.items.map(item=>item.sha256)).size===2&&initial.items.every(item=>item.capture_mode==='manual');
checks.localQueuedTruth=$('feedback').textContent.includes('Saved locally')&&$('feedback').textContent.includes('Queued')&&$('drive-sync').disabled;
$('grid-toggle').click();checks.gridPreviewOnly=!$('grid').hidden&&initial.items.every(item=>item.width===960&&item.height===640);
$('notes').focus();const before=$('count-manual').textContent;$('notes').dispatchEvent(new KeyboardEvent('keydown',{code:'Space',key:' ',bubbles:true}));await delay(180);checks.typingShortcutSafe=$('count-manual').textContent===before;
$('notes').blur();document.body.dispatchEvent(new KeyboardEvent('keydown',{code:'Space',key:' ',bubbles:true,cancelable:true}));await until(()=>$('count-manual').textContent==='3','Keyboard manual shutter');
$('countdown').value='5';$('duration').value='5';$('interval').value='1';$('target').value='custom';$('target').dispatchEvent(new Event('change'));$('custom-count').value='3';$('run-start').click();
await until(()=>$('run-state').textContent==='countdown','Five-second countdown');
checks.countdownAndDurationDistinct=$('countdown-state').textContent.includes('First shot')&&$('duration').value==='5';
await until(()=>$('run-state').textContent==='completed','Automatic target',14000);
await until(()=>Number($('count-frames').textContent)===6&&document.querySelectorAll('.dc-photo').length===6,'Automatic gallery');
const all=await(await fetch('/api/capture/sessions/'+id+'/items')).json();
checks.autoThreeFresh=all.items.filter(item=>item.capture_mode==='automatic').length===3&&new Set(all.items.map(item=>item.frame_id)).size===6;
checks.separateFishCount=$('count-specimens').textContent==='1'&&$('count-frames').textContent==='6';
$('select-all').click();$('bulk-review').value='exclude';$('bulk-save').click();await until(()=>document.querySelectorAll('.dc-photo[data-excluded="true"]').length===6,'Non-destructive review');
const reviewed=await(await fetch('/api/capture/sessions/'+id+'/items')).json();checks.rawRetainedAfterExclude=reviewed.items.length===6&&reviewed.items.every(item=>item.metadata.review_state==='exclude');
document.querySelector('.dc-photo-open').click();await until(()=>$('viewer').open&&$('viewer-image').naturalWidth===960,'Native original viewer');
checks.nativeViewer=$('viewer-details').textContent.includes('SHA-256')&&$('viewer-details').textContent.includes('960 × 640');
$('viewer-close').click();
for(const format of ['csv','json','zip']){const response=await fetch('/api/capture/sessions/'+id+'/export?format='+format);checks[format+'Export']=response.ok&&(await response.arrayBuffer()).byteLength>0;}
checks.soundFlashOptIn=!$('sound-toggle').checked&&!$('flash-toggle').checked;
checks.manualButtonAccessible=$('snapshot').textContent.includes('Capture Photo')&&$('snapshot').getAttribute('aria-describedby')==='dc-manual-help';
checks.noInspectionBootstrap=!document.querySelector('script[src*="/app.js"]')&&window.TambanInspection===undefined;
checks.noFakeDriveSuccess=!$('drive-state').textContent.includes('Connected')&&$('drive-message').textContent.includes('server');
$('camera-close').click();await until(()=>$('snapshot').disabled&&$('camera-state').textContent==='Camera closed','Capture camera close');
return {checks,photos:all.items.length,scope:'Real Chrome DOM with synthetic camera/API and local temporary storage. No hardware camera, trained models or Google Drive requests.'};
})()'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = (args.output or Path(tempfile.mkdtemp(prefix="tamban-capture-browser-"))).resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("Browser evidence must stay outside the repository")
    output.mkdir(parents=True, exist_ok=True)
    # No inherited production camera, database, OAuth or model configuration.
    for name in list(os.environ):
        if name.startswith(("FISH_", "LEMURU_", "EXPERT_LIBRARY_")):
            os.environ.pop(name)

    import cv2
    import numpy as np
    import uvicorn
    from websockets.sync.client import connect
    from src.api.capture_app import create_capture_app
    from src.api.dataset_capture.camera_source import FramePacket
    from src.api.dataset_capture.router import CaptureContext
    from src.api.dataset_capture.service import DatasetCaptureService
    from src.api.dataset_capture.storage import CaptureStore

    class SyntheticSource:
        def __init__(self, **_config):
            self.counter = 0
        def start(self):
            return {"width": 960, "height": 640, "device_index": 0, "backend": "synthetic", "camera_fps": 20.0}
        def read(self):
            self.counter += 1
            frame = np.full((640, 960, 3), (205, 215, 202), dtype=np.uint8)
            cv2.ellipse(frame, (480, 320), (245, 80), -12, 0, 360, (120, 155, 165), -1)
            cv2.line(frame, (265, 365), (130, 295), (90, 120, 135), 32)
            cv2.putText(frame, f"SYNTHETIC FRAME {self.counter}", (32, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (35, 65, 45), 2)
            return FramePacket(frame, self.counter, time.monotonic(), "browser-synthetic-generation", readbacks={"backend": "synthetic", "camera_fps": 20.0})
        def close(self):
            pass

    class OfflineOAuth:
        def status(self):
            return {"oauth_configured": False, "connected": False}
        def close(self):
            pass

    store = CaptureStore(output / "capture-data")
    service = DatasetCaptureService(store, source_factory=SyntheticSource)
    context = CaptureContext(output / "capture-data", service=service, store=store, oauth=OfflineOAuth())
    application = create_capture_app(context)
    listener = socket.socket(); listener.bind(("127.0.0.1", 0)); listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", log_level="error", access_log=False))
    thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True); thread.start()
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.is_file():
        raise RuntimeError("Chrome is unavailable; browser validation not performed")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); cdp_port = sock.getsockname()[1]
    process = None
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("Synthetic capture API failed to start")
            time.sleep(.05)
        with tempfile.TemporaryDirectory(prefix="tamban-capture-chrome-", ignore_cleanup_errors=True) as profile:
            command = [str(chrome), "--headless=new", "--disable-gpu", "--no-first-run",
                       f"--user-data-dir={profile}", f"--remote-debugging-port={cdp_port}", "--remote-allow-origins=*", "--window-size=1440,1100"]
            if os.getenv("TAMBAN_CHROME_NO_SANDBOX", "").lower() in {"1", "true", "yes", "on"}:
                command.append("--no-sandbox")
            process = subprocess.Popen([*command, f"http://127.0.0.1:{port}/capture"], stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            deadline = time.monotonic() + 20
            while True:
                try:
                    with urlopen(f"http://127.0.0.1:{cdp_port}/json", timeout=1) as response:
                        page = next(item for item in json.load(response) if item.get("type") == "page")
                    break
                except (OSError, StopIteration):
                    if time.monotonic() > deadline:
                        raise RuntimeError("Chrome debug page failed to start")
                    time.sleep(.1)
            with connect(page["webSocketDebuggerUrl"], open_timeout=5, max_size=12 * 1024 * 1024) as websocket:
                counter = 0
                def call(method, params=None):
                    nonlocal counter
                    counter += 1
                    websocket.send(json.dumps({"id": counter, "method": method, "params": params or {}}))
                    while True:
                        response = json.loads(websocket.recv(timeout=45))
                        if response.get("id") != counter:
                            continue
                        if "error" in response or "exceptionDetails" in response.get("result", {}):
                            raise AssertionError(response)
                        return response["result"]
                def evaluate(expression):
                    return call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})["result"].get("value")
                for _ in range(120):
                    if evaluate("typeof window.TambanCapture==='object'"):
                        break
                    time.sleep(.05)
                else:
                    raise RuntimeError("Capture UI failed to initialize")
                result = evaluate(EXERCISE)
                (output / "capture-browser.partial.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                assert all(result["checks"].values()), result["checks"]
                evaluate("window.scrollTo(0,0)")
                (output / "capture-desktop.png").write_bytes(base64.b64decode(call("Page.captureScreenshot", {"format": "png"})["data"]))
                call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
                evaluate("window.scrollTo(0,0)")
                mobile = evaluate("({width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth,shutterWidth:document.getElementById('dc-snapshot').getBoundingClientRect().width})")
                result["mobile"] = mobile
                result["checks"]["mobileNoHorizontalOverflow"] = mobile["scrollWidth"] <= mobile["width"] + 2
                result["checks"]["mobileShutterUsable"] = mobile["shutterWidth"] >= 280
                (output / "capture-mobile.png").write_bytes(base64.b64decode(call("Page.captureScreenshot", {"format": "png"})["data"]))
                result["chrome"] = call("Browser.getVersion")["product"]
                result["output"] = str(output)
                (output / "capture-browser.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                assert all(result["checks"].values()), result["checks"]
                print(json.dumps(result, indent=2))
    finally:
        if process is not None:
            process.terminate(); process.wait(timeout=15)
        server.should_exit = True; thread.join(timeout=10)
        listener.close()
        context.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
