# Reviewed structural features and grade eligibility

The anatomical decision still uses the existing Model 2 Body/Head/Tail weights
and evidence gates. The engine records separate anatomical, geometric,
structural, and eligibility stages in `analysis.feature_fusion`. Uncertain
Head/Body ownership, missing required regions, and other Ungraded conditions
cannot be repaired by a structural feature.

`configs/structural_features.yaml` ships disabled and uncalibrated. It contains
no crack-severity boundaries, approved reference set, or support-transfer rule.
Consequently current automatic crack candidates cannot change a classification.
Neither color nor a MobileSAM model score establishes a confirmed fracture.

## Reviewed evidence contract

`WeightedGradingEngine.evaluate` accepts optional `structural_evidence` and
`source_context`, or the corresponding entries in `frame_quality`. The source
must identify the acquisition and SHA-256 of original pixels; evidence must
match that source, parent Fish ID, and current frame. Native frame dimensions,
when supplied, also bound crack locations.

The separate review record requires a confirmed Body finding, original-frame
locations, explicit ownership/Body-mask/measurement approval, reviewer/review
IDs, matching policy reference set, and a reviewed severity label or reviewed
normalized reference boundaries. Clipping, overlap, ambiguous ownership, and
partial silhouettes must explicitly be absent. These are recorded review
attestations, not facts inferred from a successful segmenter call. Runtime
catalog loading must verify the matching original-image and mask artifacts.

A policy also needs explicit enablement, reviewed calibration metadata,
reference sample count, and reviewer provenance. A validated major Body crack
then excludes Class A. The engine selects the strongest remaining supported
grade using the existing support and margin gates; if none qualifies, the
result is Ungraded. It does not manufacture Class C or Rejected support. Existing
Rejected safeguards remain in place. Minor/Moderate do not automatically remove
Class A. An expert-approved optional B/C support transfer can be configured with
an explicit cap; no such rule is supplied by this repository.

Primary scores, effective weights, original grade and support remain recorded.
Structural eligibility does not erase anatomical scores. Thus A can retain the
largest original score while a confirmed major-crack restriction makes another
supported grade eligible. The feature-fusion final stage records the resulting
grade separately from pre-structural geometric provenance.

## Image-processing candidates

`src/features/damage.py` retains the existing local black-hat dark-ridge
response, original-RGB two-sided contrast checks, component/elongation filters,
boundary exclusion, and repeated-parallel-texture rejection. These are image
processing settings, not biological severity cutoffs. A bounded morphological
skeleton adds native-pixel graph extent, median/maximum candidate width,
localized skeleton points, and branch counts to each retained candidate.
Normalized skeleton extent is withheld without an explicitly validated Body
length. Even with that denominator, the crack cause and severity remain
unvalidated.

The skeleton measures candidate pixel support; branches can inflate its graph
extent. The existing detector does not establish a complete biological crack
length, broad-fracture detection, or boundary-tear accuracy. Scales, pigmentation,
uneven illumination, compression, touching fish, and dark edges require reviewed
negative examples. Current tests use synthetic software controls and do not
measure real-fish crack precision or recall.

## Reference-artifact workflow

Create an empty, unapproved catalog:

```powershell
python -m src.evaluation.review_structural_features --template results/qa/sam_features/structural_reference_template.json
```

Populate `records` only with real reviewed reference data. Each record identifies
the source, native BGR-pixel digest, Fish ID, original image, full-frame binary
whole-fish and Body masks, reviewer provenance, calibration/validation split, and
any reviewed structural findings. Do not place the unapproved example in the
active records list. Relative artifact paths resolve against the catalog.

Check supplied artifacts without modifying them or activating grading:

```powershell
python -m src.evaluation.review_structural_features --validate review.json --report results/qa/sam_features/structural_reference_audit.json
```

The audit checks readable original images, exact native alignment, pixel digest,
nonempty binary masks, Body containment, review IDs, source/parent matching,
localized support and calibration/validation source separation. An integrity
pass remains distinct from expert approval, held-out feature accuracy, and a
validated grading standard. Policy activation is never performed by this tool.

Still required: expert-confirmed small/large cracks, reviewed severity and
normalized anatomical measurements, clean and nuisance-pattern negatives,
isolation/overlap cases, a defensible reference distribution, and held-out
precision/recall and eligibility-outcome review. No reference labels or severity
thresholds have been fabricated.
