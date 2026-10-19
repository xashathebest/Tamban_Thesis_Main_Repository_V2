# Phase 17 — maintenance and soak procedure

Status: short synthetic resource checks passed; **30–60-minute field soak BLOCKED / not run**. Frame queues are capacity one, stream clients share one optional raw encoder, its worker is joined before restart, frontend requests are aborted when views or visibility change, and temporary URL objects are revoked. A 20-cycle encoder start/stop test and existing lifecycle/history tests passed: 30 tests (`17_stability_tests.log`). These checks do not establish leak-free hour-long operation or interrupted-write recovery. Existing capture reads can still be delayed by a stalled camera driver; the stop state must remain stopping until ownership is released.

## Repeatable supervised target run

1. Use the documented Windows startup instructions in `README.md`; use a disposable test database and representative camera, conveyor scenes and normal operator browser. Record device, application revision, settings and scene notes. `psutil` is optional and is required only for this monitor; use the project's approved environment.
2. In another PowerShell window identify the server Python PID and run, from the project root, with a new output path:

   `py -m src.evaluation.soak_monitor --pid <SERVER_PID> --url http://127.0.0.1:8000/api/status/live --duration 1800 --interval 10 --output qa/final/soak_target.jsonl`

3. Supervise normal live operation for at least 30 minutes; separately exercise start/stop/restart, multiple clients, uploads, history and graceful shutdown. Monitor reports timestamp, process RSS, CPU percentage, thread count, Windows handles or Unix descriptors, HTTP response status/errors and request duration. It does not start inspection, measure displayed FPS, inspect correctness, use LAN credentials, or overwrite existing files. Secure LAN mode requires a separately authorized measurement method; this monitor intentionally supports only unauthenticated loopback HTTP.
4. Inspect trends and errors together with camera capture/processing telemetry and independently labeled results. Record hardware/software conditions, screenshots, actual duration and any growth, driver errors or database recovery observations. A short script invocation cannot substitute for the supervised soak.

Dependencies are bounded in `requirements.txt`; installed OpenCV and Ultralytics were previously found outside the declared versions. Windows launch and data paths are documented in `README.md`. No cleanup of research datasets or legacy files was attempted.
