# Tamban Thesis - Deep Code Defects and Risks Audit

Date: 14 October 2026  
Analyzed artifact: user-supplied `Thesis-main (2).zip`  
Source root: `Thesis-main/`  
Scope: Python FastAPI runtime, YOLO adapters, grading/tracking, camera lifecycle, frontend-export integration, SQLite persistence, tests and scientific-readiness files.

## Evidence and limits

- `python -m unittest discover -s tests -q` executed with NO supplied model weights: 341 total, **330 passed, 6 failed, 5 skipped** (2 failure assertions and 4 errors). All 6 are in `tests/test_multi_model_selection.py` and depend on checkpoint files deliberately absent in the uploaded ZIP. These results show a model-free test-suite portability issue, NOT damaged checkpoints.
- Python compile checks and frontend JavaScript syntax checks passed.
- A deterministic model-free reproduction script used mocked inference paths, a temporary SQLite file, and a simulated worker to check five lifecycle bugs; see `REPRODUCTION_NOTES.md`. These are exact interleavings, not proof that the event occurs often with the real camera.
- Dummy checkpoint bytes demonstrated registry path resolution does NOT enforce expected registry SHA-256; the existing `assert_checkpoint_sha256` helper correctly fails them.
- Real inference speed, per-class grade accuracy, crack/belly-defect recognition, and true field severity were NOT measured because real checkpoint files, camera, GPU and separate labeled data were not available.

## A. Reproduced defects - fix first

| # | Priority | Finding | Source | Proof | Prompt |
|---|---|---|---|---|---|
| A1 | Critical | `/api/models/select` accepts a model switch during inspection even though `/api/settings` has a lock | `src/api/app.py:609-662`; compare `:1106-1114` | mocked running-state endpoint accepts switch | 02 |
| A2 | Critical | `/api/analyze-image` can mutate shared active Model 2 before validating image bytes | `src/api/app.py:1233-1277` | invalid image returns 400, but shared `switch_model` was called | 03 |
| A3 | Critical | `service.start()` launches worker before durable session starts | `src/api/app.py:666-671`, `:250-260`; `src/api/database.py:459-508` | simulated early event saved in previous closed session | 04 |
| A4 | High | `stop()` returns True after join timeout while worker still alive | `src/api/camera.py:551-566`; `src/api/app.py:674-682` | fake stuck worker returns stopped=True with state running | 05 |
| A5 | High | Mixed-validity settings request can partially mutate live detector threshold then return 422 | `src/api/app.py:1063-1114` | valid threshold + invalid display settings mutates threshold | 06 |
| A6 | High / research integrity | Model registry path resolution does not enforce its recorded SHA-256 | `src/inference/model_registry.py:185-209`, `src/inference/model_traceability.py` | dummy mismatched bytes resolve successfully; hash assertion fails | 14 |

## B. Source-confirmed code flaws / reliability concerns

