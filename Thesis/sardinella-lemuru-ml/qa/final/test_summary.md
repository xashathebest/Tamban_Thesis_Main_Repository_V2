# Test summary — 2026-10-18

Final checkpoint-free isolated suite: `C:/Users/User/AppData/Local/Python/bin/python.exe -B tests/run_model_free_isolated.py` — **588 passed, 6 skipped, 92 subtests, 7 warnings** in 19.53 seconds. Log: `21_final_model_free.log`. The prior phase 18 run produced the same counts in 18.72 seconds (`18_full_model_free.log`). The harness copies source to a temporary directory without model checkpoints; none of these results establishes model accuracy or real FPS. Warnings include one Starlette deprecation and six synthetic scikit-learn label warnings.

Selected focused logs: `12_preview_tests.log` (57 passed, 36 subtests), `13_navigation_tests.log` (53 passed, four subtests), `14_live_tests.log` (62 passed, 16 subtests), `15_workflow_tests.log` (76 passed), and `17_stability_tests.log` (30 passed). Browser logs: `13_dashboard_smoke.log`, `15_export_browser.log`, `15_review_browser.log`, `21_final_browser.log`; these use local test data or simulated UI state. `node --check frontend/app.js` passed.

Focused commands, from the project directory (all use `python -B -m pytest -q -p no:cacheprovider` and `--tb=short`):

- Phase 12: `tests/test_raw_preview_qa.py tests/test_runtime_diagnostics.py tests/test_session_lifecycle_qa.py tests/test_stop_timeout_qa.py tests/test_lan_security_qa.py`.
- Phase 13: `tests/test_operator_dashboard.py tests/test_status_polling.py tests/test_historical_review_qa.py tests/test_export_selection_qa.py`.
- Phase 14: `tests/test_operator_dashboard.py tests/test_session_lifecycle_qa.py tests/test_stop_timeout_qa.py tests/test_upload_limits_qa.py tests/test_tail_optional_policy.py`.
- Phase 15: `tests/test_historical_review_qa.py tests/test_historical_export_qa.py tests/test_export_selection_qa.py tests/test_settings_atomic_qa.py tests/test_model_switch_safety.py tests/test_history_performance_qa.py`.
- Phase 17: `tests/test_soak_monitor.py tests/test_raw_preview_qa.py tests/test_stop_timeout_qa.py tests/test_session_lifecycle_qa.py tests/test_history_performance_qa.py`.
- Phase 21: `tests/test_expert_library.py`.
- Browser: `python -B tests/dashboard_status_smoke.py`, `python -B tests/export_form_smoke.py`, `python -B tests/historical_review_smoke.py` and `python -B tests/navigation_qa_smoke.py`.

Observed environment: Windows, Python 3.14.6, OpenCV 5.0.0 (installed package version 5.0.0.93), PyTorch 2.14.0+cpu, CUDA unavailable, Ultralytics 8.4.138. OpenCV and Ultralytics do not meet the repository's declared runtime ranges. The active Model 1 previously loaded on CPU with explicit IoU fallback because optional ByteTrack `lap` was unavailable; that did not constitute live-camera validation. These environment facts may change and must be rechecked for a release.

Blocked plan: obtain representative target-camera empty/one/overlap scenes, independently annotated fish clips and expert grades, then execute the procedures in `performance_baseline.md`, `performance_changes.md`, `12_preview.md` and `stability_maintenance.md`. Record actual hardware metrics and repeat the paired grading/count comparisons. The current user has stated the independent videos and labels do not yet exist.

Additional actual-model compatibility check: `$env:RUN_CHECKPOINT_SMOKE='1'; $env:RUN_REAL_MODEL_TESTS='1'; python -B -m pytest -q -p no:cacheprovider tests/test_checkpoint_smoke.py tests/test_real_model2_reference.py --tb=short` — **2 passed** on CPU (`20_checkpoint_tests.log`). One uses a synthetic image; the other uses a dataset reference image that is not independent ground truth. Legacy RF-DETR smoke cases require their separate checkpoints and configured images and were not run.
