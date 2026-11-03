# Tamban deep code QA progress

Source: `Documentation/Tamban_Thesis_Deep_Code_QA_Prompts_2026-10-14`. Verified 23 unique, consecutive numeric prefixes 01–23; supporting README, audit findings and reproduction notes are not numbered prompts. Preserve the existing working tree and follow this order.

| # | Actual prompt | Status | Objective and validation |
|---|---|---|---|
| 01 | 01_Baseline_Reproducible_Test_Audit.md | COMPLETED | Baseline only; inspected tests, CI, requirements, API, detector, quality model, grading and earlier tracker. `docs/deep_code_qa_baseline.md` records issue severities, evidence, policy and environment. Unittest: 372 tests, 5 skipped; pytest: 422 passed, 5 skipped, 80 subtests; compile and JS syntax passed. No application fix or runtime change. Real-camera, checkpoint fidelity and expert labels remain unvalidated. |
| 02 | 02_Block_Live_Model_Switching_All_Paths.md | COMPLETED | Existing direct/settings/upload guards already rejected starting/running. Reproduced HIGH: a stopping or still-alive worker could accept a switch, previous temporal evidence survived a successful switch, and grading could race with switching; MEDIUM: rejected mixed settings could change display state and failed selection persistence could leave inconsistent state. `src/api/app.py`, `src/api/camera.py`, `src/inference/yolo_quality_model.py`, `src/inference/model_registry.py` now serialize start/stop/switch, reject live workers before settings mutations, lock full quality inference and grading, clear temporal evidence after a successful change, and atomically persist selection before committing. Failed loads/writes preserve the old model; identical stopped selections are no-ops. `tests/test_model_switch_safety.py` covers routes, stopping/alive workers, rollback, repeated/simultaneous selection and interleaved grading. Focused: 61 passed, 40 subtests; full unittest: 372 tests, 5 skipped; full pytest: 437 passed, 5 skipped, 80 subtests; compilation and diff checks passed. Real camera and expert accuracy remain pending. |
| 03 | 03_Isolate_Upload_Model_Choice_From_Live_Model.md | COMPLETED | Inspected `src/api/app.py::analyze_image`, `src/api/image_analysis.py`, upload tests and frontend. Earlier invalid-image switching was already prevented, but reproduced HIGH: a valid stopped upload with a different override changed the shared model. Uploads now use the active model only; compatible different overrides return 409 and unsupported IDs 400. Processing shares the live frame lock and selection lock, preserving model/session and telemetry coherence; live processing pauses during upload. Documented policy in `README.md`. `tests/test_model_switch_safety.py` covers invalid bytes, unsupported IDs, failed inference, concurrent processing, and no mutation. Focused: 107 passed, 40 subtests; full unittest: 372 tests, 5 skipped; full pytest: 441 passed, 5 skipped, 80 subtests. Hardware-dependent effects on real preview latency remain unmeasured. |
| 04 | 04_Repair_Durable_Session_Start_Race.md | COMPLETED | Reproduced first worker callback written to a previous closed session, failed startup inconsistencies, and premature close after stop timeout. `src/api/app.py` now creates the durable session before starting the worker, closes failed starts, avoids closing a live worker's session, and serializes resets with frame processing. `src/api/database.py` serializes writes with close/rotation; closed sessions accept only updates to existing fish, not new events. Rotation creation failure preserves the previous session; no historical events are deleted. `src/api/camera.py` uses a reentrant processing lock for reset ordering. `tests/test_session_lifecycle_qa.py` covers early callback, duplicate start, failures, stop timeout, closed updates, rapid restart and reset ordering. Focused: 78 passed, 4 subtests; unittest: 372 tests, 5 skipped; pytest: 451 passed, 5 skipped, 80 subtests. Actual camera timing and power-loss recovery remain untested; stop-timeout reporting is the next phase. |
| 05 | 05_Truthful_Stop_Timeout_And_Restart.md | COMPLETED | Reproduced stop returning success while a blocked worker remains alive. `src/api/camera.py` keeps the worker reserved through cleanup, bounds the request wait and uses at most one daemon finalizer per worker; it closes the session after worker exit and prevents restart until cleanup completes. `src/api/domain.py`, `src/api/app.py` and `frontend/app.js` report and display stopping, reject policy changes/restarts while stopping, and avoid claiming a completed stop while the worker is active. `tests/test_stop_timeout_qa.py` covers blocked workers, repeated stop, blocked cleanup, session closure, rapid restart and worker errors; existing lifecycle and phase 04 tests remain green. Focused: 89 passed, 4 subtests; unittest: 372 tests, 5 skipped; pytest: 456 passed, 5 skipped, 80 subtests; JS syntax and diff checks passed. Real device interruption and indefinitely blocked drivers remain hardware limitations: cleanup waits and restart stays disabled until the worker exits. |
| 06 | 06_Validate_Settings_Before_Any_Change.md | COMPLETED | Reproduced four mixed requests that returned errors after changing thresholds. `src/api/app.py` validates types, ranges, display fields, model compatibility/checkpoint and inspection locks before mutation; failures restore software settings and active policy updates rotate session metadata. Model changes require a closed session, avoiding inconsistent metadata on a failed cross-store rotation. `src/inference/yolo_quality_model.py` restores temporal evidence and the previous selection if loading, reset or persistence fails. `src/api/camera_controls.py` preflights hardware requests, attempts best-effort restoration, and reports per-property results, rollback and final readback; calibration mode changes are separate. `README.md` documents the operator behavior. `tests/test_settings_atomic_qa.py`, `tests/test_camera_settings_atomic_qa.py`, and `tests/test_model_switch_safety.py` cover mixed validation, apply/rotation/load/reset failures, hardware rejection and failed restoration. Focused: 51 passed; unittest: 372 tests, 5 skipped; final pytest: 471 passed, 5 skipped, 80 subtests. Hardware restoration depends on the physical driver and has only been simulated. |
| 07 | 07_Respect_Export_Column_Checkboxes.md | COMPLETED | Confirmed the form always sent complete_analysis=true, overriding field choices. `frontend/index.html` and `frontend/app.js` now send checked fields in display order, expose an explicit full-evidence checkbox, and explain empty selections. `/api/export` in `src/api/app.py` requires nonempty selected fields or explicit full mode, rejects duplicates/invalid types, and preserves requested column order; `README.md` documents the API change and separate Excel sheets. `tests/test_export_selection_qa.py` covers CSV/XLSX, full mode, empty/invalid fields and summary sheets; `tests/export_form_smoke.py` exercised actual checkbox choices in headless Chrome. Focused: 35 passed, 5 subtests; browser smoke passed; unittest: 372 tests, 5 skipped; pytest: 479 passed, 5 skipped, 80 subtests; JS syntax passed. Earlier API callers that omitted fields must now choose fields or explicitly request full evidence. Historical rules are addressed in phase 08. |
| 08 | 08_Export_Historical_Session_Rules_Accurately.md | COMPLETED | Reproduced historical XLSX reports showing current weights and direct lookup missing older than 1000 sessions. `src/api/database.py` now queries session IDs directly and prevents changing recorded model/policy snapshots. `src/api/app.py` and `src/api/export.py` use the saved session grading configuration and hashes, mark missing information unavailable, and include per-session configuration and row mapping for mixed-session Excel exports. Multi-session CSV requests return 422 directing users to Excel so policy provenance is not lost. `tests/test_historical_export_qa.py` covers two differing synthetic policies/hashes, row mappings, missing/unknown sessions, immutability and >1000 later sessions; original events remain intact. Focused: 42 passed, 5 subtests; unittest: 372 tests, 5 skipped; pytest: 486 passed, 5 skipped, 80 subtests. The different test weights are synthetic and do not alter production policy. |
| 09 | 09_Ensure_Tracker_Backend_Is_Explicit.md | COMPLETED | Confirmed Python 3.14.6 has no `lap` module locally: the prior source chose an IoU fallback but did not prominently warn. `src/inference/yolo_fish_detector.py` reports the actual backend, warns on fallback/custom trackers, and supports `FISH_REQUIRE_BYTETRACK=1` to fail without ByteTrack. `src/api/camera.py` and `src/api/app.py` prepare models before session creation, so persisted metadata records the selected tracker before any worker event; failed thread startup closes the session. Dashboard status shows the backend and warning. `requirements-bytetrack.txt` and `README.md` document optional lap 0.5.13 and supported wheels from PyPI; the dependency was not installed. `tests/test_tracker_backend_qa.py` covers fallback, strict failure, ByteTrack selection, session provenance, startup exceptions and synthetic overlapping detections; this does not establish overlap ID accuracy. Focused: 104 passed, 1 skipped, 11 subtests; headless Chrome warning passed; unittest: 372 tests, 5 skipped; pytest: 494 passed, 5 skipped, 80 subtests; JS syntax passed. Real-camera tracking/throughput and overlap ID stability remain unmeasured. |
| 10 | 10_Fix_FullFrame_Parent_Part_Ownership.md | COMPLETED | Existing full-frame inference already associates parts against all visible scheduled, unscheduled, finalized and untracked fish before grading selected IDs. Reproduced a remaining duplicate-tracker-ID detection being omitted as an ownership competitor: its part could be wrongly assigned. `src/api/camera.py` now gives duplicate detections frame-local competitor IDs without grading twice. `tests/test_runtime_diagnostics.py` and `tests/test_association.py` cover duplicate IDs, counted and untracked neighbors, ambiguity, no parent, ineligible ownership and fixed synthetic all-versus-subset outputs; duplicate regions remain unassigned. Focused: 22 passed and 36 subtests; unittest: 375 tests, 5 skipped; pytest: 497 passed, 5 skipped, 80 subtests. Real overlapping fish ownership and accuracy remain unvalidated without independent labeled footage. |
| 11 | 11_Preserve_Track_Evidence_Through_Short_Dropouts.md | COMPLETED | Reproduced evidence being erased after one missed detection and an expired reused ID inheriting scheduling state. `src/api/camera.py` now retains grade, scheduling, overlay and Model 2 temporal state while the domain tracker is within its monotonic timeout; it removes expired identities before inference, and uses the same timestamp for the domain update. Reset/restart clears evidence. `tests/test_runtime_diagnostics.py` covers multiple brief dropouts, no invented observations, reappearance after expiry, neighboring overlapping fish and reset. Unittest: 379 tests, 5 skipped; pytest: 501 passed, 5 skipped, 80 subtests. A sandboxed focused run hit system-temp permissions; the full runs with system-temp access passed. Real tracker ID stability and live-camera timing remain unmeasured. |
| 12 | 12_Fix_Temporal_Evidence_Counting_And_Recovery.md | COMPLETED | Verified `WeightedGradingEngine.evaluate` already requires distinct evidence-bearing frames, advances a bounded candidate window, and clears earlier evidence on uncertain ownership or model unavailability before requiring fresh evidence. Reproduced an old clipped rejection incorrectly remaining the current out-of-frame diagnostic. `src/inference/grading_engine.py` now derives current clipping and regional visibility from the latest rejection while retaining lifetime rejection counts. `tests/test_grading_engine.py` covers clipping recovery, unavailable-model recovery and contradictory grades; existing tests cover empty frames, duplicate frames, ambiguity and bounded evidence. Focused: 39 passed, 5 subtests; unittest: 382 tests, 5 skipped; pytest: 504 passed, 5 skipped, 80 subtests. No confidence thresholds or scientific policy changed; real-fish accuracy remains unvalidated. |
| 13 | 13_Safe_Model2_Error_Handling_And_Abstention.md | COMPLETED | Reproduced a Model 2 crash at the counting line preserving and counting a stale Class A grade. `src/api/camera.py` now creates explicit `UG_MODEL2_UNAVAILABLE` results for affected unfinalized fish, removes stale overlays and evidence, preserves successful crop results in partial batches, and retries with monotonic exponential delay capped at 5 seconds. A minimal fallback preserves the reason even if the abstention adapter fails; counted fish continue counting and finalized YOLO results are excluded from later cache updates. `src/inference/yolo_quality_model.py` selectively discards failed track evidence. `README.md` documents behavior; `tests/test_runtime_diagnostics.py` covers crash-at-line, adapter failure, partial crop/full-frame failure, retry/recovery, bounded delay and finalized event immutability. Focused: 59 passed, 40 subtests; unittest: 388 tests, 5 skipped; pytest: 510 passed, 5 skipped, 80 subtests. Hardware failure recovery remains untested. |
| 14 | 14_Check_Model_Checksum_And_Registry_Identity.md | COMPLETED | Reproduced explicit Model 2 path/ID mislabeling and unchecked registry SHA-256. `src/inference/yolo_quality_model.py` resolves actual registered identity, rejects explicit ID/path and registered hash/class mismatches before loading, labels unknown YOLO checkpoints custom and unverified, and hashes once per load/switch. `src/inference/model_adapters.py` requires actual class metadata. `FISH_STRICT_MODEL_INTEGRITY=1` requires registered SHA-256 matches for both models and blocks live inspection and whole-fish image analysis otherwise; custom and unhashed models are rejected. `src/api/app.py` records the load-time full hashes and paths, avoiding a changed on-disk file being described as loaded bytes. `README.md` documents the policy. Tiny-file `tests/test_model_integrity_qa.py` covers matching, tampering, override identity, absent classes, strict gates, switch rollback and snapshots. Focused: 13 passed; unittest: 388 tests, 5 skipped; pytest: 523 passed, 5 skipped, 80 subtests. Hash verification cannot prevent a file being replaced between hashing and the model loader opening it; no real-camera or expert accuracy claim. |
| 15 | 15_Limit_Upload_Size_Before_Decoding.md | COMPLETED | Reproduced full buffering of oversized lengthless/misdeclared streams, dimension checking after OpenCV decode, and BMP content accepted under a JPEG filename. `src/api/app.py` now reads incrementally and stops with 413 at the byte limit; `src/api/image_analysis.py` validates JPEG/PNG headers and WebP canvas sizes before decoding, accepts only actual supported formats, and keeps OpenCV EXIF handling and 400 invalid-image behavior. WebP dimensions are read without initializing its decoder. Direct Pillow format readers avoid an Ultralytics monkey-patched Image.open that attempted an unavailable HEIF installation on unsupported images; no dependency was installed. `tests/test_upload_limits_qa.py` covers early termination/cleanup, false lengths, oversized headers, formats, EXIF and WebP variants; README documents limits. Focused: 46 passed, 4 subtests; unittest: 388 tests, 5 skipped; pytest: 533 passed, 5 skipped, 80 subtests. Memory is bounded per upload; aggregate concurrency and reverse-proxy limits were not load-tested. |
| 16 | 16_Bound_History_Queries_And_Status_Analytics.md | COMPLETED | HIGH: confirmed history and every analytics refresh materialized all records. `src/api/database.py` now applies parameterized session/date filters, selective field queries, deterministic indexed ordering and SQLite pagination; timestamp dates retain their recorded offset semantics. `src/api/app.py` streams summaries, bounds each trend to 500 points, caches them by transactional session revision, and incrementally applies chronological inserts and review-only updates; arbitrary edits, deletions and coalesced changes rebuild correctly. SQLite change and previous-event tables support invalidation. `frontend/app.js` labels the latest observations; `README.md` explains limits. `tests/test_history_performance_qa.py` covers paging, filters, offset dates, sessions, cache updates, review clearing, multiple updates, deletes and timestamp ties; existing export/status tests pass. Full unittest: 388 tests, 5 skipped; pytest: 539 passed, 5 skipped, 80 subtests; JS syntax passed. Synthetic single-run benchmark (`results/qa/prompt16_history_before.json`, `prompt16_history_after.json`) at 100/10k/100k records: 100k first history page 12,405.78→12.32 ms and 384,354,132→65,065 Python peak bytes; repeated analytics 16,746.62→5.39 ms; new fish 16.80 ms and review 22.75 ms. Fresh 100k summary still takes 4,985.12 ms and rebuilding after non-incremental changes remains O(n); filters, exports and review queue may scan larger selections. Measurements use tracemalloc, not process RSS, and do not establish camera FPS. |
| 17 | 17_Review_Past_Sessions_Without_Losing_AI_Truth.md | COMPLETED | HIGH: the dashboard posted only a reused track ID and history loaded only the current session, so historical review could affect the wrong fish. `src/api/app.py` accepts and validates a session-qualified review while retaining current-session default; queue and audit endpoints support explicit sessions. `src/api/database.py` atomically stores the manual outcome and an append-only audit record, preserving AI grade/evidence and the event's ordering; `src/api/domain.py` synchronizes current in-memory reviews without overwriting durable provenance. `frontend/index.html` and `frontend/app.js` add a historical session selector, session-qualified review, optional reviewer and clearing controls, and label AI distribution; `src/api/export.py` separates AI and manual fields and includes reviewer/source. Analytics explicitly marks AI prediction counts, operator review counts and unavailable accuracy; README documents the API and self-reported reviewer identity. `tests/test_historical_review_qa.py` covers reused IDs, past/current, validation, repeat/clear, transactional rollback, later live updates and exported labels. `tests/historical_review_smoke.py` passed in headless Chrome; existing dashboard smoke passed; focused tests 49 passed; full unittest 388 tests, 5 skipped; pytest 545 passed, 5 skipped, 80 subtests; JS syntax passed. The session selector lists the 1,000 newest sessions; older IDs remain accessible through the API. Reviewer identity is not authenticated and manual reviews are not independent expert ground truth. |
| 18 | 18_Make_Model_Free_CI_Truly_Model_Free.md | COMPLETED | HIGH: reproduced six multi-model test failures in a temporary source copy without checkpoints; the only workflow was nested below the actual Git root and `unittest` omitted pytest-style tests. `tests/test_multi_model_selection.py` now copies registry metadata to a temporary fixture with tiny independently hashed fake checkpoints, mocks adapters and isolates selection settings, retaining traversal, switching, inference reuse and diagnostic assertions. `tests/run_model_free_isolated.py` copies source without checkpoint files or local runtime overrides and runs pytest; `requirements-test.txt` supplies pytest and httpx. Added discoverable root `.github/workflows/model-free-tests.yml`, using CPU PyTorch and the checkpoint-free runner; retained an updated standalone-project workflow template. `tests/test_checkpoint_smoke.py` is a separately invoked real-checkpoint inference test; `tests/README.md` documents its prerequisites and limits. Before: 6 failed, 10 passed; after: 16 focused passed; isolated full suite 545 passed, 6 skipped, 80 subtests; unittest 389 tests, 6 skipped. Opt-in checkpoint smoke passed on local registered weights using a synthetic frame. Workflow YAML parsed locally; actual GitHub Actions/Python 3.11 Linux execution and clean dependency installation were not available here, so hosted portability remains unverified. No camera, real-fish accuracy or FPS was established. |
| 19 | 19_Guard_LAN_Exposed_Operator_Actions.md | COMPLETED | HIGH conditional on network exposure: the launcher allowed non-loopback binding with unauthenticated writes and history. `src/api/__main__.py` now warns on network binds and requires an enabled profile, valid operator token and TLS certificate/key; `src/api/lan_security.py` and middleware in `src/api/app.py` protect API reads/writes, distinguish viewer/operator/admin roles, limit login attempts, disable LAN debug by default, hide debug details from non-admin status, and recheck stream credentials on logout/expiry. Browser sessions use Secure/HttpOnly/SameSite cookies, same-origin CSRF tokens, token rotation and an eight-hour expiry; bearer clients require HTTPS. `frontend/index.html` and `frontend/app.js` provide sign-in/sign-out while retaining normal localhost mode. `README.md` documents token generation, TLS, shared-credential limitations, one-worker requirement, proxy precautions and the independent localhost-only expert library. `tests/test_lan_security_qa.py` covers local mode, remote denial, read/write roles, misconfiguration, CSRF, logout, rotation, stream revocation, rate limiting and launcher safeguards. A temporary self-signed HTTPS headless Chrome smoke and the existing local dashboard smoke passed; focused tests 22 passed before final session-replacement test, final security tests 8 passed; unittest 389 tests, 6 skipped; final pytest 553 passed, 6 skipped, 80 subtests; JS syntax passed. Actual LAN routing, trusted certificates, firewalls and proxy deployment remain untested. Shared tokens are not individual reviewer identities; the local mode and reverse proxies that conceal client addresses require the documented deployment precautions. |
| 20 | 20_Label_Feature_Diagnostics_Honestly.md | COMPLETED | Audited runtime grading, camera statistics, offline features, UI and exports. HSV/defect adjustment switches do not apply a rule; 50/30/20 Model 2 support remains unchanged. `frontend/app.js` identifies HSV value, yellow and highlight as rectangular-ROI diagnostics, and `frontend/index.html` explains camera brightness, the limits of confidence/support and the research-only belly-defect topic. `src/api/export.py` labels each HSV CSV/XLSX column as a diagnostic ROI and fixes the feature summary to count fish with measured colour, rather than every fish. API field keys remain stable; displayed CSV/XLSX headers change. `docs/feature_claims_audit.md` classifies active, diagnostic, offline and planned features, including edge density and optional quality gates. `tests/test_feature_claims_qa.py` covers switches, claims, headers and measured/unavailable/empty summaries. Focused: 33 passed, 5 subtests; unittest: 393 tests, 6 skipped; pytest: 557 passed, 6 skipped, 80 subtests; JS syntax and historical-review browser smoke passed. No expert-validated defect model, real-fish accuracy or camera validation was established. |
| 21 | 21_Stage_Expert_Approved_Grading_Policy_Updates.md | BLOCKED | Inspected `configs/grading_engine.yaml`, `src/inference/grading_policy.py`, `src/inference/grading_engine.py`, `src/inference/structural_evidence.py`, structural review routes and existing policy tests. Default standard mode permits Body-only eligibility subject to 0.50 final support and other gates; the existing opt-in research candidate `two_part_v1` requires Body plus Head or Tail and preserves original weights. With otherwise identical gates, the extra requirement cannot reduce Ungraded counts; no real-data improvement is established. Missing detections do not establish physical absence; the current model's Rejected labels are model evidence, while separate structural review does not change the AI verdict. Prepared `docs/policy_21_expert_review_brief.md` with the proposed decisions, provenance needs and independent comparison protocol. Focused existing policy/structural tests: 22 passed. No new policy or structural gate was implemented: this prompt explicitly requires annotator confirmation first, and no signed decision was found. The user states independent videos and expert labels are not yet available, so the required held-out comparison is also blocked. Obtain the annotator's recorded decisions and suitable independently labeled overlap/occlusion data, then complete and validate this phase before phase 22. |
| 22 | 22_Repair_Independent_Test_Readiness_Gates.md | NOT STARTED | Verify independent-study readiness. |
| 23 | 23_Final_End_To_End_Regression_And_Release.md | NOT STARTED | Full end-to-end regression and release evidence. |

