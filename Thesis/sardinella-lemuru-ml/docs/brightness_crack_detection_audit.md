# Brightness and crack detection audit

Brightness now appears on the inspection image and in a visible per-fish feature monitor. Surface analysis uses the complete native MobileSAM silhouette after excluding pixels with uncertain ownership. Crack visualization uses a separate, localized binary mask. These measurements support inspection and human review; independently validated real-fish crack accuracy and grading calibration remain outstanding.

Date: November 23, 2026.

| Previous problem | Implemented behavior |
| --- | --- |
| HSV Value was a regional color diagnostic, without a prominent whole-fish brightness display. Rectangular regions could include background. | Mean, median, population standard deviation, percentiles, histogram, pixel count, owned-mask coverage and reliability use only the complete owned silhouette. Labels show the measured percentage. |
| The MobileSAM damage path required a separately reviewed Body mask. The older detector also eroded a wide boundary strip. | Surface diagnostics use the full native silhouette extent, including tips outside the detector prompt. Body measurements do not define the crack boundary. |
| Dark structures lacked an explicit taxonomy for spots, discoloration, texture, lighting and uncertain ownership. | Candidates record six hypotheses: `crack_or_split`, `dark_spot`, `discoloration`, `natural_fish_texture`, `shadow_or_lighting_artifact`, and `uncertain_defect`. Classification remains unvalidated. |
| A narrow crack touching a broad dark spot could cause the entire connected component to be retained. | Local width and two-sided contrast restrict the retained footprint around supported skeleton pixels. Broad or unsupported pixels are excluded. |
| Outlines and candidate rectangles could not show the actual crack-pixel footprint. | Crack Detection displays exact white candidate pixels on black, with the original image beside it. Red overlay is optional. Rejected hypotheses do not enter the white mask. |
| Brightness labels could collide in a crowded photograph. | Labels use contrasting backgrounds and avoid one another. Leader lines retain fish identity; selection shows one fish's measurements independently. |
| The legacy seven-fish CSV fixture had 607 columns but lacked the requested dedicated surface fields. | Both export implementations include the requested brightness and crack fields, raw measurements, reliability and validation status. A separate candidate CSV and XLSX sheet use one row per candidate. |

The reviewed material included the stored dashboard screenshot, fish feature example pixels, the legacy CSV fixture, the feature calculations, MobileSAM ownership checks, preview and processing paths, export code, and grading gates. Files named `lines_NOT_CRACKS` and proxy masks were not treated as expert crack ground truth. The initially untracked whole-fish feature module was preserved as a starting point, integrated, and corrected.

## Measurement and ownership behavior

Brightness is `100 × max(R,G,B) / 255` for every uniquely owned pixel. Its standard deviation is in percentage points. Histogram counts sum to the reported pixel count. No brightness-based exclusion removes dark fish pixels. Low, moderate and high labels remain unset because validated thresholds are unavailable. Yellowing and browning remain separate color measurements.

The native mask extent determines the analysis crop. Shared mask pixels, possible ownership by a neighboring fish whose mask failed, and masks containing conflicting anatomical evidence are withheld. Entirely ambiguous masks produce unavailable brightness and unassigned defect candidates. Coverage reports owned pixels divided by complete visible mask pixels. Clipped fish receive a partial-visibility reliability label. Mask ownership remains an engineering estimate unless separately reviewed.

The crack calculation combines masked local contrast at multiple scales, connected-component geometry, elongation, continuity, skeleton branches and endpoints, local width, original-image support on both sides, edges, texture variation, saturation and surrounding intensity. Repeated parallel structures are retained as rejected texture hypotheses. Local filtering excludes outside-mask pixels. Whole-fish masks and defect masks remain separate.

Exact row-run pixel encoding preserves thin regions that contours alone can lose. Candidate boundaries, numbering, type, heuristic strength, validation and exclusion reasons are inspectable. Length is native skeleton graph extent; area is retained native pixels; density is retained area divided by owned fish area. Fish totals measure the union of retained pixels so overlapping hypotheses cannot inflate total length or area. These quantities are not calibrated physical dimensions or biological damage severity.

Processing and preview use the same frame-scoped calculation. Source frame, parent identity, native dimensions and crop coordinates accompany the evidence. Display controls reuse completed evidence. A 256-candidate limit bounds processing; omissions explicitly lower detection reliability and are exported.

## Test results

The regression run passed **890 tests and 17 subtests**, covering surface features, masks, ownership, previews, exports, persistence, structural evidence and grading. The focused surface suite passed **38 tests**, including exact brightness statistics, background invariance, irregular and branching defects, tips, connected spots, ambiguous ownership, missing neighbors, stale sources, invalid masks, export agreement, candidate-limit reporting, and preserving brightness when optional crack processing fails.

The benchmark contains **42 synthetic scenes**, with exact drawn pixel truth: 21 positive and 21 negative images. It includes isolated fish, three lighting levels, noise, spots, rings, discoloration, shadows, repeated texture, curved and branching splits, tip defects, faint defects, and a crack touching a spot. The before/after comparison supplies identical fish masks to the old and new image algorithms. It does not compare independently reviewed real specimens or measure MobileSAM segmentation accuracy.

