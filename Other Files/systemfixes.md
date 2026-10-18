You are working directly on this repository:

https://github.com/xashathebest/Thesis

Your task is to perform a careful repository-wide refactor and integration of the Tamban Fish Inspection System.

DO NOT merely write a plan.

Inspect the existing code first, understand the current runtime paths and tests, then IMPLEMENT the changes, delete obsolete/unused code where safe, update tests/documentation, and leave the repository in a coherent working state.

The goal is to make this repository behave as ONE defensible end-to-end thesis system rather than several partially overlapping implementations.

# 1. CANONICAL SYSTEM

Treat the following as the canonical production/runtime architecture:

* `src/api/`
* `src/inference/`
* `src/evaluation/`
* `configs/`
* `frontend/`
* `tests/`

The primary runtime is:

Camera / uploaded image
→ Model 1 whole-fish detector
→ persistent Fish ID / tracking
→ individual fish evidence
→ Model 2 12-class Head/Body/Tail grade detector
→ temporal evidence aggregation
→ fish-level grading policy
→ A / B / C / Rejected / Ungraded
→ counting
→ history
→ persistence
→ analytics
→ CSV/XLSX export.

Current Model 1 role:

* detect whole parent Fish only;
* Model 1 must NEVER assign A/B/C/Rejected quality;
* provide bbox, confidence and persistent identity.

Current Model 2 classes:

* Grade_A_Body
* Grade_A_Head
* Grade_A_Tail
* Grade_B_Body
* Grade_B_Head
* Grade_B_Tail
* Grade_C_Body
* Grade_C_Head
* Grade_C_Tail
* Rejected_Body
* Rejected_Head
* Rejected_Tail

Model 2 provides grade-aware anatomical evidence.

Do not invent capabilities that the checkpoints do not contain.

Current checkpoints DO NOT explicitly detect:

* cracks
* holes
* tears
* yellowing defects
* deformation
* missing head
* missing tail
* oil percentage
* moisture percentage

Do not infer these from absence of detection.

HSV/color/brightness measurements may remain descriptive proxies only until validated.

# 2. FIRST PRIORITY — FIX THE GRADING ENGINE

There are important inconsistencies between:

* `configs/grading_engine.yaml`
* `src/inference/grading_engine.py`
* `src/evaluation/fish_level_validation.py`

These must be eliminated.

There must be ONE canonical fish-verdict implementation used by BOTH live inference and offline validation.

Same evidence + same policy config MUST return:

* identical weighted scores;
* identical observed regions;
* identical evidence coverage;
* identical top grade;
* identical support;
* identical margin;
* identical final verdict;
* identical reason codes.

Create/refactor a pure deterministic grading function/policy layer that both runtime and evaluation call.

Do NOT maintain two separately implemented grading algorithms.

# 3. REMOVE THE CURRENT MISSING-EVIDENCE RENORMALIZATION BUG

The current grading engine renormalizes remaining part weights when Head or Tail is unavailable.

This is NOT the desired behavior.

The fixed original part weights are:

Body = 0.50
Head = 0.30
Tail = 0.20

DO NOT renormalize missing evidence.

Example:

Body Class A evidence = 0.82
Head unavailable
Tail unavailable

Correct:

Class A contribution =
0.82 × 0.50
= 0.41

Evidence coverage =
0.50

DO NOT convert this to:

0.82 × 1.00 = 0.82

Missing evidence must remain missing.

Implement:

score_A =
Body_A * 0.50

* Head_A * 0.30
* Tail_A * 0.20

score_B =
Body_B * 0.50

* Head_B * 0.30
* Tail_B * 0.20

score_C =
Body_C * 0.50

* Head_C * 0.30
* Tail_C * 0.20

score_Rejected =
Body_Rejected * 0.50

* Head_Rejected * 0.30
* Tail_Rejected * 0.20

For unavailable parts, contribution is zero because no reliable evidence exists.

Do NOT alter original part weights.

Also store:

evidence_coverage =
sum(original weights of reliable available parts)

Examples:

Body only = 0.50
Body + Head = 0.80
Body + Tail = 0.70
Head + Tail = 0.50
all parts = 1.00

# 4. FIX CONFIGURATION LOADING

Currently `GradingConfig.from_mapping()` silently ignores YAML fields not present in the dataclass.

This is dangerous.

Fix configuration loading so that important keys cannot silently do nothing.

The runtime must support the grading settings that actually appear in the configuration.

At minimum support:

