# Fixbody audit, implementation, and validation record

The inspection pipeline now reuses foreground diagnostics within a frame, provides native-pixel geometry and correctly positioned evidence overlays, filters weak surface-line evidence, bounds video-job retention, and reports actual compute configuration. The continued audit also isolates optional mask failures from grading and rejects malformed damage localization consistently across evidence cards and exports. The final regression is **1,199 passed, 12 skipped, zero failures**. Existing model checkpoints, detection thresholds, grade weights, confidence safeguards, and Ungraded conditions remain in place. These changes establish tested software behavior; they do not establish fish-measurement accuracy or biological defect-detection accuracy.

The machine-readable outcome is [summary.json](../results/qa/fixbody/summary.json). The baseline was frozen before production edits in [baseline_source.zip](../results/qa/fixbody/baseline_source.zip), with its hash and 132-file manifest recorded in [baseline_manifest.json](../results/qa/fixbody/baseline_manifest.json). The [seven-record inspection CSV](../results/qa/body_width/fish-inspection-upload-all.repaired.csv) was used as diagnostic and grading-regression evidence; its audit is retained in [upload_csv_width_audit.json](../results/qa/body_width/upload_csv_width_audit.json). Its original source photograph was unavailable, so its missing segmentation or defect evidence was not reconstructed or invented.

## 1. Issues found and changes applied

| Finding and cause | Implemented behavior |
| --- | --- |
| Full-frame Model 2 grading received `fish_mask=None`, while API damage analysis separately generated a runtime GrabCut mask. Texture therefore reported `no_validated_fish_mask_in_runtime` despite a mask existing elsewhere. Identical crops could be segmented repeatedly. | A frame-local `RuntimeMaskContext` shares exact-parent foreground masks and diagnostic features. Keys contain parent ID, exact integer crop bounds, and a pixel digest. Failed results are cached; returned arrays are immutable and metadata is copied. Frame identity and edited pixels are checked, preventing equal-sized crops or reused track IDs from sharing unrelated evidence. |
| Measurement padding and grading/damage ROIs have different origins. Blind mask reuse could truncate silhouette tips or attach another crop's evidence. | Preserve the padded measurement ROI: padding is at least 8 pixels or 6% of the parent's long dimension. Full-frame analysis can project its foreground into a contained exact crop without resizing, after parent, frame, retained foreground, component, boundary, and area checks. Existing target entries, including failures, are preserved. An uncertain projection falls back to segmentation of the exact target. Source-padding edits invalidate dependent masks and features. |
| Shared foreground availability could silently alter historical rectangular HSV diagnostics. Their old caption also overstated foreground validation. | A separate texture-mask input supplies the missing texture evidence. Historical HSV pixel scopes and values remain unchanged. Whole-fish color diagnostics now explicitly identify a rectangular, unvalidated foreground scope where no original HSV foreground mask was used; separately available texture masks do not imply masked color analysis. |
| Surface evidence used edge components, component counts, and global texture density as confidence. Empty/not-detected results still displayed “Suspected Damage”; component boxes were treated as crack length, and severity had no reference labels. | Require elongated interior dark-line evidence and two-sided contrast on original RGB pixels. Exclude boundaries/thin features and reject short, broad, unsupported, and repeated aligned patterns. Report “No reliable evidence” or “Suspected Damage,” with uncalibrated heuristic strength, unassessed severity, and supported line extent. No automatic output validates damage or changes grades. Duplicate full texture extraction was removed; exact integer histogramming preserves GLCM counts. |
| Damage overlays used padded grading bounds, while quality overlays could use damage bounds. Saved live part coordinates could remain local despite being presented as frame coordinates. | Use the correct origin for each overlay. Save live part boxes and polygons in original-frame coordinates while retaining explicitly named crop-local coordinates. Geometry axes, endpoints, and boundaries carry original-frame provenance; damage boxes retain crop-local coordinates plus translated frame boxes. Renderer inputs retain their expected local coordinates. |
| The UI could describe a missing crack-validation flag as “Validated,” claim texture was unavailable without reading runtime evidence, and eagerly stringify large raw records. | Require explicit validation status, crack-validation flag, localized evidence, and validation provenance for a validated display. Show actual texture availability, failure reasons, support extent, timing, hardware, and precision. Generate raw JSON on expansion and pause video preview swapping when hidden, preserving analyzed frames. Export appended evidence/provenance fields without changing established grade-field order. |
| Uploaded-video greedy matching could assign multiple detections to one track. Unrestricted job threads and indefinite full-result retention increased memory use. | Assign a whole frame one-to-one with the existing IoU acceptance threshold. Reserve receiving/queued/running capacity before reading an upload. Default per-process limits are 2 active jobs, 4 retained terminal results, and 1,800-second terminal expiry. Invalid uploads, cancellation, thread-start errors, and worker errors release capacity; active jobs are never evicted. Existing annotation-frame limits and model/service locks remain. |
| CUDA availability automatically allowed FP16 without representative checkpoint-specific numerical acceptance. Repeated status probes also added avoidable work. | Keep CUDA with explicit CPU fallback and reuse loaded model compute reports. FP16 remains disabled, including when requested, until model-specific validation exists. The existing model instances, resolutions, full-frame Model 2 workflow, locking, and required processing remain active. |
| Eager crop-mode mask generation in still and live callers ran before optional-diagnostic exception handling. A failed mask algorithm could prevent Model 2 grading. | After strict frame/ROI checks, cache failed extraction as unavailable with error type, native crop provenance, and timing. Same-frame callers reuse the failure; the next frame can retry. Still/live and crop/full-frame tests preserve exact IDs, grades, support, parts, weights, and reasons. Invalid caller scope still raises. |
| Nonempty `locations`, including `[{}]`, could produce a damage label without usable coordinates. Empty object or whitespace provenance also differed between Python and JavaScript. | Require finite numeric pixel rectangles with nonnegative origins, positive size, and containment within recorded crop bounds. Reject booleans, numeric strings, overflow, and malformed bounds. One frontend interpretation serves the evidence panel, feature summary, zoom details, CSV, and PDF; backend CSV/XLSX applies the same contract. Blank/empty provenance cannot validate damage. Raw evidence remains intact and grading is unchanged. |

