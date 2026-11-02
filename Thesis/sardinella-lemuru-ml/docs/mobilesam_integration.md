# Optional MobileSAM integration and validation report

Implemented from `notebooks/Featureenhance.md` on November 2, 2026. MobileSAM is
an experimental candidate-mask backend. GrabCut remains the default. Candidate
success, mask score, and engineering checks do not approve anatomical ownership,
measurements, cracks, or a grading change. Independent overlap and anatomical
validation is still required before primary-workflow activation.

## Audit and root findings

| Stage | Actual source and behavior | Finding and resulting change |
| --- | --- | --- |
| Whole-fish detection | `src/inference/yolo_fish_detector.py`, `YoloFishDetector.detect`; `fish_detector.py` supplies neutral detector types/protocols | Existing Model 1 V2 checkpoint and detector behavior are preserved. MobileSAM receives original-image boxes, rather than detector-network coordinates. |
| Model 2 and ownership | `src/inference/yolo_quality_model.py`, `predict_full_frame`; `src/inference/association.py` | Full-frame parts are already normalized globally and assigned conservatively before grading. MobileSAM adds a parallel shadow proposal; the active grader continues using the original association. Legacy crop adapters cannot establish full-frame part ownership and are reported conservatively. |
| GrabCut and caching | `src/inference/preprocessing.py`, `RuntimeMaskContext` | Earlier runtime work already shares masks and features per frame, parent, exact ROI, source-pixel digest, and settings. Different padded measurement and feature ROIs can still require separate work; a rectangular crop never guarantees instance isolation during overlap. The new backend uses one full-frame SAM embedding and sequential fish prompts. |
| Geometry | `src/inference/fish_geometry_pipeline.py`, `src/inference/fish_geometry.py` | Existing PCA and transverse-width calculations can consume mask pixels, but native output resolution alone does not establish a correct boundary. Experimental SAM outputs remain estimates; final metrology and physical fields are withheld. Non-GrabCut contexts cannot silently invoke additional GrabCut when a source context is missing. |
| Image features and damage | `src/inference/frame_diagnostics.py`; quality-model feature path | Whole-fish mask support is insufficient evidence for Body-only crack localization. Ordinary Model 2 Body rectangles are not validated Body masks. SAM-mode damage processing requires separately reviewed Body pixel support; otherwise it reports unavailable reliable evidence. Rectangular RGB/HSV diagnostics retain their existing scope. |
| Optional Tail | `src/inference/yolo_quality_model.py`, association summary handling | A global ambiguity flag previously vetoed the optional-Tail grading mode even when only Tail was ambiguous. The mode now vetoes ambiguous required Head/Body, while ambiguous Tail is excluded and Body/Head redistribute to 62.5%/37.5%. Other grading modes retain their existing ambiguity behavior. This compatibility repair is separate from SAM mask quality. |
| Image/video/live | `src/api/image_analysis.py`; `src/api/camera.py` | Still images can request SAM explicitly. Video samples SAM at a bounded analyzed-frame interval and uses geometry-only processing between samples. Live camera retains its existing Model 2 schedule; contexts are frame-local and masks are never propagated as verified identities across frames. |
| UI/export provenance | `frontend/app.js`, `frontend/index.html`, `src/api/export.py` | The old estimate guard recognized only `bounded_working_grid`, hiding the new `mobilesam_candidate` measurements. Both explicit estimate modes now render/export while remaining unvalidated. Overlays require matching parent, frame, and native dimensions. Video mask snapshots keep their own preview, box, and parts. New fields append candidate provenance, timings, and shadow evidence. |

GrabCut is CPU work in this implementation. Existing CUDA detector timings did
not imply GPU segmentation. `stage_metrics.py` now reports the selected backend
explicitly. Neither image-encoder speed nor a successful segmentation call is a
measurement of end-to-end inspection improvement.

## Checkpoint, supported API, and setup

