# Annotation workflow: source and pipeline audit

**Primary-source update, 2026-11-27:** the user selected
`Fish_Annotations_Cleaned.zip` from the older repository in Downloads as the
primary baseline. It contains 345 original-resolution images and 4,867 manual
part masks. The 910-image V2 export audited below remains preserved as a
secondary collection. Its rectangle statistics and historical metrics must not
be attributed to the selected archive. The implementation/import verification,
source mappings and final QA are documented in
[annotation_workflow_qa.md](annotation_workflow_qa.md).

Audit date: 2026-11-25. This report records the existing pipeline and a new,
read-only inspection of the actual local manual COCO export before the new
annotation workspace is integrated. It does not assert model accuracy or human
approval of generated masks.

## Ground truth and source integrity

The local source is `Dried Fish Quality Grading.v7i.coco-segmentation/`.
`configs/dataset_class_reference.json` explicitly records that project annotators
assigned quality independently to each Head, Body and Tail. The labels are the
reference for **part class and part quality**, not a verified whole-fish quality
label, a specimen identity, or an expert whole-fish silhouette.

The original COCO table has one unused supercategory, ID 0,
`dried-fish-quality-grades`, and twelve used categories:

| COCO ID | Model class ID | Original category |
| --- | --- | --- |
| 1 | 0 | Grade_A_Body |
| 2 | 1 | Grade_A_Head |
| 3 | 2 | Grade_A_Tail |
| 4 | 3 | Grade_B_Body |
| 5 | 4 | Grade_B_Head |
| 6 | 5 | Grade_B_Tail |
| 7 | 6 | Grade_C_Body |
| 8 | 7 | Grade_C_Head |
| 9 | 8 | Grade_C_Tail |
| 10 | 9 | Rejected_Body |
| 11 | 10 | Rejected_Head |
| 12 | 11 | Rejected_Tail |

Map IDs by the exact category name when importing. Subtracting an assumed offset
from arbitrary future COCO exports is unsafe. Anatomical region and quality grade
are separate metadata; `Rejected_Head` remains a head annotation with rejected
quality, rather than an instruction to delete the object.

The audit read and hashed all 910 original image files and all three annotation
JSON files. No source image or source annotation was written. The complete
before snapshot is
[`source_integrity_before.json`](../results/qa/annotation_workflow/source_integrity_before.json).
The source JSON SHA-256 values are:

| Split | SHA-256 |
| --- | --- |
| train | `198b7448e307265aa269d6993a2e2cbbf993a5ee66829d4e989dede5b115b20f` |
| valid | `b48a3ac59ac8b7a5b96c048017089e76a655f03ff6b87621ecb38b8612e1bc0e` |
| test | `762ac7674bba5d7758d250299c8c1cf6db6bb4720c3be4a1b27afca3d61438aa` |

The new workflow must copy/import these sources, preserve their raw labels and
segmentation encodings, and store all changes as separately versioned records.
An imported manual example and a generated candidate must retain different
provenance. A previously verified source class does not verify a new prediction.

## Actual dataset checks

The existing `audit_coco_split` validator was run on every split. Every image was
opened, verified, fully decoded, and compared to its COCO dimensions. All polygons
were validated and rasterized at the native image size using OpenCV. All six
compressed RLE masks were decoded using the already installed `pycocotools`.
Pixel masks were checked for emptiness, components, exact duplicate masks,
bounding box agreement, edge contact and pairwise overlap.

| Check | train | valid | test | Total |
| --- | ---: | ---: | ---: | ---: |
| Images | 861 | 32 | 17 | 910 |
| Part annotations | 9,099 | 399 | 225 | 9,723 |
| Polygon annotations | 9,093 | 399 | 225 | 9,717 |
| Compressed RLE annotations | 6 | 0 | 0 | 6 |
| Rectangle-only polygon annotations | 8,799 | 387 | 219 | 9,405 |
| Nonrectangular polygon annotations | 294 | 12 | 6 | 312 |
| Nonempty decoded/rasterized masks | 9,099 | 399 | 225 | 9,723 |
| Images with no annotations | 3 | 0 | 0 | 3 |
| Maximum part annotations per image | 21 | 18 | 19 | 21 |
| Images with mask pair IoU >= 0.10 | 463 | 19 | 10 | 492 |
| Mask pairs with IoU >= 0.50 | 12 | 1 | 0 | 13 |
| Pixel masks touching the image border | 339 | 3 | 6 | 348 |

All 910 images are 640 x 640. No missing or corrupt images, metadata dimension
mismatches, invalid annotations, duplicate image IDs, duplicate annotation IDs,
or exact same-class pixel-mask duplicates were found. No exact-byte duplicate
images or `extra.name` source groups cross splits in this export. These checks
do not establish specimen/session independence from historical model training.

