# Inspection workspace, saved sessions and analytics

Implemented from `checks.md` on November 4, 2026.

## Operator workflow

Restart the backend once and refresh the dashboard to load the updated assets.
Open **Analyze Media**, drop an image/video or select **Browse Files**, and run
analysis. The viewer and **Results by final grade** share a responsive workspace.
The complete frame fits by default. Select a fish to reveal its result card;
use **Zoom fish** for the detailed crop. Measurements, cracks, Model 2 parts,
opacity, highlighting and mask controls reuse the completed analysis.

**Fit image**, zoom/pan and **Fullscreen** are available for media and the live
camera. Fullscreen uses the browser API with an in-page fallback. Closing the
media workspace keeps its completed analysis; **Replace media** and **Remove**
clear the prior file/evidence. Analysis cancellation and source-version guards
continue to prevent stale results.

Original engine classifications are the primary labels and grouping keys:
green Class A, blue Class B, orange Class C, red Rejected and gray Ungraded.
Mask fills retain distinct Fish ID colors. Mask reliability and operator reviews
remain separate from the original grade. Missing final classifications remain
Ungraded; confidence, mask color and experimental reliability never supply a
replacement grade.

Each result card contains Overview, Model 1/Model 2 Evidence, Geometry, Crack
Detection, Mask Reliability and Grading Explanation, with optional technical
diagnostics. The repeated standalone geometry/crack accordion was removed.
The live stream now publishes its computed overlays rather than discarding
them. Models, raw preview and grading still receive original capture pixels.

## Saved-session behavior

**Inspection History** opens saved-session cards with start/end dates, wall
duration, measured active time, fish count, grade distribution and status.
Selecting a session opens its grade groups. Session/Fish ID, date, final-grade
and verdict filters retain their scope through pagination. The previous detailed
record table remains available under **Advanced record table**. History works
while the camera is offline.

Existing fish records remain durable immediately. A background monitor tracks
accumulated active inspection time, excludes calibration/debug pause and missing
capture activity, checkpoints about every five seconds, and records the
automatic-save milestone at 60 active seconds. Zero-fish runs are included;
shorter runs are retained rather than discarded. Closing a run flushes its
activity metadata. Restart recovery marks abandoned open sessions Interrupted
at their last durable checkpoint and does not count offline wall time. Each new
run receives a fresh session identity, so repeated Fish IDs cannot overwrite a
different session's records. Legacy sessions have unknown active time rather
than an invented measurement.

The dedicated **Analytics** page reads durable results for the selected session
and date range. Charts show session activity, total fish, grade distribution,
graded/Ungraded rates, recorded anatomical availability, Ungraded reasons,
model support and processing performance. Chart drill-down opens the matching
saved fish records. Session-activity totals explicitly use session start dates;
fish analytics use event dates. Missing measurements are shown as not recorded.

Per-fish and complete-session CSV exports use explicit session/Fish ID scopes.
PDF actions produce printable reports using the browser's **Save as PDF**
option. Complete-session reports fetch all result pages and check identity/count
consistency before printing. Operator review values remain separate columns.

## API additions

| Endpoint | Added behavior |
| --- | --- |
| `GET /api/sessions` | Session summaries, page/page_size, session search, date and exact-session filters; measured activity metadata |
| `GET /api/history` | Exact Fish ID, verdict, reason and present anatomical-region filters; graded-only drill-down |
| `GET /api/analytics` | Derived rates, anatomical availability, model support and saved-session activity |
| `POST /api/export` | Exact `track_ids` selection requiring a `session_id` |

SQLite migration adds activity fields without replacing historical records or
model/configuration snapshots. Model weights, inference/grading code and the
configured Body/Head/Tail rules were not changed.

## Modified files

- Frontend shell and interaction: `frontend/index.html`, `frontend/app.js`,
  `frontend/styles.css`, new `frontend/inspection-layout.css` and
  `frontend/inspection-evidence.css`.
- Saved-session UI: new `frontend/session-workspace.js` and
  `frontend/session-workspace.css`.
- Persistence/API: `src/api/database.py`, `src/api/app.py`.
- Annotation presentation: `src/api/camera.py`, `src/api/image_analysis.py`,
  new `src/api/presentation.py`.
- New tests: `test_inspection_grade_workspace_ui.py`,
  `test_session_history_analytics.py`, `test_session_workspace_ui.py`,
  `test_live_overlay_presentation.py`, `inspection_workspace_browser_smoke.py`,
  and `session_workspace_browser_smoke.py` under `tests/`.
- Existing test contracts updated for actual grades, explicit zoom, new upload
  copy and new stylesheet assets: `tests/test_fish_click_zoom.py`,
  `tests/test_sam_features_ui.py`, `tests/test_sam_preview_ui.py`,
  `tests/test_session_totals_ui.py`, `tests/test_upload_control_ux.py`, and
  `tests/anatomical_debug_browser_smoke.py`.

## Actual validation

- `python -B tests/run_model_free_isolated.py`: **1,909 passed, 12 skipped**,
  plus **127 passing subtests**, in 50.32 seconds. Seven existing dependency/
  metric warnings were reported. Source/tests were copied without checkpoints
  or inspection databases.
- `tests/inspection_workspace_browser_smoke.py`: **23 browser assertions
  passed**, including real drop events, whole-image fit, synchronized selection,
  separate mask status, fullscreen/layers, live zoom/fullscreen, cached reopening,
  removal and mobile overflow. Overlay/fullscreen/selection operations made
  **zero API requests** and left the cached grade data unchanged.
- `tests/session_workspace_browser_smoke.py`: passed against a temporary SQLite
  database with three sessions, including a zero-fish session and duplicate
  Fish IDs in different sessions. Verified pagination of 30 primary records,
  exact per-fish CSV (HTTP 200), individual/full-session printable reports,
  14 Ungraded and 16 Head-evidence drill-down records, and layouts at 390, 768
  and 1366 pixels.
- Both JavaScript files passed `node --check`; `git diff --check` passed.

Browser checks used test-only headless Chrome configuration in this constrained
environment. Screenshots and workbench assertion results are generated under
`results/qa/inspection_workspace/`.

## Remaining validation limits

No physical webcam or full real-model inspection was run. Camera-dependent
latency/FPS, a long live inspection/disconnection demonstration and real-world
fish accuracy still require the actual installation. Automated tests exercise
the 60-second clock with controlled timestamps and preserve real pipeline
boundaries with fake captures/models. Crash recovery retains activity through
the last successful checkpoint; it does not fabricate time after that point.
Experimental masks and suspected cracks remain Estimated/Requires Review until
supported by the existing validation rules.
