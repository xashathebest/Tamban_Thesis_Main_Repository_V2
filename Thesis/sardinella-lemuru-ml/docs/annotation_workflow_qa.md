# Local annotation workflow: implementation and QA

The annotation workspace is available at `/annotations`. The V2 application is
served locally at `http://127.0.0.1:8001/annotations`. Upload/select an image,
choose **Auto-Annotate**, review the masks, correct individual objects if needed,
and approve the image. Saved corrections and approvals remain local. The
existing live inspection and grading application remains available.

## Baseline selected by the user

The primary source is
`C:/Users/User/Downloads/Tamban_Thesis_Main_Repository/Fish_Annotations_Cleaned.zip`.
Its SHA-256 is
`dbf50ab47c1d791860116d9c103124333f7e647d1f08bb6476b677202a31ca4e`.
It contains 345 images at 3840 x 2160 and 4,867 anatomical segmentation labels.
The source provenance records 277 training, 45 validation, and 23 test images.
These original assignments remain recorded. Declared near duplicates and
capture variants are grouped transitively; groups that contain holdout images
remain protected from training and reference retrieval.
Two declared near-duplicate pairs cross the original training/test boundary.
Their protected organization is 275 training, 45 validation and 25 test images;
the original 277/45/23 assignments remain in provenance.

The original V2 v7 COCO dataset (910 images, 9,723 annotations) remains a
secondary collection. Its original documents and revisions are retained. The
library defaults to the selected primary dataset; the dataset selector exposes
the secondary collection and an explicit combined library view. Training exports
require a single selected collection rather than silently mixing both sources.

Original COCO category IDs differ between these sources. Import uses explicit
semantic mappings. The primary `Class_C_Body/Head/Tail` labels map to the existing
model's immutable `Grade_C_Body/Head/Tail` class IDs; original source names and
category IDs remain attached to every imported label. Anatomical class, part
quality, whole-fish association, and rejected review status remain separate.

Neither source supplies verified whole-fish identities or part-to-fish parent
IDs. Imported parts remain unassigned until a reviewer supplies an association.
The source's absence of a label does not establish physical absence of anatomy.

## Problems found and changes made

The original application provided image analysis, detection, grading and mask
previews. Preview overlays were temporary and did not constitute an editable,
persistently saved training dataset. Its inspection review controls did not
offer complete anatomical mask editing, versioned per-object review, class
management, or COCO/YOLO dataset export. Different category/model ID conventions
could also cause incorrect labels if numeric IDs were assumed interchangeable.

The implementation reuses the existing detector, segmentation adapter,
MobileSAM service, conservative anatomical association, FastAPI application and
static frontend. The annotation path uses the existing auxiliary segmentation
checkpoint while preserving the live grading model. Detector thresholds and
original checkpoints have not been reduced or overwritten.

Generated objects carry real, full-resolution COCO RLE pixel masks and exact PNG
masks. Valid nonrectangular native model masks are preserved. Real-photo QA found
filled rectangular native part predictions: these now request boundaries from
the existing SAM service, using the same image embedding. Original native outputs
remain in prediction metadata. Failed replacements remain incomplete candidates.
SAM candidates are checked for frame,
parent and coordinate provenance; missing/invalid segmentation stays unreviewed.
Bounding boxes are never substituted for masks. Ambiguous ownership, duplicate
candidates, overlap, missing parts and low confidence are visible review signals.
Missing detections are reported as undetected rather than invented anatomy.

The library provides clickable colored overlays, selected-object class and
parent editing, polygon/vertex boundary editing, add/delete, undo/redo,
individual approve/reject, whole-image review, autosave, history and recovery.
Central class configuration supports adding and renaming classes and removing
unused user classes. Reserved source/model classes retain stable mappings.

Saving is revision checked and transactional. Stale edits fail visibly rather
than overwrite a newer decision. Automatic annotation cannot replace existing
manual or reviewed objects. Source metadata and manual provenance cannot be
forged by a client. Editing an approved label creates a correction revision.

## Simplifications

The primary annotation screen groups upload, automation, review and saving in
one workspace. Detailed class management and training export are collapsed.
Camera controls, metrology, crack diagnostics and live-grade settings do not
occupy the annotation workflow. Existing working inspection features remain in
their existing screen. Review buttons act directly without repeated confirmation
dialogs. Different dataset sources use one persistence layer and one class
registry rather than competing annotation databases.

## Persistence and source protection

Default accessible data folder:
`dataset/annotation_workspace/` beneath this project. `FISH_ANNOTATION_ROOT` can
select another local folder for all annotation adapters together.

