# Tamban Thesis - UI and FPS Improvement Prompts

**Source reviewed:** uploaded `Thesis-main (2).zip` (October 13, 2026).  
**Prepared:** October 14, 2026.  
**How to use:** Open **one numbered `.md` file at a time** and paste its entire content into a coding assistant with access to the current thesis repository. Run its tests, review the changed files, and only then use the next prompt.

These prompts are implementation instructions, **not completed code changes**. An audit of the provided ZIP found strong candidate bottlenecks, but there is no reliable sustained live-camera, on-device FPS benchmark in the archive. Do not claim an improvement until it is measured with the real camera, machine, and original model checkpoints.

## Recommended workflow

| Phase | Prompts | Why |
| --- | --- | --- |
| Measure before changing | 01, 02 | Determine whether CPU/GPU inference, frame processing, JPEG, or frontend is the bottleneck |
| Remove avoidable overhead | 03, 04 | Limit heavy status/analytics and repeated browser rendering |
| Tune inference safely | 05, 06, 07 | Compare Model 2 modes, devices, and inference sizes without silently reducing quality |
| Improve camera/stream architecture | 08, 09 | Reduce delivery overhead and optionally show a smoother *honestly labeled* raw preview |
| Advanced/optional model scheduling | 10 | Only pursue if benchmarking shows Model 1 is dominant |
| Simplify UI | 11, 12, 13, 14, 15 | Cut duplicate navigation, controls, and repetitive data while keeping features accessible |
| Verify + finish | 16, 17, 18 | Prove performance/accuracy, document changes, and optionally offer tested presets |

**Do not implement steps 09, 10, or 18 blindly:** they can change architecture, timing, and/or model behavior. Compare against the original benchmark, and include fish-level accuracy/counting safeguards.

## Non-negotiable safeguards

- Retain **two model roles:** Model 1 detects/counts and tracks whole fish; Model 2 predicts graded parts.
- Preserve distinct **Ungraded** vs **Rejected** semantics, temporal evidence, part ownership, and per-fish inspection history.
- Do not silently change the 50/30/20 grading weights or activate unvalidated brightness, texture, or belly-defect rules.
- Never treat physically absent head as equivalent to head nondetection due to occlusion. Expert confirmation is still pending.
- Keep model selection provenance, original checkpoint IDs/hashes, camera calibration records, review workflows, CSV/XLSX exports, and accessibility intact.
- Missing model weights in the shared ZIP are expected. Use mocks for unit tests and run real performance tests only on the research machine where the checkpoints are installed.
- Treat **preview FPS**, **processed/inference FPS**, **capture FPS**, and **per-fish grading throughput** as different measurements. Do not claim that increasing preview FPS increases classification throughput.
- Keep the camera acquisition single-owner. Never start a second `cv2.VideoCapture` for the same device.
- Make changes incrementally. Show changed files, tests, before/after numbers, risks and rollback steps for every completed prompt.

## Important baseline discoveries from code review

- `src/api/app.py` lines ~37-50 configure Model 1 at **640** input and Model 2 by selected registry entry; the persisted selection is **YOLO26m**, input **768**. Model 2 is `full_frame` by default, with interval **3**.
- `src/api/camera.py` `process_frame` invokes Model 1 on each processed frame; Model 2 runs on eligible tracks. The capture queue retains only the latest frame; frame publication follows inference, overlays, and JPEG encoding (quality 82).
- `src/api/runtime_diagnostics.py` already records bounded camera-capture/processed-FPS rates and stage p50/p95 timings. The debug endpoint `GET /api/debug/runtime` exposes them. **Do not enable debug capture to measure the clean production baseline**: enabling it can lower raw Model 2 detection threshold and save research artifacts, increasing overhead.
- A bundled still-image diagnostic file, `results/diagnostic/yolo26m_test/report.json`, reports Model 2 `device=cpu` and `full_frame_inference_seconds=0.363`; Model 1 `inference_seconds=1.563`. These are **one-off offline measurements**, not the user's sustained 5-FPS run.
- `frontend/app.js` calls `getStatus` every **900 ms** and its `render()` invokes analytics/history/KPI/model/settings/diagnostics updates even when many sections are hidden.
- `src/api/app.py` `_status_payload()` retrieves durable session events and recomputes analytics for the status response. Full historical data is not ideal for high-frequency polling.
- Visible duplicate UI: Export and Settings are each available from header and sidebar; feed overlays and settings overlays duplicate controls; Analytics sidebar item opens a disclosure in Live Inspection instead of a proper view; the separate Model page repeats data from settings/header.

Read `AUDIT_FINDINGS.md` for file-level evidence and the recommended order of investigation.

## Suggested completion record after each prompt

```text
Prompt #: 
Files changed:
Confirmed fixes:
Tests run / result:
Measured before -> after (same hardware/data):
Effect on fish count, part ownership, A/B/C/Rejected/Ungraded:
Open risks:
Rollback instructions:
```