| Synthetic metric | Older image algorithm | Updated image algorithm |
| --- | ---: | ---: |
| Positive images with a detection | 11 / 21 | 17 / 21 |
| Positive images completely missed | 10 / 21 | 4 / 21 |
| Negative images with a false detection | 0 / 21 | 0 / 21 |
| Correctly retained crack pixels | 8,505 | 12,167 |
| Missed crack pixels | 6,708 | 3,046 |
| Extra non-crack pixels | 1 | 20 |
| Pixel precision | 99.99% | 99.84% |
| Pixel recall | 55.91% | 79.98% |

All 12 positive scenes in the basic three-lighting group retain a candidate; all 18 negative scenes in that group remain black. Pixel recall within that group is 99.48%, reflecting some trimming at ends and junctions. The four complete misses have only 8/255 intensity contrast, below the engineering filters. The 20 extra pixels occur where a crack touches a spot. Synthetic brightness error is at most approximately `4.3e-14` percentage points, from floating-point arithmetic.

Real CPU Model 1, Model 2, MobileSAM, HTTP and Chrome verification passed **22 browser checks**. With the registered Model 1 checkpoint restored, the crowded photograph contains nine detector instances and all nine receive brightness measurements. All nine match independent recomputation from original decoded pixels with reported error **0.0 percentage points**. Retained crack pixels outside the owned mask total **zero** for every measured fish. Ambiguous-mask abstention is verified separately in controlled tests. These checks establish consistency with the supplied masks, not independently verified fish segmentation or biological crack accuracy.

Browser checks also verify non-overlapping labels for all nine instances, selected-fish clipping, strictly black/white pixels, no white pixels for the isolated dark-spot fixture, localized red overlay, grayscale controls, candidate details, CSV agreement and stale-source clearing. Mobile layout has a 390-pixel viewport and 390-pixel document width. The real analysis calls Model 1 once, Model 2 once, shares one SAM image embedding across nine prompts, and makes zero GrabCut calls. View changes cause no new model calls.

## CSV and grading integration

The per-fish CSV retains one row per fish. Its candidate columns contain aligned JSON arrays. The inspection viewer's **Export brightness and crack candidates CSV** button, backend `format: "surface_csv"`, and the XLSX **Surface Candidates** sheet provide scalar candidate rows. They include rejected and uncertain hypotheses; unassigned ownership stays empty. Each row includes frame and crop coordinates, units and confidence interpretation. Candidate evidence is stored once per row rather than repeating every candidate in every row.

All requested fields are present: `fish_id`, `mean_brightness`, `median_brightness`, `brightness_std`, `brightness_percentiles`, `brightness_pixel_count`, `brightness_mask_coverage`, `crack_candidate_id`, `crack_candidate_type`, `crack_confidence`, `crack_length`, `crack_width`, `crack_area`, `crack_density`, `crack_aspect_ratio`, `crack_skeleton_length`, `crack_owner_fish_id`, `crack_validation_status`, and `crack_exclusion_reason`.

Raw and calibrated measurements remain separate. Absent calibration is represented as null. Confirmed counts remain zero for these unvalidated detector outputs. Rejected-hypothesis counts are not ground-truth false-positive counts. Candidate measurements from other categories must not be summed as confirmed cracks. Source owner IDs and frame provenance remain available in complete candidate evidence, including where a display renumbers a fish.

The configured final weights remain Model 2 **70%**, size **15%**, cracks **5%**, color **5%**, and texture **5%**. Internal anatomical weights and trained classifiers are preserved. New surface diagnostics set `used_for_grading: false`; missing masks, unreliable ownership, absent candidates and uncalibrated measurements award or deduct no points. Existing reviewed-evidence gates remain responsible for any calibrated contribution. Offline replay retains uncalibrated fusion metadata and refuses calibrated replay without its frozen artifact and source-bound measurements.

All **24 pre-existing configuration/model files** in the integrity snapshot have unchanged hashes. No model was retrained. The missing MobileSAM dependency was restored from the repository's official download utility, verifying SHA-256 `6dbb90523a35330fedd7f1d3dfc66f995213d81b29a5ca8108dbcdd4e37d6c2f`. The Model 1 file declared in the registry was also absent; its exact bytes were copied from the existing Downloads deployment and verified against registered SHA-256 `c79f597c2ed51b45ac2911cdbc744f8d2a4bea2411efc6a6ec0d4bcab35901e2`. This restores the configured detector rather than relying on the older fallback file. No existing detector file or registry entry was overwritten. Separate grading-fusion edits present in the shared workspace were retained and checked for compatibility.

## Remaining limitations

Independent real-fish crack and instance-mask annotations are still required to establish biological precision, recall, ownership accuracy and grade calibration. The current evidence does not justify calling every split-like mark an actual fracture, a rejected hypothesis a proven false positive, or an empty mask proof of an undamaged fish. Real-image candidate counts are review workload, not measured accuracy.

