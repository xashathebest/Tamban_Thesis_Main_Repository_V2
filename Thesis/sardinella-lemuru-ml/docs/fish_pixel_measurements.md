# Per-fish silhouette measurements

The fish evidence panel distinguishes silhouette measurements from the older
Whole Fish and Body ROI rectangle dimensions. A detector rectangle describes a
crop, not an anatomical fish length or body width. The saved seven-record
`fish-inspection-upload-all.csv` contains rectangles and derived image features,
but no source silhouettes. Reopening it can retain the existing width proxies;
it cannot recover a fish outline or manufacture new silhouette measurements.

## Measurement definition and limits

`analysis.fish_geometry` records the current fish's segmentation source, local
pixel measurements, reliability reasons, measurement validation, and grading
eligibility. Length spans the silhouette tips along an orientation-normalized
centerline. Maximum body width is a silhouette cross-section within the
longitudinal range of that fish's associated Body detection. The width ratio is
maximum body width divided by fish length. Rotation is measured in the original
image coordinates; it does not identify which endpoint is the head.

When a Body segmentation polygon exists, its actual silhouette sections supply
the width. With the current detection-only model, the associated Body box only
selects the longitudinal region; width comes from foreground sections, not the
box's height. Fins or imperfect foreground boundaries can still influence that
silhouette. This distinction is displayed as the Body measurement source and is
one reason anatomical measurement validation remains pending.

The implementation (`segmentation_centerline_profile_v1`) obtains a principal
axis from the foreground pixels, samples transverse silhouette sections in
one-pixel bins, and fits a smooth centerline through those sections. Length
includes both silhouette tips rather than stopping at the medial skeleton's
endpoints. When a valid Body polygon is available, the cross-sections are
restricted to that polygon; otherwise the associated Body box selects the
longitudinal region and the fish silhouette supplies the transverse boundaries.
The original axis-aligned box width is not substituted for a cross-section.

These are two-dimensional silhouette measurements. They are not physical body
thickness, a biological condition index, or validated anatomical measurements.
Fins, tail shape, occlusion, camera perspective, and segmentation errors can
affect the apparent outline. Curved or uncertain profiles require abstention
rather than a confidently reported length inferred from a rectangle.

Runtime foreground extraction uses GrabCut within a Model 1 parent crop. Its
existing `validated_for_features` status means it passed computational feature
checks. It does not mean a human validated the fish boundary or a study
established measurement accuracy. Runtime mask metadata, checks for discarded
components, and segmentation provenance must therefore travel with geometric
results. Synthetic geometry regression tests establish software behavior only.
There is no independently annotated measurement-validation dataset supplied
with this change.

## Ownership and reliability

All mask coordinates and associated part coordinates must refer to the same
parent crop, at the same pixel scale. Crop translation preserves original
pixel units and records the origin. Full-frame part detections are assigned to
one parent before measuring that parent's crop. Parts with ambiguous ownership
cannot establish a trusted body measurement.

Measurement checks account for incomplete silhouettes, clipping at the frame or
crop boundary, competing visible parents, multiple foreground components,
orientation ambiguity, and poor Body-to-mask agreement. A foreground extractor
can force crop-border pixels to background, so a mask that avoids its edge is
not by itself proof that the fish is complete. Original parent and image bounds
remain necessary context.

Rejected geometry retains candidate pixel diagnostics and explicit reasons.
It supplies no trusted measurement or grading contribution. Missing masks or
missing Body evidence remain unavailable; another fish's part or a detector
rectangle must not fill the gap.

The measurement ROI is separately padded using the original image to include
background around the parent detection. It never replaces the crop or mask used
for existing grading diagnostics. `mask_crop_bounds` records its original-frame
origin, and `mask_metadata` retains its source and foreground checks. The
`status` field is `measured`, `unreliable`, or `unavailable`. Public numeric
fields are populated only for `measured`; rejected numeric candidates remain in
`candidate_measurements` for review. Reliability describes the software checks,
while `measurement_validation_status` continues to report `Not validated`.

## Centimeters and grading

Pixel measurements need no physical scale. Conversion to centimeters requires
a separately validated physical calibration with scale, provenance, and a
matching acquisition configuration. Camera exposure, white balance, a crop
size, or an assumed fish size does not establish pixels per centimeter. Without
that calibration, centimeter fields remain empty and the evidence panel reports
the uncalibrated state.