Model 1 still detects whole fish and Model 2 supplies associated body/head/tail evidence. No retraining, checkpoint replacement, model downgrade, input-resolution reduction, or grading-rule rewrite was performed. Body/head/tail weights remain 50%/30%/20%; existing conditional tail-weight redistribution and abstention safeguards remain unchanged. Width and crack evidence have no automatic grade penalty.

## 2. Before-and-after processing measurements

### Controlled software replay

[before.json](../results/qa/fixbody/before.json) and [after.json](../results/qa/fixbody/after.json) use the same synthetic images and scripted model detections. [paired_software.py](../results/qa/fixbody/paired_software.py) runs frozen/current source in `before1, after1, after2, before2` order, with one OpenCV thread and initial RNG seed 0 in each worker. Image/component rows pool two runs of five measured repetitions after warm-up. Video pools two runs of three measured repetitions; the temporal row summarizes two four-frame replays.

| Software scenario | Before ms | After ms | Observed latency reduction |
| --- | ---: | ---: | ---: |
| Image, crop mode, clean scene | 139.84 | 94.10 | 32.71% |
| Image, crop mode, dark-line scene | 149.00 | 94.63 | 36.49% |
| Image, full-frame mode, clean scene | 97.83 | 67.71 | 30.78% |
| Image, full-frame mode, dark-line scene | 102.72 | 67.88 | 33.91% |
| Scripted four-frame video | 828.29 | 559.20 | 32.49% |
| Four-frame temporal quality replay | 281.48 | 275.13 | 2.26% |