## Independent fixbody runtime repair

Implemented the user-requested `fixbody.md` runtime audit independently of the
numbered expert-policy phases. See [docs/fixbody_audit.md](docs/fixbody_audit.md)
and `results/qa/fixbody/` for the frozen baseline, controlled benchmarks,
seven-record replay, actual-checkpoint CUDA comparison, and regression results.
Shared frame/parent/ROI mask and feature caching removes repeated work; native
geometry and conservative original-RGB-supported damage diagnostics retain
provenance and remain outside grading. Model files, grading thresholds, and the
50/30/20 policy are unchanged; retraining notebooks were ignored.

The continuation repaired all eleven stale regression failures and added
mask-failure isolation plus localization-contract coverage across Python and
JavaScript evidence/export paths. Final: 1,199 passed, 12 skipped, zero failures,
127 subtests. Failed optional masks no longer interrupt grading; malformed
damage coordinates cannot produce localized or validated claims. Raw evidence
and original grades remain preserved.

This software evidence does not resolve independent anatomical measurement,
expert crack labeling, physical calibration, target-camera validation, or the
phase 21 policy approval requirement. Existing BLOCKED/NOT STARTED entries
remain in force; no scientific release approval is implied.

## Independent qualitycheck optimization

Executed `qualitycheck.md` without editing Model 1, checkpoints, or training
files. See [docs/qualitycheck_audit.md](docs/qualitycheck_audit.md). The matched
one-parent CPU replay improved from 11,666.58 to 2,099.80 ms (5.56x), with exact
recorded parts/confidence/weighted-verdict preservation. This filtered subset
does not reproduce every detection in the original 160-second inspection.
Sampled foreground remains explicitly estimated; reliable/physical geometry
and width grading remain withheld without validation. Active v4 already
requires Body and Head with optional Tail; no policy change was necessary.

