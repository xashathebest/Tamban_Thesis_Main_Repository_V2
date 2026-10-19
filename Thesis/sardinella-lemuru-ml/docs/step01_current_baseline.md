# Current step-by-step baseline — 2026-10-18

This inventory predates the subsequent `tail_optional_v1` policy change. For the current policy, see `adaptive_tail_policy.md` and `configs/grading_engine.yaml`; the baseline below describes the earlier configuration.

This is an inventory of the current checkout, including the subsequent UI/FPS and deep QA work. It does not change runtime behavior or claim real-world performance. For historical issues and their fixes see `SEQUENTIAL_DEVELOPMENT_PROGRESS.md` and `TAMBAN_DEEP_CODE_QA_PROGRESS.md`; earlier baseline findings should not be repeated as current defects without reproducing them.

## Flow and grading signals

| Component or signal | Classification | Current evidence |
|---|---|---|
| Parent detection, tracking, counting and association | LIVE VERDICT | `src/api/app.py:start_inspection`; `src/api/camera.py:CameraInspectionService.process_frame`; `src/api/domain.py`; `src/inference/association.py:associate_parts_to_parents`. Parent and ownership gates determine whether part evidence can be used. |
| Upload and Model 2 region evidence | LIVE VERDICT | `src/api/app.py:analyze_image`; `src/api/image_analysis.py:StillImageAnalyzer.analyze`; `src/inference/yolo_quality_model.py:predict`, `predict_full_frame`, `_grade_parts`. Upload uses the active model; still images do not require live temporal aggregation. |
| Weighted and temporal policy | LIVE VERDICT | `src/inference/grading_engine.py:WeightedGradingEngine.evaluate` and `_aggregate`; `src/inference/grading_policy.py:grade_fish`; `configs/grading_engine.yaml`. Region/class evidence, original coverage, temporal and acceptance gates affect the outcome. Optional quality filters affect eligibility only if configured. |
| Trained Rejected part labels | LIVE VERDICT | `grading_policy.py:grade_fish` uses Model 2 Rejected-class evidence. Insufficient evidence remains Ungraded; Rejected is a model prediction, not proof of a named physical defect. The separate override is off by default. |
| Rectangular ROI HSV, colour and highlight proxies; camera brightness | LIVE DIAGNOSTIC | `grading_engine.py:_aggregate` and colour extraction; `src/api/camera.py:_update_image_statistics`. No validated HSV/defect rule is applied even if its switch is enabled. Rectangles may include background. |
| Representative frame, display and export | LIVE DIAGNOSTIC | `src/inference/frame_quality.py`; `frontend/app.js:renderLatest`, `renderAnalytics`, `renderHistoryRows`; `src/api/export.py:inspection_row`, `make_csv`, `make_xlsx`. These display or preserve evidence, rather than independently deciding grades. |
| Masked handcrafted colour, texture, morphology and structural features | OFFLINE RESEARCH | `src/features/handcrafted.py:extract_manifest_features`; `color.py`, `texture.py`, `morphology.py`, `structure.py`; `src/inference/part_fusion.py:assess_structure`, `fuse_quality`. Not established as live grading inputs. |
| Automatically confirmed physical absence or named belly-hole detection | NOT IMPLEMENTED | `grading_engine.py:_aggregate` stores `physical_missing: None` and unknown status for unobserved parts. Structural review is separate; no expert-approved automatic structural gate or validated belly-hole model has been established. |

Default policy: Body/Head/Tail 0.50/0.30/0.20, Body required, minimum regional evidence 0.25, at least one observed region, at least 0.50 original-weight coverage, final support 0.50 and two eligible live frames in a window of 120 candidates. Missing contributions remain zero without redistributing weights. `two_part_v1` is an existing opt-in research candidate and is not approved as the default.

## Baseline and prioritized outstanding risks

1. **HIGH, validation gap:** No independent expert-labeled fish-level data or real-camera study was supplied. Difficult overlap ownership, counting, grading accuracy and realistic FPS therefore remain unverified; automated results do not establish them.
2. **HIGH, policy dependency:** Physically absent anatomy and any structural rejection rule require recorded annotator decisions and independent evaluation. The current nondetection is unknown; see `docs/policy_21_expert_review_brief.md`. Preserve existing standard behavior pending approval.
3. **MEDIUM, reproducibility:** The local installed dependency versions previously differed from declared requirements. A supported clean environment and hosted CI execution remain to be verified; the local passing suite is not proof of those environments.
4. **MEDIUM, deployment validation:** Real LAN routing, trusted TLS certificates and proxy configuration have not been tested on the target network; `README.md` documents the security profile and limitations.

## Tests

From `Thesis/sardinella-lemuru-ml`, `C:/Users/User/AppData/Local/Python/bin/python.exe -B tests/run_model_free_isolated.py` completed: **557 passed, 6 skipped, 80 subtests, 7 warnings**, 0 failed. Full output is in `results/qa/step01_model_free.log`. The runner excludes checkpoint files, clears runtime overrides and runs pytest from a temporary copy. Checkpoint-backed tests are separately opt-in as described in `tests/README.md`; this run is not a real-camera or accuracy test. Next verify temporal behavior in prompt 02.
