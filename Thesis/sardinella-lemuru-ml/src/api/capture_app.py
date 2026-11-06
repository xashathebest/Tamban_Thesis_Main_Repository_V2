"""Checkpoint-free capture-only application. Never imports inspection app/models."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .dataset_capture.router import CaptureContext, create_router


def _independent_lan_security():
    # Reuse the reviewed security implementation without sharing its mutable
    # process-local sessions or overwriting the inspection session cookie.
    spec = importlib.util.spec_from_file_location("tamban_capture_lan_security", Path(__file__).with_name("lan_security.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.COOKIE = "__Host-tamban_capture_session"
    return module


def create_capture_app(context=None):
    root = Path(__file__).resolve().parents[2]
    auth = _independent_lan_security()
    context = context or CaptureContext(hardware_enabled=os.getenv("FISH_CAPTURE_ISOLATED_DEVICE", "0") == "1")
    app = FastAPI(title="Tamban Camera Capture", version="1.0.0")
    app.state.capture_context = context
    app.state.capture_auth = auth
    app.include_router(auth.router)
    app.include_router(create_router(context))
    app.mount("/assets", StaticFiles(directory=root / "frontend"), name="capture-assets")

    @app.middleware("http")
    async def protect_capture(request: Request, call_next):
        denied = await auth.guard(request)
        if denied is not None:
            return denied
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/", include_in_schema=False)
    @app.get("/capture", include_in_schema=False)
    def capture_page():
        return FileResponse(root / "frontend/capture-only.html", media_type="text/html")

    return app


app = create_capture_app()


def main():
    import ipaddress
    import uvicorn
    from . import lan_security
    host = os.getenv("FISH_CAPTURE_HOST", "127.0.0.1")
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    cert, key = os.getenv("LEMURU_TLS_CERTFILE"), os.getenv("LEMURU_TLS_KEYFILE")
    if not loopback:
        if not lan_security.enabled() or not cert or not key:
            raise SystemExit("Remote Capture requires the existing secure LAN profile and HTTPS.")
        lan_security.configured_tokens()
    uvicorn.run(app, host=host, port=int(os.getenv("FISH_CAPTURE_PORT", "8001")), access_log=False,
                ssl_certfile=cert, ssl_keyfile=key)


if __name__ == "__main__":
    main()