- `annotations.sqlite3`: authoritative documents, revisions, imports, classes,
  dataset registry and review state, with SQLite WAL and full synchronization.
- `images/`: immutable original image bytes.
- `pixels/`: immutable lossless original-resolution image pixels.
- `masks/`: content-addressed exact instance PNG masks.
- `baselines/`: original ZIP, raw COCO, provenance and cleaning metadata, plus
  training-only reference descriptors.
- `revisions/`: immutable JSON snapshots for audit and recovery.
- `exports/`: validated dataset ZIP files.

The original external ZIP and original V2 COCO directories are read only.
Content hashes, immutable artifact publication, idempotent import keys and
revision checks protect against accidental replacement and duplicate saves.
Browser recovery drafts supplement durable server data; they are not verified
training labels. Simulated approvals used for QA live in isolated test folders.

## Export and training readiness

The class/training panel validates reviewed images before creating COCO,
YOLO detection or YOLO segmentation ZIP files. Exports include images, original
image bytes, exact PNG masks, class mappings, saved revisions, confidence and
association metadata, and a validation manifest. Only approved or imported manual
labels enter canonical training exports. Rejected objects are excluded; a
`Rejected_*` quality class remains a valid anatomical label.

COCO preserves holes and disconnected mask components losslessly. YOLO detection
uses mask-derived boxes. YOLO segmentation accepts masks that can be represented
by a single exact polygon; it refuses masks with incompatible holes/islands
rather than silently losing pixels. The library also offers versioned annotation
JSON and packages for local interchange and recovery.

The complete primary COCO export was generated and reopened successfully:
`dataset/annotation_workspace/exports/annotations-coco-8c045a2cbe99.zip`
(3,234,449,317 bytes). It contains all 345 images and 4,867 masks, organized as
275 train / 45 validation / 25 test images using the protected groups. ZIP CRC,
every original image byte sequence, every mask PNG, reviewed documents, RLEs,
class references and source revision numbers passed readback. Structural
validation had zero errors and 5,883 review warnings; these warnings include
unverified fish ownership and mask ambiguity rather than certifying each object.
Export and readback took 1,021.5 seconds. The machine-readable report is
`results/qa/annotation_workflow/primary_complete_export.json`.

Full-source topology checks exercised the actual YOLO polygon converter on all
4,867 primary masks. It accepted 4,363; 504 require COCO for exact preservation
(484 masks with incompatible components/holes and 20 tiny masks). Only 78 images
have every mask compatible with lossless YOLO segmentation. The complete baseline
should therefore use COCO. Original masks are never simplified automatically to
make a YOLO export appear successful.

Actual original-resolution YOLO round trips used source images 193 (train),
120 (validation) and 331 (test). Detection export reloaded all nine labels,
mask-derived boxes, class mappings, original image bytes and exact PNG/RLE masks.
Combined segmentation export correctly refused the disconnected source-120 mask
`manual-1967`. Compatible source 193 exported three segmentation labels that
reloaded pixel-exactly through the installed Ultralytics polygon rasterizer.
All 1,255 stored image documents and 1,255 revision documents stayed unchanged.
Evidence: `results/qa/annotation_workflow/primary_real_exports/report.json`;
reproduce with `tests/annotation_primary_yolo_smoke.py`.

Split exports retain source provenance and group exact pixels, capture variants
and declared near duplicates together. Creating a structurally valid package is
different from demonstrating independent, balanced model evaluation. The primary
source has no `Grade_B_Tail` examples and very few B/C examples. Automatic model
promotion requires validation coverage of all twelve trained classes and remains
blocked when that coverage is absent. All 45 primary validation images contain
only Grade A labels; nine model classes have no validation support. The protected
training set also has no `Grade_B_Head`. New classes remain saved/exportable but do
not silently change the existing model's fixed output taxonomy.

## Executed QA

All reported checks are actual executions. Results are separated from limitations
in model accuracy; passing persistence or UI tests does not verify predictions.

The final full run completed **2,752 passed, one failed,
12 skipped and 127 passing subtests** in 99.73 seconds. All annotation tests
passed. The failure was the pre-existing
`test_bc_color_experiment.py::test_scaffold_evaluates_validation_and_reserves_test`:
Windows Application Control blocked the installed Matplotlib `_image` DLL.
A normal direct import reproduced the same policy error. No security policy was
bypassed and the unrelated experiment was not changed to conceal the failure.
The application reported both existing CUDA models ready. The exact run is
`results/qa/annotation_workflow/final_boundary_capture_regression.xml` and `.log`.
This run used `pytest -q -s`: default capture caused Windows `DuplicateHandle`
errors in two existing Node subprocess tests. Both passed when capture was
disabled, and the complete suite was then rerun with the same setting. The earlier
capture run recorded 2,750 passes and three failures, including the same
Matplotlib block; no application code or test assertions were changed to fix the
test runner's input-handle behavior.

