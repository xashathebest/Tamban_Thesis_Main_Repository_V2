# 11 — Inference optimization: BLOCKED pending measurements

No inference optimization or configuration change was applied: phase 10 has no representative target-camera baseline, and the user states independently labeled fish clips do not yet exist. Therefore neither a latency gain nor a safe accuracy tradeoff can be established. Current full-frame interval 3 is a sampling policy, not an assurance that grades/counts are unchanged. Installed PyTorch does not expose CUDA here; an NVIDIA GPU in the machine does not imply GPU inference is active. Model adapters load checkpoints once and existing tests cover reuse, scheduling and fish-specific association.

| Candidate comparison | Measured gain | Count/ownership/grade impact | Decision |
|---|---|---|---|
| Full-frame vs crop, intervals 1–4 | NOT MEASURED | NOT MEASURED on independently labeled fish | Do not change default |
| Input size, precision, batching or GPU | NOT MEASURED | NOT MEASURED | Do not enable |

Simulation command: `python -B -m pytest -q -p no:cacheprovider tests/test_model2_schedule_benchmark.py tests/test_runtime_diagnostics.py tests/test_multi_model_selection.py tests/test_tail_optional_policy.py --tb=short`: **56 passed, 48 subtests** (`11_inference_checks.log`). The reproducible paired comparison procedure is `docs/model2_schedule_benchmark.md`; collect the phase 10 baseline and independent specimen-level truth first. Keep original settings as the rollback; no code or setting was changed in this phase.