Final combined workspace: 1,282 passed, 12 skipped, zero failures, and 127 subtests; isolated browser
and 52-page PDF checks passed. Existing CSV columns and values are preserved.
This audit did not reload the live GPU backend during external training.
Concurrent Model 1 V2 and association edits were preserved separately; one
ownership-test fixture was clarified without weakening ambiguity gates. Independent
anatomy, defect, calibration, and expert-policy requirements remain unresolved;
the numbered scientific readiness gates are unchanged.

## Independent optional MobileSAM integration

Implemented the experimental `Featureenhance.md` layer independently of the
numbered expert-policy phases. GrabCut remains the default; lazy FP32 MobileSAM
candidates share one image embedding across fish prompts and retain original
frame/parent provenance. Conservative ownership checks, shadow-only anatomical
proposals, unvalidated geometry estimates, and reviewed-Body requirements keep
mask scores and unreliable pixels outside grading. The optional-Tail ambiguity
compatibility repair preserves required Head/Body gates and original weights.

See [docs/mobilesam_integration.md](docs/mobilesam_integration.md) and
`results/qa/mobilesam/` for checkpoint metadata, baseline, real CPU probe,
matched comparison artifacts, and isolated Chrome rendering/export checks.
CPU checks do not establish ownership accuracy or RTX 2050 performance. Model
weights, training notebooks, and original annotations were preserved; no model
was retrained. Independent anatomy, crack labels, calibration, deployment
measurements, and expert-policy approvals remain unresolved. Existing numbered
BLOCKED/NOT STARTED gates remain in force.

