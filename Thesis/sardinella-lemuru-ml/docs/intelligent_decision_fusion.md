# Intelligent fish grading fusion

`WeightedGradingEngine` now applies a calibrated decision-fusion stage to the
same per-fish evidence used for live inspection and upload analysis. Eligible
supporting features change the actual verdict and confidence, rather than only
the displayed measurements. `analysis.feature_fusion.decision_fusion` records
the complete comparison and is preserved in SQLite history and exports.

The installed default has **no fitted feature calibration**. It honestly uses
the existing Model 2 decision and leaves the supporting 30% unallocated. An
existing explicitly calibrated legacy width/structural policy remains available
for historical compatibility and is labeled `legacy_reviewed_rules`; it is not
represented as calibrated 70/30 fusion. No synthetic fixture is installed as a
reference distribution. Real-fish accuracy improvement has not been established.

## Weights and evidence

| Source | Configured weight | Runtime treatment |
|---|---:|---|
| Model 2 | 70% | Exact existing Head/Body/Tail aggregation, followed by validated probability calibration when available |
| Size / proportions | 15% | Reviewed endpoints, complete ownership, local perpendicular widths and consistent ratios |
| Cracks | 5% | Reviewed structural discrimination/measurements; nuisance patterns and unverified negatives cannot establish quality |
| Color / brightness | 5% | All owned pixels, reviewed camera/lighting profile and validated RGB correction |
| Texture | 5% | Masked GLCM, LBP, entropy and surface-gradient characteristics with validated sampling |

Model 2's original Body 50%, Head 30%, Tail 20% weights, optional-Tail
redistribution, checkpoints, required-region/ownership gates, frame-quality
gates and temporal requirements are preserved. Supporting features never fill
missing anatomical evidence or override a Rejected safeguard.

Eligible features may resolve an original Ungraded result caused solely by
`UG_LOW_GRADE_SUPPORT` or `UG_LOW_MARGIN`. The combined evidence must pass fresh
confidence and class-margin checks, including the recorded anatomical policy's
thresholds. Parent, ownership, required-region, coverage, frame-quality and
temporal holds remain blocking; unknown future reason codes also remain
blocking. Without eligible features the original Ungraded result is retained.
The exact original verdict stays in `model_only_verdict`, while
`resolved_score_review_reasons` identifies an accepted score-based recovery.

A configured trained `Rejected_*` part override still applies as a safeguard
when reconsidering a score hold. The original policy may not have reached that
override because its raw score gates failed. Fusion checks the retained
regional evidence against the same configured threshold before accepting any
non-Rejected candidate; such a conflict requires review.

Model 2 emits detector confidences, not whole-fish class probabilities. Its
unchanged weighted support is normalized and temperature-calibrated on verified
validation specimens. The unmodified scores and accepted Model 2-only grade
remain separate. Feature measurements are mapped through per-class reference
means, regularized scales, empirical priors, and validation-selected
temperature scaling. Raw width, brightness or entropy is never called a class
probability.

For eligible feature `f`, effective weight is
`0.30 * configured_weight[f] * reliability[f] / sum(eligible weight * reliability)`.
Model 2 always retains 0.70. Reliability combines validation Brier skill and
balanced accuracy, the proposed class's held-out recall, and measurement
reliability. Supporting distributions are also shrunk toward Model 2 by their
reliability, so a sole eligible feature does not become certain merely by
receiving the available 30%. Raw feature-only support is recorded independently
of this shrinkage. Out-of-reference observations are withheld, not labeled bad
fish. No eligible feature means zero supporting weights and a labeled fallback;
the displayed 70% is not silently rescaled to 100%.

When calibrated fusion applies, previous width/structural score transfers are
not applied a second time. A separately reviewed structural eligibility
restriction remains an acceptance safeguard.

## Disagreement and review

* `AGREEMENT`: eligible features support the model's class. Automatic grading
  still requires the original anatomical gates, calibrated support/confidence
  and margin requirements.
