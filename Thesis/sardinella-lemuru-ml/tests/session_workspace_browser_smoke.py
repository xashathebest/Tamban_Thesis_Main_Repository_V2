"""Real session/history/analytics browser checks against an isolated temporary database."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from websockets.sync.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.api.database import InspectionDatabase
from dashboard_status_smoke import free_port, wait_json


def main():
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.is_file():
        raise RuntimeError("Chrome executable not found")
    api_port, cdp_port = free_port(), free_port()
    with tempfile.TemporaryDirectory(prefix="tamban_session_workspace_") as tmp:
        db_path = Path(tmp) / "inspection.sqlite3"
        database = InspectionDatabase(db_path)
        first = database.create_session({"started_at": "2026-11-01T12:00:00+00:00"}, session_id="workspace-primary")
        second = database.create_session({"started_at": "2026-11-02T12:00:00+00:00"}, session_id="workspace-neighbor")
        empty = database.create_session({"started_at": "2026-11-03T12:00:00+00:00"}, session_id="workspace-empty")
        for track_id in range(1, 31):
            grade = "Class B" if track_id == 7 else "Class A" if track_id % 2 == 0 else "Ungraded"
            database.upsert_event(first, {"track_id": track_id, "timestamp": f"2026-11-01T12:00:{track_id:02d}+00:00", "quality": grade, "quality_confidence": .88 if grade != "Ungraded" else None, "final_confidence": .93, "processing_time_ms": 18.5,
                "analysis": {"final_grade": grade, "verdict_status": "AUTO_GRADED" if grade != "Ungraded" else "NEEDS_REVIEW", "verdict_reason_code": "MISSING_HEAD" if grade == "Ungraded" else None, "reason_codes": ["MISSING_HEAD"] if grade == "Ungraded" else [], "final_score": .88 if grade != "Ungraded" else None,
                    "part_results": {"Body": {"present": True}, "Head": {"present": grade != "Ungraded"}, "Tail": {"present": False}}, "performance": {"model1_inference_ms": 4.5, "model2_inference_ms": 9.5}}})
        database.upsert_event(second, {"track_id": 7, "timestamp": "2026-11-02T12:00:00+00:00", "quality": "Class C", "analysis": {"final_grade": "Class C", "verdict_status": "AUTO_GRADED"}})
        for session in (first, second, empty):
            database.end_session(session)
        env = dict(os.environ, LEMURU_PORT=str(api_port), FISH_INSPECTION_DB_PATH=str(db_path), YOLO_CONFIG_DIR=tmp)
        hidden = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        code = "import os,uvicorn; from src.api.app import app; uvicorn.run(app,host='127.0.0.1',port=int(os.environ['LEMURU_PORT']))"
        api = subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
        browser = None
        try:
            wait_json(f"http://127.0.0.1:{api_port}/api/status/live", api)
            args = [str(chrome), "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={Path(tmp) / 'chrome'}", f"--remote-debugging-port={cdp_port}", "--remote-allow-origins=*"]
            if os.getenv("TAMBAN_CHROME_NO_SANDBOX", "").lower() in {"1", "true", "yes", "on"}:
                args.append("--no-sandbox")
            args.append(f"http://127.0.0.1:{api_port}/")
            browser = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
            target = next(page for page in wait_json(f"http://127.0.0.1:{cdp_port}/json", browser) if page.get("type") == "page")
            with connect(target["webSocketDebuggerUrl"], open_timeout=5) as ws:
                ident = 0

                def command(method, params=None):
                    nonlocal ident
                    ident += 1
                    ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
                    while True:
                        response = json.loads(ws.recv(timeout=30))
                        if response.get("id") == ident:
                            if "error" in response:
                                raise AssertionError(response["error"])
                            return response["result"]

                def evaluate(expression):
                    result = command("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
                    if "exceptionDetails" in result:
                        raise AssertionError(result["exceptionDetails"])
                    return result["result"].get("value")

                for attempt in range(60):
                    try:
                        if evaluate("location.pathname === '/' && document.readyState === 'complete' && Boolean(window.TambanSessions)"):
                            break
                    except AssertionError as error:
                        if "Execution context was destroyed" not in str(error):
                            raise
                    time.sleep(.1)
                else:
                    raise AssertionError("The dashboard did not finish navigation")
                result = evaluate(r'''(async()=>{
                    const wait=async(test,label)=>{for(let i=0;i<150;i++){if(test())return;await new Promise(resolve=>setTimeout(resolve,70));}throw new Error(label);};
                    await wait(()=>window.TambanSessions&&window.TambanInspection,"Module bridge did not initialize");
                    window.TambanInspection.showView("history");
                    await wait(()=>document.querySelectorAll(".sw-session-card").length===3,"Session cards did not load");
                    const zero=[...document.querySelectorAll(".sw-session-card")].find(card=>card.textContent.includes("workspace-empty"));
                    if(!zero?.textContent.includes("0 fish"))throw new Error("Zero-fish session missing");
                    window.TambanSessions.openSession("workspace-primary");
                    await wait(()=>document.querySelector("#sh-record-status").textContent.includes("30 matching fish"),"Selected session records missing");
                    if(document.querySelectorAll(".sw-fish-card").length!==25)throw new Error("History page size incorrect");
                    document.querySelector("#sh-next").click();
                    await wait(()=>document.querySelector("#sh-page").textContent.includes("Page 2")&&document.querySelectorAll(".sw-fish-card").length===5,"Second fish page missing");
                    document.querySelector("#sh-prev").click();
                    await wait(()=>document.querySelector("#sh-page").textContent.includes("Page 1")&&document.querySelectorAll(".sw-fish-card").length===25,"First page did not return");
                    const fish=[...document.querySelectorAll(".sw-fish-card")].find(card=>card.querySelector(".sw-fish-title").textContent.includes("Fish #7 ·"));
                    if(!fish?.textContent.includes("Class B"))throw new Error("Original grade or composite identity changed");
                    fish.querySelector(".sw-fish-title").click();
                    if(!document.querySelector("#history-analysis-dialog")?.open)throw new Error("Evidence dialog did not open");
                    document.querySelector("#history-analysis-dialog").close();
                    window.__reports=[];window.__printed=0;
                    window.open=()=>({closed:false,document:{open(){},write(html){window.__reports.push(html)},close(){}},focus(){},print(){window.__printed++},close(){this.closed=true}});
                    fish.querySelectorAll(".sw-fish-actions button")[2].click();
                    if(!window.__reports.at(-1).includes("Fish #7 · Class B"))throw new Error("Fish PDF lost actual grade");
                    const rawFetch=window.fetch;window.__exports=[];
                    window.fetch=async(input,options)=>{const response=await rawFetch(input,options);if(String(input)==="/api/export"){window.__exports.push({payload:JSON.parse(options.body),status:response.status,text:await response.clone().text()});}return response;};
                    fish.querySelectorAll(".sw-fish-actions button")[1].click();
                    await wait(()=>window.__exports.length===1,"Individual CSV missing");
                    const exported=window.__exports[0];
                    if(exported.status!==200||exported.payload.session_id!=="workspace-primary"||JSON.stringify(exported.payload.track_ids)!=="[7]")throw new Error("Individual CSV wrong identity");
                    document.querySelector("#sh-pdf").click();
                    await wait(()=>window.__printed===2,"Complete session PDF missing");
                    if(!window.__reports.at(-1).includes("30 fish")||window.__reports.at(-1).includes("workspace-neighbor"))throw new Error("Session PDF was incomplete or crossed sessions");
                    window.TambanInspection.showView("analytics");
                    await wait(()=>document.querySelectorAll("#sa-session option").length===4,"Analytics sessions missing");
                    document.querySelector("#sa-session").value="workspace-primary";document.querySelector("#sa-filters").requestSubmit();
                    await wait(()=>document.querySelector("#sa-status").textContent.startsWith("30 saved fish"),"Session analytics count incorrect");
                    const ungraded=[...document.querySelectorAll("#sa-grades button")].find(button=>button.textContent==="Ungraded");ungraded.click();
                    await wait(()=>document.querySelector("#sh-record-status").textContent.includes("14 matching fish"),"Grade drilldown did not match chart");
                    if([...document.querySelectorAll(".sw-fish-title")].some(title=>!title.textContent.endsWith("Ungraded")))throw new Error("Ungraded filter mixed grades");
                    window.TambanInspection.showView("analytics");
                    await wait(()=>!document.querySelector("#sa-status").textContent.startsWith("Loading"),"Analytics reload incomplete");
                    [...document.querySelectorAll("#sa-anatomy button")].find(button=>button.textContent==="Head").click();
                    await wait(()=>document.querySelector("#sh-record-status").textContent.includes("16 matching fish"),"Anatomy drilldown disagrees with recorded evidence");
                    return {cards:3,records:30,individualCsv:exported.status,printReports:window.__printed,gradeDrilldown:14,headEvidenceDrilldown:16};
                })()''')
                for width, height in ((390, 844), (768, 1024), (1366, 768)):
                    command("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600})
                    overflow = evaluate("document.documentElement.scrollWidth > innerWidth + 1")
                    if overflow:
                        raise AssertionError(f"History overflows at {width}px")
                print(json.dumps(result))
        finally:
            if browser and browser.poll() is None:
                browser.terminate()
                browser.wait(timeout=10)
            if api.poll() is None:
                api.terminate()
                api.wait(timeout=10)


if __name__ == "__main__":
    main()
