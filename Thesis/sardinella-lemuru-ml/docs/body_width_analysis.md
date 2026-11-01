# Relative body width analysis

The existing two-model inspection path reuses the Model 1 whole-fish box and
associated Model 2 Body box. It preserves original pixel dimensions and derives
the initial diagnostic ratio `min(Body width, Body height) / max(whole-fish
width, whole-fish height)` whenever both valid boxes exist. This rectangular
bounding-box proxy does not measure anatomical width, physical size, or body
weight. Color/brightness/saturation diagnostics are reused without recalculation.

Previously, any failed reliability check returned before the ratio calculation,
so valid dimensions appeared as entirely unavailable. For the reported
672 x 1511 px whole-fish and 583 x 678 px Body boxes, the diagnostic ratio is
583/1511, approximately 0.38584. Whole-box elongation is only 1511/672 = 2.248,
below the fallback orientation threshold of 4; when reliable Head/Tail axis
evidence was unavailable, that safeguard erased the measurement. Those
dimensions alone cannot prove which reliability reason affected the original
fish. Correctly associated, widely separated, near-vertical Head/Tail evidence
already passed the prior geometry check.

A second verified gap affected direct `YoloQualityModel.predict` callers:
`parent_bbox` and `frame_shape` without crop origin metadata left the coordinate
space unverified. Production camera/still paths supplied the required bounds.
Prediction now accepts explicit `CropBounds` and validates known exact crop
origin/padding geometry. Existing production coordinate transforms remain in
use. No asynchronous race or property-name mismatch was established.

Measurement availability is now separate from grading reliability:

| Status | Meaning |
|---|---|
| Measured | Both boxes and their diagnostic ratio are available with reliable geometry |
| Unreliable | Original dimensions and ratio remain visible, but orientation/ownership/clipping/overlap prevents scoring |
| Missing Detection | A valid whole-fish or Body box is absent; the reason is retained |
| Not Calibrated | Independent calibration is missing; this is recorded separately from measurement status |

The structured fields are `measurement_status`, `measurement_available`,
`reliable_for_scoring` and `calibration_status`. The legacy `status: measured`
indicates raw data availability, including unreliable diagnostic ratios.
Head/Tail centers check approximately horizontal/vertical orientation, with
strong box elongation as fallback. Diagonal, overlapping and clipped detections
cannot receive width points from the axis-aligned proxy. Intersecting boxes
can include separate fish, so overlap conservatively blocks grading support.

`configs/body_width.yaml` stores the toggle, engineering reliability settings
and calibration provenance. It ships with `scoring_enabled: false`,
`calibration_validated: false` and no normal/extreme thresholds. Reliable proxies
are visible, but supporting points read `Not calibrated` and grades retain the
existing behavior. No model is retrained or replaced.

For live tracks, width comes from the latest distinct candidate frame, carrying
its `frame_id`; duplicate frames do not replace it. Model 2 class evidence is
the existing temporal aggregate. Width is not averaged across frames and is
recomputed as a single supplement to that aggregate, so repeated observations
do not accumulate widening points. A currently unavailable width supplies no
points even when older Model 2 evidence is retained.

After independent validation, the reviewed normal range belongs in
`normal_reference_min`/`normal_reference_max`, with `extreme_reference` marking
the validated 10-point level. `calibration_id` must identify the review evidence
and `validation_sample_count` records its sample count. Only an explicit
`calibration_validated: true` declaration makes those thresholds active; the
separate `scoring_enabled` toggle controls grade contribution. Configuration
validation cannot authenticate the study or establish sufficient sample size.
The configuration is read when the grading engine starts. After editing the
YAML, restart the application so a new engine loads and snapshots the settings.

The continuous score rises from 0 at the validated normal upper limit to 10 at
the validated extreme threshold and is capped there. Slight/moderate/
significant/extreme describe this continuous score. Points are not percentages.