* body_weight
* head_weight
* tail_weight
* require_body
* grading_mode
* minimum_part_confidence
* final_verdict_threshold
* minimum_regions_observed
* minimum_original_weight_coverage
* strict_minimum_regions_observed
* strict_minimum_original_weight_coverage
* minimum_track_observations
* temporal_evidence_limit
* minimum_grade_margin
* rejected_override_threshold
* maximum_grade_stddev if used
* frame-quality settings if retained
* color_adjustments_enabled
* defect_adjustments_enabled

Unknown configuration keys should either:

1. raise a clear configuration error; or
2. be explicitly recognized as metadata-only/deprecated.

Do not silently ignore meaningful settings.

# 5. REMOVE THE THRESHOLD CONFLICT

Currently the repository contains both:

`final_verdict_threshold: 0.50`

and:

`minimum_final_score: 0.25`

while the live engine effectively uses 0.25 and offline validation uses 0.50.

Eliminate this ambiguity.

Use ONE canonical field:

`final_verdict_threshold`

The current configured baseline may remain 0.50, but document it as a provisional/validation-selected operating setting rather than scientifically proven optimum.

If backwards compatibility with `minimum_final_score` is required:

* treat it only as a deprecated alias;
* do not allow conflicting values silently;
* log/report which canonical value was used.

Live inference and offline replay must use the exact same threshold.

# 6. IMPLEMENT EVIDENCE COVERAGE GATING

The final verdict must consider how much reliable anatomical evidence exists.

Support at least two policies:

STANDARD / EXPERIMENTAL
and
STRICT / THESIS-SAFE.

For the thesis-safe strict mode, initially require:

* Body observed;
* Head observed;
* Tail observed;
* minimum_regions_observed = 3;
* minimum_original_weight_coverage = 1.00.

This follows the conservative initial thesis policy.

Allow future validation experiments such as 0.80 coverage through configuration, but do not silently weaken strict mode.

A fish without enough reliable evidence must become:

Ungraded

not A/B/C/Rejected.

# 7. ADD A TOP-VS-SECOND GRADE MARGIN GATE

Current code selects the largest weighted score even when the top two grades are almost identical.

Fix this.

Calculate:

top_grade
top_score
second_grade
second_score

and:

grade_margin = top_score - second_score

Add configurable:

`minimum_grade_margin`

If:

top_score < final_verdict_threshold

return Ungraded.

If:

grade_margin < minimum_grade_margin

return Ungraded.

The margin threshold must remain configuration-driven and validation-selected.

Do not hard-code an arbitrary scientific threshold.

# 8. IMPLEMENT FORMAL UNGRADED REASON CODES

Ungraded is already partially implemented but needs formal reason codes.

Add structured reason codes instead of relying only on prose explanations.

At minimum support:

UG_PARENT_UNCERTAIN
UG_MISSING_PART_EVIDENCE
UG_ASSOCIATION_AMBIGUOUS
UG_LOW_GRADE_SUPPORT
UG_LOW_MARGIN
UG_OUT_OF_FRAME
UG_INSUFFICIENT_COVERAGE
UG_INSUFFICIENT_REGIONS
UG_TEMPORAL_EVIDENCE
UG_FRAME_QUALITY
UG_MODEL2_UNAVAILABLE

Final successful grades may use:

GR_CONFIDENT

Rejected may use:

RJ_GRADE_EVIDENCE
RJ_CONFIRMED_DEFECT

Do NOT use `RJ_CONFIRMED_DEFECT` unless an actual validated defect detector/rule exists.

Store reason codes in:

* live state;
* history;
* database;
* API;
* frontend;
* CSV;
* XLSX;
* offline evaluation.

# 9. REJECTED LOGIC

Rejected is a real trained Model 2 quality category because Model 2 contains:

Rejected_Body
Rejected_Head
Rejected_Tail.

Therefore Rejected should normally participate in the same weighted calculation as A/B/C.

Calculate:

score_Rejected =
Body_Rejected * .50

* Head_Rejected * .30
* Tail_Rejected * .20

Do not claim that Rejected means:

* crack detected;
* missing body part;
* deformation;
* yellowing;
* hole;
* tear.

A separate optional `rejected_override_threshold` may exist only as an explicit validated override.

Keep it disabled/null by default unless already scientifically justified.

# 10. MODEL 2 TEMPORAL AGGREGATION

Preserve the useful current behavior:

For every frame and `(region, grade)` pair:

* retain only the strongest detection;
* do not sum duplicate overlapping boxes;
* aggregate across a persistent Model 1 Fish ID;
* use arithmetic mean over valid observations.

Keep temporal evidence separated per Fish ID.

Do not mix evidence between tracks.

