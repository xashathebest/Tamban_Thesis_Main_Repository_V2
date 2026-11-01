# Seven-fish upload CSV body-width audit

Reproduction input: `tests/fixtures/fish-inspection-upload-all.csv`, copied
unchanged from the user's exported file. SHA-256:
`dc7e06acb4e767650fcb7dc36ff78ab288c6039b6501f5bec8e5c40efded31fd`.
It contains seven records and 607 columns. This is a software reproduction
dataset, not an independently reviewed biological calibration dataset.

## Verified cause

The CSV has current grouped-frontend export columns, including `Body Width
Analysis` and `Body Width Threshold Configuration`, but each saved `Complete
fish event.analysis` lacks `body_width`, `geometric_support`, and the width
configuration. The saved backend model diagnostics also lack width settings.
The frontend serialized absent fields as empty objects instead of detecting
the older backend result contract. Existing Model 1 boxes, Model 2 associated
part boxes and previously extracted ROI measurements were present in a
different part of each structured record and were never reconciled into those
missing width objects.

This proves the exported records came from the older result schema. The file
alone does not prove why that backend remained active; a running Python process
does not reload already imported application modules merely because its source
files changed. New frontend assets and an old backend process can therefore
coexist. A restart is required when a running backend lacks the new contract.

The blank `Timestamp` column had a separate mapping error: the exporter read
only the per-fish timestamp, while the actual recorded analysis timestamp was
present in `Source metadata.analyzed_at` as `2026-11-01T00:20:20.811Z`. The repair
uses this recorded value without substituting the current time or the date
embedded in the image filename.

The upload serializer had an additional adapter-boundary gap: when width
analysis was absent it constructed a missing-Body result with an empty part
list, even if associated parts were already present. It now normalizes the
complete serialized fish batch after those parts and ROI measurements have
been attached. The API applies the same completion step to older adapters.

## Measurement and grading behavior

The repair reconciles stored boxes and ROI contexts through one shared backend
normalizer before API/export serialization. It does not decode the image,
rerun a detector, remeasure color, retrain a model or invent missing detections.
The complete batch supplies neighboring fish boxes for overlap checks. Raw
detector boxes and the existing pixel ROI dimensions are both retained, with
their coordinate source recorded explicitly.

Known different live/video frames and different sessions are excluded from
overlap comparisons. The normalizer fills missing or empty structures and
preserves complete authoritative geometric decisions, so a second pass does
not add points again. A legacy high-level grade without a saved competing
class vector does not acquire invented class scores.

The saved ROI boxes use floor/ceil pixel extraction and may already be clipped
to the fish crop. They therefore differ slightly from floating-point detector
boxes. The reconstructed diagnostic proxy uses the existing ROI dimensions
that were displayed to the operator; the detector-box ratio remains a separate
diagnostic field. Neither ratio is a validated anatomical width.

| Fish | Recorded grade | Existing ROI proxy | Width grading eligibility |
|---|---|---:|---|
| 1 | Class B | 583 / 1512 = 0.385582 | Unreliable geometry; no contribution |
| 2 | Ungraded | 614 / 1277 = 0.480814 | Unreliable geometry; no contribution |
| 3 | Class B | 493 / 1862 = 0.264769 | Unreliable geometry; no contribution |
| 4 | Ungraded | Missing Body detection | No contribution |
| 5 | Ungraded | 485 / 1606 = 0.301993 | Unreliable geometry; no contribution |
| 6 | Ungraded | Missing Body detection | No contribution |
| 7 | Ungraded | Missing Body detection | No contribution |

These reproduce the requested rounded values 0.386, 0.481, 0.265 and 0.302.
Clipping, overlapping parent boxes, uncertain orientation and part ownership
remain explicit reliability reasons. A measured ratio does not bypass these
checks or the existing Ungraded/Rejected rules.

All seven records retain their original grades, support values, part evidence,
original 50/30/20 weights and competing class vectors with width scoring
disabled. The original and final grades are populated separately; the
width-changed-classification field is false and the actual contribution is
zero. Numeric Class C width points remain null because there is no validated
calibration. The explicit points display and calibration status say `Not
calibrated`; an unknown score is not fabricated as zero points.

The existing shared final-stage fusion remains available for explicitly
validated calibration and reliable geometry, with a bounded configurable
transfer of normalized A/B support to C. The default configuration remains
uncalibrated and disabled. Reconstruction provenance distinguishes current
unvalidated defaults from configuration recorded with the original analysis.

## Export changes

`src/api/export.py` now normalizes missing legacy width records as a batch,
fills the recorded timestamp, and exports populated width/configuration and
original/final grading fields. Existing complete width analyses and bare
historical rows without geometric evidence remain authoritative/unknown,
respectively. Current surface-damage export fields remain intact.

New explicit columns distinguish saved ROI dimensions and ratio, detector-box
ratio, proxy source, configuration provenance, and the Class C points display.
Numeric score columns retain their numeric/null semantics. CSV and XLSX
generation do not mutate the caller's records.

