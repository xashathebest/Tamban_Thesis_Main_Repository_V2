# Final polish and QA progress

The 21 numbered prompts below were discovered in `Documentation/Tamban_Thesis_Final_Polish_and_QA_Prompts_2026-10-15/Tamban_Thesis_Final_Polish_and_QA_Prompts_2026-10-15/prompts`. Prefixes 01–21 each occur once, in ascending order, with no gaps. Supporting README and evidence templates are not numbered prompts. Work proceeds sequentially; statuses record the actual scope of verification, including hardware and study limitations.

| # | Actual filename | Status | Evidence / outstanding work |
|---|---|---|---|
| 01 | 01_Audit_Current_Code_And_Baseline.md | PROVISIONALLY VALIDATED | 567 passed, 6 skipped; syntax passed. Inventory and risk register: `qa/final/baseline_inventory.md`; commands/results: `qa/final/baseline_tests.md`. Hardware, CUDA and independent-data validation remain pending. |
| 02 | 02_Freeze_Model_Selection_And_Isolate_Uploads.md | PROVISIONALLY VALIDATED | 58 focused tests passed; model-free selection/upload contract in `qa/final/02_model_selection_contract.md`. Process and hardware limits remain. |
| 03 | 03_Session_Start_Stop_Restart_Reliability.md | PENDING HARDWARE VALIDATION | 47 lifecycle simulations passed; state diagram and limitations in `qa/final/03_lifecycle.md`. |
| 04 | 04_Atomic_Settings_Checkpoint_Integrity.md | PROVISIONALLY VALIDATED | Added concurrent settings regression; 57 focused tests passed; contract in `qa/final/04_settings_contract.md`. |
| 05 | 05_Tracker_And_Parent_Part_Association.md | PENDING HARDWARE VALIDATION | 50 tests and 44 subtests passed; actual CPU load used IoU fallback because `lap` is missing. `qa/final/05_association.md`. |
| 06 | 06_Temporal_Grading_Uncertainty_And_Dropouts.md | PROVISIONALLY VALIDATED | 58 tests and 53 subtests passed; synthetic matrix in `qa/final/06_temporal_policy.md`. |
| 07 | 07_Expert_Rules_And_Feature_Claims.md | PROVISIONALLY VALIDATED | 19 tests and 12 subtests passed; feature/claims matrix in `qa/final/07_feature_truth_table.md`; expert study pending. |
| 08 | 08_Historical_Records_Review_And_Exports.md | PROVISIONALLY VALIDATED | Fixed spreadsheet-formula interpretation; 45 tests, 12 subtests and history/export browser smoke passed; `qa/final/08_history_exports.md`. |
| 09 | 09_Input_Validation_Error_Recovery_And_LAN_Safety.md | PROVISIONALLY VALIDATED | 60 tests, 36 subtests and local HTTPS browser smoke passed; actual LAN/hardware pending. `qa/final/09_input_and_lan.md`. |
| 10 | 10_Measure_Actual_FPS_And_Timing.md | PENDING HARDWARE VALIDATION | 41 instrumentation tests passed; representative scenes and true displayed FPS/age unmeasured. `qa/final/performance_baseline.md`. |
| 11 | 11_Safely_Optimize_Model_Inference.md | BLOCKED — EMPIRICAL VALIDATION | No representative performance baseline or independent labeled clips; 56 synthetic tests passed on review. `qa/final/performance_changes.md`. |
| 12 | 12_Decouple_Preview_From_Heavy_AI.md | PENDING HARDWARE VALIDATION | Optional separate raw stream implemented; 57 tests and 36 subtests passed. Field smoothness and overhead blocked; `qa/final/12_preview.md`. |
| 13 | 13_Simplify_Sidebar_And_Dashboard.md | PROVISIONALLY VALIDATED | 53 tests, 4 subtests and 390/1280 px keyboard navigation smoke passed; `qa/final/13_navigation.md`. |
| 14 | 14_Polish_Live_Inspection_Interactions.md | PROVISIONALLY VALIDATED | 62 tests, 16 subtests and simulated browser states passed; actual camera and long run pending. `qa/final/14_live_states.md`. |
| 15 | 15_Polish_History_Settings_Exports_UX.md | PROVISIONALLY VALIDATED | 76 tests and export/review browser smokes passed; `qa/final/15_secondary_workflows.md`. |
| 16 | 16_Responsive_Visual_And_Accessibility_Finishing.md | PROVISIONALLY VALIDATED | Headless 390/1280/1366/1920 px layout and keyboard checks; live overlays and assistive tech pending. `qa/final/16_responsive.md`. |
| 17 | 17_Code_Cleanup_Resource_And_Long_Run_QA.md | PENDING HARDWARE VALIDATION | 30 short cleanup/resource tests passed; real 30–60 min soak not run. `qa/final/stability_maintenance.md`. |
| 18 | 18_Comprehensive_Automated_Manual_QA.md | PROVISIONALLY VALIDATED | Isolated suite 588 passed, 6 skipped, 92 subtests; field/science checks blocked. `qa/final/qa_test_matrix.md`. |
| 19 | 19_Independent_Science_Validation_And_Demo_Rehearsal.md | BLOCKED — SCIENTIFIC AND HARDWARE VALIDATION | Protocol, claims audit and planned walkthrough prepared; no independent labels or target-machine rehearsal. `qa/final/scientific_readiness.md`. |
| 20 | 20_Final_Release_Review_And_Documentation.md | NOT READY | Report bundle prepared; 588 model-free tests and 2 CPU model compatibility tests passed; release blockers remain. `qa/final/FINAL_QA_REPORT.md`. |
| 21 | 21_Optional_Expert_Evidence_Library.md | PROVISIONALLY VALIDATED — DISABLED | Existing empty scaffold retained; 5 access/metadata tests passed; real consented content and playback untested. `qa/final/21_expert_library.md`. |