Make aggregation metadata explicit:

* observation count;
* frames used;
* region observations;
* mean evidence;
* evidence coverage;
* stability information if configured.

# 11. TRACKING AND COUNTING

Keep Model 1 as the owner of physical fish identity.

Preserve:

* one persistent Fish ID;
* direction-aware virtual line crossing;
* one count per tracked fish;
* simultaneous fish crossing;
* wrong-direction rejection;
* track timeout;
* late quality updates without increasing total fish count.

Continue to enforce:

sum(A + B + C + Rejected + Ungraded) == total counted fish

at all times.

Record the actual tracker backend used:

* ByteTrack;
  or
* IoU fallback.

Do not pretend they are equivalent.

Expose tracker backend in session metadata and diagnostics.

# 12. SETTINGS MUST NOT CHANGE MID-FISH

The frontend currently allows detection/quality thresholds to change while inspection is active.

This can cause one fish to accumulate evidence under multiple policies.

Fix this.

Preferred behavior:

Inference-policy settings that can affect predictions or grading may only be changed while inspection is stopped.

At minimum lock:

* Model 1 confidence threshold;
* Model 2 inference threshold;
* grading mode;
* grading thresholds;
* grade margin;
* camera acquisition settings.

If a setting must be changed while running, the system must:

* terminate/reset active tracks;
* reset accumulated grading evidence;
* create a new configuration/session version.

Never mix multiple inference policies inside one fish verdict.

# 13. CLEARLY SEPARATE MODEL 2 DETECTOR THRESHOLD FROM GRADING THRESHOLD

Do not confuse:

`FISH_QUALITY_CONFIDENCE`

with:

`minimum_part_confidence`

and with:

`final_verdict_threshold`.

Use clear names and documentation:

Model 2 inference confidence:
minimum detection accepted from YOLO.

Part evidence threshold:
minimum detected-part evidence considered reliable for coverage.

Final verdict threshold:
minimum weighted fish-level support required to issue a grade.

Grade margin threshold:
minimum separation between first and second grade.

Expose all clearly in diagnostics.

Do not label all of them simply "confidence."

# 14. RENAME FINAL MODEL 2 "CONFIDENCE" TO SUPPORT WHERE APPROPRIATE

The weighted final grade score is not a calibrated probability.

In UI/export/internal naming where possible use:

Grade Support
Final Support
Weighted Support

instead of:

Grade Confidence

Keep Model 1/Model 2 raw detector output named confidence because that is the model's detector confidence value.

The weighted result must not be displayed as:

"78% probability"

unless probability calibration is later implemented.

# 15. VISIBILITY AND MISSING-EVIDENCE STATES

Current handling only has approximately:

present
unknown_not_observed

Improve this without inventing unsupported conclusions.

At minimum distinguish:

PRESENT
NOT_DETECTED
PARENT_FRAME_CLIPPED
PARENT_CROP_CLIPPED
UNKNOWN

Only use OCCLUDED if there is actual evidence that occlusion can be determined reliably.

Do not automatically mark physical missing anatomy.

Keep:

physical_missing = null

unless future validated evidence proves physical absence.

Detect parent/frame clipping geometrically from bbox vs image bounds.

If evidence may be lost because a parent touches the frame edge, use:

UG_OUT_OF_FRAME

when strict grading requires the missing region.

# 16. MODEL 1 → MODEL 2 INPUT STRATEGY

The current deployed path uses:

Model 1 full frame
→ fish crop
→ Model 2.

Keep this working.

However, do not assume crop inference is scientifically superior.

Create a clean abstraction that can support:

`quality_inference_mode: crop`
and
`quality_inference_mode: full_frame`

without duplicating grading logic.

For crop mode:

* crop one Model 1 fish;
* optionally add configured padding;
* run Model 2;
* translate part boxes back to original frame coordinates;
* keep the Model 1 track ID;
* detect crop clipping;
* avoid assuming every detection in an overlapping crop belongs to the parent with perfect certainty.

For full-frame mode:

* run Model 2 once on the full frame;
* generate candidate part-parent relationships;
* support conservative part association;
* allow UNASSIGNED.

Do not force full-frame mode as default unless tests justify it.

The purpose is to allow future controlled comparison of:

full-frame Model 2
vs
exact Model 1 crop
vs
padded Model 1 crop.

# 17. CONSERVATIVE FULL-FRAME PART ASSOCIATION

If implementing full-frame mode, add a conservative association module.

Candidate part-parent scoring may use:

* overlap with parent;
* fraction of part inside parent;
* part center inside/near parent;
* normalized center distance;
* expected Head/Body/Tail ordering;
* fish-axis consistency;
* size plausibility.