| # | Severity | Code evidence and consequence | Prompt |
|---|---|---|---|
| B1 | High | `frontend/app.js:1066` ALWAYS sends `complete_analysis: true`, overriding checked fields in `src/api/app.py:1162-1167`; user export settings do not work as implied. | 07 |
| B2 | High | XLSX export reads CURRENT `_status_payload().grading_rules` for historical queries instead of persisted historical rules: `src/api/app.py:1213-1222`. `InspectionDatabase.session()` looks only among last 1000 sessions (`src/api/database.py:434-438`). | 08 |
| B3 | High | Model 1 falls back silently to IoU tracker when `lap` cannot be imported (`src/inference/yolo_fish_detector.py:238-246`); not pinned explicitly in `requirements.txt`. `tracker_backend` is logged but operator visibility needs improvement. | 09 |
| B4 | High | Full-frame part matching gets only `eligible` parents (`src/api/camera.py:1010-1059`); excluded visible fish can distort ownership during overlap. Requires synthetic adversarial validation. | 10 |
| B5 | High | One missed detector frame triggers immediate prune of grades and temporal state (`src/api/camera.py:1094-1099`), potentially earlier than TrackingManager's timeout. | 11 |
| B6 | High | Temporal gating uses `len(track.usable_frames)` even with no part detections, while transient parent/association flags are sticky OR values (`src/inference/grading_engine.py:993-1019`). | 12 |
| B7 | Medium | Broad Model 2 exception handler updates global status without explicit per-fish failure evidence (`src/api/camera.py:1091-1093`). | 13 |
| B8 | Medium | When an explicit checkpoint override exists, loader may bind registry metadata based on preselected ID before checking whether paths match (`src/inference/yolo_quality_model.py:276-289`). | 14 |
| B9 | Medium | Manual-review route only identifies `track_id` and defaults to current session (`src/api/app.py:949-973`), making historical review and duplicate track IDs ambiguous. | 17 |
| B10 | Medium | Standard 'model-free' unittest/CI command includes six checkpoint-dependent cases from `test_multi_model_selection.py`, contradicting `tests/README.md`. | 18 |

## C. Conditional risks / optional improvements (not reproduced field failures)

| # | Risk or limitation | Evidence | Prompt |
|---|---|---|---|
| C1 | Excessive upload memory under missing Content-Length or very high compression ratios | Unbounded `await request.body()` in `src/api/app.py:1257` and OpenCV decode before dimension validation in `src/api/image_analysis.py:36-67`. | 15 |
| C2 | History/analytics slowdowns as database grows | `src/api/database.py:359-403` loads matching rows then filters in Python; `src/api/app.py:491-559` recomputes analytics on status refresh. Actual latency not measured. | 16 |
| C3 | Unauthenticated controls if bound to nonlocal network via `LEMURU_HOST` | `src/api/__main__.py` defaults safely to 127.0.0.1 but allows LAN bind; `src/api/app.py` exposes mutation, data and debug routes. | 19 |
| C4 | Misleading claims about implemented features | offline color/texture/structure feature modules exist but active grading has `hsv_adjustment.enabled: false` and `defect_adjustments_enabled: false`. No reliable belly-hole detection was demonstrated. | 20 |
| C5 | Proposed two-part grading behavior differs from current standard mode | `configs/grading_engine.yaml:25` has minimum observed regions=1, professor suggested body + head/tail; no physical-head-absence classifier exists. Requires expert input and validation. | 21 |
| C6 | Independent research conclusions cannot yet be certified | `results/stabilization/validation_readiness.json` marks dataset and final certification BLOCKED, and multiple technical validation checks PENDING. | 22 |

## D. Important behavior to preserve

1. Continue using two separate models for fish/counting and body-part quality; do not combine them as a 'bug fix'.
2. Existing standard weights are Body 50%, Head 30%, Tail 20%; missing parts currently contribute zero, with no automatic redistribution.
3. No body part detected is NOT equivalent to physically missing anatomy, and Ungraded is NOT Rejected.
4. Features such as brightness, color, texture and defect annotations must not be represented as validated final-grade inputs unless tested and integrated.
5. Operators should see which tracker actually runs; missing large model files in this ZIP are expected and not an inference-quality verdict.
6. Do not compare an altered model/policy against old session data as though both were produced by the same immutable configuration.

## E. Recommended execution order

**Group 1 (prevent data corruption):** 01 -> 02 -> 03 -> 04 -> 05 -> 06.  
**Group 2 (preserve evidence + grading):** 07 -> 08 -> 09 -> 10 -> 11 -> 12 -> 13 -> 14.  
**Group 3 (robust operation):** 15 -> 16 -> 17 -> 18 -> 19.  
**Group 4 (expert-backed research):** 20 -> 21 -> 22.  
**Final validation:** 23.

These prompts are a development roadmap, not a statement that all findings are release-blocking or that proposed improvements have already been validated.
