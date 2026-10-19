# 10 — Performance baseline: PENDING HARDWARE VALIDATION

**No 60–120 second representative fish-scene performance measurements were obtained in this phase.** Windows reports an HP Wide Vision HD Camera, but its availability for the thesis conveyor, camera view and actual fish scenes were not verified; no empty, one-fish or crowded scene was supplied or independently confirmed. RTX 2050 hardware is present but the installed PyTorch reports CUDA unavailable. The local registered Model 1 CPU load selected the IoU fallback because `lap` is missing. Selected Model 2 is `yolo26m_partdet`; the API's configured default is full-frame inference at interval 3. Runtime model device, camera resolution, scene counts, actual fish attribution, model latency and measured FPS must be captured from the running target session.

Existing instrumentation in `src/api/runtime_diagnostics.py`, `src/api/camera.py`, `src/evaluation/runtime_benchmark.py`, and `frontend/app.js` reports capture and processed counters/rates, stale queue drops, host timing windows including Model 1/2, association and JPEG, and optional browser DOM render samples. These are not synchronized GPU timings. MJPEG dispatch is not browser-displayed FPS; true browser frame display FPS and capture-to-display age are **not measured** by this baseline. Some stages overlap and timing windows can include warmup, so summing their p50/p95 cannot establish total latency. DB/API and feature timing coverage should be checked in the target workload; no measured bottleneck ranking is justified yet. Telemetry overhead has not been measured under the real workload.

The metric logic was checked using `python -B -m pytest -q -p no:cacheprovider tests/test_runtime_benchmark.py tests/test_runtime_diagnostics.py tests/test_model2_schedule_benchmark.py tests/test_status_polling.py --tb=short`: **41 passed, 36 subtests, 1 warning** (`10_metrics_tests.log`). These synthetic tests are not hardware timings.

## Windows collection procedure

Follow `docs/runtime_baseline.md` for complete prerequisites, status validity checks and telemetry-overhead comparison. On the inspection PC, start the API from the project directory with the actual supported environment, open the dashboard, confirm both models and camera are ready, and leave debug capture off. In a second PowerShell window, use the same Python environment and after placing each verified scene run:

```powershell
python -m src.evaluation.runtime_benchmark --scenario empty --warmup 15 --duration 90
python -m src.evaluation.runtime_benchmark --scenario one_fish --warmup 15 --duration 90
python -m src.evaluation.runtime_benchmark --scenario overlap --warmup 15 --duration 90
```

Record actual checkpoint IDs/hashes, model devices, input size, tracker, camera/resolution, interval, scene occupancy and lighting. The scenario argument is operator-declared, not automatically verified. Preserve each JSON/Markdown output, rerun comparable scenes, and compare accuracy/ownership against independent expert labels before adopting performance settings. Browser paint rate and end-to-end display age need a separately validated measurement method.
