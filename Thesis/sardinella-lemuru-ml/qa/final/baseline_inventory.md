# Final QA baseline inventory — 2026-10-18

Revision: `eb1e252618967b7dbce458be9ced8f3519d7bedd`; the checkout already contained extensive tracked and untracked changes. See `baseline_working_tree.txt` for the snapshot taken before this QA phase and `baseline_environment.txt` / `baseline_hardware.txt` for environment details. This revision alone does not describe the dirty working tree.

Windows 11, Ryzen 5 7535HS, NVIDIA RTX 2050 and AMD graphics were detected; the installed PyTorch reports CUDA unavailable. Python 3.14.6, NumPy 2.5.1, OpenCV 5.0.0.93 and Ultralytics 8.4.138 are installed. OpenCV violates the declared `<5` requirement and Ultralytics is below `>=8.4.142`; tests describe this environment, not a clean compliant one. A real camera, CUDA inference, target conveyor and independent expert fish labels have not been tested in this phase.

## Active pipeline and configuration

- Camera: `src/api/app.py:start_inspection` → `src/api/camera.py:process_frame` → Model 1 tracked parent detections → `src/inference/yolo_quality_model.py:predict_full_frame` and `src/inference/association.py:associate_parts_to_parents` → `src/inference/grading_engine.py:WeightedGradingEngine.evaluate` → `src/inference/grading_policy.py:grade_fish` → state/database → UI and exports. Still-image upload uses `analyze_image` and `src/api/image_analysis.py` without live temporal aggregation.
- Registry is `models/MODEL_REGISTRY.json`; `configs/active_model.json` selects `yolo26m_partdet`. Model 1 and Model 2 checkpoint files are present, but the checkpoint-free baseline does not load or validate them. API defaults specify `bytetrack.yaml`, full-frame Model 2 inference and interval 3; actual loaded tracker must be established from live runtime status, not inferred from configuration.
- `configs/grading_engine.yaml` selects policy `tail_optional_v1`, version 4.0. Body/Head/Tail weights are .50/.30/.20, or .625/.375/0 when Tail is unavailable and Body and Head meet evidence requirements. Part and final-support thresholds are .25 and .50. Reliable Rejected Tail predictions remain weighted evidence. No score or anatomy is invented for an unobserved part.
- `src/features/` contains offline research features; live ROI colour values are diagnostic rather than validated grade adjustments. `src/api/export.py` serializes the decision and its provenance; `frontend/app.js` presents it. Prior dated baselines describing fixed default weights predate the user's subsequent explicit Tail-optional request.

## Prior findings cross-check and risk register

| Finding | Status for this baseline | Evidence / limitation |
|---|---|---|
| Model switch during active inspection, upload override, session start race | FIXED in synthetic regression | `tests/test_model_switch_safety.py`, `tests/test_session_lifecycle_qa.py`; process-local guards do not establish safety across multiple server processes. |
| Stop timeout and partial settings changes | FIXED in synthetic regression | `tests/test_stop_timeout_qa.py`, `tests/test_settings_atomic_qa.py`; real camera driver and device failures remain untested. |
| Historical session reviews and exports | FIXED in synthetic regression | `tests/test_historical_review_qa.py`, `tests/test_historical_export_qa.py`; a previously observed headless historical browser smoke was intermittent and needs rechecking. |
| Tracker fallback and parent/part ownership | PARTIAL | `tests/test_tracker_backend_qa.py`, `tests/test_association.py`, `tests/test_runtime_diagnostics.py` cover synthetic warnings, overlaps and cross-fish assignments; difficult real overlap and tracking remain unvalidated. |
| Temporal evidence and Tail-optional policy | PARTIAL | `tests/test_grading_engine.py`, `tests/test_tail_optional_policy.py` cover synthetic temporal gates and weights; no independent accuracy or defect-sensitivity evidence. |
| Independent grade accuracy and defect claims | BLOCKED | User states the independent expert-labeled videos do not yet exist. Missing detections do not prove physical anatomy. Dataset leakage concerns from prior audit require a new independent specimen/session split. |
| Real camera performance and CUDA | BLOCKED | No measured camera/conveyor timing in this phase; `torch.cuda.is_available()` is false despite an NVIDIA GPU. Performance results from earlier records are historical and cannot be reused as current measurements. |
| Dependency reproducibility | CONFIRMED | Installed OpenCV and Ultralytics versions do not meet `requirements.txt`; create and test a supported environment before deployment. |

No runtime changes were made for this baseline. Already-covered findings above are retained as verification targets for their sequential phases, not assumed solved merely from progress reports. Prior records reviewed: `SEQUENTIAL_DEVELOPMENT_PROGRESS.md`, `TAMBAN_UI_FPS_DEVELOPMENT_PROGRESS.md`, `TAMBAN_DEEP_CODE_QA_PROGRESS.md`, `docs/release_readiness.md`, and `docs/adaptive_tail_policy.md`.