Do not greedily assign every part to the nearest fish.

Solve conflicts globally or conservatively.

Each parent may own at most:

* one Head;
* one Body;
* one Tail

for selected primary evidence.

Allow:

UNASSIGNED

when ownership is ambiguous.

Add association confidence/margin fields.

Do not call a part ambiguous unless the implemented scoring provides evidence for that conclusion.

# 18. ROI PADDING

Current default ROI padding is zero.

Keep padding configurable:

`FISH_QUALITY_ROI_PADDING`

but ensure it is safe and bounded.

Add diagnostics showing the actual crop bounds and whether padding hit frame limits.

Do not arbitrarily choose a scientifically optimal padding value.

Support future validation of:

0 padding
small padding
moderate padding

without changing grading logic.

# 19. MODEL 2 INTERVAL

Current Model 2 inference interval is approximately every 3 frames.

Preserve configurable:

`FISH_QUALITY_INTERVAL`

but record:

* actual interval;
* Model 2 observations per fish;
* track lifetime frames;
* number of grading frames used.

Do not silently finalize a grade with insufficient temporal evidence.

If `minimum_track_observations` is not reached:

Ungraded
reason:
UG_TEMPORAL_EVIDENCE

# 20. FRAME QUALITY MODULE

The repository already contains:

`src/inference/frame_quality.py`

Do not leave a fully implemented/tested frame-quality system disconnected from the production architecture without explanation.

Integrate useful measurements into the canonical pipeline where appropriate.

At minimum record:

* crop width;
* crop height;
* crop area;
* clipped status;
* sharpness;
* Model 1 detection confidence;
* frame-quality reasons.

Frame-quality filtering should remain conservative.

Do not introduce arbitrary blur/sharpness rejection thresholds.

If no validated threshold is configured:

measure and report,
but do not reject.

Use best-frame selection for:

* review evidence;
* optional archived image/crop metadata;
* representative measurements;

not as an undocumented replacement for temporal grading.

Temporal Model 2 evidence and representative best-frame selection solve different problems.

# 21. CAMERA REPRODUCIBILITY — EMEET 4K / UVC CAMERA

The current camera code only opens a generic OpenCV camera.

Improve the active camera implementation in:

`src/api/camera.py`

Do NOT build this in the unused placeholder `camera/capture.py`.

Support safe camera-property probing and configuration.

Where supported by OpenCV/Windows/UVC camera drivers, support:

* frame width;
* frame height;
* FPS;
* brightness;
* contrast;
* saturation;
* gain;
* exposure;
* auto exposure;
* white balance;
* auto white balance;
* focus;
* autofocus.

Do NOT assume every camera exposes every property.

For every property:

* probe support;
* attempt set;
* read it back;
* return actual accepted value;
* report unsupported values without crashing.

For Windows, prefer a suitable backend such as DirectShow where it improves camera property support, but retain a fallback when unavailable.

Do not hard-code assumptions specific only to one exact eMeet firmware.

# 22. CAMERA API + FRONTEND SETTINGS

Add backend support for camera configuration.

For example:

GET `/api/camera/settings`

Return:

* supported controls;
* current values;
* min/max if reliably discoverable;
* resolution;
* FPS;
* backend;
* camera index.

POST `/api/camera/settings`

Apply validated settings.

Camera acquisition settings must preferably only change while inspection is stopped.

Add a Camera section to the existing settings drawer.

Only show interactive controls that the current camera reports as supported.

Do not show a fake slider for unsupported properties.

Record actual accepted camera settings when a session begins.

# 23. CAMERA CONSISTENCY OVER AUTOMATIC IMAGE "FIXING"

Do not solve inconsistent images by silently applying aggressive:

* CLAHE;
* automatic contrast;
* gamma;
* automatic white balance;
* saturation correction

to inference frames.

These operations can alter grading evidence.

Preferred architecture:

stable acquisition
→ minimal deterministic preprocessing
→ model inference.

If any image transformation is used, it must be explicit, deterministic, configurable, documented and included in session metadata.

# 24. ACTIVE WEB APP PERSISTENCE

The current active dashboard stores history only in memory.

Add SQLite persistence to the canonical `src/` web application.

Do not require the separate legacy `fish_quality_system` runtime.

Use simple durable tables such as:

inspection_sessions
fish_inspections

Possible `inspection_sessions` fields:

* session_id
* started_at
* ended_at
* git_commit
* model1_path
* model1_sha256
* model2_path
* model2_sha256
* tracker_backend
* grading_config_json
* grading_config_hash
* camera_settings_json
* runtime_settings_json

