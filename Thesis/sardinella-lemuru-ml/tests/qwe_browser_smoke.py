"""Real Chrome checks for grade colors, fish zoom and persisted analytics.

The frontend is served unchanged except for omitting its live-camera polling
bootstrap. Analytics/history requests read a temporary, actual SQLite database;
media evidence is a deterministic native-pixel software fixture. No detector,
segmenter, grading engine, trained model, or hardware camera is run.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from http.server import ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
from threading import Thread
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

from PIL import Image
from websockets.sync.client import connect

import camera_workspace_browser_smoke as browser
from src.api.database import InspectionDatabase
from src.api.export import DEFAULT_EXPORT_FIELDS, make_csv


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "results/qa/qwe_workspace"
GRADES = ["Class A", "Class B", "Class C", "Rejected", "Ungraded"]
COLORS = {"Class A": "#087664", "Class B": "#175cba", "Class C": "#b54d0a", "Rejected": "#b52e40", "Ungraded": "#546c7a"}


def populate(database):
    """Create real saved records, including repeat observations and a shared ID."""
    sessions = [
        ("qwe-morning", "2026-11-01T09:00:00-05:00", "2026-11-01T09:02:00-05:00", ["Class A", "Class B", "Ungraded", "Class A"]),
        ("qwe-afternoon", "2026-11-02T14:00:00-05:00", "2026-11-02T14:01:00-05:00", ["Class C", "Rejected", "Ungraded"]),
        ("qwe-empty", "2026-11-03T10:00:00-05:00", "2026-11-03T10:01:00-05:00", []),
    ]
    for session, started, ended, grades in sessions:
        database.create_session({"started_at": started}, session_id=session)
        for identity, grade in enumerate(grades, 1):
            event = {"track_id": identity, "timestamp": started, "quality": grade,
                     "ai_final_grade": grade, "quality_confidence": .8 if grade != "Ungraded" else None,
                     "detector_confidence": .7 + identity * .03, "processing_time_ms": 15 + identity,
                     "analysis": {"final_grade": grade, "final_score": .8 if grade != "Ungraded" else None,
                        "verdict_status": "NEEDS_REVIEW" if grade == "Ungraded" else "AUTO_GRADED",
                        "reason_codes": ["UG_MISSING_HEAD"] if grade == "Ungraded" else [],
                        "observed_regions": ["Body"] if grade == "Ungraded" else ["Head", "Body", "Tail"],
                        "part_results": {region: {"present": grade != "Ungraded" or region == "Body"} for region in ["Head", "Body", "Tail"]},
                        "performance": {"model1_inference_ms": 4, "model2_inference_ms": 8, "total_processing_ms": 15 + identity,
                                        "processing_fps": 0 if identity == 4 else 3 + identity / 10, "capture_fps": 28 + identity / 10,
                                        "image_processing_time_ms": 25 + identity},
                        "model2_debug": {"raw_detections": [{"region": "Head"}, {"region": "Body"}, {"region": "Tail"}],
                                         "selected_detections": [{"region": "Body"}] if grade == "Ungraded" else [{"region": "Head"}, {"region": "Body"}, {"region": "Tail"}]}}}
            event["timestamp"] = started.replace(":00-05:00", f":{identity * 10:02d}-05:00")
            if identity == 1:
                # A second observation updates the same composite identity.
                database.upsert_event(session, {**deepcopy(event), "quality": "Ungraded", "ai_final_grade": "Ungraded", "analysis": {"final_grade": "Ungraded"}})
            database.upsert_event(session, event)
        database.checkpoint_session_activity(session, active_seconds=120 if session == "qwe-morning" else 60, status="active")
        database.end_session(session, ended_at=ended)


def media_fixture():
    source = {"frame_id": "qwe-native-source", "frame_width_px": 1000, "frame_height_px": 640}
    positions = [
        (1, "Class A", [35, 70, 275, 180]), (2, "Class B", [350, 70, 600, 180]),
        (3, "Class C", [680, 70, 920, 180]), (4, "Rejected", [35, 350, 275, 460]),
        (5, "Ungraded", [350, 300, 450, 570]), (6, "Class A", [580, 310, 880, 560]),
        (7, "Class B", [650, 350, 900, 500]),
    ]
    fish = []
    for identity, grade, box in positions:
        left, top, right, bottom = box
        width, height = right - left, bottom - top
        cx, cy = (left + right) / 2, (top + bottom) / 2
        contour = ([[cx, top], [right, top + height * .2], [cx, bottom], [left, top + height * .2]] if identity == 5 else
                   [[left, top + 30], [left + 50, top], [right, bottom - 30], [right - 50, bottom]] if identity == 6 else
                   [[left, cy], [left + width * .2, top], [right, cy], [left + width * .2, bottom]])
        segmentation = {"backend": "mobilesam_experimental", "preview_usable": True, "parent_track_id": identity,
                        "ownership_status": "checks_passed_unvalidated" if identity == 5 else "ambiguous",
                        "engineering_checks_passed": identity == 5, "used_for_grading": False,
                        "reasons": [] if identity == 5 else ["candidate_ownership_unvalidated"],
                        "mask_overlay": {"coordinate_space": "original_frame", **source,
                                         "contours": [contour], "conflict_contours": []}}
        fish.append({"id": identity, "track_id": identity, "bbox": box, "quality": "Class A" if grade == "Ungraded" else grade,
                     "ai_final_grade": grade, "detector_confidence": .99, "segmentation": segmentation,
                     "parts": [{"region": "Body", "bbox": [left + width * .25, top + height * .25, right - width * .25, bottom - height * .25], "parent_track_id": identity, "coordinate_space": "original_frame"}],
                     "analysis": {"final_grade": grade, "segmentation": segmentation,
                         "fish_geometry": {"status": "unreliable", "used_for_grading": False, "measurement_validated": False,
                            "candidate_measurements": {"fish_length_px": width, "max_body_width_px": height},
                            "candidate_visualization": {"coordinate_space": "original_frame", **source,
                                "parent_track_id": identity, "source_parent_id": identity, "status": "estimated",
                                "length_path": [[left, cy], [right, cy]], "width_axis": [[cx, top], [cx, bottom]],
                                "principal_axis": [[left, cy], [right, cy]], "reasons": ["experimental_mask_requires_ownership_validation"]}},
                         "surface_damage": {"status": "suspected", "coordinate_space": "original_frame", **source,
                            "parent_track_id": identity, "source_parent_id": identity, "validation_status": "unvalidated",
                            "severity": "unassessed", "used_for_grading": False,
                            "locations": [{"x": cx - 15, "y": cy - 2, "width": 30, "height": 4}]}}})
    return {"status": "generated", "source": source, "fish": fish}


class FixtureServer(browser.Frontend):
    database = None
    requests = []

    def send_json(self, value, status=200):
        encoded = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        url = urlsplit(self.path)
        if not url.path.startswith("/api/"):
            return super().do_GET()
        self.requests.append(self.path)
        query = {key: values[-1] for key, values in parse_qs(url.query).items()}
        try:
            if url.path == "/api/analytics":
                value = self.database.dashboard_analytics(**{key: query[key] for key in ["range_name", "session_id", "start_date", "end_date", "granularity"] if key in query})
                return self.send_json({"analytics_v2": value, **value})
            if url.path == "/api/sessions":
                page, size = int(query.get("page", 1)), int(query.get("page_size", query.get("limit", 1000)))
                rows, total = self.database.sessions_page(page=page, page_size=size, **{key: query.get(key) for key in ["search", "start_date", "end_date", "session_id"]})
                return self.send_json({"items": rows, "total": total, "page": page, "page_size": size, "total_pages": max(1, math.ceil(total / size))})
            if url.path == "/api/history":
                page, size = int(query.get("page", 1)), int(query.get("page_size", 25))
                rows, total = self.database.events_page(page=page, page_size=size, session_id=query.get("session_id"), range_name=query.get("range_name", "all"),
                    start_date=query.get("start_date"), end_date=query.get("end_date"), search=query.get("search"), grade=query.get("grade"),
                    feature=query.get("feature"), min_confidence=float(query["min_confidence"]) if query.get("min_confidence") else None,
                    verdict=query.get("verdict"), track_id=int(query["track_id"]) if query.get("track_id") else None,
                    reason_code=query.get("reason_code"), evidence_region=query.get("evidence_region"))
                return self.send_json({"items": rows, "total": total, "page": page, "page_size": size, "total_pages": max(1, math.ceil(total / size))})
            self.send_json({"detail": "Unexpected API request in browser fixture"}, 404)
        except Exception as error:
            self.send_json({"detail": str(error)}, 500)

    def do_POST(self):
        self.requests.append(self.path)
        if self.path != "/api/export":
            return self.send_json({"detail": "Inference requests are forbidden in this test"}, 409)
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        rows = self.database.events(session_id=payload.get("session_id"))
        if payload.get("track_ids"):
            rows = [row for row in rows if row["track_id"] in payload["track_ids"]]
        encoded = make_csv(rows, DEFAULT_EXPORT_FIELDS)
        self.send_response(200)
        self.send_header("Content-Type", "text/csv")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class Chrome:
    def __init__(self, url, directory):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        command = [r"C:\Program Files\Google\Chrome\Application\chrome.exe", "--headless=new", "--disable-gpu", "--no-first-run",
                   f"--user-data-dir={directory}", f"--remote-debugging-port={port}", "--remote-allow-origins=*", "--window-size=1366,768"]
        if os.getenv("TAMBAN_CHROME_NO_SANDBOX", "").lower() in {"1", "true", "yes", "on"}:
            command.append("--no-sandbox")
        self.process = subprocess.Popen([*command, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        until = time.monotonic() + 20
        while True:
            try:
                with urlopen(f"http://127.0.0.1:{port}/json", timeout=1) as response:
                    page = next(item for item in json.load(response) if item.get("type") == "page")
                break
            except (OSError, StopIteration):
                if time.monotonic() > until:
                    self.process.terminate()
                    raise RuntimeError("Chrome did not start")
                time.sleep(.1)
        self.socket = connect(page["webSocketDebuggerUrl"], open_timeout=5, max_size=24 * 1024 * 1024)
        self.counter = 0
        self.errors = []
        self.downloads = []
        self.call("Runtime.enable")

    def call(self, method, params=None):
        self.counter += 1
        self.socket.send(json.dumps({"id": self.counter, "method": method, "params": params or {}}))
        while True:
            response = json.loads(self.socket.recv(timeout=40))
            if response.get("method") == "Runtime.exceptionThrown":
                self.errors.append(response.get("params", {}))
            if response.get("method", "").startswith("Browser.download"):
                self.downloads.append(response)
            if response.get("id") != self.counter:
                continue
            if "error" in response:
                raise AssertionError(response["error"])
            if "exceptionDetails" in response["result"]:
                raise AssertionError(response["result"]["exceptionDetails"])
            return response["result"]

    def evaluate(self, script):
        return self.call("Runtime.evaluate", {"expression": script, "returnByValue": True, "awaitPromise": True})["result"].get("value")

    def wait(self, script, timeout=8):
        until = time.monotonic() + timeout
        while not self.evaluate(script):
            if time.monotonic() > until:
                self.screenshot("failure.png")
                raise AssertionError(f"Timed out waiting for {script}")
            time.sleep(.06)

    def viewport(self, width, height):
        self.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(.15)

    def click_point(self, point, count=1):
        self.call("Input.dispatchMouseEvent", {"type": "mousePressed", "button": "left", "clickCount": count, **point})
        self.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "button": "left", "clickCount": count, **point})
        time.sleep(.1)

    def point(self, selector):
        return self.evaluate("(()=>{const e=document.querySelector(" + json.dumps(selector) + ");if(!e)throw new Error('Missing target');e.scrollIntoView({block:'center',behavior:'instant'});const b=e.getBoundingClientRect();return {x:b.x+b.width/2,y:b.y+b.height/2};})()")

    def click(self, selector, count=1):
        self.click_point(self.point(selector), count)

    def key(self, name, code):
        self.call("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": name, "code": name, "windowsVirtualKeyCode": code})
        self.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": name, "code": name, "windowsVirtualKeyCode": code})
        time.sleep(.1)

    def choose(self, identifier, value):
        self.evaluate("(()=>{const e=document.getElementById(" + json.dumps(identifier) + ");e.value=" + json.dumps(value) + ";e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));return true;})()")
        time.sleep(.1)

    def screenshot(self, filename):
        result = self.call("Page.captureScreenshot", {"format": "png"})
        (OUTPUT / filename).write_bytes(base64.b64decode(result["data"]))

    def close(self):
        self.socket.close()
        self.process.terminate()
        self.process.wait(timeout=15)


SETUP_MEDIA = r'''(async()=>{
const fixture=window.__qweFixture,c=document.createElement('canvas');c.width=1000;c.height=640;
const p=c.getContext('2d');p.fillStyle='#e7f0f2';p.fillRect(0,0,c.width,c.height);
for(const fish of fixture.fish){p.fillStyle='#a1b5bb';p.beginPath();fish.segmentation.mask_overlay.contours[0].forEach(([x,y],i)=>i?p.lineTo(x,y):p.moveTo(x,y));p.closePath();p.fill();}
fixture.preview_image=c.toDataURL();const bytes=Uint8Array.from(atob(fixture.preview_image.split(',')[1]),v=>v.charCodeAt(0));
const file=new File([bytes],'native-grade-and-zoom-fixture.png',{type:'image/png'});
toggleUpload(true);setUploadSelection(file);
renderResultsDashboard(fixture.fish,{source:'upload',complete:true,scope:'qwe-native-fixture',metadata:{source_name:file.name}});
resultsSource='upload';resultsFilter='All';renderResultsDashboard(null,{renderOnly:true});mountResultsDashboard(true);elements.uploadResults.classList.remove('hidden');
await acceptAutomaticMaskPreview({fish:fixture.fish,segmentation_preview:fixture},file);
window.__qwe={before:JSON.stringify(resultDatasets.upload.rows),sourceBefore:elements.uploadImage.src};
window.__qwe.box=e=>{const b=e.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height,right:b.right,bottom:b.bottom};};
window.__qwe.fishPoint=id=>{const f=fixture.fish.find(item=>item.id===id),canvas=elements.maskPreviewCanvas,b=canvas.getBoundingClientRect();return {x:b.x+(f.bbox[0]+f.bbox[2])/2/1000*b.width,y:b.y+(f.bbox[1]+f.bbox[3])/2/640*b.height};};
return true;
})()'''


def verify_media(chrome, result):
    checks = result["checks"]
    checks["boxColorsAndLabelsMatchAllActualFinalGrades"] = chrome.evaluate("[...elements.uploadFishTargets.querySelectorAll('.fish-click-target')].every(target=>{const fish=window.__qweFixture.fish.find(item=>String(item.id)===target.dataset.fishId);const pen=document.createElement('canvas').getContext('2d');pen.fillStyle=gradeColors[fish.ai_final_grade];const expected=pen.fillStyle;pen.fillStyle=getComputedStyle(target).borderLeftColor;return target.dataset.grade===fish.ai_final_grade&&pen.fillStyle===expected&&target.getAttribute('aria-label').includes(fish.ai_final_grade);})")
    chrome.click('#upload-fish-targets [data-fish-id="3"]')
    checks["singleClickOnlySelectsFish"] = chrome.evaluate("elements.maskPreviewFish.value==='3'&&viewerZoom('upload')===1&&viewerTransforms.upload.x===0&&viewerTransforms.upload.y===0")
    checks["singleClickRevealsCorrectFishEvidence"] = chrome.evaluate("elements.resultsGroups.querySelector('details[data-inspection-fish-id=\"3\"]')?.open===true")
    chrome.click('#upload-fish-targets [data-fish-id="3"]', count=2)
    time.sleep(.15)
    checks["doubleClickActuallyZoomsSelectedFish"] = chrome.evaluate("viewerZoom('upload')>1&&elements.maskPreviewFish.value==='3'")
    focus = chrome.evaluate(r'''(()=>{
const f=window.__qweFixture.fish.find(item=>item.id===3),media=fishZoomMedia('upload'),stage=elements.uploadMediaStage;
const b=media.getBoundingClientRect(),s=stage.getBoundingClientRect(),scale=Math.min(b.width/1000,b.height/640),left=b.x+(b.width-1000*scale)/2,top=b.y+(b.height-640*scale)/2;
const bounds={left:left+f.bbox[0]*scale,top:top+f.bbox[1]*scale,right:left+f.bbox[2]*scale,bottom:top+f.bbox[3]*scale};
const inset=parseFloat(getComputedStyle(stage).getPropertyValue('--viewer-toolbar-inset'))||0;
return {bounds,stage:window.__qwe.box(stage),center:{x:(bounds.left+bounds.right)/2,y:(bounds.top+bounds.bottom)/2},targetCenter:{x:s.x+s.width/2,y:s.y+inset+(s.height-inset)/2},zoom:viewerZoom('upload')};
})()''')
    result["fish_focus"] = focus
    checks["fishSpecificZoomCentersItsNativeCoordinates"] = abs(focus["center"]["x"] - focus["targetCenter"]["x"]) < 3 and abs(focus["center"]["y"] - focus["targetCenter"]["y"]) < 3
    bounds, stage = focus["bounds"], focus["stage"]
    checks["focusedFishRemainsCompletelyVisible"] = bounds["left"] >= stage["x"] - 1 and bounds["right"] <= stage["right"] + 1 and bounds["top"] >= stage["y"] - 1 and bounds["bottom"] <= stage["bottom"] + 1
    chrome.screenshot("fish_specific_double_click.png")
    chrome.click('#upload-fullscreen-button')
    chrome.wait("document.fullscreenElement?.id==='upload-media-stage'")
    focused_fullscreen = chrome.evaluate("({stage:window.__qwe.box(elements.uploadMediaStage),fish:window.__qwe.box(document.querySelector('#upload-fish-targets [data-fish-id=\"3\"]'))})")
    result["fish_focus_fullscreen"] = focused_fullscreen
    checks["fullscreenKeepsFocusedFishFullyVisible"] = focused_fullscreen["fish"]["x"] >= focused_fullscreen["stage"]["x"] - 1 and focused_fullscreen["fish"]["right"] <= focused_fullscreen["stage"]["right"] + 1 and focused_fullscreen["fish"]["y"] >= focused_fullscreen["stage"]["y"] - 1 and focused_fullscreen["fish"]["bottom"] <= focused_fullscreen["stage"]["bottom"] + 1
    chrome.screenshot("fish_focus_fullscreen.png")
    chrome.key("Escape", 27)
    chrome.wait("!document.fullscreenElement")
    focus["center"] = chrome.point('#upload-fish-targets [data-fish-id="3"]')
    chrome.click_point(focus["center"], count=2)
    checks["secondDoubleClickReturnsToFit"] = chrome.evaluate("viewerZoom('upload')===1&&viewerTransforms.upload.x===0&&viewerTransforms.upload.y===0")
    chrome.click('#upload-fish-targets [data-fish-id="2"]', count=2)
    chrome.click('#upload-fit-button')
    checks["fitImageRestoresCompleteOriginalFrame"] = chrome.evaluate("viewerZoom('upload')===1&&viewerFitMode('upload')==='contain'")
    chrome.evaluate("document.querySelector('#upload-fish-targets [data-fish-id=\"2\"]').focus();true")
    chrome.key("z", 90)
    checks["keyboardCanExplicitlyZoomSelectedFish"] = chrome.evaluate("viewerZoom('upload')>1&&elements.maskPreviewFish.value==='2'")
    chrome.click('#upload-fit-button')
    chrome.click('label:has(> #upload-display-masks)')
    chrome.wait("!elements.maskPreviewViewport.classList.contains('hidden')")
    color_checks = chrome.evaluate(r'''(()=>{
const entries=maskPreviewEntries(uploadMaskPreview.data),rgb=hex=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16));
const records=[];elements.maskPreviewOpacity.value='80';
for(const entry of entries){selectInspectionFish(entry.id);renderMaskPreview();
 const actual=rgb(entry.color),base=rgb(gradeColors[entry.grade]);
 const shade=actual.map((value,i)=>(value-base[i])/(255-base[i]));
 const f=window.__qweFixture.fish.find(item=>item.id===entry.id),x=Math.floor((f.bbox[0]+f.bbox[2])/2),y=Math.floor((f.bbox[1]+f.bbox[3])/2);
 const pixel=[...elements.maskPreviewCanvas.getContext('2d').getImageData(x,y,1,1).data].slice(0,3);
 const expected=actual.map((value,i)=>Math.round(value*.8+[161,181,187][i]*.2));
 records.push({id:entry.id,grade:entry.grade,color:entry.color,gradeColor:entry.gradeColor,review:entry.review,
 shadePreservesGrade:Math.min(...shade)>-.01&&Math.max(...shade)<.26&&Math.max(...shade)-Math.min(...shade)<.02,
 pixel,pixelMatchesGrade:Math.max(...pixel.map((value,i)=>Math.abs(value-expected[i])))<=3});
}
selectInspectionFish('all');elements.maskPreviewOpacity.value='40';renderMaskPreview();return records;
})()''')
    result["mask_colors"] = color_checks
    checks["allFiveMaskGradesUseTheirActualFinalGrade"] = {record["grade"] for record in color_checks} == set(GRADES) and all(record["gradeColor"] == COLORS[record["grade"]] and record["shadePreservesGrade"] for record in color_checks)
    checks["renderedMaskPixelsMatchGradeColorsAndOpacity"] = all(record["pixelMatchesGrade"] for record in color_checks)
    checks["sameGradeNeighborsHaveSubtleDistinctShades"] = color_checks[0]["color"] != color_checks[5]["color"] and color_checks[0]["grade"] == color_checks[5]["grade"] == "Class A"
    ungraded = next(record for record in color_checks if record["id"] == 5)
    checks["reliableLookingUngradedMaskStillUsesGray"] = ungraded["grade"] == "Ungraded" and ungraded["gradeColor"] == COLORS["Ungraded"] and not ungraded["review"]
    checks["maskReviewNeverReplacesActualGradeLabel"] = chrome.evaluate("[...elements.maskPreviewFish.options].some(option=>option.textContent.includes('Fish #1')&&option.textContent.includes('Class A'))&&elements.maskPreviewLegend.textContent.toLowerCase().includes('review')")
    chrome.screenshot("grade_colored_masks_desktop.png")
    # Use explicit click coordinates in a known overlap. The currently selected
    # diagonal fish must win over its neighboring blue mask.
    chrome.evaluate("selectInspectionFish(6);true")
    point = chrome.evaluate("window.__qwe.fishPoint(6)")
    chrome.click_point(point)
    checks["overlappingMasksPrioritizeSelectedFish"] = chrome.evaluate("elements.maskPreviewFish.value==='6'&&viewerZoom('upload')===1")
    chrome.click_point(point, count=2)
    checks["diagonalFishDoubleClickZoomUsesItsBounds"] = chrome.evaluate("elements.maskPreviewFish.value==='6'&&viewerZoom('upload')>1")
    overlay_before = chrome.evaluate("elements.maskPreviewModel2.checked=true;elements.maskPreviewMeasurements.checked=true;elements.maskPreviewCracks.checked=true;elements.maskPreviewOpacity.value='35';renderMaskPreview();elements.maskPreviewCanvas.toDataURL()")
    zoom_before = chrome.evaluate("({zoom:viewerZoom('upload'),pan:{...viewerTransforms.upload},fish:elements.maskPreviewFish.value})")
    chrome.click('label:has(> #upload-display-boxes)')
    chrome.click('label:has(> #upload-display-masks)')
    zoom_after = chrome.evaluate("({zoom:viewerZoom('upload'),pan:{...viewerTransforms.upload},fish:elements.maskPreviewFish.value})")
    checks["boxMaskSwitchRetainsFishAndViewingState"] = zoom_before == zoom_after
    checks["nativeModel2GeometryAndCrackPixelsStayAlignedAfterZoom"] = chrome.evaluate("elements.maskPreviewCanvas.toDataURL()") == overlay_before
    checks["overlayControlsRemainEnabledDuringFishFocus"] = chrome.evaluate("elements.maskPreviewModel2.checked&&elements.maskPreviewMeasurements.checked&&elements.maskPreviewCracks.checked&&elements.maskPreviewOpacity.value==='35'")
    chrome.evaluate("elements.maskPreviewModel2.checked=false;elements.maskPreviewMeasurements.checked=false;elements.maskPreviewCracks.checked=false;renderMaskPreview();true")
    chrome.click('#upload-fit-button')
    chrome.evaluate("selectInspectionFish(5);true")
    chrome.click('#upload-zoom-fish-button')
    checks["verticalFishHasAccessibleExplicitZoomAction"] = chrome.evaluate("elements.maskPreviewFish.value==='5'&&viewerZoom('upload')>1")
    chrome.click('#upload-fit-button')
    # A double-click on background cannot select or zoom a fish.
    background = chrome.evaluate("(()=>{const b=elements.maskPreviewCanvas.getBoundingClientRect();return {x:b.x+b.width*.96,y:b.y+b.height*.96};})()")
    chrome.click_point(background, count=2)
    checks["emptyAreaDoubleClickDoesNotZoomOrChangeFish"] = chrome.evaluate("elements.maskPreviewFish.value==='5'&&viewerZoom('upload')===1")
    chrome.click('#upload-fit-button', count=2)
    checks["doubleClickingViewerControlDoesNotSelectAnotherFish"] = chrome.evaluate("elements.maskPreviewFish.value==='5'&&viewerZoom('upload')===1")
    for width, height in [(1366, 768), (1920, 1080), (1024, 700), (768, 1024), (390, 844)]:
        chrome.viewport(width, height)
        chrome.evaluate("resetViewerTransform('upload');selectInspectionFish('all');elements.uploadWorkspace.scrollTop=0;true")
        time.sleep(.1)
        info = chrome.evaluate("({width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth,stage:window.__qwe.box(elements.uploadMediaStage),canvas:window.__qwe.box(elements.maskPreviewCanvas),viewport:window.__qwe.box(elements.maskPreviewViewport),toolbar:window.__qwe.box(elements.uploadMediaStage.querySelector('.viewer-floating-tools'))})")
        result["viewports"][f"media_{width}x{height}"] = info
        checks[f"mediaResponsive_{width}x{height}"] = info["scrollWidth"] <= info["width"] + 1 and info["canvas"]["width"] <= info["viewport"]["width"] + 1 and info["canvas"]["height"] <= info["viewport"]["height"] + 1
        chrome.screenshot(f"media_{width}x{height}.png")
    # Touch selection and its explicit zoom button are both trusted browser
    # interactions even where native browser double-tap behavior varies.
    chrome.evaluate("selectInspectionFish(5);true")
    point = chrome.evaluate("window.__qwe.fishPoint(5)")
    chrome.call("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})
    for _ in range(2):
        chrome.call("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": point["x"], "y": point["y"]}]})
        chrome.call("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        time.sleep(.09)
    time.sleep(.15)
    checks["touchDoubleTapCanExplicitlyFocusFish"] = chrome.evaluate("elements.maskPreviewFish.value==='5'&&viewerZoom('upload')>1")
    chrome.call("Emulation.setTouchEmulationEnabled", {"enabled": False})
    chrome.evaluate("resetViewerTransform('upload');true")
    checks["inspectionGradesUnchangedByColorsAndZoom"] = chrome.evaluate("JSON.stringify(resultDatasets.upload.rows)===window.__qwe.before")
    chrome.evaluate("toggleUpload(false);true")


def verify_analytics(chrome, result):
    checks = result["checks"]
    chrome.viewport(1366, 768)
    chrome.click('.nav-item[data-view="analytics"]')
    chrome.wait("document.querySelector('#sa-kpis .ax-kpi strong')?.textContent==='7'")
    kpis = chrome.evaluate("Object.fromEntries([...document.querySelectorAll('#sa-kpis .ax-kpi')].map(card=>[card.querySelector('span').textContent,card.querySelector('strong').textContent]))")
    result["analytics_kpis"] = kpis
    checks["analyticsUsesRealUniquePersistedFishCounts"] = kpis.get("Total inspected fish") == "7" and kpis.get("Inspection sessions") == "3" and kpis.get("Graded fish") == "5" and kpis.get("Ungraded fish") == "2"
    checks["gradeKpiCountsMatchDirectSQLiteRows"] = all(kpis.get(grade) == str(result["sqlite_expected"]["distribution"][grade]) for grade in GRADES[:4])
    checks["analyticsIsDedicatedSidebarPageWithoutLegacyDuplicate"] = chrome.evaluate("document.querySelectorAll('.nav-item[data-view=\"analytics\"]').length===1&&!document.getElementById('analytics-disclosure')&&document.querySelectorAll('#sa-chart-grades').length===1&&!document.querySelector('#view-live .analytics-disclosure')")
    checks["gradeDoughnutHasActualGradeColorsAndPercentages"] = chrome.evaluate("document.querySelectorAll('#sa-grades .ax-interactive-legend').length===5&&[...document.querySelectorAll('#sa-grades .ax-interactive-legend')].every(item=>item.getAttribute('aria-label').includes('%'))&&document.querySelector('#sa-grades svg [aria-label^=\"Ungraded:\"]').getAttribute('stroke')==='#546c7a'")
    chrome.screenshot("analytics_overview_1366x768.png")

    # Changing scope is an actual SQLite-backed read, not an injected chart.
    chrome.choose("sa-session", "qwe-morning")
    chrome.wait("document.querySelector('#sa-kpis .ax-kpi strong')?.textContent==='4'")
    checks["individualSessionFilterMatchesPersistedRecords"] = chrome.evaluate("window.TambanAnalytics.getScope().session_id==='qwe-morning'")
    chrome.choose("sa-session", "latest")
    chrome.wait("document.querySelector('#sa-kpis .ax-kpi strong')?.textContent==='0'")
    checks["latestScopeIncludesRealZeroFishSavedSession"] = chrome.evaluate("window.TambanAnalytics.getScope().session_id==='qwe-empty'&&document.getElementById('sa-status').textContent.includes('No saved fish')")
    checks["emptyScopeDoesNotInventSupportMeasurements"] = chrome.evaluate("document.querySelector('#sa-support .ax-empty')?.textContent.toLowerCase().includes('not recorded')===true")
    chrome.choose("sa-session", "custom")
    chrome.choose("sa-start", "2026-11-01")
    chrome.choose("sa-end", "2026-11-01")
    chrome.click('#sa-filters button[type="submit"]')
    chrome.wait("document.querySelector('#sa-kpis .ax-kpi strong')?.textContent==='4'")
    checks["customDateFilterUsesRecordedFishDates"] = chrome.evaluate("window.TambanAnalytics.getScope().start_date==='2026-11-01'&&window.TambanAnalytics.getScope().end_date==='2026-11-01'")
    chrome.choose("sa-session", "")
    chrome.wait("document.querySelector('#sa-kpis .ax-kpi strong')?.textContent==='7'")
    for interval in ["hour", "day", "week", "month"]:
        chrome.choose("sa-interval", interval)
        chrome.wait("document.querySelector('#sa-kpis').getAttribute('aria-busy')==='false'")
        checks[f"persistedActivityGranularity_{interval}"] = chrome.evaluate("window.TambanAnalytics.getState().interval===" + json.dumps(interval))
    chrome.choose("sa-interval", "day")
    chrome.wait("document.querySelector('#sa-kpis').getAttribute('aria-busy')==='false'")

    # Every migrated graph, including honest unavailable-data states, uses the
    # browser Fullscreen API on its own original chart element.
    charts = chrome.evaluate("[...document.querySelectorAll('.ax-chart[data-chart]')].map(card=>({id:card.dataset.chart,tab:card.dataset.tabs.split(' ')[0]}))")
    result["analytics_charts"] = charts
    checks["allRequiredAndLegacyGraphsMigrated"] = {chart["id"] for chart in charts} == {"grades", "activity", "coverage", "anatomy", "reasons", "performance", "comparison", "support", "part-quality", "color-trend", "decision-timing"}
    download_dir = OUTPUT / "downloads"
    download_dir.mkdir(exist_ok=True)
    for chart in charts:
        path = download_dir / f"tamban_{chart['id']}.csv"
        if path.is_file():
            path.unlink()
    if (download_dir / "tamban_grades.png").is_file():
        (download_dir / "tamban_grades.png").unlink()
    chrome.call("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(download_dir), "eventsEnabled": True})
    fullscreen = {}
    for chart in charts:
        identifier = chart["id"]
        chrome.click('[data-analytics-tab=' + json.dumps(chart["tab"]) + ']')
        chrome.wait("window.TambanAnalytics.getState().tab===" + json.dumps(chart["tab"]))
        chrome.click('[data-chart-fullscreen=' + json.dumps(identifier) + ']')
        chrome.wait("document.fullscreenElement?.id===" + json.dumps("sa-chart-" + identifier))
        info = chrome.evaluate("(()=>{const card=document.fullscreenElement,b=card.getBoundingClientRect();return {width:b.width,height:b.height,viewportWidth:innerWidth,viewportHeight:innerHeight,context:getComputedStyle(card.querySelector('.ax-chart-context')).display,unrelatedHidden:card.contains(document.elementFromPoint(5,5))};})()")
        fullscreen[identifier] = info
        checks[f"chartNativeFullscreen_{identifier}"] = abs(info["width"] - info["viewportWidth"]) <= 1 and abs(info["height"] - info["viewportHeight"]) <= 1 and info["context"] != "none" and info["unrelatedHidden"]
        chrome.screenshot(f"chart_fullscreen_{identifier}.png")
        chrome.click('[data-chart-csv=' + json.dumps(identifier) + ']')
        chrome.key("Escape", 27)
        chrome.wait("!document.fullscreenElement")
        checks[f"chartEscapeRestoresDashboard_{identifier}"] = chrome.evaluate("!document.getElementById('view-analytics').classList.contains('hidden')")
    result["chart_fullscreen"] = fullscreen
    until = time.monotonic() + 5
    while not all((download_dir / f"tamban_{chart['id']}.csv").is_file() for chart in charts):
        if time.monotonic() > until:
            raise AssertionError("A chart CSV download did not finish")
        time.sleep(.1)
    checks["everyGraphExportsUnderlyingCsv"] = all((download_dir / f"tamban_{chart['id']}.csv").stat().st_size > 60 for chart in charts)
    import csv
    with (download_dir / "tamban_grades.csv").open(newline="", encoding="utf-8-sig") as stream:
        csv_rows = list(csv.DictReader(stream))
    checks["downloadedGradeCsvMatchesSQLiteExactly"] = {row["label"]: int(float(row["value"])) for row in csv_rows} == result["sqlite_expected"]["distribution"]
    chrome.click('[data-analytics-tab="overview"]')
    chrome.click('[data-chart-png="grades"]')
    until = time.monotonic() + 6
    while not (download_dir / "tamban_grades.png").is_file():
        if time.monotonic() > until:
            raise AssertionError("Grade PNG did not download")
        time.sleep(.1)
    with Image.open(download_dir / "tamban_grades.png") as exported:
        result["png_export"] = {"size": list(exported.size), "format": exported.format}
        checks["chartPngIsRealReadableHighResolutionImage"] = exported.format == "PNG" and exported.width >= 1000 and exported.height >= 600

    # Fullscreen chart filters refresh the same persisted scope, and selecting
    # its Ungraded category exits fullscreen before opening exact fish records.
    chrome.click('[data-chart-fullscreen="grades"]')
    chrome.wait("document.fullscreenElement?.id==='sa-chart-grades'")
    chrome.evaluate("document.querySelector('#sa-chart-grades .ax-context-session').value='qwe-morning';true")
    chrome.click('#sa-chart-grades .ax-chart-context button[type="submit"]')
    chrome.wait("document.querySelector('#sa-kpis .ax-kpi strong')?.textContent==='4'")
    checks["fullscreenChartFiltersReadRealPersistedScope"] = chrome.evaluate("document.fullscreenElement?.id==='sa-chart-grades'&&window.TambanAnalytics.getScope().session_id==='qwe-morning'")
    point = chrome.evaluate("(()=>{const e=document.querySelector('#sa-grades .ax-interactive-legend[aria-label^=\"Ungraded:\"]');const b=e.getBoundingClientRect();return {x:b.x+b.width/2,y:b.y+b.height/2};})()")
    chrome.click_point(point)
    chrome.wait("!document.fullscreenElement&&!document.getElementById('view-history').classList.contains('hidden')&&document.getElementById('sh-record-status').textContent.includes('1 matching fish')")
    checks["chartGradeDrilldownPreservesSessionAndGrade"] = chrome.evaluate("document.getElementById('sh-selected-id').textContent.includes('qwe-morning')&&document.getElementById('sh-grade').value==='Ungraded'&&[...document.querySelectorAll('.sw-fish-title')].every(title=>title.textContent.includes('Ungraded'))")
    chrome.screenshot("analytics_to_exact_history.png")
    chrome.click('#sh-back-analytics')
    chrome.wait("!document.getElementById('view-analytics').classList.contains('hidden')")
    checks["returnToAnalyticsPreservesDashboardScope"] = chrome.evaluate("document.getElementById('sa-session').value==='qwe-morning'&&document.querySelector('#sa-kpis .ax-kpi strong').textContent==='4'")
    chrome.choose("sa-session", "")
    chrome.wait("document.querySelector('#sa-kpis .ax-kpi strong')?.textContent==='7'")
    chrome.click('[data-analytics-tab="performance"]')
    chrome.choose("sa-performance-mode", "ai_fps")
    ai_labels = chrome.evaluate("[...document.querySelectorAll('#sa-performance svg circle[aria-label]')].map(node=>node.getAttribute('aria-label'))")
    fps_x = chrome.evaluate("[...document.querySelectorAll('#sa-performance svg circle[aria-label]')].map(node=>Number(node.getAttribute('cx')))")
    checks["performanceTimelineUsesActualTimestampGaps"] = len(fps_x) == 7 and fps_x[4] - fps_x[3] > 100 * (fps_x[1] - fps_x[0])
    chrome.choose("sa-performance-mode", "camera_fps")
    camera_labels = chrome.evaluate("[...document.querySelectorAll('#sa-performance svg circle[aria-label]')].map(node=>node.getAttribute('aria-label'))")
    result["recorded_fps_labels"] = {"ai": ai_labels, "camera": camera_labels}
    checks["analyticsSeparatesRecordedAiAndCameraFps"] = len(ai_labels) == len(camera_labels) == 7 and any("3.1 FPS" in label for label in ai_labels) and any("28.1 FPS" in label for label in camera_labels)
    checks["recordedZeroAiFpsIsShownAsZero"] = any(": 0 FPS" in label for label in ai_labels)
    chrome.choose("sa-performance-mode", "throughput")
    checks["throughputUsesRecordedSessionActiveMinutes"] = chrome.evaluate("[...document.querySelectorAll('#sa-performance svg g[aria-label]')].some(node=>node.getAttribute('aria-label').includes('qwe-morning: 2 fish/min'))")
    comparison = chrome.evaluate("(()=>{const e=[...document.querySelectorAll('#sa-comparison svg rect[aria-label]')].find(node=>node.getAttribute('aria-label').includes('afternoon')&&node.getAttribute('aria-label').includes('Rejected'));e.scrollIntoView({block:'nearest',behavior:'instant'});const b=e.getBoundingClientRect();return {x:b.x+b.width/2,y:b.y+b.height/2};})()")
    chrome.click_point(comparison)
    chrome.wait("!document.getElementById('view-history').classList.contains('hidden')&&document.getElementById('sh-record-status').textContent.includes('1 matching fish')")
    checks["comparisonSegmentDrilldownPreservesExactSessionAndGrade"] = chrome.evaluate("document.getElementById('sh-selected-id').textContent.includes('qwe-afternoon')&&document.getElementById('sh-grade').value==='Rejected'")
    chrome.click('#sh-back-analytics')
    chrome.click('[data-analytics-tab="evidence"]')
    checks["rawAndAssignedAnatomyAreSeparateRecordedCounts"] = chrome.evaluate("[...document.querySelectorAll('#sa-anatomy svg g[aria-label]')].some(node=>node.getAttribute('aria-label').includes('Head · fish with raw detection: 7'))&&[...document.querySelectorAll('#sa-anatomy svg g[aria-label]')].some(node=>node.getAttribute('aria-label').includes('Head · fish with assigned evidence: 5'))")
    for width, height in [(1366, 768), (1920, 1080), (1024, 700), (768, 1024), (390, 844)]:
        chrome.viewport(width, height)
        for tab in ["overview", "grades", "evidence", "performance"]:
            chrome.click('[data-analytics-tab=' + json.dumps(tab) + ']')
            chrome.evaluate("window.scrollTo({top:0,behavior:'instant'});document.querySelector('.app-main').scrollTop=0;true")
            info = chrome.evaluate("({width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth,filter:window.__qwe.box(document.getElementById('sa-filters')),kpis:window.__qwe.box(document.getElementById('sa-kpis')),charts:[...document.querySelectorAll('.ax-chart:not(.hidden)')].map(card=>({id:card.id,box:window.__qwe.box(card),labels:[...card.querySelectorAll('.ax-svg-label')].slice(0,8).map(label=>({text:label.textContent,height:label.getBoundingClientRect().height}))}))})")
            result["viewports"][f"analytics_{tab}_{width}x{height}"] = info
            checks[f"analyticsResponsive_{tab}_{width}x{height}"] = info["scrollWidth"] <= info["width"] + 1 and all(card["box"]["width"] >= 200 and card["box"]["right"] <= width + 1 for card in info["charts"])
            checks[f"analyticsReadableLabels_{tab}_{width}x{height}"] = all(label["height"] >= 9 for card in info["charts"] for label in card["labels"])
            chrome.screenshot(f"analytics_{tab}_{width}x{height}.png")
    sticky_results = {}
    for width, height in [(1366, 768), (390, 844)]:
        chrome.viewport(width, height)
        chrome.evaluate("(()=>{window.scrollTo({top:0,behavior:'instant'});const main=document.querySelector('.app-main');main.scrollTop=0;if(main.scrollHeight>main.clientHeight+2&&getComputedStyle(main).overflowY==='auto')main.scrollTop=500;else window.scrollTo({top:500,behavior:'instant'});return true;})()")
        time.sleep(.15)
        sticky = chrome.evaluate("({filters:window.__qwe.box(document.getElementById('sa-filters')),tabs:window.__qwe.box(document.querySelector('.ax-tabbar')),height:innerHeight,windowScroll:scrollY,mainScroll:document.querySelector('.app-main').scrollTop,bodyOverflow:getComputedStyle(document.body).overflow})")
        sticky_results[f"{width}x{height}"] = sticky
        checks[f"analyticsFiltersAndTabsStayAccessibleOnScroll_{width}"] = sticky["filters"]["y"] >= -1 and sticky["tabs"]["y"] >= sticky["filters"]["bottom"] - 1 and sticky["tabs"]["bottom"] <= height
        chrome.screenshot(f"analytics_sticky_{width}x{height}.png")
        chrome.click('[data-analytics-tab="grades"]')
        chrome.wait("window.TambanAnalytics.getState().tab==='grades'")
        checks[f"stickyTabsRemainClickableAfterLongScroll_{width}"] = True
        chrome.click('[data-analytics-tab="performance"]')
    result["analytics_sticky"] = sticky_results
    checks["filtersAndTabsRetainTheirSelections"] = chrome.evaluate("window.TambanAnalytics.getState().interval==='day'&&window.TambanAnalytics.getState().tab==='performance'&&window.TambanAnalytics.getScope().session_id===''")


def verify_live_media(chrome, result):
    """The shared interactions also work on recorded live-source dimensions."""
    checks = result["checks"]
    chrome.viewport(1366, 768)
    chrome.evaluate(r'''(()=>{
latestStatus={inspection_status:'running',camera_status:'connected',model_status:'ready',segmenter_status:'ready',
model_info:{detector:{device:'cpu'},quality:{status:'ready'}},active_tracks:window.__qweFixture.fish,
live_frame_status:{camera_state:'active',ai_state:'paused',capture_fps:0,processing_fps:0,capture_resolution:[1000,640]}};
renderResultsDashboard(window.__qweFixture.fish,{source:'live',complete:true,scope:'qwe-live-source-fixture'});
streamAttached=true;streamReady=true;elements.video.src=window.__qweFixture.preview_image;renderCamera(latestStatus);return true;
})()''')
    chrome.wait("elements.video.naturalWidth===1000&&elements.liveFishTargets.children.length===7")
    chrome.click('#live-fish-targets [data-fish-id="4"]')
    checks["liveSingleClickSelectsWithoutZoom"] = chrome.evaluate("elements.liveFishTargets.dataset.selection==='4'&&viewerZoom('live')===1")
    chrome.click('#live-fish-targets [data-fish-id="4"]', count=2)
    checks["liveDoubleClickFocusesActualFish"] = chrome.evaluate("elements.liveFishTargets.dataset.selection==='4'&&viewerZoom('live')>1")
    chrome.click('#live-fullscreen-button')
    chrome.wait("document.fullscreenElement?.id==='live-media-stage'")
    position = chrome.evaluate("({stage:window.__qwe.box(elements.liveMediaStage),fish:window.__qwe.box(document.querySelector('#live-fish-targets [data-fish-id=\"4\"]'))})")
    checks["liveFullscreenKeepsFocusedFishVisible"] = position["fish"]["x"] >= position["stage"]["x"] - 1 and position["fish"]["right"] <= position["stage"]["right"] + 1 and position["fish"]["y"] >= position["stage"]["y"] - 1 and position["fish"]["bottom"] <= position["stage"]["bottom"] + 1
    chrome.screenshot("live_fish_focus_fullscreen.png")
    chrome.key("Escape", 27)
    chrome.wait("!document.fullscreenElement")
    chrome.click('#live-fit-button')
    chrome.click('#live-zoom-fish-button')
    checks["liveViewerHasAccessibleSelectedFishZoomAction"] = chrome.evaluate("elements.liveFishTargets.dataset.selection==='4'&&viewerZoom('live')>1")
    chrome.click('#live-fit-button')
    checks["liveCameraAndExposureControlsPreserved"] = chrome.evaluate("['live-camera-select','live-model-selector','camera-exposure-mode','camera-exposure-ev','open-camera-controls','start-button','reset-button','live-fullscreen-button','live-viewer-fit-mode'].every(id=>document.getElementById(id))")
    chrome.evaluate("latestStatus.inspection_status='stopped';latestStatus.camera_status='disconnected';latestStatus.live_frame_status.camera_state='disconnected';latestStatus.live_frame_status.ai_state='stopped';renderCamera(latestStatus);true")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    result = {"checks": {}, "viewports": {}, "scope": "Actual Chrome trusted input/native canvas plus real persisted temporary SQLite analytics/history; synthetic recorded evidence, no models/inference/hardware accuracy claims"}
    with tempfile.TemporaryDirectory(prefix="tamban_qwe_browser_", ignore_cleanup_errors=True) as directory:
        database = InspectionDatabase(Path(directory) / "persisted.sqlite3")
        populate(database)
        FixtureServer.database = database
        FixtureServer.requests = []
        with sqlite3.connect(database.path) as connection:
            result["sqlite_expected"] = {"total": connection.execute("SELECT count(*) FROM fish_inspections").fetchone()[0],
                "sessions": connection.execute("SELECT count(*) FROM inspection_sessions").fetchone()[0],
                "distribution": dict(connection.execute("SELECT final_grade,count(*) FROM fish_inspections GROUP BY final_grade").fetchall())}
        server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureServer)
        server.daemon_threads = True
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        chrome = None
        try:
            chrome = Chrome(f"http://127.0.0.1:{server.server_port}/", Path(directory) / "chrome")
            chrome.wait("typeof elements!=='undefined'&&!!window.TambanInspection&&!!window.TambanSessions")
            chrome.viewport(1366, 768)
            chrome.evaluate("window.__qweFixture=" + json.dumps(media_fixture()) + ";true")
            chrome.evaluate(SETUP_MEDIA)
            verify_media(chrome, result)
            verify_live_media(chrome, result)
            verify_analytics(chrome, result)
            result["checks"]["fixtureHasSevenUniqueSavedFish"] = result["sqlite_expected"]["total"] == 7
            result["checks"]["fixtureIncludesAllActualFinalGrades"] = set(result["sqlite_expected"]["distribution"]) == set(GRADES)
            result["chrome"] = chrome.call("Browser.getVersion")["product"]
            result["runtime_errors"] = chrome.errors
            result["requests"] = FixtureServer.requests
            result["checks"]["noRuntimeExceptions"] = not chrome.errors
            result["checks"]["displayAndAnalyticsNeverRunAiInference"] = not any(any(fragment in path for fragment in ["/api/analyze", "/api/segmentation", "/api/inspection/start"]) for path in FixtureServer.requests)
            (OUTPUT / "qwe_browser.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"checks": len(result["checks"]), "failed": [key for key, value in result["checks"].items() if not value]}, indent=2))
            assert all(result["checks"].values()), result["checks"]
        except Exception:
            (OUTPUT / "qwe_browser.partial.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            raise
        finally:
            if chrome:
                chrome.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    main()
