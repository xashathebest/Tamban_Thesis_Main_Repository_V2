"""Server-only OAuth PKCE and allowlisted Google Drive transport.

No SDK or credentials are bundled. OAuth uses a short-lived loopback callback
with access logging disabled; authorization codes and tokens never enter the UI.
Protocol references: Google's desktop OAuth and Drive v3 documentation.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


FOLDER_RE = re.compile(r"[A-Za-z0-9_-]{10,200}\Z")
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
# The existing owner-specified folder requires user-account Drive authorization.
# The transport enforces a single destination and never updates/deletes files.
SCOPE = "https://www.googleapis.com/auth/drive"


class DriveHTTPError(Exception):
    def __init__(self, status_code: int, detail: str = "Drive request failed.", retry_after: float | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.retry_after = retry_after


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GoogleHTTP:
    """Bounded HTTPS requests without forwarding credentials through redirects."""
    def request(self, method, url, *, headers=None, body=None):
        target = urlsplit(url)
        if target.scheme != "https" or target.hostname not in {"www.googleapis.com", "oauth2.googleapis.com"} or target.username:
            raise DriveHTTPError(400, "Unexpected Google API destination.")
        req = Request(url, data=body, headers=headers or {}, method=method)
        try:
            with build_opener(_NoRedirect).open(req, timeout=15) as response:
                data = response.read(4 * 1024 * 1024 + 1)
                if len(data) > 4 * 1024 * 1024:
                    raise DriveHTTPError(502, "Drive response exceeded the limit.")
                return response.status, dict(response.headers), json.loads(data) if data else {}
        except HTTPError as exc:
            retry = exc.headers.get("Retry-After", "") if exc.headers else ""
            raise DriveHTTPError(exc.code, f"Google API returned HTTP {exc.code}.", float(retry) if retry.isdigit() else None) from None
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise DriveHTTPError(503, "Google API unavailable; local originals remain saved.") from None


def _protect(data: bytes, decrypt=False) -> bytes:
    """Windows current-user DPAPI; private filesystem permissions elsewhere."""
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, result = Blob(len(data), buffer), Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    fn.restype = wintypes.BOOL
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise DriveHTTPError(401, "The current OS user cannot access saved Drive authorization.")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


class PrivateTokenStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self):
        if not self.path.exists():
            return {}
        raw = self.path.read_bytes()
        if raw.startswith(b"DPAPI1\n") and os.name == "nt":
            raw = _protect(raw[7:], decrypt=True)
        elif raw.startswith(b"PRIVATE1\n") and os.name != "nt":
            if self.path.stat().st_mode & 0o077:
                raise DriveHTTPError(401, "Saved Drive authorization permissions must be private.")
            raw = raw[9:]
        else:
            raise DriveHTTPError(401, "Saved Drive authorization is not usable by this OS user.")
        return json.loads(raw)

    def save(self, value):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        raw = json.dumps(value).encode("utf-8")
        raw = b"DPAPI1\n" + _protect(raw) if os.name == "nt" else b"PRIVATE1\n" + raw
        temporary = self.path.with_name(self.path.name + "." + secrets.token_hex(6) + ".tmp")
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()


class OAuthManager:
    def __init__(self, private_root: Path, *, http=None, client_file=None, clock=time.time):
        self.http = http or GoogleHTTP()
        self.clock = clock
        self.token_store = PrivateTokenStore(private_root / "drive-authorization.bin")
        self.client_file = client_file or os.getenv("FISH_CAPTURE_OAUTH_CLIENT_FILE")
        self._lock = threading.RLock()
        self._tokens = {}
        self._pending = None
        self._stop = threading.Event()
        self._worker = None
        self.last_error = None
        try:
            self._tokens = self.token_store.load()
        except (OSError, ValueError, DriveHTTPError):
            self.last_error = "Saved Drive authorization is unavailable; reconnect using this OS account."

    def _client(self):
        if not self.client_file:
            raise DriveHTTPError(409, "Set FISH_CAPTURE_OAUTH_CLIENT_FILE to the server-side Desktop OAuth client JSON, then restart Capture.")
        try:
            path = Path(self.client_file)
            if path.stat().st_size > 65536:
                raise ValueError()
            config = json.loads(path.read_text(encoding="utf-8"))["installed"]
            client_id = config["client_id"]
            if not isinstance(client_id, str) or not client_id.endswith(".apps.googleusercontent.com"):
                raise ValueError()
            return {k: config[k] for k in ("client_id", "client_secret") if config.get(k)}
        except (OSError, ValueError, KeyError, TypeError):
            raise DriveHTTPError(409, "The server needs a valid Google Desktop OAuth client JSON file.") from None

    def status(self):
        try:
            self._client()
            configured = True
        except DriveHTTPError:
            configured = False
        with self._lock:
            return {"oauth_configured": configured, "connected": bool(self._tokens.get("refresh_token") or self._tokens.get("access_token")),
                    "authorization_pending": bool(self._pending), "error": self.last_error,
                    "scope": SCOPE}

    def start_authorization(self):
        client = self._client()
        with self._lock:
            if self._worker and self._worker.is_alive():
                raise DriveHTTPError(409, "A Google consent window is already pending.")
            verifier = secrets.token_urlsafe(64)
            state = secrets.token_urlsafe(32)
            manager = self

            class Callback(BaseHTTPRequestHandler):
                def setup(self):
                    super().setup()
                    self.connection.settimeout(5)

                def log_message(self, *_args):
                    pass

                def do_GET(self):
                    parsed = urlsplit(self.path)
                    if parsed.path != "/oauth/callback" or len(self.path) > 8192:
                        self.send_error(404)
                        return
                    query = parse_qs(parsed.query)
                    success = False
                    try:
                        manager.finish_authorization(query.get("state", [""])[0], query.get("code", [""])[0], query.get("error", [None])[0])
                        success = True
                    except DriveHTTPError:
                        pass
                    body = ("Drive authorization received. Return to Camera Capture and test folder access." if success else
                            "Drive authorization did not complete. Return to Camera Capture and reconnect.").encode()
                    self.send_response(200 if success else 400)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            server = HTTPServer(("127.0.0.1", 0), Callback)
            server.timeout = 0.5
            redirect = f"http://127.0.0.1:{server.server_port}/oauth/callback"
            self._pending = {"state": state, "verifier": verifier, "redirect_uri": redirect, "expires": self.clock() + 300}
            self._stop.clear()

            def listen():
                try:
                    while not self._stop.is_set():
                        pending = self._pending
                        if not pending or self.clock() >= pending["expires"]:
                            break
                        server.handle_request()
                finally:
                    server.server_close()
                    with self._lock:
                        self._pending = None

            self._worker = threading.Thread(target=listen, name="capture-oauth-loopback", daemon=True)
            self._worker.start()
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            params = {"client_id": client["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
                      "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent"}
            return {"authorization_url": AUTH_URL + "?" + urlencode(params), "expires_in": 300}

    def finish_authorization(self, state, code, error=None):
        with self._lock:
            pending = self._pending
            if not pending or self.clock() >= pending["expires"] or not isinstance(state, str) or not secrets.compare_digest(state, pending["state"]):
                raise DriveHTTPError(400, "Invalid or expired OAuth state.")
            self._pending = None
            if error or not code or len(code) > 4096:
                self.last_error = "Google consent was cancelled or denied. Local capture remains available."
                raise DriveHTTPError(401, self.last_error)
            fields = {**self._client(), "code": code, "code_verifier": pending["verifier"], "redirect_uri": pending["redirect_uri"], "grant_type": "authorization_code"}
            try:
                _, _, tokens = self.http.request("POST", TOKEN_URL, headers={"Content-Type": "application/x-www-form-urlencoded"}, body=urlencode(fields).encode())
                self._accept_tokens(tokens)
            except DriveHTTPError:
                self.last_error = "Google authorization exchange failed; reconnect to retry."
                raise

    def _accept_tokens(self, tokens):
        if not isinstance(tokens.get("access_token"), str) or not tokens["access_token"]:
            raise DriveHTTPError(401, "Google did not return an access token.")
        scope = tokens.get("scope", SCOPE).split()
        if SCOPE not in scope:
            raise DriveHTTPError(403, "Google did not grant the requested Drive authorization.")
        merged = {**self._tokens, **tokens, "expires_at": self.clock() + float(tokens.get("expires_in", 3600))}
        self.token_store.save(merged)
        self._tokens = merged
        self.last_error = None

    def access_token(self):
        with self._lock:
            if self._tokens.get("access_token") and self._tokens.get("expires_at", 0) > self.clock() + 60:
                return self._tokens["access_token"]
            if not self._tokens.get("refresh_token"):
                raise DriveHTTPError(401, "Connect Google Drive using OAuth consent first.")
            fields = {**self._client(), "refresh_token": self._tokens["refresh_token"], "grant_type": "refresh_token"}
            try:
                _, _, tokens = self.http.request("POST", TOKEN_URL, headers={"Content-Type": "application/x-www-form-urlencoded"}, body=urlencode(fields).encode())
                self._accept_tokens(tokens)
            except DriveHTTPError:
                self.last_error = "Drive authorization needs attention; reconnect if authorization expired or was revoked."
                raise
            return self._tokens["access_token"]

    def close(self):
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=1.5)


class GoogleDriveClient:
    """Immutable originals with idempotent search, checksum proof and one root."""
    def __init__(self, oauth: OAuthManager, folder_id: str, *, http=None):
        if not FOLDER_RE.fullmatch(folder_id):
            raise DriveHTTPError(400, "Invalid allowlisted Drive folder ID.")
        self.oauth, self.root, self.http = oauth, folder_id, http or oauth.http

    def _request(self, method, url=DRIVE_URL, *, params=None, body=None, content_type="application/json"):
        if params:
            url += "?" + urlencode(params)
        headers = {"Authorization": "Bearer " + self.oauth.access_token(), "Content-Type": content_type}
        _, response_headers, data = self.http.request(method, url, headers=headers, body=body)
        return response_headers, data

    def _get(self, file_id, fields):
        if not FOLDER_RE.fullmatch(file_id):
            raise DriveHTTPError(400, "Invalid Drive file identity.")
        return self._request("GET", DRIVE_URL + "/" + file_id, params={"fields": fields, "supportsAllDrives": "true"})[1]

    def test_access(self):
        folder = self._get(self.root, "id,name,mimeType,trashed,capabilities(canAddChildren,canListChildren),driveId")
        if folder.get("id") != self.root or folder.get("trashed") or folder.get("mimeType") != "application/vnd.google-apps.folder":
            raise DriveHTTPError(403, "The authorized destination is not an available Drive folder.")
        capabilities = folder.get("capabilities", {})
        if not capabilities.get("canAddChildren") or not capabilities.get("canListChildren"):
            raise DriveHTTPError(403, "This account cannot add and verify files in the destination folder.")
        return {"folder_id": self.root, "folder_name": folder.get("name"), "can_upload": True,
                "drive_type": "shared_drive" if folder.get("driveId") else "my_drive", "verified": True}

    def _list(self, query):
        return self._request("GET", params={"q": query, "spaces": "drive", "fields": "files(id,name,parents,mimeType,sha256Checksum,size),nextPageToken",
                                             "pageSize": 100, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"})[1]

    def _under_root(self, file):
        parents = file.get("parents", [])
        for _ in range(6):
            if self.root in parents:
                return True
            if len(parents) != 1:
                return False
            folder = self._get(parents[0], "id,parents,mimeType,trashed")
            if folder.get("trashed") or folder.get("mimeType") != "application/vnd.google-apps.folder":
                return False
            parents = folder.get("parents", [])
        return False

    def find_file(self, idempotency_key, folder_id):
        if folder_id != self.root or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", idempotency_key):
            raise DriveHTTPError(400, "Upload destination or capture identity is not allowlisted.")
        result = self._list(f"trashed = false and appProperties has {{ key='capture_id' and value='{idempotency_key}' }} and appProperties has {{ key='capture_root' and value='{self.root}' }}")
        files = result.get("files", [])
        if result.get("nextPageToken") or len(files) > 1:
            raise DriveHTTPError(409, "More than one remote file claims this capture identity; review is required.")
        if not files:
            return None
        file = files[0]
        if not self._under_root(file):
            raise DriveHTTPError(403, "The mapped remote original is outside the authorized destination.")
        return {"id": file["id"], "sha256": file.get("sha256Checksum"), "size": file.get("size")}

    def _folder(self, parent, name, key):
        result = self._list(f"trashed = false and '{parent}' in parents and mimeType = 'application/vnd.google-apps.folder' and appProperties has {{ key='capture_folder' and value='{key}' }}")
        if result.get("nextPageToken") or len(result.get("files", [])) > 1:
            raise DriveHTTPError(409, "Capture subfolder identity is ambiguous; review Drive before retrying.")
        if result.get("files"):
            return result["files"][0]["id"]
        metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent], "appProperties": {"capture_folder": key, "capture_root": self.root}}
        data = self._request("POST", params={"fields": "id", "supportsAllDrives": "true"}, body=json.dumps(metadata).encode())[1]
        if not FOLDER_RE.fullmatch(data.get("id", "")):
            raise DriveHTTPError(502, "Drive did not confirm the capture subfolder.")
        return data["id"]

    def upload_file(self, path, *, filename, folder_id, idempotency_key, sha256, metadata):
        return self._upload(path, filename=filename, folder_id=folder_id, idempotency_key=idempotency_key,
                            sha256=sha256, metadata=metadata, manifest=False)

    def upload_manifest(self, path, *, filename, folder_id, idempotency_key, sha256, metadata):
        if not filename.lower().endswith((".csv", ".json")):
            raise DriveHTTPError(400, "A manifest must be CSV or JSON.")
        return self._upload(path, filename=filename, folder_id=folder_id, idempotency_key=idempotency_key,
                            sha256=sha256, metadata=metadata, manifest=True)

    def _upload(self, path, *, filename, folder_id, idempotency_key, sha256, metadata, manifest):
        if folder_id != self.root:
            raise DriveHTTPError(400, "Drive destination is not allowlisted.")
        existing = self.find_file(idempotency_key, folder_id)
        if existing:
            return existing
        self.test_access()
        path = Path(path)
        if path.stat().st_size > 64 * 1024 * 1024:
            raise DriveHTTPError(413, "This raw file exceeds the bounded upload limit.")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != sha256:
            raise DriveHTTPError(409, "Local checksum mismatch; the original was not uploaded.")
        session_id = str(metadata.get("session_id", ""))
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", session_id):
            raise DriveHTTPError(400, "Capture session lineage is missing.")
        date = str(metadata.get("captured_utc", ""))[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise DriveHTTPError(400, "Capture date lineage is missing.")
        date_id = self._folder(self.root, date, "date:" + date)
        session_folder = self._folder(date_id, session_id, "session:" + session_id)
        parent = session_folder if manifest else self._folder(session_folder, "raw", "raw:" + session_id)
        mime = (("application/json" if filename.lower().endswith(".json") else "text/csv") if manifest else
                "image/png" if filename.lower().endswith(".png") else "image/jpeg")
        descriptor = {"name": Path(filename).name, "parents": [parent], "appProperties": {"capture_id": idempotency_key, "capture_root": self.root, "capture_session": session_id, "capture_sha256": sha256}}
        headers, _ = self._request("POST", UPLOAD_URL, params={"uploadType": "resumable", "fields": "id,sha256Checksum,size", "supportsAllDrives": "true"}, body=json.dumps(descriptor).encode())
        location = next((v for k, v in headers.items() if k.lower() == "location"), "")
        target = urlsplit(location)
        if target.scheme != "https" or target.hostname != "www.googleapis.com" or not target.path.startswith("/upload/drive/") or target.username:
            raise DriveHTTPError(502, "Drive did not return a safe resumable upload location.")
        result = self._request("PUT", location, body=data, content_type=mime)[1]
        if not FOLDER_RE.fullmatch(result.get("id", "")):
            raise DriveHTTPError(502, "Drive did not confirm an uploaded file ID.")
        verified = self._get(result["id"], "id,sha256Checksum,size,parents")
        if not self._under_root(verified):
            raise DriveHTTPError(403, "Uploaded original could not be verified inside the destination.")
        return {"id": verified["id"], "sha256": verified.get("sha256Checksum"), "size": verified.get("size")}
