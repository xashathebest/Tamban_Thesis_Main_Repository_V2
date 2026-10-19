# Deep code QA baseline — 2026-10-18

The current checkout, including earlier UI/FPS work and its existing uncommitted changes, is the baseline. Prompt 01 does not change application behavior. The earlier ZIP's reported 341-test result is historical and does not describe this checkout.

## Environment and commands

- Windows 11; Python 3.14.6, executable `C:/Users/User/AppData/Local/Python/bin/python.exe`; CPU-only PyTorch 2.14.0; CUDA unavailable in the preceding local check. Installed pytest 9.1.1, NumPy 2.5.1, FastAPI 0.141.1, Starlette 1.3.1 and httpx 0.28.1. Local checkpoint files exist; their presence is not a model-accuracy validation.
- `python -B -m unittest discover -s tests -v`: **372 tests, 5 skipped, 0 failures/errors**. Full log: `results/qa/baseline_unittest.log`. The five skips concern three opt-in real-image/checkpoint tests, one opt-in real Model 2 regression, and an unavailable canonical comparison dataset. No missing-checkpoint failure was reproduced here.
- `python -B -m pytest -q -p no:cacheprovider tests`: **422 passed, 5 skipped, 80 subtests passed**, seven warnings. Full log: `results/qa/baseline_pytest_tests.log`. This run required access to the normal system temporary directory; use a temp directory outside the repository because expert-library access intentionally rejects files inside it. This is the broader regression command for the current checkout; it requires pytest, which is not declared in `requirements.txt`.
- `python -X pycache_prefix=results/qa/pycache -m compileall -q src tests` and `node --check frontend/app.js`: passed. Compilation used a separate cache so existing tracked bytecode was not replaced. `python -m pip check` reported no broken *installed-distribution* requirements, which does not verify this repository's `requirements.txt` bounds.
- A first pytest run with its base temp inside the repository had three expert-library failures because the access guard correctly rejected those test paths. A separate normal-temp run inside the sandbox had 28 fixture errors because `pytest-of-User` was inaccessible. The successful run above used normal temp outside the sandbox and restricted collection to `tests`. These were setup/access failures, not established expert-library logic defects. An intermediate failed run left `results/qa/pytest_baseline` with restricted permissions; explicit `tests` collection avoids it. Raw logs preserve these observations.

## Architecture and current policy

`src/api/app.py` coordinates FastAPI controls, settings, durable sessions and status; `src/api/camera.py` runs the shared frame pipeline; `src/api/domain.py` owns tracked fish and counting; `src/api/database.py` stores sessions and events. `src/inference/yolo_fish_detector.py` detects whole fish, while `src/inference/yolo_quality_model.py` collects and associates part evidence for per-fish grading. `frontend/app.js` consumes live state and the review/history API. The previous UI/FPS tracker records already completed optimizations and an expert-data blocker.

The active configuration in `configs/grading_engine.yaml` and `src/inference/grading_engine.py` uses Body 0.50, Head 0.30, Tail 0.20; standard mode requires Body, one observed region, 0.50 original-weight coverage and 0.50 weighted support. Live temporal grading requires two usable observations. Unobserved anatomy does not prove physical absence; insufficient evidence remains Ungraded, distinct from the trained Rejected classes. These are operating rules, not independently validated biological accuracy claims.

## Findings and risk register

| Priority | Finding | Evidence and interpretation |
|---|---|---|
| MEDIUM | CI's documented unittest command does not exercise pytest-style function tests. | `.github/workflows/model-free-tests.yml` runs only `unittest discover`; `tests/test_status_polling.py`, `tests/test_model2_schedule_benchmark.py` and others use pytest functions. Pytest collected 427 cases while unittest ran 372. The commands count test cases differently, but the omitted function-style tests are directly observable. Review CI dependencies and scope in Prompt 18. |
| MEDIUM | Installed local packages differ from this checkout's declared supported ranges. | `requirements.txt` requests Pillow `<12`, ultralytics `>=8.4.142`, and opencv-python `<5`; installed versions are 12.3.0, 8.4.138 and 5.0.0.93 respectively. The passing local tests do not certify a supported environment; no dependency was changed during baseline. |
| MEDIUM, source-confirmed; verify in Prompt 06 | A mixed settings request can apply the detector threshold before later fields are validated. | `src/api/app.py::_update_settings_locked` calls `state.set_confidence_threshold` before checking whether `display_settings` is an object. An invalid later field can therefore return 422 after an earlier mutation. Its field incidence has not been measured. |
| HIGH, conditional; verify in Prompt 04 | A newly started worker may produce an event before its durable session is opened. | `src/api/app.py::start_inspection` invokes `service.start()` before `inspection_sessions.start(...)`; the exact interleaving and effect require a controlled reproduction. |
| Unresolved | Model fidelity, fish ownership in difficult overlaps, independent accuracy and representative camera throughput remain unvalidated. | No independently labelled fish-level dataset has been collected, and the baseline is primarily automated/software-only. The earlier UI/FPS tracker documents the blocked comparison and remaining camera work. |

The Starlette TestClient deprecation warning and small-sample sklearn warnings were observed, not treated as proven application failures. Audit hypotheses from later prompts are not counted as confirmed bugs until their own reproductions.

Next: inspect and test all active model-switch paths under Prompt 02, preserving the model-selection lock and previous dashboard/API behavior.