* `MINOR_DISAGREEMENT`: at least one eligible feature contradicts Model 2.
  Distribution distance, class separation, class-distance severity and
  reliability affect confidence. A single low-weight feature that changes the
  winning grade requires review; there is no automatic downgrade rule.
* `MAJOR_DISAGREEMENT`: two or more reliable feature families exceed the
  configured contradiction margin. Confidence is penalized and automatic
  grading is withheld, even when Model 2 still wins the weighted score.
* `CRITICAL_ANATOMICAL_DISAGREEMENT`: source-bound, independently reviewed Head
  absence blocks automatic grading regardless of the quality score. Missing
  Head detections alone never establish absence. A saved Review & Teach Head
  absence/conflict also puts the record in the review queue without rewriting
  the original AI prediction or inventing an automatic rejection.

Conflict comparisons retain every Model 2 grade tied within the shared 1e-12
roundoff tolerance. A feature supporting one of those leaders can resolve score
uncertainty without falsely contradicting the first class in the class list.
Only feature leaders disjoint from all Model 2 leaders establish a contradiction;
separation and severity use the closest supported Model 2 leader. Confidence,
combined-margin, anatomical and Rejected gates still apply. A lone cracks, color
or texture family cannot choose between tied Model 2 grades, including when
other eligible families supply neutral support for the tied grades.
This safeguard checks each rival separately in multi-class ties; partially
neutral families cannot hide one low-weight feature deciding a remaining pair.

Feature distributions with tied leaders use the lowest validated reliability
among those classes. Their assessment is recorded as ambiguous, with every
leader retained. A tied feature-only or combined distribution has no unique
candidate prediction. The explanation tables, CSV/XLSX exports and paired
evaluation outcomes retain those leaders and identify features that distinguish
the tied Model 2 grades. Calibration recall does not count a tied prediction as
correct by class order; probability metrics also report its ambiguity count.

Evidence Agreement is one minus the reliability-weighted total-variation
distance between Model 2 and eligible feature distributions. The separate
model-to-feature disagreement compares Model 2 with feature-only support.
These are consistency measurements, not measured correctness, independent
votes or confidence calibration certificates. With no eligible features the
agreement score is unavailable, not 100%.

The explanation panel appears in individual result cards and fish details. It
shows original Model 2 grade, feature assessments and reliability, configured
and effective weights, per-class support, fused prediction, agreement,
conflicts, decision confidence and automatic/review status. Green, amber and
red badges include text labels; the uncalibrated fallback is neutral. CSV/XLSX
and printed reports preserve the same evidence and separate manual corrections.

Each feature now records `weighted_class_contributions`: its effective weight
times its reliability-adjusted class support. The corresponding
`class_support_delta` compares that share with assigning the same share to
calibrated Model 2. These signed deltas sum to the change from calibrated Model 2
support to fused support; they are score attribution, not a measured accuracy
gain or independent causal effects. `per_source_class_contributions` includes
the 70% Model 2 term and zero entries for excluded feature families. Its columns
sum to `per_class_combined_support`. This ledger is unavailable in a fallback;
no calibrated contribution is invented from the original detector scores.

The dashboard and printed report show support points for the recorded
`contribution_target_grade`, including when automatic acceptance is withheld.
Server CSV/XLSX and browser CSV retain the per-source ledger. A supporting
feature can contribute without changing the winning class. A changed candidate
can also remain Ungraded when the acceptance safeguards require review.
The per-class dashboard table shows signed size, cracks, color and texture
changes for **each** of A, B, C and Rejected, to two decimal support points.
Adding those changes to calibrated Model 2 support reconstructs the combined
support when calibrated fusion applies. Missing historical amounts stay
unavailable. Server CSV/XLSX expose the same four-class changes in
`fusion_feature_class_deltas`; browser CSV uses
`Fusion per-feature class support changes`.
`analysis.fish_geometry.used_for_grading` and its `grading_contribution` identify
actual calibrated size use after fusion; successful measurement alone keeps
that flag false. The original geometry input snapshot remains unchanged.