Focused regression command:

```powershell
python -B -m pytest -q -p no:cacheprovider tests/test_upload_csv_width_exports.py
```

The tests use all seven exact records, verify source-file integrity, reproduce
all four ratios, preserve every original class vector and support, verify
missing Body cases, and check CSV/XLSX timestamp/configuration serialization.
API, normalization and grouped-browser checks are recorded with the final task
validation report.

## Changed implementation files

- `src/inference/inspection_results.py`: shared result completion, coordinate/
  ROI provenance, reliability, original/final grading snapshots and timestamp
  recovery using the existing measurement and scoring services.
- `src/api/image_analysis.py`: complete the batch after serialization; remove
  the empty-parts width fallback; add `body_width_v3` result contract metadata.
- `src/api/app.py`: enforce completion on uploaded-image responses and provide
  bounded `POST /api/inspection-results/normalize` without inference/history
  mutation. The endpoint accepts `fish` and recorded `source_metadata`.
- `src/api/export.py`: complete legacy measurements before CSV/XLSX export and
  populate ROI, calibration, points-status, original/final grade and date fields.
- `frontend/app.js`, `frontend/index.html`: normalize incomplete result sets
  through the backend; refuse empty width exports; recover recorded dates;
  expose the ROI measurement source and preserve grouped cards. Async recovery
  cannot replace newer fish evidence, and the asset version forces refresh.
- `tests/test_upload_csv_width_regression.py`, `tests/test_upload_csv_width_api.py`,
  `tests/test_upload_csv_width_exports.py`, `tests/test_upload_csv_width_frontend.py`:
  all-seven regressions across extraction, serialization, API, UI and exports.
- `tests/test_body_width_exports.py`, `tests/body_width_browser_smoke.py`:
  update frontend helper coverage and exercise all seven actual rows in Chrome.
- `docs/body_width_csv_audit.md`: this audit and reproduction record.

The existing verbatim fixture remains at
`tests/fixtures/fish-inspection-upload-all.csv`. Model weights and calibration
thresholds were not changed. Existing surface-damage and video work was retained.

## Reviewable repaired artifacts

After the silhouette measurement integration, these artifacts were refreshed
using `results/qa/fish_geometry/refresh_exports.py`. The browser CSV now contains
765 columns and the backend CSV 273 columns, with all seven records and all 607
original browser columns retained. The repaired JSON and 48-page PDF also contain
the new geometry fields. Silhouette dimensions remain unavailable for these
saved records because the source CSV contains no masks; known clipping warnings
are retained. All original measurements, IDs, grades, weighted scores, and
recorded timestamps are preserved. The follow-up CSV/export/frontend regression
run passed 33 tests and headless Chrome passed.

- `results/qa/body_width/fish-inspection-upload-all.repaired.csv`: seven rows
  in the grouped browser export format, with populated width/calibration/grade
  evidence, all original exported fish identities and the recorded timestamp.
- `results/qa/body_width/fish-inspection-upload-all.repaired.full-evidence.csv`:
  the backend CSV/XLSX field mapping of the same seven normalized records.
- `results/qa/body_width/fish-inspection-upload-all.repaired.json`: complete
  normalized structured results and original source metadata.
- `results/qa/body_width/fish-inspection-upload-all.repaired.pdf`: browser print
  report generated from those same seven rows.
- `results/qa/body_width/upload_csv_width_audit.json`: per-fish numerical audit.
- `results/qa/body_width/upload_csv_baseline_failures.json`: isolated HEAD proof
  of the unrelated existing failures.

Restart a backend that was running before these code changes and reload the
dashboard to load the new response contract. Saved rows lacking geometry are
recovered through the normalization endpoint; expanding cards does not run
either model. No biological calibration is claimed by these repaired exports.

## Final validation (November 1, 2026)

- Focused reproduction/API/frontend/export/scoring checks: **49 passed**.
- Full pytest suite: **893 passed, 12 skipped, 11 failed**, with 127 subtests
  passed. The same 11 failures reproduce on isolated Git HEAD
  `27c1279de2f8266a3ff0d38ce7a6f961e883b273` (20 passed, 11 failed in the
  selected baseline files): nine model-switch fixture failures and two existing
  interface-copy/source assertions. They are not introduced by this repair.
- Headless Chrome: all seven actual CSV records passed normalization through
  the local API, rendered seven grouped cards (2 Class B, 5 Ungraded), retained
  the recorded dates, matched all four proxies, and passed mobile layout.
  Chrome also generated the complete 47-page seven-fish PDF report.
- Python/JavaScript syntax and changed-file whitespace checks passed.

The browser check uses an isolated temporary database/server/profile and does
not invoke a model or a physical camera. The PDF can be long because it retains
per-fish ROI contexts, grading settings and provenance. Original input bytes
remain unchanged. Calibration and actual widening-related Class C accuracy
remain unvalidated; the copied seven rows do not supply independent labels.