`configs/fish_geometry.yaml` holds engineering measurement checks and a separate
`physical_calibration` section. A physical scale needs `validated`,
`calibration_id`, a positive finite `pixels_per_cm`, the original
`reference_frame_size` in `[width, height]` order, and `source_id` identifying the
reviewed camera, measurement plane, and acquisition context. Both the current
frame dimensions and supplied source context must match. Resizing an image does
not silently rescale a saved calibration. No physical calibration is supplied
or enabled by default.

Revalidate the scale after moving the camera or measurement plane, changing
optics/zoom, or otherwise changing capture geometry. Source and resolution checks
cannot independently verify the physical placement of a fish.

Live capture identifies its current physical context as `camera:<index>` (for
example, `camera:0`). That identifier must refer to the reviewed acquisition
arrangement; moving the camera or measurement plane invalidates its scale.
Uploads do not assert that a photo was captured in the calibrated plane. Equal
image dimensions alone cannot establish that context, so an arbitrary uploaded
photo receives no centimeter conversion.

Engineering reliability, anatomical measurement validation, physical scale
validation, and width-to-grade calibration are distinct states. This change
does not enable width grading. New silhouette measurements explicitly report
`measurement_validated: false` and `used_for_grading: false`; the existing
Body/Head/Tail 50/30/20 grading calculation remains authoritative. A plausible
ratio or a valid physical scale alone must never activate width-based grading.

The older `analysis.body_width` rectangle proxy remains separate for historical
compatibility. Its raw dimensions and previous grading evidence are preserved.

## Regression checks

Run the synthetic measurement and integration regressions with:

```powershell
python -B -m pytest tests/test_fish_geometry.py tests/test_fish_geometry_integration.py tests/test_fish_geometry_exports.py -q
```

The tests cover rotated silhouettes, geometry rejection, physical calibration
gates, parent assignment, independent measurement crops, serialization, and
unchanged weighted grades. The seven saved CSV records must retain their grades
and raw rectangle proxies while reporting silhouette measurements unavailable.
An ellipse rotation sweep also checks that full silhouette tips, rather than a
short medial skeleton, determine length. Rasterization permits small pixel
differences across rotations; these tests do not establish anatomical accuracy
on real fish.

## Root cause and modified files

The existing path recorded axis-aligned detector dimensions and integer ROI
sizes. Those rectangles could not establish rotation-independent fish dimensions.
The full-frame path supplied no foreground mask, `_part_to_crop` dropped part
polygons, and foreground extraction discarded component evidence before a
measurement consumer could check it. Its `validated_for_features` flag certified
only basic foreground usability, not anatomical measurement accuracy.

The new measurement stage runs after the weighted verdict and retains its own
mask origin, source, frame, and parent ID. A segmentation failure reports missing
measurements while preserving the already calculated grade and support.

| File | Change in this task |
| --- | --- |
| `src/inference/fish_geometry.py` | Native-pixel contour profile, rotation, ownership/reliability checks, validated physical scale gate; no grading input. |
| `src/inference/fish_geometry_pipeline.py` | Dedicated padded original-frame measurement crop and mask/part coordinate translation. |
| `configs/fish_geometry.yaml` | Engineering checks and disabled physical calibration; no biological grading thresholds. |
| `src/inference/preprocessing.py` | Preserve component evidence and initialization-boundary contact before morphology/filtering. |
| `src/inference/yolo_quality_model.py` | Shared crop/full-frame metrology result; preserve polygons, frame/parent reliability, and grade on diagnostic failure. |
| `src/inference/inspection_results.py` | Explicit unavailable historical silhouette fields without deriving silhouettes from boxes. |
| `src/api/camera.py` | Original-frame measurement context, mask provenance, and camera source ID. |
| `src/api/image_analysis.py` | Original-frame upload context, mask provenance, and response completeness check. |
| `src/api/export.py` | Named geometry/reliability/calibration fields and complete geometry JSON in CSV/XLSX. |
| `frontend/app.js` | Measurements inside each fish card, browser CSV/PDF fields, and gated centimeters. |
| `frontend/index.html` | Refresh the JavaScript asset version. |
| `tests/test_fish_geometry.py` | 66 measurement and calibration regressions. |
| `tests/test_fish_geometry_integration.py` | 14 parent, original-grade, diagnostic-failure, historical CSV, and calibration integration regressions. |
| `tests/test_fish_geometry_exports.py` | 8 API export and browser evidence/report regressions. |
| `tests/body_width_browser_smoke.py` | Real browser measurement rows, centimeter gate, and seven-record historical report checks. |
| `docs/fish_pixel_measurements.md` | Measurement definitions, limits, files, and validation report. |