## Preparing verified references

The existing dataset is the class-label reference. The user confirmed that the
grading categories came from the experts and the project annotators assigned
quality grades to **Head, Body and Tail separately**. Model 1 has the single
`Fish` detection class and supplies no quality grade. Model 2 learns the
annotator-assigned part classes. The final fish grade is produced by the
configured weighted part policy; the parts do not inherit one whole-fish grade.
This provenance is recorded in `configs/dataset_class_reference.json`; expert
names and undocumented rubric files are not invented.
Additional application reviews or a separately collected expert dataset are not
required merely to recognize these human labels as the reference.

The updated `decision_fusion_data_audit.json` counts **9,723 graded part
annotations**. This is an annotation count, including augmented observations,
not a count of independent fish. The report separates those reference labels
from the 77 saved application inspections, zero application review entries and
zero source-bound reviewed feature bundles. An empty runtime review history
does not mean the original dataset has no human reference labels.

Fitting calibration pairs measured features with those supplied class labels.
The export primarily contains rectangular part regions, with some nonrectangular
part polygons, and no explicit part-to-fish identity fields. The labels remain
usable references; a part rectangle does not establish a complete fish
silhouette or identify which neighboring parts belong to the same fish.
The existing source group names should retain augmentation lineage. Class
coverage, physical fish identities and acquisition groups still need to be
resolved before treating a held-out comparison as an independent four-class
study. No AI prediction replaces an existing human label.

These part labels are the appropriate targets for learning feature support
within each annotated anatomical region. A future dataset-driven part-feature
stage must preserve the individual region grades and pass its calibrated part
support through the existing weighted fish policy. Whole-silhouette size and
structural evidence still require measurements and targets appropriate to their
scope; an independently graded Head label cannot label the entire silhouette.

The `fit`/`evaluate` commands below currently calibrate the separate **whole-fish**
70/30 decision-fusion stage. They do not implement part-level calibration or
convert this part dataset into whole-fish truth. Their manifest accepts
`reference_unit: whole_fish`; explicit part or detector reference units are
rejected. Historical v1 records without the field retain their defined
whole-fish meaning. A weighted policy result computed from part labels can be
used to test policy replay, but is not a separately assigned human whole-fish
grade and must not be supplied as one.

Create an empty manifest, then populate it from verified records:

```powershell
python -m src.evaluation.calibrate_decision_fusion template --output results/fusion/records.json
python -m src.evaluation.calibrate_decision_fusion audit --output results/fusion/data_audit.json
```

Every whole-fish calibration manifest record identifies the physical `specimen_id`,
`capture_group_id`, `duplicate_group_id`, original `image_sha256`, partition,
annotator/review IDs, explicit `annotator_verified: true`, human grade, original
AI prediction, original `ai_baseline` policy verdict, source-bound `measurements`,
`model_context` and `anatomical_policy`. Original predictions and corrections
are separate fields. The exact checkpoint and anatomical policy fingerprints
must match deployment.

Use one representative observation per physical specimen. Assign all related
capture/augmentation/near-duplicate families to one partition. Exact original
image and native-pixel hashes must not cross partitions. The tool rejects
unknown identities, repeated specimens, split leakage and pseudo-labels.
Known near-duplicate families must be supplied from the dataset audit; hashes
alone cannot identify every transformed duplicate or undocumented acquisition.
Model 2 training exposure must also be checked against the study's independent
dataset-lineage protocol before calling test performance independent of model
training. A declared identity is not authenticated by the software.

Distributions fit on `calibration`; temperature selection and acceptance-policy
comparison use `validation`. `test` is reserved for the separate evaluation
command. Five independent specimens per class per fit/validation partition is
an engineering minimum, not evidence of adequate statistical power.

### Source-bound measurement validation

