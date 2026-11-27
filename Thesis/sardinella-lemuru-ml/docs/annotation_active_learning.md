# Verified review and annotation learning

The existing dashboard's **Review Queue** now includes annotation review above
the existing fish-grade review. Add local images, inspect the masks and labels,
then **Approve**, **Edit**, or **Decline**. Shortcuts are A, E, and D when focus
is outside an input or editor. Approve accepts the complete displayed set and
advances after its durable save. Edit stays on the same screen; it supports
individual class/ownership corrections, polygon vertices, missing parts, and
removal. **Save verified edits** saves and verifies the complete corrected set
in one transaction. Decline preserves images, labels, revision history, and an
optional reason, while excluding the current result from positive learning.

This integrates with the shared annotation library and existing automation.
The sole canonical annotation database is
`dataset/annotation_workspace/annotations.sqlite3` (or `FISH_ANNOTATION_ROOT`).
The learning adapter stores no second copy of annotation truth. It adds small
feedback metadata, model/run records, and immutable training artifacts beside
that database. Existing camera grading and inspection history remain separate
from annotation-model selection.

## What is implemented

1. **Immediate verified feedback.** Original automated predictions, subsequent
   human edits, complete-set approvals, declines, original manual COCO bytes,
   source IDs, images, and native masks remain versioned. Revision checks reject
   stale requests. A failed review audit rolls back the labels and approval.
   Difference reports identify class changes, mask boundaries, missing masks,
   missing/extra/duplicate annotations, and fish ownership changes. Removing an
   extra object does not automatically call it a duplicate.
2. **Verified reference retrieval.** Color histograms, low-resolution appearance,
   and mask geometry rank prior verified *training* examples. References use
   the selected baseline and subsequent verified feedback, with a cache
   invalidated by source/label revisions. Declined, unverified, quarantined,
   secondary-dataset, validation, and test examples
   cannot supply positive context. The image itself is excluded. Context is
   attached to subsequent predictions as evidence and uncertainty warnings.
   Strong class suggestions need three independent source groups and strict
   similarity/agreement checks. Class rewrites are disabled by default. No
   mask is copied, stretched, or invented from another fish.
   Bounded crop descriptors are indexed in the background and cached in the
   same database. Prediction continues with an explicit uncertainty message
   while indexing runs. Cached features contain no replacement annotation truth;
   the full-resolution source masks stay unchanged.
3. **Controlled batch learning.** Background maintenance checks accumulated
   feedback once per minute and after reviews. Defaults require 25 new verified
   images **and 25 independent source groups**, with a 24-hour cooldown. It does
   not retrain after every approval. Restarts recover abandoned jobs after
   confirming their worker process has exited; they never promote unfinished
   candidates. A running job does not hold the reference/status lock while
   fitting a model.
4. **Local candidate fitting and evaluation.** A versioned YOLO segmentation
   dataset records exact source revisions, class mapping, image/pixel/label
   hashes, validation fingerprint, exclusions, and a lossless source-annotation
   snapshot. Dataset integrity is checked before and after training/evaluation.
   Both models use the same immutable validation set. The real local trainer
   fine-tunes the existing auxiliary segmentation checkpoint; it downloads no
   new model and uses CPU FP32 by default.
5. **Gated deployment and rollback.** Candidates need at least +0.005 absolute
   segmentation mAP50–95 and no regression in any reported aggregate/per-class
   metric. Missing, nonfinite, or mismatched metrics cannot promote a model.
   Evaluation must cover all 12 trained classes. Original and accepted model
   checkpoints remain checksummed and available for rollback; rejected models
   cannot be selected through rollback. Promotion affects annotation only.

The annotation incumbent is the existing local 12-class `exp-4.pt` segmentation
model, preserved before use. Original and promoted versions both plug into the
existing annotation engine, retaining Model 1 detection, part association, and
mask uncertainty checks. Comparing a candidate against that same incumbent
avoids claiming improvement over an unrelated model. If no compatible local
annotation checkpoint exists, the existing detector path remains available and
training is unavailable. Predictions record the model actually used, including
fallbacks, separately from reference evidence and model-management state.

## Ground truth safeguards

- The user-selected primary baseline is **Fish_Annotations_Cleaned.zip**,
  dataset `fish-annotations-cleaned-dbf50ab47c1d`. The canonical importer preserves
  the ZIP, original COCO JSON, provenance, category IDs, and annotation bytes.
  The 910-image V2 COCO v7 dataset remains separately accessible and supplies
  neither default learning examples nor default reference context. New approved
  feedback joins the selected baseline; old secondary records are not moved.
  Importing, failed, or incomplete primary profiles hold learning without
  silently falling back to the secondary baseline. Original files remain read
  only and import errors are surfaced.
- Original COCO category IDs stay stable. The adapter maps by the immutable
  source name to the existing model's IDs 0–11; custom or inconsistent mappings
  cannot enter that model's training set.
