Continue from the current stabilized repository state.

DO NOT perform another architecture refactor.

DO NOT modify model weights, confidence thresholds, grading thresholds,
Body/Head/Tail weights, temporal rules, association policy, or grading
policy during this task.

The purpose of this task is to prepare the system for a scientifically
defensible independent conveyor-belt validation study.

=========================================================
CURRENT VERIFIED STATE
=========================================================

Software stabilization has already been completed.

Verified:

- 240 tests passed
- 3 skipped
- Python compilation passes
- FastAPI startup passes
- Camera hardware works
- HP Wide Vision HD Camera was successfully captured at 640x480
- Both local Model 1 and Model 2 load successfully on CPU
- Model 1 smoke test:
  12/12 test images returned detections
- Conservative full-frame association tests pass
- Real two-model static smoke test:
  10 ambiguous observations remained Ungraded
- Production and research-only paths are separated
- Fixed grading weights remain:
    Body = 50%
    Head = 30%
    Tail = 20%
- Missing evidence is NOT renormalized
- Duplicate part candidates are not silently combined
- No threshold optimization has occurred
- No model retraining has occurred

Current Model 2 compatibility result:

Precision = 0.8454
Recall = 0.8297
mAP50 = 0.8147

BUT THESE ARE NOT INDEPENDENT VALIDATION RESULTS.

Data audit found source-group overlap:

109 / 115 validation images overlap training source groups
102 / 115 test images overlap training source groups

Therefore these metrics must remain explicitly labeled:

NON-INDEPENDENT COMPATIBILITY RESULTS

They must NEVER be presented as final validated Model 2 performance.

=========================================================
PRIMARY OBJECTIVE
=========================================================

Prepare a reproducible independent validation workflow for:

1. Camera/acquisition validation
2. Model 1 validation
3. Model 2 validation
4. Body/Head/Tail association validation
5. Tracking validation
6. End-to-end grading validation

The workflow must work with FUTURE unseen data.

Do NOT fabricate data.

Do NOT manufacture independent metrics from the existing contaminated
split.

=========================================================
1. PRESERVE CURRENT SYSTEM BEHAVIOR
=========================================================

Treat the current production runtime as frozen unless a genuine bug is
discovered.

Do not modify:

- grading weights
- grading thresholds
- detector thresholds
- temporal rules
- coverage gates
- margin gates
- Ungraded logic
- association rules
- rejection logic
- HSV grading behavior
- model checkpoints

This task is measurement infrastructure, not optimization.

=========================================================
2. DATA INDEPENDENCE MUST BE ENFORCED
=========================================================

Create a proper data-grouping strategy.

Images must not be considered independent merely because filenames differ.

Where possible, group samples by their physical/acquisition origin.

Potential group identifiers include:

- original video
- recording session
- camera session
- physical fish
- image burst
- source folder
- augmentation parent
- original source image

Derived/augmented images originating from the same original sample must
stay in the SAME split.

Never allow:

original image -> training

while augmented/cropped/modified version of that same source appears in:

validation or test.

=========================================================
3. CREATE A DATA LEAKAGE AUDITOR
=========================================================

Add a research-only command/tool that audits dataset independence.

It should detect where possible:

- identical files
- identical hashes
- duplicate filenames
- renamed duplicates
- known augmentation-parent relationships
- same source-group membership
- suspicious near duplicates

The tool should output something like:

DATASET INDEPENDENCE AUDIT

Train groups: ...
Validation groups: ...
Test groups: ...

Train ↔ Validation overlap: ...
Train ↔ Test overlap: ...
Validation ↔ Test overlap: ...

Independent validation:
PASS / FAIL

Independent test:
PASS / FAIL

If overlap exists:

FINAL PERFORMANCE CERTIFICATION = BLOCKED

Do not automatically delete or move data.

Only report the problem.

=========================================================
4. ADD GROUP-AWARE SPLIT SUPPORT
=========================================================