Runtime extraction uses the same `owned_fish_fusion_v1` definition as offline
calibration. A reviewed artifact in `FISH_REVIEWED_FEATURES_PATH` can carry a
`fusion_validation` object with matching `fish_id`, `frame_id`, `source_id` and
native BGR `frame_pixels_sha256`, explicit review provenance, `reviewed`,
`complete_mask`, `ownership_validated`, `measurement_validated`, and a known
`capture_profile_id`. The existing reviewed-image/mask loader must accept the
actual native masks before this record is passed to grading. These attestations
must come from real review; extraction success never creates them.

Required family checks in that object are:

| Family | Additional reviewed checks |
|---|---|
| `size` | `anatomical_endpoints`, `perpendicular_widths`, `proportions` |
| `cracks` | `structural_discrimination` |
| `color` | `lighting_calibrated` |
| `texture` | `glcm_valid`, `lbp_valid`, `surface_valid` |

Size checks additionally verify endpoint ownership, width alignment with the
local centerline and measurement-ratio consistency. Any lost native silhouette
pixels prevent complete-mask eligibility. Color requires `lighting.validated`,
matching `lighting.profile_id`, validated three-channel `rgb_gains` and
`rgb_offsets`; clipped corrected pixels reduce reliability. An identity
correction still requires a validated capture profile.

The narrow dark-line detector uses original-image contrast and geometry to
reject compact spots, one-sided shadows and repeated fine texture. Its absence
of candidates does not establish intact structure, and its limited scope is
recorded. For independently reviewed complete crack measurements, the `cracks`
object can declare `measurement_source: reviewed_structural_measurement`, with
verified `values.crack_area_fraction` and `values.crack_length_to_fish_length`.
Reviewed negatives require the same validation as reviewed positives. A
candidate's heuristic score or segmentation confidence cannot enable this
feature.

An independent `head_integrity_evidence` object requires matching source/fish/
frame identity, `state: confirmed_absent`, `reviewed`, `ownership_validated`,
`visibility_validated`, reviewer and review ID. A suspected or stale claim is
recorded without establishing anatomical absence.

### Review & Teach import

The exporter reads SQLite in read-only mode and joins human corrections with
their audit entries. A separate identity file maps actual `session_id` and
`track_id` pairs to reviewed specimen/capture/duplicate IDs, image hash and
partition. It withholds records with unknown specimens, missing reviewers or
missing original source-bound feature bundles. It never trains on the AI grade.

```powershell
python -m src.evaluation.calibrate_decision_fusion export-reviews --database results/inspection_history.sqlite3 --identities results/fusion/identities.json --output results/fusion/review_records.json
```

`identities.json` has an `identities` list containing these mappings. Legacy
history with no original pixels/validated measurements cannot be reconstructed
into calibrated references from rectangular ROI statistics.

## Fitting and evaluating

```powershell
python -m src.evaluation.calibrate_decision_fusion fit --manifest results/fusion/records.json --output results/fusion/calibration.json
python -m src.evaluation.calibrate_decision_fusion evaluate --manifest results/fusion/records.json --artifact results/fusion/calibration.json --output results/fusion/test_comparison.json
```

The fit tool records class-specific distributions, sample counts, per-class
recall, Brier scores, calibration error, temperatures, reliability and provenance.
Runtime rejects a mismatched checkpoint, policy, extraction version, capture
profile, malformed artifact or failed validation comparison. Validation requires
non-decreasing paired four-class macro F1 and Rejected recall, no increase in
false Rejected rate, and actual automatic decisions that used eligible features.
Automatic fallback decisions alone cannot pass this last requirement. Reports
record `eligible_fusion_count`, `eligible_fusion_automatic_count` and
`per_feature_usage_counts`, in addition to the original paired class metrics.

