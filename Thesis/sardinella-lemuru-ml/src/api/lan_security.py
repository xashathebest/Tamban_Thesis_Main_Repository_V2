"""Opt-in LAN authentication, role checks and browser-session CSRF protection."""
from __future__ import annotations

from collections import deque
from contextvars import ContextVar
from hashlib import sha256
import ipaddress
import json
import os
import secrets
from threading import RLock
from time import monotonic
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


router = APIRouter(prefix="/api/auth", include_in_schema=False)
COOKIE = "__Host-tamban_session"
SESSION_SECONDS = 8 * 60 * 60
_sessions: dict[str, dict[str, object]] = {}
_login_attempts: dict[str, deque[float]] = {}
_lock = RLock()
_levels = {"viewer": 1, "operator": 2, "admin": 3}
request_role: ContextVar[str | None] = ContextVar("lan_request_role", default=None)


def diagnostics_allowed() -> bool:
    return not enabled() or (os.getenv("FISH_LAN_DEBUG", "0") == "1" and request_role.get() == "admin")


def enabled() -> bool:
    return os.getenv("FISH_LAN_AUTH", "0").strip().lower() in {"1", "true", "yes", "on"}


def configured_tokens() -> dict[str, str]:
    tokens = {role: os.getenv(f"FISH_LAN_{role.upper()}_TOKEN", "") for role in _levels}
    tokens = {role: token for role, token in tokens.items() if token}
    if "operator" not in tokens:
        raise ValueError("Secure LAN mode requires an operator token.")
    if any(len(value) < 32 or len(value) > 512 or not value.isascii() or not value.isprintable() or any(ch.isspace() for ch in value) for value in tokens.values()):
        raise ValueError("LAN tokens must contain 32 to 512 non-whitespace ASCII characters.")
    if len(set(tokens.values())) != len(tokens):
        raise ValueError("LAN role tokens must be distinct.")
    return tokens


def _role(token: str, tokens: dict[str, str]) -> str | None:
    if not token.isascii() or len(token) > 512:
        return None
    for role, expected in tokens.items():
        if secrets.compare_digest(token, expected):
            return role
    return None