- Explicit source aliases map `Class_C_Body`, `Class_C_Head`, and `Class_C_Tail`
  to existing model IDs 6, 7, and 8 (canonical registry IDs 7, 8, and 9).
  Their displayed source names remain `Class_C_*`; immutable model semantics
  retain `Grade_C_*`. No numeric category-ID guessing is used.
- The baseline has no fish ownership IDs. Its anatomical parts remain unassigned;
  the system does not fabricate whole-fish relationships.
- Duplicate detection compares decoded image pixels and class/mask pixels,
  rather than encoded image bytes or polygon-versus-RLE JSON. Equivalent copies
  are one example. Contradictory feedback copies are quarantined; a feedback
  copy cannot displace permanent manual truth.
- Source groups and image identities belonging to validation or test reserve
  that identity against training feedback. Existing splits are preserved.
  Primary capture/near-duplicate groups use the importer's leakage-group and
  protected-split metadata. A training member of a held-out group cannot enter
  training or reference context. Corrections to a manual baseline stay
  identifiable; explicit approvals can version corrected training labels while
  evaluation snapshots retain their original labels. Evaluation feedback never
  silently rewrites the holdout. Unknown manual splits remain unassigned.
- COCO RLE, holes, and disconnected masks remain lossless. Class-only edits
  preserve their exact segmentation. Redrawing an entire complex mask is an
  explicit edit. A YOLO export excludes incompatible *training* masks with a
  recorded reason; an incompatible validation mask blocks model evaluation.
- Empty/degenerate masks and drafts containing only bounding boxes cannot be
  approved through the review interface.

## Actual baseline limitations

The selected ZIP contains **345 images and 4,867 part annotations**, with 11
source categories. Its provenance declares 277 training, 45 validation, and 23
test images. Eight near-duplicate pairs form 337 independent groups. Two pairs
cross training/test, so their two training members are held out of positive
training/reference use; source split metadata is preserved. No new split is
invented to fill gaps.

The entire primary baseline has **zero `Grade_B_Tail` examples**, only two
`Grade_B_Body`, one `Grade_B_Head`, and eight `Class_C_*` annotations. The
immutable validation set therefore cannot cover all 12 existing model classes.
Automatic candidate training/promotion stays blocked and reports the exact
missing coverage. A protocol-approved validation extension is required before
automatic deployment can establish performance for all trained classes.
The imported validation images currently cover only the three Grade A classes;
Grade B, Class C, and Rejected parts have no validation support.

The retained secondary V2 dataset contains 910 images and 9,723 annotations
(861 training, 32 validation, 17 test). Most of those masks are rectangles;
its validation split lacks `Grade_B_Body` and `Grade_B_Head`. Those historical
findings are not measurements of the selected primary baseline. Structural mask
fidelity and user-designated manual labels do not independently establish
whole-fish ownership or anatomical boundary accuracy.

Reference retrieval and accumulation work now. There is **no measured reduction
in real human corrections yet**, and no production model improvement is claimed.
Immediate context does not autonomously improve mask boundaries; verified masks
can improve model weights only through the evaluated batch path.

The coordinated five-scene primary diagnostic matched anatomical regions on
24/24 parts but quality grades on 0/24. The existing SAM fallback was then
reused for filled rectangular native part masks: on the same 22 matched masks,
mean pixel IoU increased from 0.540535 to 0.772807, with no quality-grade
improvement. This is a small paired diagnostic of a mask-processing fix;
weights and confidence thresholds were unchanged. It is not evidence of
feedback-driven model learning or a measured reduction in human corrections.

## Measurements and small status display

The indicator reports verified examples, recorded corrections, the deployed
annotation version, new data awaiting training, baseline indexing, evaluation
status, and any validation block. Optional details show the percentage approved
without editing, corrected masks/classes, decline rate, and measured review time.

“Approved without editing” uses distinct reviewed image pixels, including
declines in the denominator, and compares the final verified set against the
original prediction set. Quarantined duplicate/contradictory copies do not inflate
the result. Review precision/recall, class accuracy, mask IoU, and missing-part
rates describe stable-object differences against complete human-reviewed sets.
They are not held-out model accuracy. Model evaluation metrics are recorded
separately. Unavailable measurements remain null/“Not measured.”

## Acceptance evidence

Focused command (89 passed):

```powershell
py -m pytest -q tests/test_annotation_review.py tests/test_annotation_learning.py tests/test_annotation_review_ui.py tests/test_annotation_ground_truth_safety.py tests/test_annotation_feedback.py --basetemp results/qa/task3-primary-final-r4
```