The default `scoring_method: post_weighted_v2` runs after the unchanged weighted
grading policy. That policy retains the original Body/Head/Tail weights of
50/30/20 and its existing effective-weight rules. The geometric stage requires
an already accepted baseline, reliable calibrated width and independent
confident Model 2 Body Class C evidence. Baseline Ungraded and Rejected outcomes
remain unchanged. Width cannot supply missing required grading evidence.

For an eligible fish, the stage normalizes competing weighted class support
to a unit total and transfers a bounded share of A/B support to C. It preserves
the normalized Rejected share. `maximum_geometric_contribution` is configurable
from 0 to the hard cap of 0.10; an 8/10 width score with the 0.10 cap transfers
0.08 of total normalized support. For example, an eligible baseline B=0.54,
C=0.46 can become B=0.46, C=0.54. This illustrates the implemented math; it is
not a prediction of a real fish's outcome. Final support/margin gates still
apply, and a candidate failing them preserves the original accepted result.
No-op paths retain the exact original score scale and outcome.

Raw part classifications, confidence, `grade_evidence`, effective weights and
anatomical contributions remain unchanged by this stage. `geometric_support`
records original/final grades, support vectors, score scale, points, actual
shift and `width_changed_classification`. Width `score_applied` and
`score_contributed` indicate an accepted geometric contribution. The retained
legacy `body_component_v1` method redistributes Body support only for explicitly
selected legacy rules or historical replay; `maximum_body_score_shift` belongs
to that older method.

Full runtime/session snapshots retain settings at `grading_config.body_width`.
`recompute_final_verdict(record, EvaluationRules.from_mapping(snapshot))` calls
the same final-stage helper from raw regional evidence once. Disabling only
`scoring_enabled` replays the exact baseline. Enabled replay requires the saved
calibration/geometry settings; changed thresholds cannot reuse stale points.
Historical snapshots without `scoring_method` replay `body_component_v1`.
Missing width evidence or a rules object without width configuration preserves
baseline behavior. Exports retain full-precision structured analysis as well
as readable numeric columns, distinguishing 0-10 points from support fractions.

The unified result area groups unique fish by final class, with one expandable
card containing grading evidence, geometry, image measurements and the final
explanation. Export adapters consume the structured fish records, independent
of which cards are expanded. CSV/XLSX preserve raw detections, ROI/frame
contexts, all existing image proxies, original/final class vectors, reliability
and thresholds; the PDF report includes each fish's corresponding evidence.

## Calibration and independent validation

No suitable independently reviewed individual-fish width calibration records
were found in the inspected evaluation/docs/results files. Existing debug
detections and training annotations do not establish reviewed physical-fish
identity, normal width labels or independent Class C outcomes. Real-fish
normal ranges, abnormal thresholds and Class C performance therefore remain
pending; synthetic software tests do not validate those scientific claims.

Collect manually verified Class A, B and C fish, using one paired record per
physical fish. Review the Model 1/Model 2 Body
association against the source image; record wrong associations as incorrect
and leave their width unavailable. Include horizontal, vertical, diagonal,
overlapping and clipped cases. Obtain the true grade independently with the
system prediction hidden. Review width normality separately: a Class C grade
alone is not a width-abnormality label.

The offline evaluator accepts JSON, JSONL or CSV records. These fields are
required:

| Field | Meaning |
|---|---|
| `fish_id`, `specimen_id` | Unique, known individual and physical specimen IDs; one row per specimen |
| `capture_session`, `split` | Capture group and `train`, `validation` or `test`; keep each capture group in one split |
| `expert_reviewer`, `review_reference` | Reviewer and the retained truth/review evidence reference |
| `independent_grade_review`, `system_prediction_hidden` | Explicit `true` declarations for independent blind truth |
| `association_reviewed`, `association_correct` | Explicit booleans from manual association review |
| `true_grade` | Independent A/B/C/Rejected grade |
| `baseline_grade`, `candidate_grade` | Paired final grades with width contribution disabled/enabled, retaining `Ungraded` |
| `geometry_case` | `horizontal`, `vertical`, `diagonal`, `overlapping` or `clipped` |
| `manual_width_label` | Optional `normal`, `widened`, `uncertain` or `unreviewed`; defaults to unreviewed |
| `analysis.body_width` | Retained runtime analysis, including its threshold configuration; missing evidence remains unavailable |