An estimate-schema mismatch initially hid `mobilesam_candidate` geometry in
UI/exports because the old guard accepted only bounded GrabCut grids. Both
explicit estimate modes now display/export with distinct interpretation while
final metrology, centimeter conversion, and grading fields remain withheld.
Four meaningful Node/API CSV/XLSX regression cases reproduced this gap before
the correction; the SAM UI/export module now has 16 passing cases.

Final combined regression: 1,420 passed, 12 skipped, zero failures, 7 warnings,
127 subtests in 45.77 seconds. The isolated Chrome candidate smoke passed 27
assertions; the seven-record browser replay and 52-page PDF also passed. These
tests preserve uncalibrated measurement gates and do not certify real-fish
mask correctness or live GPU behavior.

## On-demand SAM preview and Model 2 display repair — November 2, 2026

Executed `notebooks/sam.md`. Inspect fish masks now requests real native
MobileSAM candidates and displays a separate shaded original-image canvas with
fish selection, opacity, boxes/assigned-part toggles, and lifecycle/error guards.
The bounded five-minute metadata token reuses existing detections without
rerunning Model 2, GrabCut, grading, geometry, or crack extraction.

Removed unowned debug boxes from normal fish zoom overlays. Real Model 2
outputs and all 17-image evaluation metrics match the pre-SAM report exactly;
existing unmatched detections remain, with no threshold or weight changes.
See [the preview report](docs/sam_preview.md) and
[Model 2 audit](docs/model2_falsepositive_audit.md).