Measurements and fitted artifacts explicitly identify `reference_unit` as
`whole_fish`. Runtime rejects an explicit part target as well as the fitting
tool's record-level check. Historical v1 records without this field retain their
defined whole-fish meaning. The policy fingerprint now includes
`whole_fish_feature_validation_v5` and the mathematical measurement domains;
calibrations fitted under the previous acceptance rules require refitting.
Version v4 additionally withholds tied combined scores even with a zero configured
margin and preserves explicit inference/frame-quality holds with cached scores.
Version v5 compares all tied leaders symmetrically, retains the single-low-weight
tie safeguard, and excludes ambiguous class predictions from calibration recall.
No previous artifact can be reused without validation against these rules.
This includes the previous v2 rule that left all original Ungraded results on
hold. Validation and untouched-test reports now count resolved score holds and
how many match their human reference grades. These counts describe the supplied
evaluation records, not a guarantee of production accuracy.

The shared fitting/runtime checks reject negative measurements, zero size
length ratios, pixel fractions outside [0,1], and texture values outside the
fixed extractor's possible range. Length ratios may exceed one; crack length
is not capped at one. These are unit constraints, not invented A/B/C/Rejected
boundaries. An extraction error withholds that family, malformed texture counts
cannot interrupt extraction, and a separately reviewed complete crack
measurement remains usable if the optional candidate detector fails.

The separate test report compares Model 2-only and fused predictions on the
same held-out physical fish. It includes four-class precision/recall, a 4x5
confusion matrix retaining Ungraded, automatic accuracy/coverage, review counts,
false Rejected rate and denominators, exact conflicts, and a paired capture-group
bootstrap accuracy-difference interval. Reviewing an interval or majority
agreement does not prove an improvement. Do not repeatedly tune against test
labels. Never install a failed or materially regressing calibration.

An evaluated artifact can be placed at the configured
`configs/decision_fusion_calibration.json` (or the configured artifact path).
Restart the inspection process to load its frozen calibration; each record
retains the calibration ID/hash and policy snapshot. No model retraining,
checkpoint replacement or runtime hot-swap occurs in this feature.

## Verification and limits

`tests/test_decision_fusion.py` exercises actual grade changes from calibrated
size evidence, agreement, minor/major conflicts, reliability redistribution,
outliers, stale and mismatched evidence, Head holds, calibration partitions,
Review & Teach import and evidence exports. `tests/test_decision_fusion_ui.py`
executes the dashboard's explanation logic with Node. All reference labels and
distributions in those tests are artificial software controls, not real-fish
performance evidence. Existing anatomical, temporal, mask and review tests
remain part of the regression suite.

`tests/test_feature_contribution_integration.py` additionally runs native,
reviewed-mask controls through the real Model 2 adapter, geometry extraction,
feature extraction and final decision. Each family changes actual class scores;
size can change an accepted A to B, while a lone cracks/color/texture grade
change requires review. The same checks run with image diagnostics enabled and
disabled. They verify contribution sums, size-use metadata, export preservation,
and the Model 2 fallback for malformed optional review provenance. Synthetic
references stay inside temporary tests and are never installed as calibration.

The diagonal class distributions and engineering acceptance settings are a
starting estimator, not a validated biological grading standard. Correlated
features, capture drift, reviewer disagreement and class imbalance need
specimen-separated real evaluation. The current audited data cannot establish
an accuracy gain, so no improvement percentage is reported and supporting
features remain ineligible until their verification/calibration requirements
are satisfied.

Verification on 2026-11-23: the complete checkpoint-free isolated suite passed
**1,928 tests and 127 subtests**, with 12 tests skipped. The focused feature
contribution, fusion, UI and shared-measurement checks passed all 83 tests.
JavaScript syntax and
Git whitespace checks also passed. Synthetic controls demonstrate actual final
grade changes and the four conflict states; these counts do not measure
biological grading accuracy. The isolated runner copies the launcher/dependency
contracts and uses a fresh temporary directory outside its project copy so
private-reference tests retain their intended isolation.

The fresh read-only inventory at
`results/qa/feature_contribution/data_audit.json` still reports 77 inspections,
zero human reviews and zero reviewed source-bound feature bundles. No production
calibration or reference data was created or enabled by these verification tests.
The subsequent reference-provenance audit recognizes the existing 9,723 human
part labels independently of those application counts. Its five new regressions
and the existing decision-fusion tests passed **59 tests**. It changes reference
inventory reporting and documentation, not runtime grading thresholds.