For CSV, place the serialized width object in `body_width_analysis` or
`body_width`; JSON records can retain their original `analysis.body_width`.
Boolean CSV values use `true`/`false`. Exported inspection events need the
review metadata and paired baseline/candidate outcomes added before evaluation.
The evaluator does not create expert truth or run model inference.

```powershell
./.venv/Scripts/python.exe -B -m src.evaluation.body_width_validation --records reviewed_width_fish.jsonl --dataset-split validation --output results/body_width_validation.json
```

The report includes paired Class C precision, recall, false-positive rate,
confusion counts, abstentions, changed grades, geometry/reliability coverage,
configuration and input SHA-256. Undefined rates are null. All fish remain in
the denominator, including missing width evidence and Ungraded outcomes. Grade
changes without a recorded applied score are rejected, as are duplicate
specimens, uncertain claimed reliable measurements and mixed configurations.

The `reference_preparation` section reports observed ranges of manually normal
and widened, reliable validation measurements. These are descriptive ranges;
the evaluator never chooses thresholds or marks calibration validated. Select
and approve the continuous score thresholds on validation data, retain the
study/provenance and freeze the configuration before the held-out test
comparison. Run that locked comparison with `--dataset-split test`, check Class
C precision/recall/false positives and confirm missing width evidence preserves
the baseline. Independent dataset identity and reviewer declarations still
require human verification.

Focused software checks:

```powershell
./.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider tests/test_body_width.py tests/test_body_analysis_measurement.py tests/test_body_analysis_grading.py tests/test_body_width_validation.py tests/test_body_analysis_exports.py
```

Final application verification on October 31, 2026: the complete pytest suite
reported **855 passed, 12 skipped, 10 failed**, with 127 subtests passed. All ten
failures are the already reproduced baseline failures: one missing historical
UI-copy assertion and nine model-switch fixture failures. Baseline evidence is
retained in `results/qa/body_width/baseline_existing_failures.json`. The current
feature-specific backend run passed 172 tests and 45 subtests before the final
small additions, which were included in the complete suite.

Headless Chrome verified one card per identity, class updates, lazy evidence,
source isolation, complete color diagnostics, missing-Body replacement,
historical manual review and 390px mobile layout. Actual Chrome PDF generation
produced a valid nine-page report for three complete fish records. JavaScript
syntax and changed-file whitespace checks passed. Browser tests use an isolated
temporary database and do not run either model or open a camera.

These software checks do not replace reviewed real-fish measurements, approved
width thresholds or the independent Class C comparison. Scoring remains
disabled and uncalibrated until that evidence exists.

## Files changed for the integration

- `src/inference/body_width.py`, `yolo_quality_model.py`: measurement states,
  diagnostic availability, coordinate verification and calibration settings.
- `src/inference/geometric_support.py`, `grading_engine.py`: shared final-stage
  scoring, original/final evidence and ungraded diagnostic retention.
- `src/api/image_analysis.py`, `camera.py`: original image dimensions, source
  metadata and consistent per-fish evidence.
- `src/api/export.py`: complete original/final scores, all image diagnostics,
  provenance and explicit score units in CSV/XLSX.
- `src/evaluation/fish_level_validation.py`, `body_width_validation.py`: exact
  new/legacy replay, paired validation and reliable calibration preparation.
- `frontend/app.js`, `index.html`, `styles.css`: unified grouped cards,
  identity updates, lazy measurements, source isolation and PDF/CSV exports.
- `configs/body_width.yaml`: default-off versioned scoring configuration.
- `tests/test_body_analysis_*.py`, `tests/test_body_width*.py`,
  `tests/test_upload_evidence_ui.py`, `tests/body_width_browser_smoke.py`:
  measurement, scoring, tracking, export, grouping and browser regression checks.
