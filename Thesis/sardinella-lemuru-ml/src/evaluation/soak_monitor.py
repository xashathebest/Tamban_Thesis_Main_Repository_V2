"""Read-only process and local status monitor for a supervised soak run.

Requires optional psutil. Does not start inspection, change data or measure FPS.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import monotonic, sleep, time
from urllib.request import urlopen
from urllib.parse import urlsplit


def sample(process, url: str) -> dict[str, object]:
    result: dict[str, object] = {"unix_time": time()}
    try:
        result.update(rss_bytes=process.memory_info().rss, cpu_percent=process.cpu_percent(), threads=process.num_threads())
        handles = getattr(process, "num_handles", None)
        fds = getattr(process, "num_fds", None)
        result["handles_or_fds"] = handles() if handles else fds() if fds else None
    except Exception as exc:
        result["process_error"] = str(exc)
    started = monotonic()
    try:
        with urlopen(url, timeout=5) as response:
            response.read(1024 * 1024)
            result["http_status"] = response.status
    except Exception as exc:
        result["http_error"] = str(exc)
    result["request_ms"] = round((monotonic() - started) * 1000, 2)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True, help="PID of the server process to monitor")
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/status/live")
    parser.add_argument("--duration", type=float, default=1800, help="Duration in seconds (default 30 minutes)")
    parser.add_argument("--interval", type=float, default=10, help="Sampling interval in seconds")
    parser.add_argument("--output", type=Path, required=True, help="New JSONL file; existing files are not overwritten")
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.query:
        parser.error("URL must be an unauthenticated local HTTP endpoint without query parameters")
    if args.duration <= 0 or args.interval <= 0:
        parser.error("duration and interval must be positive")
    try:
        import psutil
    except ImportError:
        parser.error("optional psutil is required to record process resources")
    process = psutil.Process(args.pid)
    process.cpu_percent()  # Prime CPU measurement.
    deadline = monotonic() + args.duration
    with args.output.open("x", encoding="utf-8") as output:
        while True:
            output.write(json.dumps(sample(process, args.url)) + "\n")
            output.flush()
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            sleep(min(args.interval, remaining))


if __name__ == "__main__":
    main()