If dataset metadata supports it, add a RESEARCH-ONLY utility capable of
creating group-aware split manifests.

Example:

train_manifest.csv
validation_manifest.csv
test_manifest.csv

Each record should include:

sample_id
source_group_id
image_path
annotation_path
class information
split
original_source if known

IMPORTANT:

Do not automatically replace the current dataset.

The utility should create a proposed manifest for review.

=========================================================
5. FUTURE INDEPENDENT DATASET
=========================================================

Prepare the project for a future locked independent test dataset.

This dataset must contain:

- previously unseen physical fish where possible
- newly captured acquisition sessions
- production-like conveyor conditions
- no frames used during model training
- no augmented derivatives of training samples
- no threshold-tuning samples

Recommended logical structure:

datasets/
    development/
    validation_independent/
    test_locked/

Do not create fake images to populate these directories.

Empty directory structures/readmes are acceptable.

=========================================================
6. CAMERA CALIBRATION MUST OCCUR BEFORE DATA COLLECTION
=========================================================

The camera is functioning, but calibration is incomplete.

Add or verify a formal calibration workflow.

Operator must establish:

- camera device
- resolution
- camera height
- camera angle
- conveyor position
- lighting position
- exposure
- gain
- brightness
- contrast
- white balance
- focus

where supported.

After adjustment, allow:

SAVE INSPECTION CAMERA PROFILE

Store:

camera device identity
backend
capture resolution
processing resolution
FPS
actual hardware values
unsupported properties
timestamp

Do not mark calibration complete automatically.

Require explicit operator confirmation.

=========================================================
7. REFERENCE SCENE
=========================================================

Support recording a calibration reference scene.

The reference should contain:

- empty conveyor frame
- optional representative dried fish frame

Store image statistics such as:

background mean brightness
background median brightness
background standard deviation
fish/background contrast if fish exists
HSV statistics if appropriate

These statistics are for acquisition monitoring only.

They must NEVER directly determine grade.

=========================================================
8. CAMERA CONDITION LOCK
=========================================================

After the operator saves the final profile:

mark:

CAMERA PROFILE = LOCKED

During validation sessions detect changes such as:

- exposure changed
- camera resolution changed
- camera disconnected/reconnected
- background brightness significantly changed
- white balance setting changed
- profile cannot be reproduced

Record warnings.

Do not silently adjust grade.

=========================================================
9. MODEL 1 INDEPENDENT VALIDATION
=========================================================

Prepare evaluation infrastructure for Model 1.

Do NOT use the current 12-image smoke test as performance validation.

For independent data calculate:

TP
FP
FN

and appropriate detection metrics.

Also track operational measures:

physical fish presented
physical fish detected
missed physical fish
duplicate detections
track creation failures

Report:

fish detection rate
miss rate
duplicate detection rate

If ground-truth boxes exist, also calculate standard detector metrics.

=========================================================
10. MODEL 2 INDEPENDENT VALIDATION
=========================================================

Prepare evaluation for:

Body
Head
Tail

per class where applicable.

Calculate:

Precision
Recall
F1
mAP50
mAP50-95 if supported

per Body/Head/Tail class and overall.

Most importantly:

do not calculate these as "independent" unless the dataset audit passes.

Attach:

dataset_manifest_hash
model_hash
evaluation_timestamp

to every report.

=========================================================
11. ASSOCIATION VALIDATION
=========================================================

Model detection quality and association quality must be evaluated
separately.

Measure:

correct part assigned to correct fish
wrong fish assignment
duplicate candidate
unassigned candidate
ambiguous candidate
part outside fish ROI

Produce:

association_accuracy
wrong_assignment_rate
ambiguous_rate
unassigned_rate

Do not hide ambiguous cases.

=========================================================
12. TRACKING VALIDATION
=========================================================

For real conveyor sessions measure:

physical fish count
system track count
track fragmentation
ID switches
duplicate tracks
missed tracks

