"""Run the local operator dashboard with ``python -m src.api``."""

from __future__ import annotations

import os
import ipaddress
import logging
from pathlib import Path

import uvicorn
from src.api import lan_security


def main() -> None:
    host = os.getenv("LEMURU_HOST", "127.0.0.1")
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() == "localhost"
    certfile = os.getenv("LEMURU_TLS_CERTFILE")
    keyfile = os.getenv("LEMURU_TLS_KEYFILE")
    if not loopback:
        logging.warning("Binding the dashboard beyond localhost exposes it to the network; secure LAN authentication and HTTPS are required.")
        if not lan_security.enabled():
            raise SystemExit("Set FISH_LAN_AUTH=1 and configure role tokens before binding beyond localhost.")
        if not certfile or not keyfile:
            raise SystemExit("Set LEMURU_TLS_CERTFILE and LEMURU_TLS_KEYFILE before binding beyond localhost.")
    if lan_security.enabled():
        try:
            lan_security.configured_tokens()
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    if bool(certfile) != bool(keyfile) or (certfile and (not Path(certfile).is_file() or not Path(keyfile).is_file())):
        raise SystemExit("Both TLS certificate and key must be existing files.")
    uvicorn.run(
        "src.api.app:app",
        host=host,
        port=int(os.getenv("LEMURU_PORT", "8000")),
        reload=False,
        ssl_certfile=certfile,
        ssl_keyfile=keyfile,
    )


if __name__ == "__main__":
    main()