**96.73% of the original annotations are axis-aligned rectangle polygons.** They
encode pixels, but do not trace fish or anatomical foreground boundaries. Calling
the folder a segmentation export does not establish boundary-level ground truth.
The remaining polygons and RLE masks must also be visually checked before an
expert-boundary accuracy claim. Rectangle baselines should remain visible as
original references, and must not silently become validated SAM masks.

All six RLE masks decoded successfully. Three have two foreground components;
these belong to three augmented versions of one source image. This is a review
signal, not proof of a corrupt mask. The audit found no mask/bounding-box edge
disagreement above 2 pixels. The existing continuous polygon check reported 451
COCO area-versus-shoelace differences above one square pixel. Raster counts also
differ from continuous COCO area due to inclusive pixels, rounding, and encoding;
none of those diagnostic differences was automatically repaired.

Overlap is expected for rectangular labels around crossing fish and adjacent
parts. The 492 overlap images and 13 high-overlap pairs are **candidates for
review**, not 492 known errors. Their per-image/category/annotation details are in
[`manual_coco_audit.json`](../results/qa/annotation_workflow/manual_coco_audit.json)
and [`real_image_scenario_candidates.json`](../results/qa/annotation_workflow/real_image_scenario_candidates.json).

No original annotation contains a fish ID, parent annotation ID, track ID,
association status, review status, or per-object provenance field. Original
annotation keys are only `id`, `image_id`, `category_id`, `bbox`, `iscrowd`,
`area`, and `segmentation`. A system cannot claim that original parts already
have verified fish ownership. Similarly, an absent part label does not prove
physical absence: there are 84 nonempty images with no tail labels and 36
nonempty images with no head labels.

## Existing pipeline and reusable components

1. `src/api/image_analysis.py::decode_uploaded_image` validates uploads and
   decodes the image. `StillImageAnalyzer` runs local whole-fish detection and
   part-quality analysis while retaining original-coordinate evidence. The
   frontend uses the canonical preview and native coordinate transforms.
2. The default Model 1 registry entry is the local YOLO26s V2 whole-fish detector,
   `model1_v2_yolo26s_best.pt`, input size 768, confidence 0.50, NMS IoU 0.70.
   It emits **boxes**, not fish segmentation masks. The counting threshold 0.70
   is separate from detection confidence.
3. The default Model 2 is local YOLO26m `r03_devbest`, input size 768,
   confidence 0.25. It emits twelve-class part-quality **boxes**. Its
   `YoloDetectionAdapter.predict` must not be represented as segmentation.
4. The existing `YoloSegmentationAdapter` for local `exp-4.pt` does emit actual
   original-coordinate anatomical polygons, paired to boxes by result index,
   through `PartDetection.mask`. It validates the exact twelve-class mapping.
   This is a reusable separate segmentation capability; it should not require
   replacing the active grading model or changing its operating threshold.
5. `association.py::associate_parts_to_parents` provides conservative geometric
   ownership, ambiguity reporting, and constrained one-to-one selection.
   Ambiguous/unassigned parts remain evidence for review, rather than being
   copied into each overlapping fish. `PartDetection` already separates region,
   grade, source class, score, native box and optional polygon.
6. `MobileSamService.open_frame` and `MobileSamFrame.predict` generate real
   native H x W binary candidate masks with one embedding per frame and
   original-parent/frame/checkpoint provenance. CPU default, memory budgets,
   serialized shared embedding, and explicit failures already exist.
7. `ExperimentalFrameSegmentation` and `mask_ownership.py` check candidate
   geometry, overlap, fragmentation, neighbor intrusion and missing support.
   The compact `mask_overlay.contours` are display approximations; they lack a
   contour hierarchy and cannot substitute for exact saved binary masks where
   holes or multiple components matter. Persist exact masks separately.
8. `POST /api/segmentation/preview` already returns real candidate silhouettes.
   `PreviewSnapshotCache` protects same-image reuse with hashes, original shape,
   detector identity/configuration, bounded capacity and expiration. It is
   transient metadata and is not a persistent annotation dataset.
9. `InspectionDatabase`, ordinarily `results/inspection_history.sqlite3`, has
   durable inspection events and a manual **whole-fish grade** audit. Existing
   `/api/reviews` and structural-review actions do not provide an anatomical
   polygon editor, object-level mask approval, or reusable training labels.
   Existing CSV/XLSX exports serialize inspection/evidence fields; they are not
   COCO or YOLO annotation dataset exports.
10. `prepare_canonical_parts.py` has useful strict part-category and source-group
    handling. `prepare_reviewed_coco.py` correctly rejects raw part annotations
    masquerading as four-class whole-fish instances. `polygon_masks.py` already
    expects explicit reviewed specimen and mask associations before a scientific
    masked-instance dataset is materialized. Preserve these safeguards.