Do not assume one track automatically equals one physical fish.

Provide a simple manual ground-truth annotation mechanism if one already
fits the architecture.

=========================================================
13. END-TO-END VALIDATION
=========================================================

Prepare a locked study mode.

For each physical fish record:

study_sample_id
session_id
system_fish_id
ground_truth_grade
system_grade
Ungraded reason
Body evidence
Head evidence
Tail evidence
camera profile
model versions
configuration version

Ground truth must be entered independently.

Do not infer ground truth from model output.

=========================================================
14. BLIND LABELING SUPPORT
=========================================================

Where practical, make the ground-truth labeling workflow independent
from the model result.

Preferred workflow:

1. assign sample ID
2. human evaluator records reference grade
3. reference grade is stored
4. system prediction is evaluated later

Avoid presenting the system prediction to the person before they provide
the reference grade, if practical.

=========================================================
15. END-TO-END METRICS
=========================================================

When real independent labels exist, calculate:

confusion matrix

per-class:
precision
recall
F1

overall:
accuracy
macro F1
weighted F1

also separately report:

Ungraded count
Ungraded rate
Model 1 misses
Model 2 insufficient-evidence cases
association failures

DO NOT silently exclude Ungraded samples.

Report metrics both where scientifically appropriate, for example:

A. all presented samples
B. gradeable samples

but clearly state the denominator for every metric.

=========================================================
16. DO NOT TREAT UNGRADED AS A BUG
=========================================================

The current conservative system intentionally produced:

10 / 10 ambiguous observations -> Ungraded

during the static two-model smoke test.

Preserve this behavior.

An ambiguous fish should remain Ungraded rather than receiving a
fabricated confident grade.

Future validation should measure:

Ungraded rate

and analyze why those cases occur.

=========================================================
17. FORMAL FAILURE CATEGORIES
=========================================================

For independent studies categorize failures as:

MODEL1_MISS
MODEL1_FALSE_POSITIVE
TRACK_FRAGMENTATION
TRACK_ID_SWITCH
MODEL2_BODY_MISS
MODEL2_HEAD_MISS
MODEL2_TAIL_MISS
PART_ASSOCIATION_AMBIGUOUS
PART_WRONG_FISH
INSUFFICIENT_TEMPORAL_EVIDENCE
LOW_CONFIDENCE
GRADE_DISAGREEMENT
CAMERA_CONDITION_INVALID

Preserve existing formal Ungraded reason codes where appropriate.

=========================================================
18. VALIDATION SESSION LOCKING
=========================================================

Once a formal validation session begins:

snapshot:

camera profile
Model 1 hash
Model 2 hash
grading policy version
thresholds
weights
Model 2 interval
ROI padding
processing resolution

After the session starts, changing any of these should:

either

A. be blocked

or

B. terminate the validation session and require a new one.

Never allow settings to change halfway through a study unnoticed.

=========================================================
19. VALIDATION MANIFEST
=========================================================

Every formal study should generate a machine-readable manifest.

Example:

validation_manifest.json

containing:

study ID
date/time
dataset ID
dataset manifest hash
camera profile ID
camera settings
Model 1 hash
Model 2 hash
grading configuration hash
application commit hash
sample count
operator-supplied notes

This is important for thesis reproducibility.

=========================================================
20. RECORD GIT COMMIT
=========================================================

When a validation session begins, record the current Git commit SHA if
available.

Do NOT require a clean Git state to run normal production inspection.

For research validation:

if repository has uncommitted changes, show:

RESEARCH VALIDATION WARNING:
Working tree contains uncommitted modifications.

Allow operator to cancel or explicitly continue.

Record that state in the manifest.

=========================================================
21. CERTIFICATION GATES
=========================================================

Implement a read-only validation-readiness checklist.

Example:

SOFTWARE
✓ regression suite passes

CAMERA
✗ inspection profile not calibrated

MODEL 1
✗ independent validation not completed

