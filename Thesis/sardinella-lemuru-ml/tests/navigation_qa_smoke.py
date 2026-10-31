"""Headless navigation and responsive action smoke test with a temporary DB."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from websockets.sync.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard_status_smoke import free_port, wait_json


def main():
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    api_port, cdp_port = free_port(), free_port()
    output = Path(os.environ.get("TAMBAN_NAV_SMOKE_OUTPUT", Path(__file__).resolve().parents[1] / "qa" / "final"))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tamban_navigation_") as tmp:
        env = dict(os.environ, LEMURU_PORT=str(api_port), FISH_INSPECTION_DB_PATH=str(Path(tmp) / "test.sqlite3"), YOLO_CONFIG_DIR=tmp)
        hidden = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        code = "import os,uvicorn; from src.api.app import app; uvicorn.run(app,host='127.0.0.1',port=int(os.environ['LEMURU_PORT']))"
        api = subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
        browser = None
        try:
            wait_json(f"http://127.0.0.1:{api_port}/api/status/live", api)
            chrome_args = ["--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={Path(tmp) / 'chrome'}", f"--remote-debugging-port={cdp_port}", "--remote-allow-origins=*"]
            if os.getenv("TAMBAN_CHROME_NO_SANDBOX", "").strip().lower() in {"1", "true", "yes", "on"}:
                chrome_args.append("--no-sandbox")
            chrome_args.append(f"http://127.0.0.1:{api_port}/")
            browser = subprocess.Popen([str(chrome), *chrome_args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
            page = next(target for target in wait_json(f"http://127.0.0.1:{cdp_port}/json", browser) if target.get("type") == "page")
            with connect(page["webSocketDebuggerUrl"], open_timeout=5) as ws:
                counter = 0
                def command(method, params=None):
                    nonlocal counter
                    counter += 1
                    ws.send(json.dumps({"id": counter, "method": method, "params": params or {}}))
                    while True:
                        message = json.loads(ws.recv(timeout=15))
                        if message.get("id") == counter:
                            if "error" in message:
                                raise AssertionError(message["error"])
                            return message["result"]
                def evaluate(expression):
                    result = command("Runtime.evaluate", {"expression": expression, "returnByValue": True})
                    if "exceptionDetails" in result:
                        raise AssertionError(result["exceptionDetails"])
                    return result["result"].get("value")
                time.sleep(3)
                for width, height, label in ((1280, 900, "desktop"), (1366, 768, "laptop"), (1920, 1080, "wide"), (390, 844, "mobile"), (375, 812, "mobile375"), (768, 1024, "tablet")):
                    command("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600})
                    evaluate("document.querySelector('.overlay-settings').open = false")
                    for view in ("history", "review", "model", "live"):
                        evaluate(f"document.querySelector('[data-view={view}]').focus()")
                        command("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"})
                        command("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
                        assert evaluate(f"!document.getElementById('view-{view}').classList.contains('hidden')"), (label, view, evaluate("JSON.stringify({ready:document.readyState, focus:document.activeElement?.outerHTML, handler:typeof showView, inert:document.getElementById('app-shell').inert})"))
                    for name in ("settings", "export"):
                        header = f"{name}-button"
                        sidebar = f"sidebar-{name}"
                        visible = evaluate(f"[getComputedStyle(document.getElementById('{header}')).display !== 'none' && document.getElementById('{header}').getClientRects().length > 0, getComputedStyle(document.getElementById('{sidebar}')).display !== 'none' && document.getElementById('{sidebar}').getClientRects().length > 0]")
                        assert sum(visible) == 1, (label, name, visible)
                        target = header if visible[0] else sidebar
                        evaluate(f"document.getElementById('{target}').focus()")
                        command("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"})
                        command("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
                        panel = "settings-drawer" if name == "settings" else "export-modal"
                        assert evaluate(f"document.getElementById('{panel}').getAttribute('aria-hidden') === 'false'")
                        command("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
                    assert evaluate("document.getElementById('settings-grades').closest('section').classList.contains('hidden') && !document.querySelector('.overlay-settings').open")
                    evaluate("document.querySelector('.overlay-settings').open = true")
                    assert evaluate("document.getElementById('toggle-grades').getClientRects().length > 0")
                    assert evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), label
                    screenshot = command("Page.captureScreenshot", {"format": "png"})["data"]
                    (output / f"13_navigation_{label}.png").write_bytes(base64.b64decode(screenshot))
                evaluate("document.querySelector('[data-anchor=analytics-section]').click()")
                assert evaluate("document.getElementById('analytics-disclosure').open && !document.getElementById('view-live').classList.contains('hidden')")
                states = evaluate("""JSON.stringify((() => {
                  const results = {};
                  for (const value of ['stopped', 'starting', 'running', 'stopping', 'errored']) {
                    streamAttached = true;
                    renderCamera({...latestStatus, model_status:'ready', inspection_status:value, message:'Synthetic tracker error'});
                    results[value] = {state:elements.inspectionState.textContent.trim(), start:elements.start.disabled, stop:elements.stop.disabled, description:elements.placeholderCopy.textContent, visibleStarts:[elements.start, elements.emptyStart].filter(button => button.getClientRects().length > 0).length};
                  }
                  renderCamera(latestStatus);
                  return results;
                })())""")
                states = json.loads(states)
                assert states['stopped']['stop'] and not states['stopped']['start']
                assert states['starting']['start'] and not states['starting']['stop']
                assert states['running']['start'] and not states['running']['stop']
                assert states['stopping']['start'] and states['stopping']['stop']
                assert states['errored']['description'] == 'Synthetic tracker error'
                assert all(state['visibleStarts'] == 1 for state in states.values()), states
                (output / "14_synthetic_states.json").write_text(json.dumps(states, indent=2), encoding="utf-8")
                print("PASS: keyboard navigation, Settings/Export, Live analytics and 375/390/768/1280/1366/1920 px visibility")
                print("PASS: simulated stopped/starting/running/stopping/error controls")
        finally:
            if browser is not None:
                browser.terminate()
                browser.wait(timeout=10)
            api.terminate()
            api.wait(timeout=10)


if __name__ == "__main__":
    main()