Final regression: 1,453 passed, 12 skipped, zero failures, 7 warnings, 127
subtests in 35.34 seconds. Real-model HTTP/Chrome validation passed 33 named
checks and mobile layout, including visible nonrectangular masks and no grade
mutation. The stopped dashboard was reloaded and the real preview endpoint
verified on port 8000. Candidate ownership remains unvalidated; no width or
crack contribution was enabled. Training notebooks, weights, and annotations
were preserved.

## Independent non-model association repair - November 3, 2026

Executed `docs/additional.md`: corrected eligible-parent competition, supported
one-to-one ownership, uncertain-axis gates, optional-Tail conflict handling,
contextual crops, native coordinate/debug provenance, clipping diagnostics,
reviewed-mask boundary proof and reviewed-assignment uniqueness. The main
viewer retains every control and adds optional per-fish association diagnostics
with append-only exports and explicit video source/display IDs.

Full CPU regression: 1,660 passed, 12 skipped, 7 warnings, 127 subtests passed,
zero failures in 40.86 seconds. Actual Chrome passed 23 checks with zero fetches
or model requests. The exact original seven-fish CSV photo was recovered;
all 22 native Model 2 detections reproduce within numerical tolerance.
Five of seven remain Ungraded. Frozen 17-image coverage changes from 108 to
105 Ungraded out of 117, without independent ownership accuracy claims.