All compared software grading signatures match. Counts in each worker include its warm-up: crop-mode image calls decrease from 18 to 12 segmentations and 12 to 6 texture extractions across six calls; full-frame calls decrease from 12 to 6 segmentations, while texture extraction remains 6. Required stages were preserved; the reductions come from scoped reuse and removal of duplicate work.

Damage-component medians are 11.1056 to 1.1260 ms for the clean scene, 11.0838 to 2.4901 ms for the dark line, and 9.6225 to 7.6613 ms for stripes. The [damage validation record](fixbody_damage_validation.md) explains intentional evidence-method differences. Original unpaired runs remain archived separately and are excluded from these tables.

These are controlled software timings with scripted detections, not field throughput, measured live-camera FPS, or model accuracy. Raw samples, p95 values, and controls are retained in the JSON files; the small sample sizes do not establish statistical significance or performance across all fish scenes.

These benchmark tables describe the initial optimization stage. The continuation repairs failure handling and evidence interpretation; its regression and live replays do not establish a new throughput improvement.

### Same-GPU model-backed FP32 comparison

[before_fp32.json](../results/qa/fixbody/before_fp32.json) and [after_fp32.json](../results/qa/fixbody/after_fp32.json), reproduced by [paired_fp32.py](../results/qa/fixbody/paired_fp32.py), use the same known dataset image, checkpoints, NVIDIA GeForce RTX 2050, and FP32 precision. Each version has three timed samples after warm-up.

| Recorded measure | Before | After |
| --- | ---: | ---: |
| End-to-end median | 982.19 ms | 969.53 ms |
| Peak CUDA allocated memory | 405,712,384 bytes | 405,712,384 bytes |
| Peak CUDA reserved memory | 497,025,024 bytes | 497,025,024 bytes |
| Sampled peak process RSS | 1,497,411,584 bytes | 1,469,980,672 bytes |
| Process CPU, percent of one core over measured span | 99.97% | 99.60% |

The median difference is **1.29%**, with exactly equal signatures for all nine detections, boxes, associated parts, raw weighted scores, confidence values, and final grades. This one-image, three-sample result is a regression check with a small observed timing difference; it does not prove a general FPS improvement or meaningful memory/utilization improvement. GPU utilization samples are device-wide and coarse, can include background work, and cannot attribute utilization gains to individual stages.

An additional historical FP16/current FP32 comparison on this image retained nine detections and the same final classes, but raw weighted-score drift reached approximately 0.001023. One image is insufficient representative numerical validation, so production FP16 remains guarded off. This precision comparison is distinct from the same-FP32 equivalence result.

### Video identity correction and live verification

The model-backed repeated-still clip has two analyzed frames with unchanged per-frame detection counts of **9 and 10**. Unique reported tracks change from **8 to 10** after one-to-one assignment. This is an intentional association correction, not an increase in detection accuracy. No ground-truth fish identities exist for this clip. Its HTTP job wall time changes from approximately 2,200.69 to 2,461.69 ms; polling is quantized at 250 ms and precision/features differ, so it is not an isolated speedup benchmark.

[live_verification.json](../results/qa/fixbody/live_verification.json) records the backend at `http://127.0.0.1:8000`: both models ready on `cuda:0`, CUDA FP32 active, runtime texture available, and width/crack grading disabled. A real-image request returned nine detections with a signature matching the controlled FP32 reference. Historical seven-record IDs, timestamps, scores, and grades remained preserved: **2 Class B and 5 Ungraded**. Inspection was stopped and the camera disconnected; representative live fish-scene FPS was not measured.

## 3. Geometry and structural-evidence validation

Geometry continues to use the native-pixel fish silhouette, its principal axis, and perpendicular transverse sections in the associated Body region. A Body polygon can provide segmentation support; a Body detection box only identifies an approximate longitudinal region. Reliable geometry supplies fish length, maximum body width, width/length ratio, axis endpoints, and boundaries. Bounding-box dimensions remain separately identified approximations. Uncertain parent ownership, overlap, clipping, boundary contact, disconnected foreground, low resolution, irregular/curved profiles, or missing associated Body evidence retain explicit failure reasons and withheld measurements. Physical units require validated calibration.