After the user confirmed independent part grading, the reference-unit guard,
per-region label inventory, existing fusion checks and weighted-grading checks
passed **87 tests and 5 subtests**. The current command still fits whole-fish
fusion; part-level feature calibration has not been implemented or activated.

Earlier feature-classification QA on 2026-11-23: the isolated suite passed
**2,054 tests and 127 subtests**, with **12 tests skipped**. The opt-in CPU
checkpoint smoke and real reference-image upload regression separately passed
**2 tests**. JavaScript syntax and Git whitespace checks passed. The complete
isolated log is at `results/qa/feature_score_recovery/model_free_tests.log`.
`tests/test_feature_classification_qa.py` covers mathematical boundaries,
all class-transition pairs with the Rejected safeguard, actual feature-use
validation, reference-unit mismatches, malformed texture counts, extraction
failure recovery, and CSV/XLSX attribution round trips. Node checks exercise
the dashboard's four-class contribution table.
`tests/test_fusion_score_recovery.py` additionally verifies score-only recovery
for all existing classes, fresh acceptance checks, preserved evidence holds,
pending trained Rejected overrides, live temporal gates, original-result
preservation, and validation/test recovery counts. Dashboard explanations and
exports identify the score reasons resolved by features.

The final read-only inventory still finds 9,723 independently graded part
labels and zero reviewed source-bound feature records. No feature calibration
is installed. These are software and checkpoint-integration checks; they do
not establish improved biological grading accuracy or fit a production model.

Grading accuracy-guard QA on 2026-11-23: the final isolated suite passed **2,103
tests and 127 subtests**, with **12 tests skipped**. The focused grading, fusion,
replay and version-contract checks passed **303 tests and 17 subtests**. Both
opt-in CPU checkpoint and reference-image upload tests passed. JavaScript syntax
and Git whitespace checks passed. Logs and the read-only reference inventory are
under `results/qa/features_grading_*`.

The 49 new cases in `tests/test_grading_accuracy_guards.py` cover all six tied
class pairs in every grading mode, floating-point ties, ordinary positive margins,
cached scores during inference/frame-quality holds, live recovery, nested offline
availability flags, correct override support in runtime/replay/exports, tied
optional geometry/structural transfers, and calibration policy compatibility.
The formerly accepted Class A tie behavior is intentionally replaced with review.
Configuration 4.1 records the active corrections; standard-mode defaults record
3.1. Existing weights and numerical acceptance thresholds are retained, and saved
historical verdicts are not rewritten. Replaying old evidence with this corrected
implementation can change results affected by these defects.

The fresh audit still recognizes **9,723 independently assigned part labels**,
including augmented observations, and finds **zero reviewed source-bound feature
bundles**. No production feature calibration was created or installed. These
software and checkpoint checks do not measure biological classification accuracy;
that still requires an appropriately separated, independently labeled evaluation.

Decision-fusion tie QA on 2026-11-23: the complete checkpoint-free isolated suite
passed **2,200 tests and 127 subtests**, with **12 tests skipped**. The focused
fusion, grading, explanation and export checks passed **352 tests and 5 subtests**.
JavaScript syntax and Git whitespace checks passed. The full log is at
[`../../tmp/fusion_ties_qa/model_free_tests.log`](../../tmp/fusion_ties_qa/model_free_tests.log).

The 97 synthetic controls in `tests/test_fusion_ties.py` cover symmetric recovery
across every grade pair, live temporal acceptance, ambiguous reference reliability,
three-way ties under permissive configured thresholds, unresolved combined ties,
calibration recall, frozen-policy compatibility, and CSV/XLSX round trips. The
existing workbook regression also verifies complete, checksum-matched recovery
when larger evidence records require Excel's Extended Evidence sheet. These
checks verify software behavior; no production calibration was fitted or installed,
and real-fish accuracy remains unvalidated.