Other pre-existing surface-damage, video, model, and grading changes were retained.
Neither model was retrained. The existing width calibration remains disabled;
new silhouette values never enter the original 50/30/20 weighting or fusion stage.

## Validation result — November 1, 2026

- All **88 new regression tests passed** in the full suite.
- Full suite: **981 passed, 12 skipped, 11 pre-existing failures**, with 127
  passing subtests. The existing failures are nine model-switch fixture failures
  and two stale UI source-text assertions. Their isolated HEAD reproduction is
  recorded in `results/qa/body_width/upload_csv_baseline_failures.json`.
- Headless Chrome passed measurement rendering, the uncalibrated centimeter
  gate, Class A/B/C/Rejected/Ungraded grouping, recorded timestamps, seven-fish
  isolation, mobile layout, and a 48-page PDF print report.
- JavaScript syntax validation passed.
- All seven source CSV records retained their original weighted scores and
  grades. All nine synthetic ellipse rotations measured full tip-to-tip length
  and width within three pixels of the raster reference. This is software
  regression evidence, not a real-fish accuracy study.

`results/qa/fish_geometry/validation.json` contains the per-record and rotation
audit. `results/qa/body_width/fish-inspection-upload-all.pixel-measurements.pdf`
contains the seven historical fish with the new fields and explicit missing
silhouette measurements.

Restart a backend running older code, reload the dashboard, and reanalyze the
source photographs or live frames to obtain new silhouette measurements. A saved
CSV containing only detector/ROI measurements cannot recover source contours.

## Artifact and dashboard follow-up

The repaired exports were regenerated after the silhouette integration. The
browser CSV now has **7 rows and 765 columns**, retaining all 607 original
columns; the companion server CSV has **7 rows and 273 columns**. The JSON and
48-page repaired PDF include the new measurement fields. Original fish identities
(`upload:1:1` through `upload:1:7`), measurements, grades, support vectors, source
metadata, and recorded analysis timestamps remain unchanged.

Reproduce the data exports, without model inference, with:

```powershell
python -B results/qa/fish_geometry/refresh_exports.py
```

The script explicitly normalizes the original fixture, invokes the actual
frontend CSV exporter in an isolated Node context, runs the server CSV exporter,
and verifies preservation before writing the artifacts. It does not reconstruct
silhouettes or update PDFs. Headless Chrome regenerated the repaired PDF and
passed the grouped-card, measurement, calibration, timestamp, and mobile checks.
The focused CSV/export/frontend regression run passed **33 tests**.

The previously running backend returned 404 for the normalization endpoint. A
candidate backend loaded both existing models and normalized all seven records
before replacement. After confirming inspection was stopped and the old write
queue was fully drained, the repaired backend was started at
`http://127.0.0.1:8000`. Both models report ready; inspection remains stopped and
the camera remains disconnected. The temporary candidate on port 8001 was then
stopped. No models were retrained or calibration settings enabled.

`results/qa/fish_geometry/live_backend_verification.json` records the live check;
the updated `results/qa/body_width/upload_csv_width_audit.json` records artifact
hashes and preservation checks. Reload the dashboard to use this running backend.

## Method references

The orientation calculation follows the foreground principal-axis approach
described in [OpenCV's PCA tutorial](https://docs.opencv.org/3.4.4/d1/dee/tutorial_introduction_to_pca.html).
The padded segmentation context and initialization-contact safeguard account for
the rectangle initialization and foreground/background limitations described in
[OpenCV's GrabCut tutorial](https://docs.opencv.org/4.12.0/dd/dfc/tutorial_js_grabcut.html).
