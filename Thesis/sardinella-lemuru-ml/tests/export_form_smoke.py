"""Exercise the export form and tracker warning in headless Chrome."""
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


def main() -> None:
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.is_file():
        raise RuntimeError("Chrome executable not found")
    api_port, cdp_port = free_port(), free_port()
    with tempfile.TemporaryDirectory(prefix="tamban_export_smoke_") as tmp:
        env = dict(os.environ, FISH_INSPECTION_DB_PATH=str(Path(tmp) / "history.sqlite3"), PYTHONDONTWRITEBYTECODE="1")
        hidden = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        code = ("import importlib, uvicorn; m=importlib.import_module('src.api.app'); "
                f"uvicorn.run(m.app, host='127.0.0.1', port={api_port}, lifespan='off')")
        server = subprocess.Popen([sys.executable, "-B", "-c", code], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
        browser = None
        try:
            wait_json(f"http://127.0.0.1:{api_port}/api/status/live", server)
            browser = subprocess.Popen([str(chrome), "--headless=new", "--disable-gpu", "--no-first-run",
                                        f"--user-data-dir={Path(tmp) / 'chrome'}", f"--remote-debugging-port={cdp_port}",
                                        "--remote-allow-origins=*", f"http://127.0.0.1:{api_port}/"],
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
                evaluate("""window.__exports = []; window.__originalFetch = window.fetch;
                  window.fetch = function(url, options) {
                    if (url === '/api/export') { window.__exports.push(JSON.parse(options.body)); return Promise.reject(new Error('Test interception')); }
                    return window.__originalFetch.apply(this, arguments);
                  }; true""")
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
                warning = json.loads(evaluate("""(() => {
                  const data = {...latestStatus, model_status: 'ready', segmenter_status: 'ready',
                    inspection_status: 'stopped', runtime_mode: 'whole_fish',
                    tracker_backend: 'IoU fallback', tracker_warning: 'ByteTrack is unavailable.'};
                  renderAlert(data); renderModel(data);
                  return JSON.stringify({visible: !elements.alert.classList.contains('hidden'),
                    title: elements.alertTitle.textContent, detail: elements.alertDetails.textContent,
                    tracker: elements.detectorTracker.textContent});
                })()"""))
                assert warning == {"visible": True, "title": "Tracker warning", "detail": "ByteTrack is unavailable.", "tracker": "IoU fallback"}
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
                print("Export choices, validation, in-dialog failure and tracker warning passed")
        finally:
            if browser is not None:
                browser.terminate()
                browser.wait(timeout=10)
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    main()