The optional model is MobileSAM Tiny-ViT, using the documented
[Ultralytics MobileSAM interface](https://docs.ultralytics.com/models/mobile-sam/)
and [SAM predictor](https://docs.ultralytics.com/reference/models/sam/predict/).
The upstream architecture is documented in the
[official MobileSAM repository](https://github.com/ChaoningZhang/MobileSAM).
No heavy SAM model, training job, detector replacement, or annotation edit is
introduced.

| Item | Value |
| --- | --- |
| Local checkpoint | `models/experimental/mobilesam/mobile_sam.pt` |
| Download | [Official Ultralytics v8.4.0 asset](https://github.com/ultralytics/assets/releases/download/v8.4.0/mobile_sam.pt) |
| File size | 40,728,226 bytes; disk size is not a VRAM measurement |
| SHA-256 | `6dbb90523a35330fedd7f1d3dfc66f995213d81b29a5ca8108dbcdd4e37d6c2f` |
| Metadata | `models/experimental/mobilesam/checkpoint.json` |
| Precision | FP32; FP16 activation is not implemented or validated |

From the project root, use an existing suitable environment:

```powershell
python -m src.evaluation.download_mobilesam_checkpoint
```

The helper downloads only the optional asset, verifies its expected digest,
and refuses to replace an existing mismatched file. Runtime loading also checks
the digest before model construction. No dependency was installed or changed for
this task. The implementation uses the existing `torch`, `ultralytics`, `numpy`,
and OpenCV packages; a separate `mobile_sam`/`timm` installation is unnecessary
for this adapter. An incompatible installed predictor is reported as unavailable
rather than silently discarding the shared embedding.

The observed CPU-validation environment was Python 3.14.6 on Windows, PyTorch
2.11.0+cu128, torchvision 0.26.0+cu128, Ultralytics 8.4.197, NumPy 2.5.4, and
opencv-python 5.0.0.93. The installed Torch wheel supports CUDA, but these runs
explicitly selected CPU and hid CUDA devices. Those observations are not a
clean-install compatibility guarantee for other package versions.

## Runtime interface and resource controls

`src/inference/mobilesam_backend.py` exposes `MobileSamSettings` and the
process-wide `get_mobilesam_service()` singleton. Importing the module or reading
status does not load the model, initialize CUDA, or encode an image. A frame with
no fish does not load MobileSAM. Configuration changes after service creation
require an explicit application restart rather than creating duplicate models.

A locked `open_frame(image_bgr, frame_key)` session computes one embedding on
the first valid prompt. Each `predict(parent_id, bbox_global, ...)` reuses that
embedding. Calling the Ultralytics predictor with `source=None` is essential:
passing the image again would reset its source and invalidate embedding reuse.
An actual image-encoder forward hook verifies reuse in the real checkpoint
probe. Prompt caches include parent ID, box, detection version, and reviewed
point prompts. Frame keys include a digest of all source pixels; editing pixels
outside a fish crop also invalidates the full-image embedding.

The supported predictor performs prompt scaling and returns a native-size
binary mask. The service checks exact original-frame shape, records source and
clipped prompt boxes, frame identity/digest, parent ID, checkpoint hash, device,
precision, and timings, and returns immutable masks. Feature consumers receive
explicit native-pixel ROI projections. Temporary frame state is released at
session exit; the lazily loaded predictor remains available for future frames.

| Setting | Default | Meaning |
| --- | --- | --- |
| `SEGMENTATION_BACKEND` | `grabcut` | `grabcut`, `mobilesam_experimental`, or `geometry_only`; invalid names are rejected |
| `MOBILESAM_CHECKPOINT` | path above | Optional checkpoint path; the official digest remains required by environment configuration |
| `MOBILESAM_DEVICE` | `cpu` | `cpu`, `auto`, `cuda`, or `cuda:N` |
| `MOBILESAM_MIN_FREE_GPU_MB` | `1024` | Device-wide free-memory preflight requirement |
| `MOBILESAM_GPU_BUDGET_MB` | `1024` | Additional free-memory requirement; not a hard allocator limit or reservation |
| `MOBILESAM_MAX_PROMPTS` | `32` | Maximum uncached fish prompts per frame |
| `MOBILESAM_VIDEO_FRAME_INTERVAL` | `5` | SAM once per five analyzed video frames; intervening frames use geometry-only processing |
| `MobileSamSettings.maximum_cached_mask_bytes` | 128 MiB | In-process cached native-mask limit; currently a Python setting rather than an environment variable |

An explicit GPU request checks `nvidia-smi` free memory before CUDA model work
and checks pressure again before encoding. Missing preflight information,
unavailable CUDA, insufficient free memory, or supported out-of-memory paths
fall back to CPU and record the reason. Predictor access and prompts are
serialized, and inference uses `torch.inference_mode()`. The GPU budget cannot
reserve memory against another process and is not a global limit for Model 1 or
Model 2. CPU fallback controls failure behavior; it does not guarantee real-time
latency. A missing checkpoint or failed CPU inference reports unavailable
candidates and preserves the already computed weighted grade. SAM mode does not
also run GrabCut; only the comparison harness explicitly runs both backends.

`GET /api/segmentation/status` reports lazy setup and load state. Image
`POST /api/analyze-image` and video `POST /api/analyze-video` accept optional
`X-Segmentation-Backend: mobilesam_experimental`; no header retains the server
default. Video polling remains `GET /api/analyze-video/{job_id}`. Unknown backend
names return HTTP 422 before inference. Analyze Media exposes an unchecked
advanced option that sets this header for that single analysis.

The production full-frame live-camera path uses the configured backend only on scheduled Model 2 work; the
existing quality interval defaults to three frames and other existing skip
conditions still apply. No tracking-based SAM mask propagation is implemented.
The legacy crop-only camera adapter does not prepare a globally associated SAM
candidate batch and is unsupported for candidate isolation; it must not be
treated as equivalent to the full-frame path. Camera compatibility is tested
with model-free fixtures, rather than actual live-camera GPU operation.
Uploaded video keeps a diagnostic source-frame snapshot separately from the
best grading frame and records both the stable video Fish ID and source
detection ID. The preview is capped at 1024 pixels along its longest side;
overlay coordinates remain native original-frame pixels.

## Candidate ownership, geometry, and damage safeguards

`src/inference/mask_ownership.py` checks binary shape, parent/frame/prompt
identity, foreground size, connected components, holes, PCA elongation,
boundary clipping, target support, neighboring exclusive pixels, pairwise mask
conflicts, own required anatomy, and neighboring assigned Head/Body coverage.
Engineering rejection settings are exposed through `MaskOwnershipConfig`; they
are not fabricated class-calibration ranges. SAM mask score is diagnostic and
never participates in approval. See [the ownership contract](mobilesam_ownership.md)
for details.

Candidate outcomes are `unavailable`, `rejected`, `ambiguous`, or
`checks_passed_unvalidated`. Every outcome retains
`ownership_validated=false`, `approved_for_grading=false`,
`measurement_validated=false`, and `mask_validated_for_cracks=false`.
Mask-assisted part assignments are `PROPOSED`, `AMBIGUOUS`, or `UNASSIGNED`
shadow records, assign each physical candidate to at most one parent, and are
never sent to the active weighted grader. Raw detector parts and confidence
values remain available.

Reviewed original-frame anatomical pixel masks/polygons can be supplied through
`RuntimeMaskContext.prepare_instances(..., trusted_parts=...)`. The helper
requires matching parent, explicit review/validation provenance, and reliable
orientation before deriving positive or negative point prompts. Ordinary
detector rectangles supply no invented anatomical center points. There is no
new user-facing expert annotation workflow and no reviewed fish mask was
created by this task.

The existing geometry path estimates the longitudinal PCA axis, fish extent,
transverse profiles, maximum and central Body width, and ratios from suitable
mask support. A SAM engineering-pass mask can supply an explicitly unvalidated
estimate. Occluded visible width is not true hidden anatomical width. Final
reliable metrology and centimeter fields remain withheld for experimental
SAM masks, including when a separate physical scale is configured. Width
supporting points remain uncalibrated and contribute zero to classification.

The Body-support hook requires separately reviewed Body pixels and at least 95%
retained support after intersection with the current candidate. It never grows
a Body rectangle into anatomical ground truth. Normal detection-only SAM
analysis therefore reports no trustworthy Body mask for crack localization.
Dark lines, texture, shadows, and neighboring edges are not confirmed defects;
no crack contribution to grading is enabled. Reviewed localization examples are
still required to evaluate any detection improvement.

Active weighted grades remain Body 50%, Head 30%, Tail 20%; required Head/Body
uncertainty remains Ungraded. Optional-Tail redistribution is 62.5%/37.5% in
`tail_optional_v1`. No detector thresholds, confidence values, model weights,
class-width ranges, physical calibration, or structural grading rule were
changed.

## Measurements and visual examples

The frozen pre-integration source and test record are
[`baseline_source.zip`](../results/qa/mobilesam/baseline_source.zip),
[`baseline_manifest.json`](../results/qa/mobilesam/baseline_manifest.json), and
[`baseline_tests.log`](../results/qa/mobilesam/baseline_tests.log). Baseline:
1,282 passed, 12 skipped, zero failures, 127 subtests in 39.67 seconds.

The real checkpoint [CPU probe](../results/qa/mobilesam/backend_cpu_probe.json)
uses one warmup and two measured repetitions per case, FP32, one CPU thread:

| Case | End-to-end session wall time | Embedding | Prompt decoding | Encoder calls |
| --- | --- | --- | --- | --- |
| Two controlled ellipses, two prompts | 777.29–787.45 ms | 678.70–680.18 ms | 94.83–104.51 ms total | Exactly one per frame |
| Recorded clipped Fish #5, original 3840×2160 photo | 814.93–909.85 ms | 671.43–759.92 ms | 68.70–70.38 ms | Exactly one per frame |

These are checkpoint/API smoke measurements, not fish-isolation accuracy or
complete two-model inspection times. The ellipses are synthetic controls. Fish
#5 has no reviewed reference mask and its candidate touches the image boundary.
Its approximately 0.958 model score does not validate ownership or metrology.
GPU peak memory is **not measured**, because all validation in this task ran on
CPU while a separate training workload could use the GPU. No RTX 2050 latency,
GPU out-of-memory hardware test, FP16 benefit, or speedup is claimed.

The matched comparison harness is
[`src/evaluation/evaluate_mobilesam.py`](../src/evaluation/evaluate_mobilesam.py).
The [scenario manifest](../results/qa/mobilesam/scenario_manifest.json) and
[full measured results](../results/qa/mobilesam/benchmark.json) cover ten scenes
and 56 prompted detections, with per-scenario `.comparison.png` visualizations.
The harness uses unchanged real Model 1 V2/Model 2 CPU inference once per
scenario and replays fixed outputs across GrabCut, MobileSAM, and geometry-only
processing, including one warmup and three measured repetitions. Natural images
and controlled transformations are identified separately. Engineering-pass mask
counts are not ownership-accuracy percentages. Expert instance masks,
ownership labels, crack labels, and anatomical measurements are unavailable;
those accuracy/localization outcomes must be recorded as unmeasured.

The first three scene timings were replayed after the concurrent regression
suite ended; the JSON retains this timing provenance and the separately observed
single detector passes. The following values are medians in milliseconds;
`wall / segmentation` separates post-detection pipeline wall time from the
enclosed segmentation stage. Geometry-only segmentation time is zero. These
values exclude model loading, the fixed neural detector/part pass, file I/O,
decode, network transport, and browser rendering. Annotation and JPEG output
encoding inside the analyzer are included.

| Scene | Detections | GrabCut wall / segmentation | MobileSAM wall / segmentation | Geometry-only wall |
| --- | ---: | ---: | ---: | ---: |
| Natural multi-fish | 9 | 1,610.20 / 1,431.19 | 1,679.68 / 1,370.07 | 143.93 |
| Severe overlap | 6 | 1,006.59 / 890.25 | 1,381.28 / 1,152.23 | 102.84 |
| Touching pair and neighboring detections | 3 | 443.39 / 391.26 | 1,043.84 / 972.79 | 48.08 |
| Visible surface-damage example | 4 | 493.16 / 434.63 | 1,238.84 / 1,098.60 | 44.42 |
| Derived dark lighting | 9 | 1,003.42 / 880.62 | 2,125.14 / 1,859.54 | 102.85 |
| Derived uneven lighting | 7 | 1,398.51 / 1,282.32 | 1,544.03 / 1,334.43 | 98.39 |
| Derived clipping | 4 | 333.01 / 289.54 | 1,792.32 / 1,706.11 | 63.80 |
| Narrow crop retaining neighboring evidence | 2 | 153.87 / 126.38 | 1,818.15 / 1,774.69 | 28.04 |
| Recorded reproduction photo, resized 1280×720 | 11 | 8,392.71 / 7,724.43 | 2,187.34 / 1,266.42 | 627.33 |
| Rotated clean isolated-fish crop | 1 | 180.44 / 155.55 | 900.48 / 878.88 | 21.58 |

SAM was slower in nine of ten post-detection scene comparisons. The larger
reproduction photo improved in CPU wall time, but none of its candidates passed
all ownership checks. The isolated crop contains a visibly complete single fish;
Model 2 detected Head and Tail but no required Body, so it remained Ungraded.
There is no demonstrated improvement in grading coverage.

All ten frames had exactly one actual SAM encoder call despite multiple prompts,
and SAM paths executed no GrabCut. SAM generated 56 candidates: two passed
engineering checks while remaining unvalidated, 25 were ambiguous, and 29 were
rejected. GrabCut retained 23 cached candidates: two engineering passes,
11 ambiguous, ten rejected, and 33 unavailable. These counts measure software
gate outcomes, not correct/incorrect separation or fish-detection accuracy.
Natural examples include Head and Tail boxes inside competing parent rectangles;
their recorded associations remain unverified against expert ownership labels.

All 56 weighted signatures and assigned-part evidence matched across backends;
four scene-specific detections were graded in each backend. These are not four
distinct physical fish across the derived images. SAM produced only two candidate
width estimates, zero centimeter measurements, and zero width grading
contributions. Crack evidence was unavailable for all 56 SAM candidates because
no reviewed Body pixel support was supplied. Confirmed-crack and localization
accuracy were not established. Both protected detector checkpoint hashes matched
before and after the benchmark, and inference source hashes were unchanged
during the final measurement run.

The JSON's `estimated_total_with_single_detector_pass_ms` adds each backend's
post-detection wall median to the separately measured M1 and M2 CPU passes.
For natural multi-fish this estimate is 5,777.91 / 5,847.39 / 4,311.64 ms for
GrabCut / SAM / geometry-only; for the resized reproduction photo it is
8,890.46 / 2,685.10 / 1,125.09 ms. This arithmetic estimate is not a repeated
end-to-end upload latency or camera FPS measurement. Startup and model-loading
costs are recorded separately; GPU peak remains unavailable.

Before/after mask comparisons retain the original image with each backend's
candidate and engineering outcome:

- [Multiple fish](../results/qa/mobilesam/natural_multi.comparison.png)
- [Severe overlap](../results/qa/mobilesam/natural_severe_overlap.comparison.png)
- [Recorded reproduction photo](../results/qa/mobilesam/recorded_reproduction.comparison.png)
- [Clean isolated fish](../results/qa/mobilesam/isolated_clean.comparison.png)

Visual software review finds plausible whole-fish SAM boundaries in the clean
isolated example, but absent Body evidence still makes its ownership result
ambiguous. In the multi-fish image, one detector prompt covers the white image
border: SAM returns a broad background candidate and the engineering checks
reject it. These examples show why output success and apparent contour quality
cannot independently approve identity. This qualitative review is not an expert
mask annotation or an accuracy score.

The natural-photo and derived-scene source images, operations, hashes, detector
outputs, and original associations are retained in the QA artifacts. Original
external photos are local inputs; reproducing the detector pass elsewhere
requires those inputs or an explicitly documented substitute. The comparison
images do not supply independent instance-mask ground truth.
Additional methodology and qualitative review are recorded in
[`benchmark_review.md`](../results/qa/mobilesam/benchmark_review.md).

## UI, exports, and regression evidence

Analyze Media retains grouped Class A, B, C, Rejected, and Ungraded results,
with per-fish evidence disclosures. The optional mask section identifies scores
as model-mask diagnostics, explains unreliable ownership, and displays shared
embedding and prompt timing separately. The fish viewer paints only the
selected candidate and that observation's assigned parts; an ID, frame, or
dimension mismatch withholds annotations. New selections and canceled late
image loads clear old evidence. Video previews use their recorded source-frame
box and parts. Real elapsed analysis seconds use a monotonic browser clock.

Thirteen candidate fields append to API CSV/XLSX and browser exports, including
backend/state, ownership status, validation status, mask score, reasons,
checkpoint SHA-256, frame, timing, zero grading effect, shadow association, and
structured candidate evidence. Existing columns retain their order and values.
Derived candidate JSON omits duplicate source-preview bytes; complete raw event
evidence remains available. Experimental validation and grading-effect columns
remain conservative even when an incoming raw record asserts validation.

The [Chrome UI smoke result](../results/qa/mobilesam/ui_browser_smoke.json) passed
27 assertions using synthetic candidate payloads and no model/GPU inference.
It verifies default-off/header behavior, lazy capability lookup, running and
completion timing, selected-fish drawing, native coordinates over a smaller
preview, visible SAM geometry estimates with withheld centimeters,
wrong-parent/frame rejection, video snapshots, and stale-load reset.
The [viewer screenshot](../results/qa/mobilesam/ui_candidate_fixture.png) is a
rendering fixture, not a segmentation example or accuracy result. The browser
reported 0.4 seconds after an injected 375 ms response delay.

The actual `mobilesam_candidate` geometry sampling mode now has explicit UI and
CSV/XLSX handling. Its measurements remain estimates even when contradictory
raw flags claim measured/validated status. Four regression cases failed before
this correction; the SAM and prior sampled-geometry UI/export modules then
passed 26 tests in 1.18 seconds (16 SAM UI/export cases and ten prior
sampled-geometry cases). Existing CSV estimate-column names retain
their historical `sampled mask` text for compatibility; SAM rows identify
unvalidated ownership in the interpretation and sampling JSON rather than
claiming a downsized CPU mask.

The unchanged
seven-record browser replay also passed, preserving proxies 0.386, 0.481,
0.265, and 0.302, grouped counts `[0,2,0,0,5]`, timestamps, uncalibrated width
effects, mobile layout, and the
[52-page PDF](../results/qa/mobilesam/seven_record_browser_report.pdf). Its
[log](../results/qa/mobilesam/seven_record_browser_smoke.log) records the check.
The final combined regression run passed **1,420 tests**, with 12 skipped,
7 warnings, 127 subtests, and zero failures in 45.77 seconds; see
[`final_tests.log`](../results/qa/mobilesam/final_tests.log). Software and browser
checks are not independent scientific or deployment approval.

New automated tests cover backend native boxes, shared embedding/cache identity,
CPU/GPU-failure fallback via test doubles, contamination/conflicts, reviewed
Body/point contracts, optional Tail versus required anatomy, unavailability,
no-GrabCut experimental paths, frame changes, exports, and UI restrictions.
Synthetic review flags in tests are fixtures and do not supply expert approval.

## Implementation files and remaining validation

The [final source manifest](../results/qa/mobilesam/final_manifest.json) records
exact baseline-relative hashes and confirms the protected configurations and
Model 1 detector source remain unchanged. Compared with the frozen manifest,
existing implementation files changed are
`frontend/app.js`, `frontend/index.html`, `src/api/app.py`,
`src/api/export.py`, `src/api/image_analysis.py`,
`src/inference/preprocessing.py`, `src/inference/yolo_quality_model.py`,
`src/inference/fish_geometry.py`, `src/inference/fish_geometry_pipeline.py`,
`src/inference/frame_diagnostics.py`, and `src/inference/stage_metrics.py`.
`tests/test_qualitycheck_ui_exports.py` now checks its seven-field historical
suffix as a contiguous preserved block before the appended SAM fields.

New implementation files are `src/inference/mobilesam_backend.py`,
`src/inference/experimental_segmentation.py`,
`src/inference/mask_ownership.py`,
`src/evaluation/download_mobilesam_checkpoint.py`, and
`src/evaluation/evaluate_mobilesam.py`. New tests are
`tests/test_mobilesam_backend.py`, `tests/test_mask_ownership.py`,
`tests/test_optional_tail_ambiguity.py`,
`tests/test_mobilesam_service_regression.py`,
`tests/test_experimental_segmentation_pipeline.py`,
`tests/test_mobilesam_camera_compatibility.py`,
`tests/test_mobilesam_ui_exports.py`, and `tests/mobilesam_browser_smoke.py`.
Documentation changes comprise this report, `docs/mobilesam_ownership.md`,
the README setup section, and a separate progress entry. Checkpoint metadata,
the optional MobileSAM asset, and QA artifacts live only in their new
experimental/QA locations. Model 1/Model 2 weights, original datasets and
annotations, and training notebooks were not edited or retrained for this work.

Primary activation remains blocked on independently reviewed per-fish instance
masks, difficult-overlap ownership examples, reliable Body support, anatomical
pixel measurements, crack review examples, and a measured deployment budget on
the actual 4 GB GPU. The current shadow proposal path deliberately does not
resolve uncertain ownership by changing active grades. CPU timing does not
justify enabling SAM by default. Existing expert-policy and scientific release
gates remain unchanged.