Focused final checks additionally passed 63 store/import tests, 89 review/learning
tests, 30 automation tests and the library's API/JavaScript checks. These overlap
the full run and must not be added together as a unique-test count. Later small
UI layout and request-validation fixes were checked in their affected suites.

| Requested scenario | Evidence and practical limit |
| --- | --- |
| One fish | Actual local models run on a visually inspected original photo; masks saved as unreviewed candidates. |
| Multiple/crowded/overlapping fish | Real-photo model smoke and ownership/overlap tests; uncertainty retained. |
| Different orientations and partial visibility | Visually inspected real-photo cases and original-coordinate output checks. |
| Missing/undetected anatomy | No invented masks; explicit undetected flags and incomplete-mask approval guards. |
| Incorrect predicted class | HTTP/browser class edits change only the target; no extra inference. |
| Incorrect boundary | Browser polygon/vertex editing, undo/redo and exact mask persistence tests. |
| Duplicate objects | Pixel-equivalent polygon/RLE duplicate guards and ambiguity flags. |
| Missing manual object | Browser drawing and API add/save tests. |
| Class changes after prediction | Central class metadata and saved/exported labels checked. |
| Save/reopen | New store instance reads the exact saved revision. |
| Export/reload | COCO/PNG and YOLO pixel/coordinate readback, manifest validation. |
| Restart/recovery | Durable revisions, stale edits, interrupted learning and browser draft checks. |
| Approval integrity | Per-object and full-image review, failed-save rollback, rejected-object exclusion. |
| Source protection | Original file/checkpoint hashes and exact imported-mask comparisons. |

The original broad regression passed 2,664 tests, 12 skips and 127 subtests before
the later primary-dataset integration. An initial expert-library test invocation
failed three privacy checks because its temporary directory was inside the
repository; rerunning with temporary data outside the repository passed. The
privacy protection was retained.

The final actual browser fixture passed 12 checks with zero JavaScript errors. This
included save failure/retry, stale conflicts, history, editing independent
objects, mask selection, undo/redo, downloads, classes and narrow mobile layout.
A long class name initially caused horizontal overflow on a 390-pixel viewport;
the layout was corrected and the browser check passed.

Six further read-only browser checks used the real primary and secondary
collections. The default view showed 345 images / 4,867 labels; the secondary
view showed 910 / 9,723; All showed 1,255 / 14,590. Rendered RLE pixel hashes
matched independently decoded saved masks. Current, selected and complete-primary
JSON downloads were opened and checked, including source categories. Empty
approved-only export failed visibly with HTTP 422. No original document or
revision changed. See `results/qa/annotation_library/primary-dataset-browser.json`.

Actual learning-pool verification found 343 eligible primary documents: 275
training, 45 validation and 23 original test documents. Two original training
members of protected test groups were quarantined. The 910 secondary examples
remained retained but excluded from the positive reference pool. Five retrieved
references all came from primary training images; the adaptation path received
them. Labels, all revisions, source ZIP, V2 COCO and deployed checkpoint hashes
were unchanged. No production training or approvals occurred. See
`results/qa/task3_primary_baseline_learning.json`.

The independent full-source integrity audit passed with zero errors and SQLite
integrity `ok`. All 4,867 saved primary RLE masks and all 4,867 PNG masks matched
official pycocotools COCO rasterization exactly. All 345 original images and
source annotation/category metadata were retained; the source ZIP hash was
unchanged. The secondary audit checked 910 original revision-one documents,
9,723 masks/PNGs and 913 source files without any change. All 1,255 immutable
revision JSON artifacts were present and exact. The training descriptor contained
exactly 3,989 eligible source annotations from 275 training images and zero
holdout leaks. Evidence: `results/qa/annotation_workflow/primary_integrity.json`;
reproduce with `tests/annotation_primary_integrity.py`.

### Actual primary-image model diagnostic

Five visually inspected original test scenes (IDs 331, 324, 337, 338 and 334)
cover one fish, crowds, crossing fish, rotations and clipping. Their manual
reference has 56 anatomical parts. Existing models produced 17 whole-fish
detections and 31 part detections. After the native-mask guard, all 48 objects
had actual RLE masks, none were missing, and zero of the 31 part masks were
filled rectangles under the documented 99.5% box-fill heuristic. This does not
prove that all boundaries or fish associations are correct.