| Requested acceptance | Evidence |
|---|---|
| Approve correct image | Canonical-store HTTP test; complete set verified, next pending image returned |
| Edit class | Only targeted class changes; source prediction remains in history |
| Edit segmentation | Pixel differences counted; atomic verified revision |
| Add missing anatomy | New Tail mask accepted and reported as missing annotation |
| Decline unusable image | Labels excluded from verified pool; image and reason retained |
| Restart persistence | New canonical-store instance reopens decisions and immutable originals |
| Approved result enters pool | Same SQLite, positive pool and pending training count checked |
| Declined result excluded | Positive examples and pending training remain empty |
| Subsequent image uses history | Earlier verified result appears in the next prediction's context |
| References affect evidence | Executed retrieval/suggestion tests; no mask copying or default class rewriting |
| Sufficient feedback schedules candidate | Threshold/cooldown/concurrent-job tests with a controlled trainer |
| Train/evaluate real candidate | Actual CPU one-epoch isolated smoke using the secondary V2 dataset: two real training images, all 32 established validation images |
| Compare and reject worse candidate | Same validation snapshot for both models; fake-adapter gate tests plus actual regression rejected |
| Preserve original dataset | Original COCO hashes and checkpoint hashes unchanged; original revisions retained |

The actual selected default workspace also passed the pool/reference check:
345 primary images and 910 retained secondary images; 343 eligible verified
examples comprising 275 training, 45 validation, and 23 test images. The two
training members of test groups are reserved. Five retrieved references all
belong to eligible primary training images, and the prediction-context path
receives them. All canonical labels/revisions, the original ZIP and V2 source
COCO files, and the deployed checkpoint remained unchanged. This check made
no approvals and performed no production training. Approval-rate improvement
remains unmeasured. Evidence:
`results/qa/task3_primary_baseline_learning.json`.

Other tested safeguards include failed-audit rollback, stale revisions, complete
complex masks, decoded duplicates, contradictory labels, protected holdout groups,
independent-group thresholds, snapshot tampering, incompatible class mappings,
invalid metrics, rejected-model rollback refusal, and interrupted-job recovery.
Existing learning schemas can reopen while an independent SQLite writer owns
the database. Maintenance retries setup after temporary contention and notices
when a primary import completes without needing an application restart.
Reference validation checks exact uncompressed COCO run dimensions, integer
counts, complete extent, and nonempty foreground without allocating a native
bitmap for each historical part. Invalid/empty runs remain excluded; actual
training and export decode the original masks when required.
Model selection and the completed evaluation audit also commit atomically;
a failed evaluation-audit write cannot deploy a candidate.
Reapproving identical labels or editing metadata does not count as new training
data. Feedback waits for completion of the original baseline identity index;
custom classes outside the fixed model mapping remain saved without silently
becoming incomplete training labels. Explicit image dataset/group associations
are retained.
The JavaScript review tests execute the controller using Node, covering keyboard
shortcuts, native coordinates, saves, failures, and next-image behavior.

The earlier coordinated repository regression passed 2,664 tests with 12 skips
and 127 subtests (`results/qa/annotation_workflow/final_regression.xml`). The
latest boundary/capture run passed 2,752 tests and 127 subtests, with 12 skips
and one failure: Windows Application Control blocked the existing Matplotlib
`_image` DLL in `test_bc_color_experiment`. A direct import reproduced that
environment restriction; security settings and unrelated source were not
changed (`results/qa/annotation_workflow/final_boundary_capture_regression.log`).
Latest Task 3 changes passed the focused suite above.

Actual training smoke:

```powershell
py tests/annotation_learning_smoke.py --output results/qa/task3_real_learning_20261125_r3
```

This deliberately tiny 64-pixel, one-epoch CPU check proves fitting, dataset
export, paired evaluation, checkpoint preservation, and rejection execute. Its
QA-only incomplete-validation option is permanently ineligible for promotion.
It is **not an accuracy benchmark** or a production training run. The candidate
regressed and was rejected. Reports, manifests, and weights remain under the
ignored `results/qa/` directory. The production selection was not changed.

## Integration files

- `src/api/annotation_review.py`: review routes, atomic decisions, baseline
  bootstrap, maintenance, annotation model adapter, contextual references.
- `src/api/annotation_store.py`: read-only learning projection of canonical
  documents, pixel identity, split isolation, and derived progress.
- `src/api/annotation_feedback.py`: measured object-level differences.
- `src/annotation_learning.py`: references, versioned datasets, controlled fitting,
  evaluation gate, model history, and rollback.
- `frontend/annotation-review.js` and `.css`: isolated review controls and editor.
- `src/api/app.py` and `frontend/index.html`: small integration hooks.

Primary review APIs are `GET /api/annotations/pending`,
`GET /api/annotations/{image_id}`, `POST /api/annotations/{image_id}/review`
with `action` and `revision`, and `GET /api/annotations/learning/status`.
`POST /api/annotations/learning/rollback` selects a preserved accepted version.
These reuse the application's existing local/LAN access policy. Ordinary
annotation needs no training controls or parameter selection.
