"""Exercise selecting and reviewing a historical fish in headless Chrome."""
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
    with tempfile.TemporaryDirectory(prefix="tamban_history_review_") as tmp:
        env = dict(os.environ, LEMURU_PORT=str(api_port), FISH_INSPECTION_DB_PATH=str(Path(tmp) / "test.sqlite3"), YOLO_CONFIG_DIR=tmp)
        hidden = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        server = ("import importlib, os, uvicorn; m=importlib.import_module('src.api.app'); "
                  "m.inspection_sessions.start({}); uvicorn.run(m.app, host='127.0.0.1', port=int(os.environ['LEMURU_PORT']))")
        api = subprocess.Popen([sys.executable, "-c", server], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
        browser = None
        try:
            current = wait_json(f"http://127.0.0.1:{api_port}/api/status/live", api)["durable_session"]["session_id"]
            db = InspectionDatabase(Path(tmp) / "test.sqlite3")
            past = db.create_session({"started_at": "2020-01-01T00:00:00+00:00"})
            for session, grade in ((past, "Class A"), (current, "Class B")):
                db.upsert_event(session, {"track_id": 7, "timestamp": "2020-01-01T00:00:00+00:00", "quality": grade,
                                         "analysis": {"final_grade": grade, "verdict_status": "NEEDS_REVIEW"}})
            chrome_args = ["--headless=new", "--disable-gpu", "--no-first-run",
                           f"--user-data-dir={Path(tmp) / 'chrome'}", f"--remote-debugging-port={cdp_port}",
                           "--remote-allow-origins=*"]
            if os.getenv("TAMBAN_CHROME_NO_SANDBOX", "").strip().lower() in {"1", "true", "yes", "on"}:
                chrome_args.append("--no-sandbox")
            chrome_args.append(f"http://127.0.0.1:{api_port}/")
            browser = subprocess.Popen([str(chrome), *chrome_args],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
            page = next(target for target in wait_json(f"http://127.0.0.1:{cdp_port}/json", browser) if target.get("type") == "page")
            with connect(page["webSocketDebuggerUrl"], open_timeout=5) as ws:
                def evaluate(expression, ident):
                    ws.send(json.dumps({"id": ident, "method": "Runtime.evaluate", "params": {"expression": expression, "returnByValue": True, "awaitPromise": True}}))
                    while True:
                        message = json.loads(ws.recv(timeout=20))
                        if message.get("id") == ident:
                            if "exceptionDetails" in message["result"]:
                                raise AssertionError(message["result"]["exceptionDetails"])
                            return message["result"]["result"].get("value")
                script = """(async () => {
                    const pause = () => new Promise(resolve => setTimeout(resolve, 100));
                    for (let i=0; i<100 && typeof showView !== 'function'; i++) await pause();
                    showView('history');
                    for (let i=0; i<100 && ![...elements.historySession.options].some(x => x.value === PAST); i++) await pause();
                    elements.historySession.value = PAST; elements.historySession.dispatchEvent(new Event('change'));
                    for (let i=0; i<100 && !elements.historyBody.textContent.includes('Class A'); i++) await pause();
                    if (!elements.historyBody.textContent.includes('Class A')) throw new Error('Historical row did not load');
                    elements.historyBody.querySelector('.history-open').click();
                    const select = document.querySelector('[aria-label="Manual final grade"]'); select.value = 'C'; select.dispatchEvent(new Event('change'));
                    document.querySelector('.manual-review-panel input').value = 'Smoke reviewer';
                    document.querySelector('.manual-review-panel button.primary').click();
                    for (let i=0; i<100 && !document.querySelector('.manual-review-message')?.textContent.includes('Class C'); i++) await pause();
                    return document.querySelector('.manual-review-message')?.textContent;
                })()""".replace("PAST", json.dumps(past))
                message = evaluate(script, 1)
                if "Class C" not in (message or ""):
                    raise AssertionError(message)
            assert db.events(session_id=past)[0]["manual_grade"] == "Class C"
            assert not db.events(session_id=current)[0].get("manual_override")
            print("Historical review selected the past session, retained its AI grade, and left the current fish unchanged.")
        finally:
            if browser and browser.poll() is None:
                browser.terminate()
                browser.wait(timeout=10)
            if api.poll() is None:
                api.terminate()
                api.wait(timeout=10)


if __name__ == "__main__":
    main()