See [the integrated report](docs/additional_audit.md),
[association audit](docs/additional_association_audit.md), and
[reproduction report](docs/additional_reproduction.md). Both trained models,
detector thresholds, annotations and training notebooks remain unchanged.
Uncalibrated width evidence contributes nothing. Existing numbered scientific
readiness and expert-approval gates remain unchanged.

## End-to-end runtime validation - November 3, 2026

Validated actual CPU Model 1 V2, Model 2 and MobileSAM on 24 isolated,
overlapping, touching, clipped and rotated image cases, preserving a real
working-source baseline and exact native outputs for paired software replay.
Every case used one detector call per model, one shared SAM embedding and
zero GrabCut calls. All native/crop/trace/approval invariants passed; all 16
automatic verdicts retained correct weighted arithmetic. The 17-photo cohort
remains 105/117 Ungraded; required Head/Body ownership remains the main gate.

Fixed exact required-part contradictions in full-frame and crop adapters,
double-translated live debug coordinates, misleading mask success messages,
silent Excel JSON truncation, and source/display ID collisions in structural
video overlays. The actual nine-fish HTTP result now preserves all 347 fields
per fish in CSV/XLSX, with 45 truncated cells before and zero after.

Final suite: 1,715 passed, 12 skipped, 7 warnings, 127 subtests passed, zero
failures in 43.32 seconds. Actual HTTP/Chrome passed 46 checks plus four
lifecycle checks and mobile validation; final recorded-real-payload replay
passed 16 checks without model requests. Models, thresholds, training files,
annotations, weighted grading and all existing controls remain preserved.

See [the end-to-end report](docs/runtime_e2e_validation.md) and
`results/qa/runtime_e2e/`. Grading accuracy and ownership precision remain
unmeasured because independent expert truth is absent. Existing scientific
readiness/approval gates remain unchanged. The running live GPU service and
training processes were not restarted or reconfigured.

Final requested QA recheck: 1,715 passed, 12 skipped, 7 warnings, 127 subtests
passed in 43.50 seconds; all 24 source-bound replay cases passed; actual
HTTP/Chrome passed 46 checks plus four lifecycle checks and mobile layout;
the final real-result frontend replay passed 16 checks without model calls.
All 347 export fields per fish survived CSV/XLSX exactly, with zero lost
evidence. No additional production changes were needed. See
[the QA recheck](docs/runtime_e2e_qa_recheck.md) and
`results/qa/runtime_e2e/recheck/` for fresh logs and scope limitations.
