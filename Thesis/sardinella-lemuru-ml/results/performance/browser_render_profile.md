# Dashboard render comparison

Chrome headless on the local machine, with the inspection stopped and an empty isolated SQLite session. The same five-second observer and `performance.now()` wrapper were used before and after the change. Each run captured six scheduled live renders. Percentiles use linear interpolation; timing resolution was approximately 0.1 ms. Raw samples are in `browser_render_before.json` and `browser_render_after.json`.

| Metric | Before | After |
|---|---:|---:|
| Live render p50 | 0.80 ms | 0.20 ms |
| Live render p95 | 0.98 ms | 0.28 ms |
| MutationObserver records in live view | 252 | 132 |
| Closed analytics redraws | 6 | 0 |
| Scheduled live requests | About 1 per 900 ms | About 1 per 900 ms |

These are browser main-thread wall-clock render durations, not total browser CPU utilization or camera FPS. The sample is small and does not represent an active camera or crowded fish. The after run separately verified one analytics request across six initial live polls, with one additional request after a new event and after a manual review. In a visibility simulation, live polling stopped while hidden and resumed when shown. An isolated history fixture verified no repeated history request across two idle seconds, two-page navigation, delayed-request cancellation on rapid navigation, and a saved manual grade. The 900 ms visible polling interval remains unchanged; response time and network delay determine actual freshness.

Reproduce the software checks on Windows from the project directory with `python tests/dashboard_status_smoke.py` and, to create a new raw profile, `python tests/dashboard_status_smoke.py --profile-file results/performance/<new-filename>.json`. The test launches Chrome and a local API with a temporary database; it does not start the camera. Use the real-camera procedure in `docs/runtime_baseline.md` to assess responsiveness and FPS under actual inspection.

To revert this phase, restore the pre-phase-04 `render`, polling, view-navigation and history/review loading code in `frontend/app.js`; preserve the phase-03 lightweight endpoint and revision-triggered analytics changes. Remove the phase-04 browser profile artifacts and expanded smoke checks if no longer needed.
