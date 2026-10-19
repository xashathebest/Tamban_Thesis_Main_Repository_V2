# Phase 12 — optional raw preview

Status: software checks passed; **PENDING HARDWARE VALIDATION**. Real-camera/browser field acceptance is blocked.

Before: camera capture → one-slot inference queue → model processing and annotations → JPEG → existing MJPEG feed. Browser feed cadence was tied to processed frames.

After, only when `FISH_RAW_PREVIEW_ENABLED=1` at startup and a client selects raw: camera capture → copied frame → separate one-slot preview queue → one shared JPEG encoder → `/api/video-feed/raw`. The raw stream contains no inference or grade overlays. The existing annotated feed remains the default and the processing path and scientific policy are unchanged. Raw capture is capped at 15 offers per second and idle subscribers incur no JPEG encoding. This cap is a limit, not a measured rate. One encoder serves multiple clients; disconnected streams decrement the subscriber count; stale queued or in-flight images are discarded after the last subscriber leaves or a worker restarts. Stream access rechecks the existing LAN authorization.

The UI labels AI processing FPS and explicitly says browser preview FPS and display latency are not measured. `tests/test_raw_preview_qa.py` exercises copied raw images, stalled-inference queue behavior, bounded replacement, subscribers, revocation, restart and in-flight disconnect. The focused command in `12_preview_tests.log` passed 57 tests and 36 subtests with one warning; JavaScript syntax passed. An initial unprivileged test attempt produced 12 Windows temporary-directory permission errors; the rerun with access passed. These are synthetic tests, not a before/after performance measurement.

Rollback: unset the flag or set `FISH_RAW_PREVIEW_ENABLED=0` and restart; the processed feed remains available. Verify on the intended camera, browser and network: actual displayed FPS and capture-to-display age, CPU/JPEG/network overhead, multiple clients, disconnect/reconnect, start/stop/restart and paired count/grade invariants. No throughput, accuracy or performance improvement is claimed until then.