## 01 — Fresh baseline

Objectives: inventory the current flow, prior findings, environment and risks before edits. Inspected README, runtime API/inference/feature modules, model registry/configuration, previous progress reports, dataset claims and associated tests. Findings: prior synthetic regressions protect model switching, lifecycle, settings, tracking, temporal evidence and historical exports; actual overlapping fish, hardware timing and independent grades remain unvalidated. Installed OpenCV and Ultralytics conflict with declared requirements. No application code changed; added baseline inventory, test evidence and environment/working-tree snapshots under `qa/final/` and this tracker. Model-free suite: 567 passed, 6 skipped, 88 subtests; Python and JavaScript syntax passed. Status is provisional because model-backed, camera, CUDA and independent-study evidence were not established by these checks.

## 02 — Model identity and upload isolation

Objectives: freeze active model/config and avoid upload-driven mutation. Inspected selection, settings, upload and camera paths, registry, model adapter and loaded identity/hash snapshots. Existing locks, validation and regression tests cover active-route attempts, invalid uploads, concurrent upload/camera processing, idle switch, unavailable checkpoint and loaded-model identity; no defect was reproduced. No application files changed; added `qa/final/02_model_selection_contract.md` and `02_model_selection.log`. Focused tests: 58 passed, one dependency warning. Real camera/model execution and cross-process exclusion remain unvalidated; status provisional.

## 03 — Lifecycle and session ownership

Objectives: create sessions before events, report truthful stop state, prevent restart until cleanup and reset transient evidence. Inspected `src/api/app.py`, `src/api/camera.py`, `src/api/database.py`, and lifecycle tests; existing code and tests cover startup/failure, immediate event, timeout, cleanup, restart and error handling. No application defect was reproduced or code changed. Added lifecycle diagram and test log under `qa/final/`. Focused simulations: 47 passed, one warning; real camera acquisition, stalled driver and resource release remain PENDING HARDWARE VALIDATION.

## 04 — Atomic settings and checkpoint integrity

Objectives: validate complete settings before mutation, serialize changes and preserve checkpoint/config provenance. Inspected settings routes, config snapshots, registry and loaded model hashes. Existing tests cover mixed invalid payloads, rollback, integrity failures and explicit overrides; added `tests/test_settings_atomic_qa.py` concurrent-request regression to check serialization and consistent final detector/state values. No production code changed. Added `qa/final/04_settings_contract.md` and test log. Focused tests: 57 passed, one warning; physical driver restoration and cross-process behavior remain unverified.

## 05 — Tracker identity and part ownership

