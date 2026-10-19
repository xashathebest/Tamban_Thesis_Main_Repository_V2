# Baseline test evidence — 2026-10-18

Run from `Thesis/sardinella-lemuru-ml` with `C:/Users/User/AppData/Local/Python/bin/python.exe`.

| Check | Outcome |
|---|---|
| `python -B tests/run_model_free_isolated.py` | PASS: 567 passed, 6 skipped, 88 subtests passed, 7 warnings in 13.85 s. Full console log: `baseline_tests.log`. The temporary source copy explicitly excludes model checkpoints and runtime overrides. |
| Python `compile()` over all `src/**/*.py` and `tests/**/*.py` | PASS: 167 files; no bytecode artifacts required. See `baseline_syntax.log`. |
| `node --check frontend/app.js` | PASS. See `baseline_syntax.log`. |
| Checkpoint-backed and physical camera tests | NOT RUN in this baseline; no accuracy or runtime claim. Six opt-in/environment-dependent checks were skipped in the model-free run. |
| CUDA, conveyor and independent fish-grade comparison | BLOCKED for this baseline: CUDA unavailable to installed PyTorch; real conveyor and independently expert-labeled videos not supplied. |

Warnings in the captured output include the installed Starlette/httpx deprecation and synthetic single-label metric warnings. No baseline test failures or stack traces were produced. The preceding task separately observed a flaky historical-review Chrome smoke; it is not counted as a baseline failure or pass here and should be revisited in its appropriate phase.
