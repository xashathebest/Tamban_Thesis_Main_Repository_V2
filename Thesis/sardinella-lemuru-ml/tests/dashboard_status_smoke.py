"""Headless Chrome smoke test for status polling; requires websockets and Chrome."""
from __future__ import annotations

import json
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from websockets.sync.client import connect
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.api.database import InspectionDatabase


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_json(url: str, process: subprocess.Popen, timeout: float = 30) -> object:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process.poll() is None:
        try:
            with urlopen(url, timeout=1) as response:
                return json.load(response)
        except OSError:
            time.sleep(.2)
    raise RuntimeError(f"Service did not respond: {url}; exit={process.poll()}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-file", type=Path)
    args = parser.parse_args()
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.is_file():
        raise RuntimeError("Chrome executable not found")
    api_port, cdp_port = free_port(), free_port()
    with tempfile.TemporaryDirectory(prefix="tamban_dashboard_") as tmp:
        env = dict(os.environ, LEMURU_PORT=str(api_port), FISH_INSPECTION_DB_PATH=str(Path(tmp) / "test.sqlite3"), YOLO_CONFIG_DIR=tmp)
        hidden = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        server_code = ("import importlib, os, uvicorn; m=importlib.import_module('src.api.app'); "
                       "m.inspection_sessions.start({}); uvicorn.run(m.app, host='127.0.0.1', port=int(os.environ['LEMURU_PORT']))")
        api = subprocess.Popen([sys.executable, "-c", server_code], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
        browser = None
        try:
            initial_status = wait_json(f"http://127.0.0.1:{api_port}/api/status/live", api)
            session_id = initial_status["durable_session"]["session_id"]
            browser = subprocess.Popen([str(chrome), "--headless=new", "--disable-gpu", "--no-first-run",
                                        f"--user-data-dir={Path(tmp) / 'chrome'}", f"--remote-debugging-port={cdp_port}",
                                        "--remote-allow-origins=*", f"http://127.0.0.1:{api_port}/"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
            targets = wait_json(f"http://127.0.0.1:{cdp_port}/json", browser)
            page = next(target for target in targets if target.get("type") == "page")
            with connect(page["webSocketDebuggerUrl"], open_timeout=5) as ws:
                time.sleep(5)
                expression = """JSON.stringify({title: document.title,
                  status: typeof latestStatus === 'undefined' ? null : latestStatus.inspection_status,
                  analytics: typeof latestStatus === 'undefined' ? false : Boolean(latestStatus.analytics),
                  gradeCount: latestStatus?.analytics?.grade_distribution?.Ungraded,
                  manualReviewed: latestStatus?.analytics?.manual_reviewed,
                  live: performance.getEntriesByType('resource').filter(x => x.name.includes('/api/status/live')).length,
                  analyticsRequests: performance.getEntriesByType('resource').filter(x => x.name.includes('/api/analytics?')).length})"""
                def read_page(number):
                    ws.send(json.dumps({"id": number, "method": "Runtime.evaluate", "params": {"expression": expression, "returnByValue": True}}))
                    while True:
                        message = json.loads(ws.recv(timeout=10))
                        if message.get("id") == number:
                            return json.loads(message["result"]["result"]["value"])
                next_id = 100
                def evaluate(script):
                    nonlocal next_id
                    next_id += 1
                    ws.send(json.dumps({"id": next_id, "method": "Runtime.evaluate", "params": {"expression": script, "returnByValue": True}}))
                    while True:
                        message = json.loads(ws.recv(timeout=10))
                        if message.get("id") == next_id:
                            if "exceptionDetails" in message["result"]:
                                raise AssertionError(message["result"]["exceptionDetails"])
                            return message["result"]["result"].get("value")
                result = read_page(1)
                if result["status"] != "stopped" or not result["analytics"] or result["live"] < 2 or result["analyticsRequests"] != 1:
                    raise AssertionError(result)
                if args.profile_file:
                    instrument = """(() => {
                      window.__pollProfile = {samples: [], analyticsCalls: 0, mutations: 0};
                      const originalRender = render, originalAnalytics = renderAnalytics;
                      render = function(...args) { const start = performance.now(); try { return originalRender(...args); }
                        finally { window.__pollProfile.samples.push(performance.now() - start); } };
                      renderAnalytics = function(...args) { window.__pollProfile.analyticsCalls++; return originalAnalytics(...args); };
                      new MutationObserver(records => { window.__pollProfile.mutations += records.length; }).observe(document.querySelector('#view-live'),
                        {subtree: true, childList: true, attributes: true, characterData: true}); return true;
                    })()"""
                    ws.send(json.dumps({"id": 10, "method": "Runtime.evaluate", "params": {"expression": instrument, "returnByValue": True}}))
                    while json.loads(ws.recv(timeout=10)).get("id") != 10:
                        pass
                    time.sleep(5)
                    ws.send(json.dumps({"id": 11, "method": "Runtime.evaluate", "params": {"expression": "JSON.stringify(window.__pollProfile)", "returnByValue": True}}))
                    while True:
                        message = json.loads(ws.recv(timeout=10))
                        if message.get("id") == 11:
                            profile = json.loads(message["result"]["result"]["value"])
                            break
                    with args.profile_file.open("x", encoding="utf-8") as handle:
                        json.dump(profile, handle, indent=2)
                    print("profile:", json.dumps(profile))
                database = InspectionDatabase(Path(tmp) / "test.sqlite3")
                database.upsert_event(session_id, {"track_id": 1, "timestamp": "2026-01-01T00:00:00+00:00", "quality": "Ungraded",
                                                  "manual_override": False, "analysis": {"final_grade": "Ungraded", "verdict_status": "NEEDS_REVIEW"}})
                time.sleep(3)
                inserted = read_page(2)
                if inserted["gradeCount"] != 1 or inserted["analyticsRequests"] != 2:
                    raise AssertionError(inserted)
                database.apply_manual_review(session_id, 1, "Class A")
                time.sleep(3)
                reviewed = read_page(3)
                if reviewed["manualReviewed"] != 1 or reviewed["analyticsRequests"] != 3:
                    raise AssertionError(reviewed)
                for track_id in range(2, 28):
                    database.upsert_event(session_id, {"track_id": track_id, "timestamp": "2026-01-01T00:00:00+00:00", "quality": "Ungraded",
                                                      "manual_override": False, "analysis": {"final_grade": "Ungraded", "verdict_status": "NEEDS_REVIEW"}})
                time.sleep(3)
                evaluate("showView('history')")
                time.sleep(2)
                page_one = json.loads(evaluate("JSON.stringify({rows: elements.historyBody.rows.length, page: elements.historyPage.textContent, next: !elements.historyNext.disabled, requests: performance.getEntriesByType('resource').filter(x => x.name.includes('/api/history?')).length})"))
                time.sleep(2)
                stable_requests = evaluate("performance.getEntriesByType('resource').filter(x => x.name.includes('/api/history?')).length")
                if page_one["rows"] != 25 or page_one["page"] != "Page 1 of 2" or not page_one["next"] or stable_requests != page_one["requests"]:
                    raise AssertionError((page_one, stable_requests))
                evaluate("elements.historyNext.click()")
                time.sleep(1)
                page_two = json.loads(evaluate("JSON.stringify({rows: elements.historyBody.rows.length, page: elements.historyPage.textContent})"))
                if page_two != {"rows": 2, "page": "Page 2 of 2"}:
                    raise AssertionError(page_two)
                # Delay history requests, change views twice, then ensure the newest view wins.
                evaluate("""window.__realFetch = window.fetch; window.fetch = async (url, options) => {
                  if (String(url).includes('/api/history?')) await new Promise(resolve => setTimeout(resolve, 1500));
                  return window.__realFetch(url, options);
                }; showView('review'); showView('history'); showView('review'); true""")
                time.sleep(3)
                rapid = json.loads(evaluate("JSON.stringify({view: selectedView, rows: elements.reviewBody.rows.length, aborted: historyController === null || historyController.signal.aborted})"))
                if rapid["view"] != "review" or rapid["rows"] != 25 or not rapid["aborted"]:
                    raise AssertionError(rapid)
                evaluate("window.fetch = window.__realFetch; elements.reviewBody.querySelector('.review-action').click(); const select = document.querySelector('[aria-label=\"Manual final grade\"]'); select.value = 'B'; select.dispatchEvent(new Event('change')); document.querySelector('.manual-review-panel button').click(); true")
                time.sleep(3)
                saved = evaluate("document.querySelector('.manual-review-message')?.textContent || ''")
                if "Class B" not in saved:
                    raise AssertionError(saved)
                evaluate("document.querySelector('#history-analysis-dialog').close(); Object.defineProperty(document, 'hidden', {value: true, configurable: true}); document.dispatchEvent(new Event('visibilitychange')); true")
                time.sleep(1)
                hidden_before = evaluate("performance.getEntriesByType('resource').filter(x => x.name.includes('/api/status/live')).length")
                time.sleep(2)
                hidden_after = evaluate("performance.getEntriesByType('resource').filter(x => x.name.includes('/api/status/live')).length")
                evaluate("Object.defineProperty(document, 'hidden', {value: false, configurable: true}); document.dispatchEvent(new Event('visibilitychange')); true")
                time.sleep(2)
                resumed = evaluate("performance.getEntriesByType('resource').filter(x => x.name.includes('/api/status/live')).length")
                if hidden_before != hidden_after or resumed <= hidden_after:
                    raise AssertionError((hidden_before, hidden_after, resumed))
                print(json.dumps({"history_page_one": page_one, "history_page_two": page_two, "rapid_views": rapid,
                                  "review": saved, "hidden_polls": [hidden_before, hidden_after], "resumed_polls": resumed}, indent=2))
            print(json.dumps({"initial": result, "after_insert": inserted, "after_review": reviewed}, indent=2))
        finally:
            if browser and browser.poll() is None:
                browser.terminate()
                browser.wait(timeout=10)
            if api.poll() is None:
                api.terminate()
                api.wait(timeout=10)


if __name__ == "__main__":
    main()
