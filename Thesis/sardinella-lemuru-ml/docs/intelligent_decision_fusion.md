# Intelligent fish grading fusion

`WeightedGradingEngine` now applies a calibrated decision-fusion stage to the
same per-fish evidence used for live inspection and upload analysis. Eligible
supporting features change the actual verdict and confidence, rather than only
the displayed measurements. `analysis.feature_fusion.decision_fusion` records
the complete comparison and is preserved in SQLite history and exports.

The installed default has **no calibrated feature references**. It honestly uses
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

## Preparing verified references

The current inventory is recorded in `decision_fusion_data_audit.json`: 77 saved
inspections, zero human review audit entries, and zero source-bound reviewed
feature bundles. The COCO export contains part annotations and lacks physical
specimen identities. Those labels cannot be promoted into verified whole-fish
feature relationships or an independent performance study.

Create an empty manifest, then populate it from verified records:

```powershell
python -m src.evaluation.calibrate_decision_fusion template --output results/fusion/records.json
python -m src.evaluation.calibrate_decision_fusion audit --output results/fusion/data_audit.json
```

Every manifest record identifies the physical `specimen_id`,
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
non-decreasing paired four-class macro F1, no increase in false Rejected rate,
and actual eligible-feature automatic decisions.

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

The diagonal class distributions and engineering acceptance settings are a
starting estimator, not a validated biological grading standard. Correlated
features, capture drift, reviewer disagreement and class imbalance need
specimen-separated real evaluation. The current audited data cannot establish
an accuracy gain, so no improvement percentage is reported and supporting
features remain ineligible until their verification/calibration requirements
are satisfied.

Verification on 2026-11-23: the complete checkpoint-free isolated suite passed
**1,914 tests and 127 subtests**, with 12 tests skipped. JavaScript syntax and
Git whitespace checks also passed. Synthetic controls demonstrate actual final
grade changes and the four conflict states; these counts do not measure
biological grading accuracy. The isolated runner copies the launcher/dependency
contracts and uses a fresh temporary directory outside its project copy so
private-reference tests retain their intended isolation.