The added work protects crop identity and coordinate transforms and exposes accepted axes and boundaries; it does not claim a new biologically validated measurement algorithm. Controlled rotated-silhouette tests cover 0, 30, and 90 degrees, native-frame axis placement, perpendicular width, rejection of unreliable overlays, and the distinct grading/damage ROI origins. Cache tests cover frame/parent isolation, in-place pixel changes, immutable results, failed-result reuse, conservative projection fallback, and padded-source dependency invalidation.

The available COCO test split contains 17 images and 225 annotations, with 216 rectangular polygons. These annotations are not independent anatomical silhouette, width/length, or crack references. The historical seven-record photograph is unavailable. Consequently, no measurement error distribution, crack precision/recall, or expert agreement is reported.

Surface analysis checks narrow interior dark-line continuity against the original RGB image. It returns **No reliable evidence** or **Suspected Damage**; automatic candidates remain unclassified surface discontinuities, with heuristic strength rather than damage probability and `severity="unassessed"`. Supported straight-line extent is not full curved crack length. **Validated Damage** requires separate explicit validation provenance and is never automatically generated by this feature. See [fixbody_damage_validation.md](fixbody_damage_validation.md) for thresholds, coordinates, controlled positive/negative fixtures, exact GLCM equivalence, and the 40-test feature result.

Feature-checked GrabCut masks remain software foreground estimates. They are not expert-validated anatomical masks or crack labels. The existing scientific readiness blocks, Prompt 11 requirements, and Deep 21 requirements remain in effect; this audit does not mark those stages complete or validate width/defect grading.

## 4. Regression results

The frozen baseline had **981 passed, 12 skipped, and 11 failed**. The initial fixbody run had **1,092 passed, 12 skipped, 11 failed, 127 subtests passed, and 9 warnings in 47.17 seconds**, preserved in [regression.initial_fixbody.log](../results/qa/fixbody/regression.initial_fixbody.log). The continued audit repaired those eleven stale tests and added failure/localization coverage. The final [regression.log](../results/qa/fixbody/regression.log) reports **1,199 passed, 12 skipped, zero failures, 127 subtests passed, and 7 warnings in 44.51 seconds**.

| Repaired failure group | Count | Cause and repair |
| --- | ---: | --- |
| `test_model_switch_safety.py` registry/model-selection mocks | 9 | Old mocks lacked the real `is_allowed_model2` checkpoint-admission contract. Spec-set registry doubles now expose registered IDs, admission, and compatibility. Existing active-inspection, worker, no-op, and concurrency assertions remain intact. |
| `test_feature_claims_qa.py::FeatureClaimsTests::test_interface_names_proxies_and_never_advertises_defect_capabilities` | 1 | Required retired belly-defect prose. Now executes the feature/evidence renderers and verifies diagnostic wording, unchanged model capabilities, and rejection of false validated-damage claims. |
| `test_session_totals_ui.py::test_session_totals_show_one_exclusive_bucket_per_counted_fish` | 1 | Looked for class cards in the runtime KPI renderer after they moved into the results dashboard. Now executes both renderers and verifies disjoint counts for empty data, all seven original fish, missing/unknown grades, and manual overrides. |

Added coverage verifies compute fallback and guarded precision; mask/feature cache validity; exact native coordinate transforms; diagnostic failure isolation from grades; one-to-one video association; video admission/expiry/error cleanup; export interpretation; and controlled damage/texture behavior. Existing source and new evidence tests preserve historical weighted grades. Concurrent user UI changes were retained, including click-target/zoom work and removal of the Graded count card; test stubs and optional-element handling were adapted without claiming that user work as this audit's contribution.

The continuation adds five mask-failure cases and 91 localization-contract tests. The latter execute Python CSV/XLSX and actual JavaScript evidence, feature, CSV, and printable-report paths, including malformed and nonfinite rectangles, local/original-frame bounds, mixed valid/invalid locations, and explicit review provenance. Raw diagnostic JSON, weighted grades, and support are preserved. Isolated JavaScript harnesses now load the shared interpretation helper; their grading/export assertions were retained.