Objectives: establish the actual tracker and protect per-fish ownership. Inspected `yolo_fish_detector.py`, `association.py`, `part_fusion.py`, camera scheduling, requirements and tests. Actual CPU checkpoint load selected IoU fallback with an explicit missing-`lap` warning; it was not a live-camera run. Added `tests/test_association.py` known-ID crossing/ambiguous-overlap recovery test; existing tests cover duplicate IDs, excluded parents, dropouts and independent grades. No production code changed. Focused suite: 50 passed, 44 subtests; details and model-load log in `qa/final/05_association.md`. Real overlap, tracking continuity and visual sample validation remain pending.

## 06 — Temporal evidence and uncertainty

Objectives: verify distinct usable frames, bounded windows, uncertainty recovery, dropout handling and per-part eligibility. Inspected grading engine/policy, camera track pruning and adaptive policy tests. The prompt's older fixed-weight instruction is superseded by the user's explicit Tail-optional implementation request; no scientific policy changed during QA. Added mandatory-region, zero-confidence and equal-support margin tests in `tests/test_tail_optional_policy.py`; added `qa/final/06_temporal_policy.md` with a synthetic behavior matrix. Corrected focused suite: 58 passed, 53 subtests. An initial invocation named a nonexistent test file and ran no tests; it is recorded in the matrix. Independent validation remains unavailable.

## 07 — Expert rules and feature claims

Objectives: distinguish live grade inputs, diagnostics, offline features and unvalidated structural proposals. Inspected grading configuration/engine, feature-claims audit, UI copy and expert-policy brief. Existing disclosures do not describe HSV, edge density or nondetection as validated structural defects; no production changes were necessary. Added `qa/final/07_feature_truth_table.md` and log. Disclosure, structural-evidence and adaptive-policy tests: 19 passed, 12 subtests. Expert approval and independent fish-level labels remain pending; no new structural override was activated.

## 08 — History, review and exports

Objectives: preserve historical model/policy provenance, user-selected fields, original AI grades and review audit history. Inspected database, API, UI and export paths. Reproduced formula-like reviewer input being emitted as spreadsheet-executable text (pre-fix: 1 failed, 1 passed). Changed `src/api/export.py` to neutralize formula-like CSV text and keep XLSX cells literal; changed `tests/test_export_selection_qa.py` and documented CSV representation in `README.md`. No schema or saved history changed. Focused tests: 45 passed, 12 subtests, one warning; historical review and export browser smoke passed. Added synthetic export samples and `qa/final/08_history_exports.md`; earlier intermittent Chrome protocol failures remain a harness limitation.

## 09 — Input, recovery and LAN safety

Objectives: verify bounded upload/decode, error recovery and local/LAN access controls. Inspected upload reader/decoder, camera failure handling, launcher and LAN middleware. Existing limits, recovery and authorization tests passed; no additional production changes were justified. Focused suite: 60 passed, 36 subtests, one warning. Local self-contained HTTPS browser smoke passed. Added `qa/final/09_input_and_lan.md` and logs. Actual remote routing, trusted certificates, firewall/proxy setup, camera and GPU recovery remain unvalidated.

## 10 — Runtime measurement baseline

Objectives: establish correctly labeled timing and comparable empty/one/overlap scene measurements. Inspected runtime diagnostics, camera, benchmark and frontend telemetry; 41 simulated checks and 36 subtests passed. Windows lists an HP webcam, but its thesis-conveyor suitability and required fish scenes are unverified; no real scene timing was measured. PyTorch reports CUDA unavailable, while a local CPU Model 1 load used IoU fallback. Browser display FPS and capture-to-display age are not measured by the existing MJPEG path. Added `qa/final/performance_baseline.md` with exact reproduction commands and limitations; no runtime code changed. Representative timing and overhead remain PENDING HARDWARE VALIDATION.

## 11 — Measured inference optimization

Objectives: optimize measured bottlenecks only after paired speed/accuracy evaluation. Inspected device selection, model reuse, scheduling and the existing replay methodology; 56 model-free tests and 48 subtests passed. A/B gains and safety cannot be measured because target-scene timing and independent labeled clips are unavailable. No optimization, model or policy change was made. Added `qa/final/performance_changes.md` with candidate decisions and rollback. Status BLOCKED; obtaining the missing data is necessary for this phase's empirical acceptance.