## Gaps and simplification targets before the new workspace

- The main product is an inspection/grading dashboard. Manual anatomical class
  correction, durable mask editing, undo/redo, adding missing instances, class
  management, image/object approval and local training-dataset exports were not
  supplied by its inspection review controls.
- Successful segmentation preview was transient. Candidate contour overlays
  alone did not preserve exact raster data, editable approved versions, source
  images or crash recovery for annotation work.
- Manual category configuration, trained checkpoint classes and final quality
  classes have different meanings. A new annotation class registry must not
  mutate trained-model class mappings or reinterpret independent part grades.
- Never infer a missing head/tail from the detector's silence. Use explicit
  review flags such as undetected, uncertain, physically absent (user verified),
  occluded and clipped; do not invent masks for missing anatomy.
- Keep the existing inspection, model selection, masks and evidence workflows.
  A dedicated annotation route can expose upload/select, Auto-Annotate, one
  mask canvas, selected-object class/quality/parent controls, Approve/Reject,
  reliable saving and export without the camera, crack, metrology and grading
  diagnostics occupying its primary workflow.
- Batch image approval must explicitly accept the visible annotation set.
  New predictions remain unreviewed; changing a verified mask or class creates
  a correction revision and must never overwrite its original manual source.
- Annotation deletion/rejection and rejected **quality** are different actions.
  Preserve that distinction in UI labels and exported metadata.

## Real-image scenarios located and visually inspected

Paths below are relative to `Dried Fish Quality Grading.v7i.coco-segmentation/`.
These observations are qualitative software QA, not newly created expert truth.

| Scenario | Image | Observed content |
| --- | --- | --- |
| One visible diagonal fish | `train/WIN_20260823_20_10_07_Pro_jpg.rf.bf4c016dea7d84c6ac57bb19f0cdc76f.jpg` | One fish with Head/Body/Tail labels; head meets lower edge of the photographed content. |
| Crowded, overlapping, varied orientations | `valid/WIN_20260823_22_03_45_Pro_jpg.rf.91366fccd7b13d49fa582c4d44c10109.jpg` | Multiple crossing fish, opposite orientations and clipped objects; 18 part annotations and a mask pair IoU above 0.50. |
| Damaged/disconnected anatomy | `valid/WIN_20260902_18_12_46_Pro_jpg.rf.790fd6ded13e7129850d3c160b24320d.jpg` | Several detached heads and damaged bodies; 4 Head and 1 Body labels, no Tail labels. Missing labels cannot establish physical absence. |
| Opposite orientations and edge truncation | `train/WIN_20260823_20_18_24_Pro_jpg.rf.4513a095bccccfd49033cfc98775c5fc.jpg` | Two fish at the right edge; one points upward and another downward; 5 part labels, 3 touch source image border. |
| Association/counting trap | `train/WIN_20260823_20_13_50_Pro-1-_jpg.rf.47ffaac41a7f6f7da860af10ce6ff521.jpg` | Two partial fish although the file has just one Head, one Body and one Tail annotation. A triplet is not a verified single fish. |

The full candidate manifest includes all 910 images, their part and grade
counts, native dimensions, boundary-touching annotation IDs, and selected
overlap pairs. It avoids asserting fish counts from part labels.

## Existing evaluation and limits on accuracy claims

`src/evaluation/evaluate_active_model2_parts.py` loads the exact manual COCO
category names and has existing class-aware box precision/recall/AP matching.
Its saved report at `results/evaluation/active_model2_coco_part_compatibility.json`
records 17 test images and 225 annotated boxes. The historical operating-point
results are 190 matched boxes, 53 unmatched predictions and 35 missed boxes,
macro precision 0.501555, macro recall 0.555360, mAP50 0.548903, and mAP50-95
0.317795. These are archived **part-box compatibility** results, not measurements
rerun in this source audit. The saved exposure check reports 15/17 test-export
images matched historical training bytes. They cannot support independent
generalization or an improvement claim.

`evaluate_mobilesam.py` already contains real and transformed scenario QA,
ownership engineering checks, source manifests and checkpoint integrity checks.
It explicitly has no expert whole-fish mask or ownership truth.
`evaluate_segmentation.py` can run a real segmentation evaluation after its
strict dataset preflight passes. `docs/validation_preflight/report.md` and
`configs/dataset.yaml` correctly keep the old collapsed four-class dataset
blocked pending actual whole-fish review.

The new read-only checks above passed structural decoding and referential
validation. The original dataset is **not established as boundary-accurate
whole-fish training truth**. No new detection precision/recall, fish-mask IoU,
class accuracy, correction rate, or segmentation quality improvement has been
measured by this audit. Those require saved candidate predictions compared with
appropriate reviewed, independent annotation units. UI or persistence test
success cannot replace that evaluation.