def _digest(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def _same_origin(request: Request) -> bool:
    try:
        origin = urlsplit(request.headers.get("origin", ""))
        target = urlsplit(str(request.base_url))
        if origin.scheme not in {"https", "http"} or origin.username or origin.password or origin.path or origin.query or origin.fragment:
            return False
        def effective_port(value):
            return value.port or (443 if value.scheme == "https" else 80)
        return (origin.scheme, origin.hostname, effective_port(origin)) == (target.scheme, target.hostname, effective_port(target))
    except ValueError:
        return False


def _failure(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status, headers={"Cache-Control": "no-store"})


def _allow_login(request: Request) -> bool:
    peer = request.client.host if request.client else "unknown"
    with _lock:
        now = monotonic()
        if peer not in _login_attempts and len(_login_attempts) >= 4096:
            for key in [key for key, attempts in _login_attempts.items() if not attempts or attempts[-1] <= now - 60]:
                _login_attempts.pop(key, None)
            if len(_login_attempts) >= 4096:
                return False
        attempts = _login_attempts.setdefault(peer, deque())
        while attempts and attempts[0] <= now - 60:
            attempts.popleft()
        if len(attempts) >= 10:
            return False
        attempts.append(now)
        return True


def _local_client(request: Request) -> bool:
    if not request.client:
        return False
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        # Starlette's in-process TestClient has no network peer address.
        return request.client.host == "testclient" and request.scope.get("server", (None,))[0] == "testserver"


def _session(request: Request, tokens: dict[str, str]) -> dict[str, object] | None:
    cookie = request.cookies.get(COOKIE, "")
    with _lock:
        session = _sessions.get(cookie)
        if session is None:
            return None
        role = session["role"]
        token = tokens.get(role)
        if session["expires"] <= monotonic() or token is None or not secrets.compare_digest(session["digest"], _digest(token)):
            _sessions.pop(cookie, None)
            return None
        return dict(session)


def stream_authorized(request: Request) -> bool:
    """Recheck credentials while an already-open camera stream is running."""
    if not enabled():
        return _local_client(request)
    try:
        tokens = configured_tokens()
    except ValueError:
        return False
    authorization = request.headers.get("authorization", "")
    if authorization:
        return authorization.startswith("Bearer ") and _role(authorization[7:], tokens) is not None
    return _session(request, tokens) is not None


async def guard(request: Request):
    path = request.url.path
    if not path.startswith("/api/"):
        return None
    if not enabled():
        if not _local_client(request):
            return _failure(403, "Remote access requires the secure LAN profile.")
        return None
    if path == "/api/auth/mode" and request.method == "GET":
        return None
    try:
        tokens = configured_tokens()
    except ValueError:
        return _failure(503, "Secure LAN authentication is not configured correctly.")
    if request.url.scheme != "https":
        return _failure(403, "Secure LAN access requires HTTPS.")
    if path == "/api/auth/login" and request.method == "POST":
        return None
    if path.startswith("/api/debug/") and os.getenv("FISH_LAN_DEBUG", "0") != "1":
        return _failure(404, "Debug access is disabled.")
    authorization = request.headers.get("authorization", "")
    session = None
    role = None
    if authorization:
        if authorization.startswith("Bearer "):
            role = _role(authorization[7:], tokens)
    else:
        session = _session(request, tokens)
        role = session["role"] if session else None
    if role is None:
        return _failure(401, "Authentication required.")
    required = "admin" if path.startswith("/api/debug/") else (
        "viewer" if request.method in {"GET", "HEAD"} or (path in {"/api/export", "/api/auth/logout"} and request.method == "POST") else "operator"
    )
    if _levels[role] < _levels[required]:
        return _failure(403, "This role is not permitted to perform that action.")
    if session and request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("x-csrf-token", "")
        if not _same_origin(request) or not csrf.isascii() or not secrets.compare_digest(csrf, session["csrf"]):
            return _failure(403, "A same-origin request and valid CSRF token are required.")
    request.state.lan_role = role
    request.state.lan_csrf = session["csrf"] if session else None
    return None


@router.get("/mode")
def auth_mode():
    return JSONResponse({"lan_security": enabled()}, headers={"Cache-Control": "no-store"})


@router.post("/login")
async def auth_login(request: Request):
    if not enabled():
        return _failure(404, "LAN authentication is disabled.")
    if not _same_origin(request) or request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        return _failure(403, "A same-origin JSON request is required.")
    if not _allow_login(request):
        return _failure(429, "Too many sign-in attempts; try again later.")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 2048:
            return _failure(413, "Login request too large.")
    try:
        payload = json.loads(data)
        token = payload.get("token") if isinstance(payload, dict) else None
        tokens = configured_tokens()
    except (ValueError, UnicodeDecodeError):
        return _failure(400, "Invalid login request.")
    role = _role(token, tokens) if isinstance(token, str) else None
    if role is None:
        return _failure(401, "Authentication failed.")
    session_id, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with _lock:
        now = monotonic()
        _sessions.pop(request.cookies.get(COOKIE, ""), None)
        for key in [key for key, session in _sessions.items() if session["expires"] <= now]:
            _sessions.pop(key, None)
        if len(_sessions) >= 512:
            _sessions.pop(next(iter(_sessions)))
        _sessions[session_id] = {"role": role, "csrf": csrf, "expires": now + SESSION_SECONDS, "digest": _digest(token)}
    response = JSONResponse({"role": role, "csrf_token": csrf}, headers={"Cache-Control": "no-store"})
    response.set_cookie(COOKIE, session_id, max_age=SESSION_SECONDS, path="/", secure=True, httponly=True, samesite="strict")
    return response


@router.get("/session")
def auth_session(request: Request):
    if not enabled():
        return _failure(404, "LAN authentication is disabled.")
    return JSONResponse({"role": request.state.lan_role, "csrf_token": request.state.lan_csrf}, headers={"Cache-Control": "no-store"})


@router.post("/logout")
def auth_logout(request: Request):
    with _lock:
        _sessions.pop(request.cookies.get(COOKIE, ""), None)
    response = JSONResponse({"logged_out": True}, headers={"Cache-Control": "no-store"})
    response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    return response