The final [headless Chrome check](../results/qa/fixbody/browser.log) passed all seven records, API normalization, class-grouped expandable cards, recorded dates, mobile layout, lazy diagnostics, measurement/calibration gates, and the [51-page evidence PDF](../results/qa/body_width/fish-inspection-upload-all.repaired.pdf). JavaScript syntax and the scoped whitespace check passed. The loaded-backend verification is reproducible with [verify_live.py](../results/qa/fixbody/verify_live.py); it checks CUDA FP32, drained persistence, original seven-record grading, actual model-backed signatures, and truthful rectangular color-source labels without opening the camera or writing inspection history.

## 5. Remaining limitations and calibration requirements

- Real-fish anatomical measurement accuracy and crack/fracture/tear accuracy remain unvalidated. Natural markings, folds, narrow shadows, occlusion, repeated genuine defects, and boundary damage can still produce false candidates or missed evidence. No automatic crack labels, severity grades, or penalties are justified by the controlled tests.
- Physical calibration, independent reference lengths/widths, expert defect labels, and a representative evaluation split separate from threshold selection are still required. Curved fish need separately validated centerline measurements; overlap is withheld rather than resolved by fabricated geometry.
- Real-camera scene throughput, robust identity tracking in moving/overlapping fish, and representative model-specific FP16 numerical acceptance remain pending. The repeated-still clip has no identity ground truth, and the GPU timing sample is too small for general throughput claims.
- Video jobs are bounded per API process, not globally across multiple worker processes. Full retained annotation payloads, upload bytes, decode buffers, and transient copies still consume memory. No streaming-storage rewrite or removal of existing analyzed frames was introduced.
- The measured environment uses Python 3.14.6, PyTorch `2.14.1+cu130`, and OpenCV 5.0.0. Existing `requirements.txt` bounds OpenCV below 5; local verification does not certify every declared or future environment. No dependency declarations or model files were changed by these optimizations.

## 6. Files and setup

The following source files contain fixbody contributions. Frontend files also contain concurrent user edits, which were preserved. Tracked/generated bytecode is not an implementation deliverable.

| Area | Exact files |
| --- | --- |
| API coordination, live/still/video evidence, timings, bounded jobs | [src/api/app.py](../src/api/app.py), [src/api/camera.py](../src/api/camera.py), [src/api/image_analysis.py](../src/api/image_analysis.py) |
| Evidence exports | [src/api/export.py](../src/api/export.py) |
| Surface evidence and exact GLCM | [src/features/damage.py](../src/features/damage.py), [src/features/texture.py](../src/features/texture.py) |
| Compute precision, shared masks, Model 2 integration | [src/inference/compute.py](../src/inference/compute.py), [src/inference/preprocessing.py](../src/inference/preprocessing.py), [src/inference/yolo_quality_model.py](../src/inference/yolo_quality_model.py), [src/inference/grading_engine.py](../src/inference/grading_engine.py) |
| Geometry integration and native overlays | [src/inference/fish_geometry.py](../src/inference/fish_geometry.py), [src/inference/fish_geometry_pipeline.py](../src/inference/fish_geometry_pipeline.py), new [src/inference/frame_diagnostics.py](../src/inference/frame_diagnostics.py) |
| Evidence display, lazy raw JSON, preview scheduling | [frontend/app.js](../frontend/app.js), [frontend/index.html](../frontend/index.html) |
| Reproducible software evaluation | New [src/evaluation/fixbody_benchmark.py](../src/evaluation/fixbody_benchmark.py); archived replay helpers [paired_software.py](../results/qa/fixbody/paired_software.py), [paired_fp32.py](../results/qa/fixbody/paired_fp32.py), [capture_model_replay.py](../results/qa/fixbody/capture_model_replay.py) |

