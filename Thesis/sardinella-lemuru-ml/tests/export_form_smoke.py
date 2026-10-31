"""Exercise the export form and hidden tracker fallback in headless Chrome."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from websockets.sync.client import connect
from dashboard_status_smoke import free_port, wait_json
from src.api.database import InspectionDatabase


def main() -> None:
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.is_file():
        raise RuntimeError("Chrome executable not found")
    api_port, cdp_port = free_port(), free_port()
    with tempfile.TemporaryDirectory(prefix="tamban_export_smoke_") as tmp:
        database_path = Path(tmp) / "history.sqlite3"
        database = InspectionDatabase(database_path)
        historical_session = database.create_session({"started_at": "2020-01-01T00:00:00+00:00"})
        database.upsert_event(historical_session, {"track_id": 1, "timestamp": "2020-01-01T00:00:00+00:00", "quality": "Class A", "analysis": {}})
        database.create_session({"started_at": "2021-01-01T00:00:00+00:00"})
        env = dict(os.environ, FISH_INSPECTION_DB_PATH=str(database_path), PYTHONDONTWRITEBYTECODE="1")
        hidden = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        code = ("import importlib, uvicorn; m=importlib.import_module('src.api.app'); "
                f"uvicorn.run(m.app, host='127.0.0.1', port={api_port}, lifespan='off')")
        server = subprocess.Popen([sys.executable, "-B", "-c", code], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
        browser = None
        try:
            wait_json(f"http://127.0.0.1:{api_port}/api/status/live", server)
            chrome_args = ["--headless=new", "--disable-gpu", "--no-first-run",
                           f"--user-data-dir={Path(tmp) / 'chrome'}", f"--remote-debugging-port={cdp_port}",
                           "--remote-allow-origins=*"]
            # Keep this reduced-sandbox setting explicit and test-only; it is
            # needed only in constrained Windows QA environments.
            if os.getenv("TAMBAN_CHROME_NO_SANDBOX", "").strip().lower() in {"1", "true", "yes", "on"}:
                chrome_args.append("--no-sandbox")
            chrome_args.append(f"http://127.0.0.1:{api_port}/")
            browser = subprocess.Popen([str(chrome), *chrome_args],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
            page = next(item for item in wait_json(f"http://127.0.0.1:{cdp_port}/json", browser) if item.get("type") == "page")
            with connect(page["webSocketDebuggerUrl"], open_timeout=5) as ws:
                counter = 0
                def evaluate(expression):
                    nonlocal counter
                    counter += 1
                    ws.send(json.dumps({"id": counter, "method": "Runtime.evaluate", "params": {"expression": expression, "returnByValue": True}}))
                    while True:
                        response = json.loads(ws.recv(timeout=10))
                        if response.get("id") == counter:
                            if "exceptionDetails" in response["result"]:
                                raise AssertionError(response["result"]["exceptionDetails"])
                            return response["result"]["result"].get("value")
                for _ in range(100):
                    if evaluate("typeof elements !== 'undefined' && !!document.querySelector('#export-all-evidence')"):
                        break
                    time.sleep(.1)
                else:
                    raise AssertionError("Export form did not load")
                evaluate("openExport(); true")
                for _ in range(100):
                    if evaluate(f"[...document.querySelector('#export-session').options].some(x => x.value === {json.dumps(historical_session)})"):
                        break
                    time.sleep(.1)
                else:
                    raise AssertionError("Historical inspection run did not load into the export selector")
                evaluate("""window.__exports = []; window.__originalFetch = window.fetch;
                  window.fetch = function(url, options) {
                    if (url === '/api/export') { window.__exports.push(JSON.parse(options.body)); return Promise.reject(new Error('Test interception')); }
                    return window.__originalFetch.apply(this, arguments);
                  }; true""")
                default_run = json.loads(evaluate("""(() => {
                  document.querySelector('input[name=export-range][value=current_session]').click();
                  document.querySelector('#export-form').requestSubmit(); return JSON.stringify(window.__exports[0]);
                })()"""))
                assert default_run["range"] == "current_session" and "session_id" not in default_run
                time.sleep(.1)
                historical_run = json.loads(evaluate("""(() => {
                  document.querySelector('input[name=export-range][value=specific_session]').click();
                  const select = document.querySelector('#export-session'); select.value = PAST; select.dispatchEvent(new Event('change', {bubbles:true}));
                  document.querySelector('#export-form').requestSubmit(); return JSON.stringify(window.__exports[1]);
                })()""".replace("PAST", json.dumps(historical_session))))
                assert historical_run["range"] == "current_session" and historical_run["session_id"] == historical_session
                time.sleep(.1)
                evaluate("document.querySelector('input[name=export-range][value=current_session]').click(); window.__exports = []; true")
                selected = json.loads(evaluate("""(() => {
                  document.querySelectorAll('.export-fields input').forEach(x => x.checked = ['fish_id', 'grade'].includes(x.value));
                  document.querySelector('#export-all-evidence').checked = false;
                  document.querySelector('#export-form').requestSubmit(); return JSON.stringify(window.__exports[0]);
                })()"""))
                assert selected["fields"] == ["fish_id", "grade"] and selected["complete_analysis"] is False
                full = json.loads(evaluate("""(() => {
                  document.querySelectorAll('.export-fields input').forEach(x => x.checked = false);
                  document.querySelector('#export-all-evidence').checked = true;
                  document.querySelector('#export-form').requestSubmit(); return JSON.stringify(window.__exports[1]);
                })()"""))
                assert full["fields"] == [] and full["complete_analysis"] is True
                empty = json.loads(evaluate("""(() => {
                  document.querySelector('#export-all-evidence').checked = false;
                  document.querySelector('#export-form').requestSubmit();
                  return JSON.stringify({calls: window.__exports.length, error: !document.querySelector('#export-fields-error').classList.contains('hidden')});
                })()"""))
                assert empty == {"calls": 2, "error": True}
                disabled = json.loads(evaluate("""(() => {
                  document.querySelector('#export-all-evidence').dispatchEvent(new Event('change', {bubbles:true}));
                  const noFields = document.querySelector('#confirm-export-button').disabled;
                  document.querySelector('#export-all-evidence').checked = true;
                  document.querySelector('#export-all-evidence').dispatchEvent(new Event('change', {bubbles:true}));
                  const valid = !document.querySelector('#confirm-export-button').disabled;
                  document.querySelector('input[name=export-range][value=custom]').click();
                  const openRange = !document.querySelector('#confirm-export-button').disabled;
                  document.querySelector('#export-start-date').value = '2026-10-18';
                  document.querySelector('#export-end-date').value = '2026-10-17';
                  document.querySelector('#export-end-date').dispatchEvent(new Event('input', {bubbles:true}));
                  const reversedDates = document.querySelector('#confirm-export-button').disabled;
                  return JSON.stringify({noFields, valid, openRange, reversedDates});
                })()"""))
                assert disabled == {"noFields": True, "valid": True, "openRange": True, "reversedDates": True}
                time.sleep(.1)
                # A failed request is visible inside the modal, not behind its scrim.
                evaluate("document.querySelector('input[name=export-range][value=current_session]').click(); document.querySelector('#export-form').requestSubmit()")
                time.sleep(.1)
                assert "Test interception" in evaluate("document.querySelector('#export-feedback').textContent")
                fallback = json.loads(evaluate("""(() => {
                  const data = {...latestStatus, model_status: 'ready', segmenter_status: 'ready',
                    inspection_status: 'stopped', runtime_mode: 'whole_fish',
                    tracker_backend: 'IoU fallback', tracker_warning: 'ByteTrack is unavailable.'};
                  renderAlert(data);
                  return JSON.stringify({visible: !elements.alert.classList.contains('hidden')});
                })()"""))
                assert fallback == {"visible": False}
                pending = json.loads(evaluate("""(() => {
                  window.__pendingExports = 0;
                  window.fetch = (url, options) => url === '/api/export'
                    ? (window.__pendingExports++, new Promise((resolve) => { window.__finishExport = resolve; }))
                    : window.__originalFetch(url, options);
                  document.querySelector('#export-form').requestSubmit();
                  document.querySelector('#export-all-evidence').dispatchEvent(new Event('change', {bubbles:true}));
                  document.querySelector('#export-form').requestSubmit();
                  return JSON.stringify({calls: window.__pendingExports, disabled: document.querySelector('#confirm-export-button').disabled});
                })()"""))
                assert pending == {"calls": 1, "disabled": True}
                evaluate("window.__finishExport(new Response(JSON.stringify({detail:'test'}), {status:400,headers:{'Content-Type':'application/json'}})); true")
                print("Selected-run export, export choices, validation, in-dialog failure and hidden tracker fallback passed")
        finally:
            if browser is not None:
                browser.terminate()
                browser.wait(timeout=10)
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    main()