Faint defects can be missed, and some touching-spot pixels remain included. Scales, wrinkles, long dark marks and unusual lighting can resemble splits. Incorrect pixels inside a SAM silhouette can still contaminate mask-conditioned measurements; outside-mask exclusion does not validate the silhouette itself. Occluded fish surfaces are not reconstructed. Pixel geometry requires a validated capture calibration before physical-unit reporting. Dense scenes can hit the candidate limit. The recorded CPU still-image run took approximately 12.15 seconds for nine fish, including approximately 4.38 seconds in structural diagnostics and associated lookups; nested timings must not be summed. This is not a live-throughput benchmark.

Software measurement, display, ownership safeguards and export agreement are verified within the tested conditions. Full real-specimen accuracy acceptance and automatic brightness/crack grading remain open pending independent labels and calibration.

## Reproduction and evidence

The existing dashboard on port 8000 serves the older Downloads checkout; its JavaScript bytes match that checkout and do not contain the new brightness monitor. The repaired source is in this V2 workspace. The [V2 review dashboard](http://127.0.0.1:8001) uses CPU inference and an isolated QA database, keeping the older process and its inspection data intact. Both registered models are ready with strict integrity checks enabled. The JavaScript and stylesheet asset versions change with this UI release to avoid stale browser code.

From `Thesis/sardinella-lemuru-ml`:

```powershell
py -m pytest tests/test_fish_surface.py -q --basetemp results/qa/surface_repeat_tmp
py tests/evaluate_surface_features.py
py tests/surface_features_browser_smoke.py
```

For supplied expert crack annotations, the evaluator also accepts `--manifest path/to/manifest.json`. Each case supplies `id`, `image_path`, `fish_mask_path`, `crack_mask_path`, and optionally `fish_id` and `condition`; paths resolve relative to the manifest. Images and masks must already share native dimensions. Crack truth outside the owned fish mask is rejected. This evaluator measures the detector given those masks and does not validate SAM ownership automatically.

- [Detection metrics and per-case results](C:/Users/User/Tamban_Thesis_Main_Repository_V2/Thesis/sardinella-lemuru-ml/results/qa/surface_features/detection_metrics.json)
- [Per-case confusion CSV](C:/Users/User/Tamban_Thesis_Main_Repository_V2/Thesis/sardinella-lemuru-ml/results/qa/surface_features/detection_cases.csv)
- [Actual photograph fish measurements CSV](C:/Users/User/Tamban_Thesis_Main_Repository_V2/Thesis/sardinella-lemuru-ml/results/qa/surface_features/actual_fish_measurements.csv) and [actual photograph candidate CSV](C:/Users/User/Tamban_Thesis_Main_Repository_V2/Thesis/sardinella-lemuru-ml/results/qa/surface_features/actual_crack_candidates.csv)
- [Regression log](C:/Users/User/Tamban_Thesis_Main_Repository_V2/Thesis/sardinella-lemuru-ml/results/qa/surface_features/regression.log) and [selected test files](C:/Users/User/Tamban_Thesis_Main_Repository_V2/Thesis/sardinella-lemuru-ml/results/qa/surface_features/regression_selection.json)
- [Real model and browser evidence](C:/Users/User/Tamban_Thesis_Main_Repository_V2/Thesis/sardinella-lemuru-ml/results/qa/surface_features/browser/actual_e2e.json)
- [Actual photograph with measured labels](C:/Users/User/Tamban_Thesis_Main_Repository_V2/Thesis/sardinella-lemuru-ml/results/qa/surface_features/browser/actual_inspection.png)
- [Desktop comparison screenshot](C:/Users/User/Tamban_Thesis_Main_Repository_V2/Thesis/sardinella-lemuru-ml/results/qa/surface_features/browser/actual_preview_desktop.png) and [mobile screenshot](C:/Users/User/Tamban_Thesis_Main_Repository_V2/Thesis/sardinella-lemuru-ml/results/qa/surface_features/browser/actual_preview_mobile.png)
- [Binary crack fixture](C:/Users/User/Tamban_Thesis_Main_Repository_V2/Thesis/sardinella-lemuru-ml/results/qa/surface_features/browser/binary_cracks.png) and [red overlay fixture](C:/Users/User/Tamban_Thesis_Main_Repository_V2/Thesis/sardinella-lemuru-ml/results/qa/surface_features/browser/red_overlay.png)
- [Configuration and model integrity audit](C:/Users/User/Tamban_Thesis_Main_Repository_V2/Thesis/sardinella-lemuru-ml/results/qa/surface_features/integrity_audit.json)
- [Restored registered Model 1 dependency](C:/Users/User/Tamban_Thesis_Main_Repository_V2/Thesis/sardinella-lemuru-ml/results/qa/surface_features/restored_model1_dependency.json) and [local review runtime](C:/Users/User/Tamban_Thesis_Main_Repository_V2/Thesis/sardinella-lemuru-ml/results/qa/surface_features/review_runtime.json)

Generated QA artifacts stay under the repository's ignored `results/qa` directory. The test and evaluator scripts, implementation and this audit are reviewable source files.
