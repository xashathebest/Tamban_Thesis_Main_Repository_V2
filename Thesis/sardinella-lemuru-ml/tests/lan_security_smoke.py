"""Exercise the LAN sign-in, CSRF and sign-out flow in headless Chrome."""
from __future__ import annotations

import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from websockets.sync.client import connect
from dashboard_status_smoke import free_port, wait_json


def main():
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    openssl = Path(r"C:\Program Files\Git\usr\bin\openssl.exe")
    if not chrome.is_file() or not openssl.is_file():
        raise RuntimeError("Chrome and Git's OpenSSL are required for this smoke test")
    api_port, cdp_port = free_port(), free_port()
    with tempfile.TemporaryDirectory(prefix="tamban_lan_smoke_") as tmp:
        cert, key = Path(tmp) / "cert.pem", Path(tmp) / "key.pem"
        hidden = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.run([str(openssl), "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-keyout", str(key),
                        "-out", str(cert), "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden)
        token = "synthetic-operator-token-" + "x" * 40
        env = dict(os.environ, LEMURU_HOST="127.0.0.1", LEMURU_PORT=str(api_port), LEMURU_TLS_CERTFILE=str(cert),
                   LEMURU_TLS_KEYFILE=str(key), FISH_LAN_AUTH="1", FISH_LAN_OPERATOR_TOKEN=token,
                   FISH_INSPECTION_DB_PATH=str(Path(tmp) / "test.sqlite3"), YOLO_CONFIG_DIR=tmp)
        env.pop("FISH_LAN_VIEWER_TOKEN", None)
        env.pop("FISH_LAN_ADMIN_TOKEN", None)
        api = subprocess.Popen([sys.executable, "-m", "src.api"], env=env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=hidden)
        browser = None
        try:
            address = f"https://localhost:{api_port}"
            context = ssl._create_unverified_context()  # Ephemeral self-signed certificate in this test only.
            deadline = time.monotonic() + 30
            while True:
                try:
                    with urlopen(address + "/api/auth/mode", context=context, timeout=1) as response:
                        assert json.load(response)["lan_security"]
                    break
                except OSError:
                    if time.monotonic() >= deadline or api.poll() is not None:
                        raise RuntimeError("HTTPS test server did not start")
                    time.sleep(.2)
            browser = subprocess.Popen([str(chrome), "--headless=new", "--disable-gpu", "--no-first-run", "--ignore-certificate-errors",
                                        f"--user-data-dir={Path(tmp) / 'chrome'}", f"--remote-debugging-port={cdp_port}",
                                        "--remote-allow-origins=*", address + "/"], stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, creationflags=hidden)
            page = next(target for target in wait_json(f"http://127.0.0.1:{cdp_port}/json", browser) if target.get("type") == "page")
            with connect(page["webSocketDebuggerUrl"], open_timeout=5) as ws:
                script = """(async () => {
                  const pause = () => new Promise(resolve => setTimeout(resolve, 100));
                  for (let i=0; i<100 && !document.querySelector('#lan-login-dialog')?.open; i++) await pause();
                  if (!document.querySelector('#lan-login-dialog')?.open) throw new Error('No login dialog');
                  document.querySelector('#lan-token').value = TOKEN;
                  document.querySelector('#lan-login-form').requestSubmit();
                  for (let i=0; i<100 && document.querySelector('#lan-login-dialog').open; i++) await pause();
                  if (document.querySelector('#lan-login-dialog').open) throw new Error('Login did not complete');
                  const missing = await unwrappedFetch('/api/reviews/1', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
                  const protectedRequest = await fetch('/api/reviews/1', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
                  const visibleCookie = document.cookie.includes('__Host-tamban_session');
                  document.querySelector('#lan-logout').click();
                  for (let i=0; i<100 && !document.querySelector('#lan-login-dialog').open; i++) await pause();
                  return JSON.stringify({missing:missing.status, protected:protectedRequest.status, visibleCookie, loggedOut:document.querySelector('#lan-login-dialog').open});
                })()""".replace("TOKEN", json.dumps(token))
                ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": script, "returnByValue": True, "awaitPromise": True}}))
                while True:
                    message = json.loads(ws.recv(timeout=20))
                    if message.get("id") == 1:
                        if "exceptionDetails" in message["result"]:
                            raise AssertionError(message["result"]["exceptionDetails"])
                        result = json.loads(message["result"]["result"]["value"])
                        break
                assert result == {"missing": 403, "protected": 422, "visibleCookie": False, "loggedOut": True}, result
                print("HTTPS browser sign-in, HttpOnly cookie, CSRF rejection, authorized request, and sign-out passed.")
        finally:
            if browser and browser.poll() is None:
                browser.terminate()
                browser.wait(timeout=10)
            if api.poll() is None:
                api.terminate()
                api.wait(timeout=10)


if __name__ == "__main__":
    main()