New tests are [test_fixbody_compute.py](../tests/test_fixbody_compute.py), [test_runtime_mask_context.py](../tests/test_runtime_mask_context.py), [test_fixbody_pipeline.py](../tests/test_fixbody_pipeline.py), [test_live_part_coordinates.py](../tests/test_live_part_coordinates.py), [test_video_job_limits.py](../tests/test_video_job_limits.py), [test_damage_reliability.py](../tests/test_damage_reliability.py), [test_texture_histogram.py](../tests/test_texture_histogram.py), [test_fixbody_evidence_exports.py](../tests/test_fixbody_evidence_exports.py), [test_mask_failure_isolation.py](../tests/test_mask_failure_isolation.py), and [test_damage_localization_contract.py](../tests/test_damage_localization_contract.py).

Existing test files adjusted are [test_upload_control_ux.py](../tests/test_upload_control_ux.py), [body_width_browser_smoke.py](../tests/body_width_browser_smoke.py), [test_model_switch_safety.py](../tests/test_model_switch_safety.py), [test_feature_claims_qa.py](../tests/test_feature_claims_qa.py), [test_session_totals_ui.py](../tests/test_session_totals_ui.py), [test_body_width_exports.py](../tests/test_body_width_exports.py), [test_fish_geometry_exports.py](../tests/test_fish_geometry_exports.py), and [test_upload_csv_width_frontend.py](../tests/test_upload_csv_width_frontend.py). The [export refresh helper](../results/qa/fish_geometry/refresh_exports.py) also loads the shared frontend evidence helper.

This report and [fixbody_damage_validation.md](fixbody_damage_validation.md) document the work. Setup notes were appended to [README.md](../README.md), and independent fixbody notes were appended to [TAMBAN_DEEP_CODE_QA_PROGRESS.md](../TAMBAN_DEEP_CODE_QA_PROGRESS.md) and [TAMBAN_FINAL_POLISH_QA_PROGRESS.md](../TAMBAN_FINAL_POLISH_QA_PROGRESS.md), preserving their blocked scientific stages. `frontend/styles.css` changes belong to concurrent user work and are outside this audit's modifications. All `Model1_Retraining*` content was excluded from the work and left untouched.

No additional package is required by the new damage or mask algorithms; they use existing NumPy/OpenCV facilities. The video assignment uses SciPy already available through the existing scientific stack. Use the project's existing configured checkpoints and environment. For a fresh backend process from the project directory, the supported settings and entry point are:

```powershell
$env:FISH_DETECTOR_DEVICE = "auto"
$env:FISH_QUALITY_DEVICE = "auto"
$env:FISH_INFERENCE_FP16 = "off"
.venv\Scripts\python.exe -B -m src.api
```

`auto` selects CUDA where available and otherwise retains CPU execution with a reported fallback reason. The observed backend uses `cuda:0`; these environment examples do not change checkpoints or grading thresholds. FP16 cannot be approved merely through an environment request. Optional video limits are `FISH_VIDEO_MAX_ACTIVE_JOBS`, `FISH_VIDEO_MAX_COMPLETED_JOBS`, and `FISH_VIDEO_JOB_TTL_SECONDS`.

Reproduce the model-free regression and controlled software replay from the project directory:

```powershell
python -B -m pytest -q -p no:cacheprovider tests
node --check frontend/app.js
python results/qa/fixbody/paired_software.py
```

Pytest is a test-environment dependency rather than a new production dependency. The full regression command now passes with the twelve existing skips. The replay writes fresh controlled artifacts and preserves the initial unpaired records. The GPU replay additionally requires the recorded dataset image, unchanged registered checkpoints, a working CUDA environment, and `nvidia-smi`; its archived results remain available when those conditions are absent.

The final [source and artifact manifest](../results/qa/fixbody/final_manifest.json) lists exact paths and SHA-256 hashes for these implementation files, the evaluation helpers and evidence artifacts, and the refreshed seven-record browser/server exports and PDF. It records the tested working-tree contents rather than implying that the uncommitted changes are represented by the baseline Git commit.