## Regression through phase 11 and continuation point

After the phase 08 export fix and added tests, `python -B tests/run_model_free_isolated.py` passed **579 tests, 6 skipped, 92 subtests, 7 warnings** in 14.26 seconds (`qa/final/regression_through_11.log`). Python syntax passed for 167 source/test files; `node --check frontend/app.js` and the scoped `git diff --check` passed (the latter reported line-ending notices). This is a regression of work through phase 11, not the final integration review required after phase 21.

Phase 11 cannot be empirically completed until representative target-camera baseline runs and independent fish-level labels/clips are available. The user subsequently authorized skipping that blocker for now and continuing software-only work in order. Resume phase 11 using `qa/final/performance_baseline.md` and `docs/model2_schedule_benchmark.md` when data are available. No measured accuracy/FPS improvement, hardware acceptance, full release or thesis-defense readiness is claimed.

## Continuation dependency review

Read `continuee.md`, reviewed phase 11's performance documentation and tests, and read prompts 12–21 in numerical order. Reran the phase 11 model-free suite: 56 passed, 48 subtests (`qa/final/11_continuation_review.log`). Added `qa/final/continuation_dependency_review.md` with prompt-by-prompt technical and empirical dependencies. The user explicitly authorized skipping phase 11 for now and continuing software-only work. Phase 11 remains blocked; this permission does not constitute empirical acceptance.

## 12 — Separate optional raw preview

The existing browser stream followed AI processing despite a separate capture thread. Added a startup-flagged, subscriber-aware raw JPEG preview with a one-frame queue and a separate encoder shared across clients; it never carries AI overlays. The processed feed stays the default. The interface identifies the mode, labels AI processing FPS, and states that browser preview FPS and latency are unmeasured. Added `src/api/raw_preview.py`, integrated camera/API/frontend, documented `FISH_RAW_PREVIEW_ENABLED`, and added model-free lifecycle/security/queue tests. Focused run: 57 passed, 36 subtests, one warning (`qa/final/12_preview_tests.log`); `node --check frontend/app.js` passed. An initial sandboxed run had 12 temp-directory permission errors; rerun with access passed. Actual display FPS, latency, overhead, camera release and multi-client field behavior remain BLOCKED pending hardware. See `qa/final/12_preview.md` for trace and rollback.

## 13 — Navigation and dashboard

Desktop duplicated Settings and Export between the header and sidebar; mobile needed the header because the sidebar actions are hidden. Hid the desktop header duplicates while preserving mobile access and existing IDs/handlers. Kept the single visible feed-overlay controls in the Live disclosure and labeled Analytics as a Live destination. Focused dashboard, status, history and export tests: 53 passed, 4 subtests, one warning (`qa/final/13_navigation_tests.log`); existing dashboard browser smoke passed. Added keyboard and 390/1280 px headless navigation smoke and screenshots; the final run passed (`qa/final/13_navigation_smoke.log`). Initial harness import and synthetic key-event issues were corrected before the successful run. No backend API changed. Physical devices and assistive technology remain untested. See `qa/final/13_navigation.md`.

## 14 — Live operator states

Reviewed lifecycle feedback, model/camera status, controls, grade reasons and upload separation. Corrected an errored worker being described as a camera failure regardless of backend cause, and disabled repeated Stop while already stopping. Included backend message and raw-preview availability in the camera render key so changed errors and stream mode are reflected. Focused simulated lifecycle, upload and grade tests: 62 passed, 16 subtests (`qa/final/14_live_tests.log`). Headless browser checks simulated stopped, starting, running, stopping and error controls (`qa/final/14_state_browser.log`; state table in `14_synthetic_states.json`). Real camera, dropped signal, multiple fish and long-running workflows remain pending; screenshots from phase 13 are stopped synthetic-data views. See `qa/final/14_live_states.md`.

## 15 — History, settings and exports

Reviewed session-aware history, review, settings and selected-column exports. Export failures previously appeared behind the modal; added in-dialog feedback and disabled submission for no fields or reversed dates, retaining open-ended ranges. No API or historical data changed. Focused history/review/export/settings/model-switch suite: 76 passed, one warning (`qa/final/15_workflow_tests.log`); browser export validation/error and cross-session review smokes passed. Prior dashboard smoke exercised pagination and stale response handling. Some 422 and keyboard-only end-to-end cases remain untested; see `qa/final/15_secondary_workflows.md`.