Possible `fish_inspections` fields:

* session_id
* track_id
* timestamp
* final_grade
* final_support
* second_grade
* second_support
* grade_margin
* evidence_coverage
* observed_regions
* reason_codes
* Model 1 confidence
* weighted_scores_json
* part_results_json
* color_measurements_json
* analysis_json
* processing_time_ms

Use proper primary/unique keys.

Persist completed inspection events.

Live in-memory state may remain for low-latency UI, but the database is the durable history source.

# 25. HISTORY AND EXPORT MUST USE DURABLE RECORDS

Update:

* `/api/history`
* analytics;
* CSV export;
* XLSX export

so they can use persistent session records.

"Today" must mean today's stored records, not merely events since the last backend restart.

Preserve current-session filtering.

Allow session-aware filtering.

Keep exports explainable.

# 26. XLSX / CSV CONTENT

Continue exporting the useful current calculations.

Include:

* Fish ID;
* Session ID;
* Timestamp;
* Final Grade;
* Final Support;
* Second Grade;
* Second Support;
* Grade Margin;
* Evidence Coverage;
* Reason Codes;
* Model 1 confidence;
* Model 2 detector threshold;
* Part evidence threshold;
* Final verdict threshold;
* Body/Head/Tail status;
* Body/Head/Tail evidence;
* Body/Head/Tail fixed original weight;
* per-grade part contribution;
* weighted A/B/C/Rejected scores;
* temporal observation count;
* tracker backend;
* camera settings/session reference;
* HSV/color measurements;
* processing time.

Retain multiple Excel sheets.

Recommended sheets:

Fish Inspections
Session Summary
Feature Summary
Grade Calculation Rules
Session Configuration

Do not export unsupported defect labels.

# 27. HSV / COLOR MEASUREMENTS

Current HSV measurements use rectangular Model 1/Model 2 ROIs.

Keep this provenance explicit.

Never call these:

fish segmentation mask
body segmentation mask

unless real segmentation exists.

Keep:

color_adjustments_enabled = false

by default.

Do not let yellow/brown/dark proxies change the grade without a separately validated rule.

The UI must clearly say these are measured appearance proxies and currently do not affect final grade.

# 28. DO NOT INVENT DEFECT FEATURES

Remove any active UI/export wording that implies the system detects:

* cracks;
* yellowing;
* deformity;
* fatty fish;
* physical missing anatomy

if the actual active models do not support those predictions.

It is acceptable to retain future/experimental code in research modules only if clearly separated and genuinely useful.

Production output must reflect actual model capability.

# 29. CLEAN UP DUPLICATE / LEGACY ARCHITECTURES

Perform a repository-wide dependency/reference audit.

Use:

* imports;
* route usage;
* tests;
* README references;
* config references;
* CLI entry points;
* ripgrep/search;
* model path references

to determine what is truly used.

The canonical runtime must be easy to identify.

Likely cleanup candidates include, but are not automatically limited to:

* `fish_quality_system/`
* `camera/capture.py`
* placeholder `src/evaluation/evaluate.py`
* placeholder `src/preprocessing/preprocess.py`
* stale model placeholder directories/readmes
* legacy part-preview code
* obsolete duplicate inference adapters
* duplicate dataset copies
* stale README sections
* obsolete tests for removed implementations

BUT:

DO NOT blindly delete these paths.

Before deleting anything:

1. prove it is not required by the canonical runtime;
2. migrate any useful implementation that is still needed;
3. update imports/tests/docs;
4. rerun the test suite;
5. only then delete the obsolete path.

# 30. `fish_quality_system/` CLEANUP

There is a second mostly separate architecture under:

`fish_quality_system/`

It assumes features/models such as:

* explicit crack segmentation;
* yellowing segmentation;
* dark discoloration;
* broken surface;
* anatomical segmentation;
* physical missing-part evidence;
* independent A/B/C/D grading.

These semantics do not match the current deployed two-checkpoint system.

Do not keep two competing "production" architectures.

If nothing in the canonical runtime depends on `fish_quality_system/`:

* migrate only genuinely useful generic pieces such as SQLite patterns if needed;
* remove the obsolete duplicate application;
* remove its obsolete tests and requirements;
* update documentation.

If some part is genuinely still required, move that reusable functionality into the canonical `src/` package and remove the duplicate runtime wrapper.

# 31. PLACEHOLDER FILES

Remove placeholder-only modules that only raise `NotImplementedError` if they are not active APIs.

Known candidates include:

* `camera/capture.py`
* `src/evaluation/evaluate.py`
* `src/preprocessing/preprocess.py`

Do not keep dead placeholder files merely to make the tree look larger.

If a placeholder corresponds to a real required feature, replace it with the canonical implementation rather than keeping a stub.

# 32. LEGACY PART PREVIEW

Audit the old YOLO26/part-preview path.

If it is no longer needed for the current thesis system:

* remove the runtime mode;
* remove dead UI wording;
* remove unused adapters;
* remove obsolete configs/checkpoints only if they are not part of required research evidence.

Do not let legacy preview logic complicate the production two-model flow.

If it must remain for research comparison, isolate it clearly under an experimental/legacy namespace and ensure it cannot be confused with Model 2 production runtime.

# 33. DUPLICATE DATASETS

The repository audit previously identified duplicate COCO export copies.

Before deleting any dataset:

* compare hashes;
* check all code/config/docs references;
* preserve the canonical source copy;
* update references;
* never delete unique training/evaluation data.

Remove only proven byte-identical duplicate copies.

Do not remove audit reports, provenance, split manifests or important thesis evidence just because they are not imported by Python.

# 34. MODEL CHECKPOINT SAFETY

Do NOT:

* retrain models;
* overwrite checkpoints;
* fabricate new weights;
* download unknown models;
* alter class mappings;
* convert checkpoints unnecessarily.

Preserve the existing expected Model 1 and Model 2 locations/environment overrides.

The application should fail gracefully when checkpoints are absent.

Add model SHA-256 calculation when available so sessions can record exactly which checkpoint was used.

# 35. REPRODUCIBILITY

Every inspection session should record enough information to reproduce its decision policy.

Record:

* Git commit hash where possible;
* Model 1 checkpoint SHA-256;
* Model 2 checkpoint SHA-256;
* model class mappings;
* image size;
* detector inference thresholds;
* grading thresholds;
* grading mode;
* part weights;
* grade margin;
* quality interval;
* ROI padding;
* tracker backend;
* camera settings;
* relevant preprocessing settings;
* grading config hash.

Do not hard-code fake Git/model hashes if unavailable.

Use null/unavailable explicitly.

# 36. CONFIG VERSIONING

Create one canonical serialized grading/session policy object.

Each session should have a configuration snapshot.

A fish event should reference the session/configuration under which it was produced.

Changing settings should start a new policy version/session rather than rewriting the meaning of earlier records.

# 37. FRONTEND UPDATES

Keep the existing frontend style/layout where possible.

Do not rewrite the entire UI unnecessarily.

Update terminology and functionality.

Settings should show:

Model 1

* detection threshold
* model/checkpoint
* device

Model 2

* detector threshold
* model/checkpoint
* quality interval
* ROI padding if operator-safe

Grading

* mode
* final verdict threshold
* minimum grade margin
* evidence coverage requirement
* read-only 50/30/20 weights unless deliberately configured

Camera

* actual camera
* resolution
* FPS
* supported controls

Display

* current overlays

Latest Inspection should show:

* Fish ID
* Final Grade or Ungraded
* Final Support
* Evidence Coverage
* Margin
* Reason Code(s)
* Body/Head/Tail evidence
* observation count

If Ungraded, explain WHY.

Do not display missing Tail as physical missing Tail.

# 38. ANALYTICS

Keep analytics honest.

Useful metrics:

* total fish;
* A/B/C/Rejected/Ungraded counts;
* graded coverage;
* Ungraded rate;
* average support;
* average evidence coverage;
* reason-code distribution;
* Model 2 observations/fish;
* processing latency;
* FPS.

Do not claim accuracy from live unlabeled conveyor data.

Accuracy requires ground truth.

# 39. OFFLINE FISH-LEVEL VALIDATION

Refactor `src/evaluation/fish_level_validation.py` so it uses the SAME fish-verdict policy as live runtime.

Offline replay should feed stored regional evidence into the same pure grading function.

Do not duplicate formulas.

Retain useful evaluation outputs:

* confusion matrix;
* per-class precision/recall/F1;
* automatic grading count;
* Ungraded count;
* selective coverage;
* selective accuracy;
* accuracy including abstention;
* reason-code counts;
* evidence coverage;
* B vs C confusion.

Do not automatically select a "winning" policy using the final test set.

# 40. ADD END-TO-END VALIDATION SUPPORT

Do not fabricate accuracy numbers.

Add tooling/interfaces for future labeled end-to-end evaluation.

The evaluation design should support:

Model 1 parent detection:

* precision
* recall
* AP50
* AP50:95

Counting:

* MAE
* RMSE
* signed bias
* exact-count rate
* within ±1

Model 2:

* per-class P/R/F1/AP

Fish-level:

* A/B/C/Rejected confusion
* macro F1
* per-class recall

Ungraded:

* abstention rate
* selective coverage
* selective accuracy
* accuracy-vs-coverage

Crowded/isolated subsets where labels exist.

Do not invent ground truth from Model 2 predictions.

# 41. TESTS — REQUIRED

Add or update automated tests.

At minimum add tests proving:

A. NO RENORMALIZATION

Body A=.82 only

Expected:
A weighted score=.41
coverage=.50

NOT:
A=.82

B. COMPLETE EVIDENCE

Body A=.82
Head A=.76
Tail A=.70

Expected:
A =
.82*.50 + .76*.30 + .70*.20
=.778

coverage=1.00

C. THRESHOLD

top=.45
final threshold=.50

Expected:
Ungraded
UG_LOW_GRADE_SUPPORT

D. MARGIN

A=.51
B=.50
minimum margin=.05

Expected:
Ungraded
UG_LOW_MARGIN

E. COVERAGE

Body only under strict mode

Expected:
Ungraded
UG_INSUFFICIENT_COVERAGE and/or UG_MISSING_PART_EVIDENCE

F. UNKNOWN IS NOT MISSING

Tail not observed

Expected:
physical_missing=null

Never auto-Rejected.

G. REJECTED COMPETES NORMALLY

Strong weighted Rejected evidence can produce Rejected through the same fish-level weighted policy.

H. RUNTIME / OFFLINE PARITY

Give identical evidence/config to:

live grading
and
offline replay

Assert all final fields match.

I. CONFIG VALIDATION

Meaningful unknown YAML keys cannot silently disappear.

J. TRACKING INVARIANT

A+B+C+Rejected+Ungraded == total fish.

K. LATE GRADE UPDATE

Changing one counted fish from Ungraded to a valid final grade moves its quality bucket without increasing total fish.

L. CAMERA PROPERTY MOCKS

Unsupported camera properties do not crash.

M. SETTINGS LOCK

Policy-changing settings cannot silently mutate active fish evidence.

N. DATABASE PERSISTENCE

Inspection history survives backend/service restart using SQLite.

O. EXPORT

CSV/XLSX values match stored database analysis.

# 42. KEEP EXISTING GOOD TRACKING TESTS

Preserve or improve tests covering:

* persistent identity;
* one count per crossing;
* simultaneous crossings;
* wrong direction;
* timeout;
* session reset;
* horizontal and vertical directions;
* duplicate crossing prevention;
* late quality corrections.

Do not break working tracking logic while refactoring grading.

# 43. NO NETWORK DEPENDENCY FOR NORMAL TESTS

The normal unit/integration test suite must not require:

* webcam;
* GPU;
* Roboflow API;
* internet;
* real model checkpoint.

Use mocks/fakes where appropriate.

Real-model and real-camera tests should remain optional smoke/integration tests.

# 44. DEPENDENCY CLEANUP

Audit Python requirements.

Create clearer dependency groups if appropriate:

* runtime;
* training;
* comparison/development.

Avoid relying on the huge unrelated environment dump in `requirements_actual.txt` as the deployable runtime specification.

Pin or constrain important runtime packages sufficiently for reproducibility, especially:

* ultralytics;
* FastAPI;
* OpenCV;
* numpy;
* pandas/openpyxl if exports need them.

Do not add unnecessary packages.

# 45. CI

Add a lightweight GitHub Actions workflow if the repo has none.

It should:

* install the normal test/runtime dependencies;
* run model-free tests;
* not require model checkpoints;
* not require GPU;
* not require camera;
* not require secrets.

# 46. README / DOCUMENTATION CLEANUP

Update README and technical docs so they describe the ACTUAL final architecture.

Remove stale claims such as:

* Ungraded not implemented;
* Fish IDs not implemented;
* video tracking is future work;
* weighted grading not implemented

if those capabilities are now implemented.

Clearly distinguish:

IMPLEMENTED
IMPLEMENTED BUT VALIDATION PENDING
EXPERIMENTAL
NOT IMPLEMENTED
NOT SUPPORTED BY CURRENT CHECKPOINTS

Document the known limitations honestly.

The main remaining scientific limitation should remain explicit:

There is not yet a locked independent end-to-end test using unseen physical fish and independent acquisition sessions.

Do not invent final thesis accuracy.

# 47. ARCHITECTURAL TARGET

After refactoring, the code organization should conceptually resemble:

src/
api/
app.py
camera.py
database.py
domain.py
export.py
image_analysis.py

inference/
yolo_fish_detector.py
yolo_quality_model.py
grading_engine.py
frame_quality.py
association.py
preprocessing.py

evaluation/
fish_level_validation.py
end_to_end_validation.py   # only if useful

configs/
grading_engine.yaml
camera.yaml or equivalent if useful

frontend/
index.html
app.js
styles.css

tests/
focused canonical tests

Exact filenames may differ if an existing structure is cleaner.

Do not reorganize merely for aesthetics.

# 48. PURE GRADING POLICY DESIGN

Prefer separating evidence aggregation from verdict policy.

For example:

FrameEvidence
→ TrackEvidence
→ AggregatedPartEvidence
→ FishGradingInput
→ FishVerdict

`FishVerdict` should contain at least:

fish_id
provisional_grade
final_grade
final_support
second_grade
second_support
grade_margin
weighted_scores
evidence_coverage
observed_regions
part_results
observation_count
reason_codes
explanation
override
color
grading_policy_snapshot

Keep it JSON serializable.

# 49. EXAMPLE FINAL DECISION ORDER

Implement the final fish verdict approximately in this order:

1. Validate parent evidence.

If parent unusable:
→ Ungraded / UG_PARENT_UNCERTAIN.

2. Validate association when applicable.

If ambiguous:
→ Ungraded / UG_ASSOCIATION_AMBIGUOUS.

3. Determine available/reliable part evidence.

Never infer physical absence from nondetection.

4. Calculate original evidence coverage.

Do NOT renormalize.

5. Check minimum required region count.

If insufficient:
→ Ungraded.

6. Check minimum coverage.

If insufficient:
→ Ungraded.

7. Check temporal evidence.

If insufficient:
→ Ungraded.

8. Calculate weighted:

A
B
C
Rejected

using fixed original 50/30/20 weights.

9. Find top and second scores.

10. Check final verdict threshold.

If too low:
→ Ungraded / UG_LOW_GRADE_SUPPORT.

11. Check grade margin.

If too small:
→ Ungraded / UG_LOW_MARGIN.

12. Apply a separately configured Rejected override only if explicitly enabled and validated.

13. Otherwise emit the top grade.

Reason:
GR_CONFIDENT
or RJ_GRADE_EVIDENCE.

# 50. VERY IMPORTANT — DO NOT "FIX" THIS BY MAKING THE SYSTEM MORE CERTAIN

The goal is NOT to maximize how often the system produces a grade.

The system must be allowed to say:

Ungraded

when evidence is incomplete or unreliable.

Do not reduce Ungraded cases merely for presentation.

The correct behavior is:

uncertain evidence
→ explicit uncertainty

not:

uncertain evidence
→ forced grade.

# 51. CLEANUP RULE

At the end, there should be ONE obvious active system.

Remove dead duplicate implementations and stale placeholders, but do not delete scientific evidence or valuable datasets simply because they are not imported by Python.

Before deletion, confirm each candidate is:

* not imported;
* not executed;
* not referenced by active config;
* not needed by tests;
* not needed as unique thesis evidence;
* not the only copy of valuable data.

Update all references after deletion.

# 52. FINAL VERIFICATION

After implementing everything:

1. Run all model-free unit/integration tests.
2. Fix failures rather than weakening tests.
3. Run static/import checks sufficient to catch broken imports.
4. Verify FastAPI can initialize without actual model files and reports them unavailable cleanly.
5. Verify database initialization.
6. Verify CSV/XLSX export tests.
7. Verify no remaining import references point to deleted files.
8. Search repository for stale references to removed architectures.
9. Search for `minimum_final_score` and make sure there is no conflicting live policy.
10. Search for renormalization logic in grading and ensure unavailable part weights are not redistributed.
11. Search for unsupported defect claims.
12. Verify runtime/offline grading parity tests pass.
13. Verify README accurately matches the resulting architecture.

# 53. DELIVERABLE AT THE END

Do the implementation, then provide a concise final report containing:

* files changed;
* files deleted;
* architecture that remains;
* grading inconsistencies fixed;
* camera features added;
* persistence changes;
* configuration changes;
* tests added/updated;
* test results;
* any item that could not be completed;
* any remaining scientifically unvalidated assumptions.

Do not claim completion for anything that was not actually implemented.

Do not fabricate model performance.

Do not retrain or replace the model checkpoints.

The final repository should be simpler, internally consistent, testable, reproducible, conservative about uncertainty, and clearly aligned with the actual capabilities of Model 1 and Model 2.