MODEL 2
✗ independent validation dataset not available

DATASET
✗ existing validation/test split has source-group leakage

END-TO-END
✗ locked unseen-fish study not completed

FINAL CERTIFICATION
BLOCKED

Do not provide a fake percentage score.

Use explicit pass/fail/not-tested states.

=========================================================
22. CURRENT METRIC LABELING
=========================================================

The following existing Model 2 result:

P = 0.8454
R = 0.8297
mAP50 = 0.8147

must be displayed only as:

NON-INDEPENDENT COMPATIBILITY METRICS

Reason:

109 / 115 validation samples overlap training source groups
102 / 115 test samples overlap training source groups

Do not label these as:

final accuracy
validated performance
independent test performance
production accuracy

=========================================================
23. PRESERVE EXISTING EVIDENCE
=========================================================

Do not delete:

results/stabilization/
model2_validation/
val_metrics.json
existing datasets
existing split files
existing compatibility results

They are still useful as historical development evidence.

Instead clearly label their limitations.

=========================================================
24. REPORT GENERATION
=========================================================

Add or improve a research report generator capable of producing:

STUDY SUMMARY

Software version
Camera profile
Model versions
Dataset independence result
Sample counts
Model 1 results
Model 2 results
Association results
Tracking results
End-to-end results
Ungraded analysis
Known limitations

Reports must distinguish:

COMPATIBILITY TEST
DEVELOPMENT VALIDATION
INDEPENDENT VALIDATION
LOCKED TEST

=========================================================
25. NO PERFORMANCE CLAIM WITHOUT GATE
=========================================================

Add a safeguard in research reporting.

Before using wording such as:

"independent test performance"

verify:

dataset independence audit = PASS

Otherwise use:

"development/compatibility result"

This is reporting protection only.

Do not interfere with normal production inspection.

=========================================================
26. KEEP RESEARCH AND PRODUCTION SEPARATE
=========================================================

Do not make research labels or ground-truth fields part of normal
production decisions.

Production:

camera
→ detection
→ tracking
→ Model 2
→ grading policy
→ inspection result

Research:

production result
+
independent ground truth
→ evaluator
→ metrics/report

Ground truth must NEVER feed back into the production prediction during
the same evaluation.

=========================================================
27. TESTS
=========================================================

Add model-free tests covering:

source-group leakage detection
duplicate source detection
group-aware manifest generation
certification blocked on dataset leakage
certification blocked without camera calibration
locked validation configuration
manifest creation
model/config hashes
Ungraded included in study counts
ground truth does not affect production prediction
current compatibility metrics cannot be mislabeled as independent

Preserve all existing tests.

=========================================================
28. DO NOT RETRAIN
=========================================================

This task must NOT:

- retrain Model 1
- retrain Model 2
- download new checkpoints
- tune hyperparameters
- optimize thresholds
- change 50/30/20 weights
- adjust class balance
- modify grading policy

If the new independent study later shows problems, tuning/retraining will
be a separate future task using DEVELOPMENT data only.

=========================================================
29. FINAL OUTPUT
=========================================================

After completing the validation-readiness work, provide:

1. Files changed
2. Tests added
3. Full regression test result
4. Dataset leakage audit result
5. Current camera calibration status
6. Model 1 validation status
7. Model 2 validation status
8. Association validation status
9. Tracking validation status
10. End-to-end study status
11. Certification blockers
12. Exact data that must be collected next

Do not claim the system is validated.

The expected final state at this stage is likely:

SOFTWARE VERIFICATION: PASS
CAMERA CALIBRATION: PENDING
INDEPENDENT MODEL VALIDATION: PENDING
END-TO-END VALIDATION: PENDING
FINAL CERTIFICATION: BLOCKED

That is an acceptable and scientifically correct result.

=========================================================
CRITICAL PRINCIPLE
=========================================================

Do not try to make the numbers look better.

The objective is to make future numbers trustworthy.