## 16 — Responsive layout and accessibility

Inspected semantic labels, focus outlines, dialogs, reduced-motion CSS and contained video sizing. Extended headless keyboard and horizontal-overflow checks to 390×844, 1280×900, 1366×768 and 1920×1080 (`qa/final/16_responsive_browser.log`). Reviewed the stopped laptop and mobile screenshots; wide screenshot also saved. No additional CSS rewrite was warranted. Real video overlay alignment, browser zoom, console audit, physical devices, contrast tooling and assistive-technology testing remain pending. See `qa/final/16_responsive.md`.

## 17 — Resource stability

Reviewed bounded frame queues, capture/finalizer cleanup, stream subscriber lifecycle, frontend request aborts and historical database paths. Added a read-only, optional-psutil local process/status monitor and a 20-cycle preview encoder cleanup test. Focused suite: 30 passed (`qa/final/17_stability_tests.log`); monitor help passed. Actual 30–60-minute camera/AI soak, CPU/memory/handle trend, hundreds of uploads and interrupted-write recovery are BLOCKED pending a supervised target setup. No datasets or historic files were removed. See `qa/final/stability_maintenance.md` for procedure and limitations.

## 18 — Comprehensive QA matrix

Ran the isolated checkpoint-free suite: 588 passed, 6 skipped, 92 subtests, 7 warnings in 18.72 seconds (`qa/final/18_full_model_free.log`). Created `qa/final/qa_test_matrix.md`, `test_summary.md` and `test_summary.json`, linking software checks and preserving field and scientific blockers. Browser smoke and focused results from phases 12–17 are included. Python 3.14.6, CPU-only PyTorch, incompatible installed OpenCV/Ultralytics versions and missing optional tracker dependency remain environment risks. This is not final release acceptance.

## 19 — Independent science and demo

Reviewed readiness JSON, historical split audit, preflight and development part metrics. The historical audit reports 39 train/validation and 38 train/test overlapping lineage groups; its near-duplicate scan was incomplete. The inspected 17-image test preflight has no Class A part annotations. No independent labels or clips are available. Added `qa/final/scientific_readiness.md`, `demo_script.md` and `hardware_checklist.md` with separate claim scopes and planned walkthrough. No accuracy, expert agreement, live timing, or rehearsal result was invented. Independent evaluation and defense-machine rehearsal remain BLOCKED.

## 20 — Final release review

Prepared the six named report artifacts under `qa/final/`. Actual registered-model CPU compatibility and reference-image tests passed: 2 (`20_checkpoint_tests.log`); this is not independent accuracy. The latest complete isolated model-free run remains 588 passed, 6 skipped, 92 subtests, seven warnings. The only release decision is **NOT READY** because independent science, target-camera measurement, long soak and rehearsal are absent and the installed dependencies are outside declared ranges. Reference Git HEAD is `eb1e252618967b7dbce458be9ced8f3519d7bedd`, but the working tree contains extensive uncommitted changes and is not represented by that hash. Phase 21 optional-library review is the remaining numbered phase; no commit, deployment or schema migration was performed.

## 21 — Optional expert consultation library

Inspected the existing default-disabled read-only library, empty schema template and consent/access documentation. No additional media, quotes, identity claims or implementation were added. Existing synthetic access, missing-media and metadata tests passed: 5, one warning (`qa/final/21_expert_library_tests.log`); headless navigation into Expert and back to Live passed. Real consented playback, source-link design, timestamp verification and expert approval remain blocked. See `qa/final/21_expert_library.md`.

## Final regression after phase 21

`python -B tests/run_model_free_isolated.py`: 588 passed, 6 skipped, 92 subtests, 7 warnings in 19.53 seconds (`qa/final/21_final_model_free.log`). Final headless navigation/state smoke passed at all four selected widths (`qa/final/21_final_browser.log`), as did JavaScript syntax and the scoped whitespace check (one line-ending notice). The six release-report artifacts exist and their local Markdown links resolve. The final decision remains **NOT READY**; the post-phase-18 checks do not resolve phase 11, target-hardware validation or independent science.