Class-aware part-box precision and recall at IoU 0.5 were both **zero** on this
sample. Among 24 one-to-one spatial matches, anatomical region was correct in
24/24 but quality grade in **0/24**. Source-to-model class IDs were checked
explicitly; this is a prediction-quality problem rather than a numeric import
mapping assumption. All predictions remained unreviewed in an isolated QA store.

The repeat run preserved identical detector boxes, classes, confidences and
associations. On the same 22 matched parts with masks in both runs, mean mask
IoU increased from 0.540535 to 0.772807: 13 improved, nine were unchanged, none
worsened. Two previously missing matched masks became available; mean IoU over
all 24 available spatial matches was 0.786563. These are class-agnostic,
match-conditional development diagnostics, not whole-dataset accuracy. Missing
detections and the failing grade classifications remain material limitations.

Reports, raw predictions and visual overlays are under
`results/qa/annotation_workflow/primary_real_models_r2/`, including `report.json`
and `mask_guard_comparison.json`. Historical training may have used related
captures; these five selected scenes do not establish independent generalization.
No human correction rate was measured, and no model weights were changed.

The real ASGI smoke exercised actual model inference, unreviewed persistence,
class edit without peer changes, stale revision rejection, protected rerun,
simulated approval, restart, validation and pixel-exact COCO/PNG export. All
simulated approvals stayed outside the user's dataset.

An isolated real one-epoch CPU training smoke fitted a candidate and evaluated it
against the same incumbent/validation snapshot. The candidate regressed and was
rejected. Original weights and COCO hashes were unchanged; no production model
was promoted. This proves the fitting/rejection mechanism executes, not improved
prediction quality.

## Remaining limits

There is no independent whole-fish silhouette or ownership truth, and no measured
real-user correction rate yet. Automatic geometric associations require visual
review, especially for crossing or partly visible fish. Uncertain candidates
remain unreviewed. Source part masks and their class conventions are retained
without asserting that every original boundary is correct.

The software supports the requested human review, editing, persistence and export
workflow. The intended accuracy level is **not yet verified**: quality grades
failed on the five-image primary diagnostic, and crowded masks and associations
still need correction. A trustworthy improvement requires representative verified
examples and validation support for the missing classes. The application does
not hide this limitation by rewriting predictions to the most common class or
promoting a model against incomplete validation data.

## Acceptance status

| Acceptance criterion | Verified outcome |
| --- | --- |
| Manual annotations preserved and used as baseline | All primary pixels/metadata exact; primary training-only references verified. |
| Actual instance segmentation | Native/SAM masks generated, saved and exported; all 48 real-smoke objects have masks. |
| Each mask correctly associated with its fish | Conservative associations and ambiguity flags implemented; universal correctness remains unverified without ownership ground truth. |
| Visual review | Real-browser overlays, pixel hashes, hit selection and readable labels passed. |
| Individual and batch approval | API/browser tests passed; QA never approved production predictions. |
| Editing incorrect predictions | Class, association, polygon/vertex edits and undo/redo passed. |
| Class management | Central stable IDs, additions, renaming and safe unused custom-class removal passed. |
| Add missing annotations | Browser drawing and persisted mask tests passed. |
| Original annotation protection | Immutable baseline artifacts, hashes, provenance and revision guards verified. |
| Persistent approved annotations | Isolated actual API approval and exact export/reopen tests passed. |
| Restart recovery | New store/restart, browser draft and revision recovery passed. |
| Export actual segmentation | Complete primary COCO readback and actual YOLO round trips passed; incompatible YOLO masks refuse visibly. |
| Export structural validation | Complete COCO has zero errors, with review warnings retained. |
| Simpler workflow | Dedicated annotation screen; unrelated inspection controls remain in the existing screen. |
| Core QA scenarios | Executed and documented above; one unrelated regression remains blocked by Windows DLL policy. |

The software mechanisms are delivered. Reliable automatic quality grades and
universally correct crowded-fish ownership are outstanding accuracy criteria,
not completed acceptance claims.

Measurements on historical V2 test exports are supplementary software QA, not
evidence of independent generalization or improvement on the selected primary
source. The original V2 audit found 96.73% rectangular polygon labels, making
whole-fish boundary-accuracy claims inappropriate for that secondary dataset.
Primary-source model smoke measurements are small-sample diagnostics and must
be interpreted with their exact sample and matching procedure.

See [the source/pipeline audit](annotation_workflow_audit.md),
[library operation and browser QA](annotation_library_qa.md), and
[review/learning safeguards](annotation_active_learning.md) for implementation
details. Reproducible scripts and machine-readable outputs are under
`tests/annotation_*` and the local ignored `results/qa/` folder.
