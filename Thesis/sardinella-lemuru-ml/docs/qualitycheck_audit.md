# Qualitycheck implementation and validation record

The feature pipeline now limits expensive CPU foreground solves, shares native-pixel feature intermediates, avoids launching segmentation merely to refresh a live overlay, and separates fish-observation timings from shared frame costs. A paired CPU replay of one recorded fish improved from **11,666.58 ms to 2,099.80 ms, an observed 5.56x speedup**. That replay uses the original photograph and recorded parent/part detections; it does not run either model or reproduce every detection in the original inspection.

Model 1, its checkpoints, architecture, thresholds, and training files were left untouched. No GPU model inference was performed for this audit. Existing weighted grading and operating policy were preserved. These are software and performance results, not anatomical accuracy, defect accuracy, or scientific release approval.

## Reproduction and root causes

The matched [reproduction CSV](../results/qa/qualitycheck/reproduction.csv) is the filtered Downloads export `fish-inspection-upload-class-b (3).csv`. It has **one record and 946 columns**, representing Fish #5 from `WIN_20260823_20_47_00_Pro.jpg`. The [inventory](../results/qa/qualitycheck/reproduction_inventory.json) records its hash, metadata, exact parent box, timings, and image search. Both read-only source-photo copies are identical 3840 x 2160 JPEGs with SHA-256 `99bd6f4ab0d6bf3f7662690758d14030ffc4d1ca00d44c18302e79f24b6ce35b`.

The recorded sample reports 160,053.937 ms total frame processing and 146,293.640 ms foreground segmentation, with nine generation calls and nine cache hits. These are **frame-global costs repeated in the fish's performance record**. Its separate `analysis.mask_context` contains a six-call cumulative snapshot taken before frame completion; that is not Fish #5's exclusive segmentation latency. Nine mask generations do not establish the original Model 1 detection count. A matching all-fish export was not found, and that count remains unrecorded.

| Finding | Implemented change |
| --- | --- |
| Each unique large native ROI still paid for three-iteration CPU GrabCut, full-resolution morphology, and component analysis. Cache reuse avoided duplicate ROIs but did not reduce the first solve's cost. | Bound the working grid, retain the original native path as an explicit option, and lift sampled masks to the exact native ROI dimensions with provenance. Separate GrabCut, resize, morphology, components, lifting, lookup, and projection timings. |
| Different feature calls repeated RGB normalization, HSV/Lab conversion, grayscale work, and interior-mask preparation. LBP allocated an eight-channel bit stack and large reductions. | An immutable per-parent feature context shares coordinate-correct native-pixel maps and ROI summaries. Release phase-specific maps; count LBP bits/transitions with bounded accumulators and share the eroded interior. |
| Live annotation requested damage diagnostics on display frames even when Model 2 was intentionally skipped. A frame-local mask cache cannot reuse a prior frame safely. | Render only the current quality-observation damage result. Interval gaps launch no new diagnostic segmentation and do not reuse stale masks. Preserve the separate standalone diagnostic mode. |
| Shared frame totals, per-fish stages, and enclosing HSV/grading durations could be read as independent costs. | Store `analysis.frame_performance` separately from `analysis.performance`, label nested scopes, retain the legacy total alias explicitly, and expose real cache/fallback counts. |
| Fast sampled masks could otherwise be mistaken for precise anatomical boundaries or physical measurements. | Keep length/width/ratio candidates explicitly estimated, with native/working grids and sampling footprint. Withhold reliable final dimensions, centimeters, overlays, and width-grading claims for sampled geometry. |
| The UI could treat a generic `fps` metadata value as processing throughput. | Display measured `processing_fps` only; source/capture FPS is not substituted for throughput. Missing telemetry has an explicit unavailable state. |

The frozen pre-edit source/config/test snapshot contains 252 files. Its [manifest](../results/qa/qualitycheck/baseline_manifest.json) and [archive](../results/qa/qualitycheck/baseline_source.zip) identify the actual working-tree baseline rather than treating Git HEAD as a complete representation of uncommitted code. The preliminary [segmentation profile](../results/qa/qualitycheck/segmentation_initial_profile.json) and [pipeline probe](../results/qa/qualitycheck/pipeline_probe.json) are retained separately; they are not substituted for the paired results below.

## Measured performance and numerical preservation

The paired runs use the same source image/ROIs or controlled scenes, frozen/current software, and CPU arithmetic. OpenCV uses one thread; the scripts bound relevant numerical-library thread settings and do not load models or initialize GPU inference. ABBA ordering and warm-ups reduce simple ordering effects, but four timed samples per version on a machine also running external work do not establish statistical significance or a general speed guarantee.

| Measurement scope | Before median | After median | Observed speedup |
| --- | ---: | ---: | ---: |
| Original photo, one recorded parent and two Model 2 parts: real diagnostic pipeline with scripted detections | 11,666.58 ms | 2,099.80 ms | 5.56x |
| Actual exported Fish #5 ROI, CPU foreground extraction, 490 x 1561 | 3,012.15 ms | 468.79 ms | 6.43x |
| Controlled 1280 x 480 ellipse, CPU foreground extraction | 631.37 ms | 152.62 ms | 4.14x |
| Native-pixel color/texture component, 640 x 320 | 166.306 ms | 115.981 ms | 1.434x |
| Native-pixel color/texture component, 1280 x 640 | 1,354.062 ms | 945.161 ms | 1.433x |
| Native-pixel color/texture component, 1920 x 1080 | 3,208.458 ms | 2,244.508 ms | 1.429x |

The pipeline [paired summary](../results/qa/qualitycheck/pipeline_before_after.json) pools four samples per version from `before1, after1, after2, before2`; each worker warms once and then records two repetitions. The underlying [before1](../results/qa/qualitycheck/pipeline_before1.json), [before2](../results/qa/qualitycheck/pipeline_before2.json), [after1](../results/qa/qualitycheck/pipeline_after1.json), and [after2](../results/qa/qualitycheck/pipeline_after2.json) retain samples and diagnostic details. Compared parent/part boxes, recorded Model 2 confidence values, and weighted-verdict signatures match exactly. The replay remains Class B with support 0.681470014154911. That support follows the recorded Body 0.7231252789497375 and Head 0.6120445728302002 at effective weights 0.625 and 0.375; rejected association candidates are not promoted into Tail evidence.

This is **not a measured reduction of the original complete 160-second job to 2.1 seconds**. Only one exported parent and two selected part records are available for the replay. No fresh Model 1/Model 2 inference, full-source detection workload, representative live-camera throughput, or new model accuracy was measured. The subset's replay ID is local to that scripted replay and is not proof of original whole-frame identity preservation.

The [segmentation evidence](../results/qa/qualitycheck/segmentation_before_after.json) includes native-control comparisons and an archived source snapshot. With native settings and the same seed, optimized native masks exactly match the frozen generator on both cases. Bounded masks intentionally differ: the actual ROI has IoU **0.89723 against the unvalidated native baseline** and approximately **5.87% relative foreground-area difference**. The controlled ellipse has IoU 0.99272. Neither baseline is independent anatomical ground truth. These changes are disclosed and are the reason sampled geometry cannot populate reliable measurement fields. See [qualitycheck_segmentation.md](qualitycheck_segmentation.md).

The [feature benchmark](../results/qa/qualitycheck/feature_benchmark.json) compares the same original RGB pixels and masks. All color/texture values match the frozen source exactly, including NaNs, on three measured sizes and eight additional controlled scenes. This equivalence does not extend to swapping a native mask for a newly estimated mask. The immutable source snapshot has a measured memory cost: 1080p traced peak allocation rose from 354,589,664 to 360,811,524 bytes, approximately **1.75%**. Those are feature-call tracemalloc peaks, not process RSS or GPU memory. The [feature/camera methods](../results/qa/qualitycheck/feature_camera_methods.md) document phase release and the tradeoff.

## Features, geometry, and grading safeguards

`RuntimeFeatureContext` belongs to one immutable original-RGB parent crop. Integer ROI bounds, mask-pixel digests, and settings identify reusable summaries; matching dimensions alone do not establish ownership. HSV/lightness maps are released before texture, and normalized RGB is released after its consumers. Frame history retains summaries rather than those temporary arrays. Part rectangles and whole-fish mask support retain their different definitions.

Texture continues to measure native RGB pixels under the recorded foreground support. `foreground_estimated=true` qualifies sampled support; known overlap/association uncertainty receives an unreliable-isolation qualification. Neither a measured texture statistic nor a feature-checked GrabCut mask validates an anatomical contour or physical crack. Damage retains original-RGB contrast checks, sampling provenance, and conservative boundary handling. Its outputs remain unvalidated supporting evidence without automatic grade penalties.

Runtime mask keys include frame/parent identity, exact native ROI, pixel digest, and immutable sampling policy. A native metrology request cannot receive a sampled-policy cache entry. Nearest-neighbor lifting preserves the exact native output shape and coordinate origin but does not restore missing contour detail. `sampling.native_shape`, `working_shape`, `scale_to_native`, `native_output_shape`, and `boundary_sampling_footprint_native_px` describe that operation. A working-cell footprint is **not a validated anatomical error bound**.

Sampled geometry retains candidate length, maximum Body width, ratio, and orientation only with appropriate restrictions. It records `resampled_foreground_requires_native_validation`; reliable final fields, centimeter values, and measured overlays remain unavailable. Overlap, clipping, missing Body association, and uncertain ownership are not resolved by downsampling. The UI shows estimated candidate dimensions only when explicit bounded-grid provenance is present; unrelated withheld candidates are not relabeled as measurements. Contradictory sampled/validated metadata cannot enable physical output in UI or exports.

The active policy was already **config version 4.0 / `tail_optional_v1`** at the qualitycheck baseline. No policy or calibration configuration was changed. Body and Head remain required. Reliable Tail retains 50/30/20 weights; absent or insufficient Tail gives Body 0.625 / Head 0.375. Parent uncertainty, ambiguous association, missing required evidence, configured support/margin gates, and temporal requirements remain active. Missing detections do not establish physical absence. Class C width scoring remains disabled and uncalibrated; no normal anatomical ranges were invented. Historical normalization preserves recorded rules and weighted results; the existing seven-record fixture retains two Class B and five Ungraded records.

## Instrumentation, live scheduling, and UI/export compatibility

The new [stage metrics helper](../src/inference/stage_metrics.py) and API integration distinguish the following scopes:

- `analysis.performance`: current fish-observation color, texture, policy, damage, and geometry stages. Full-frame Model 2 inference is explicitly shared rather than charged repeatedly as independent work.
- `analysis.frame_performance`: frame-scope wall time, shared segmentation stages, annotation/JPEG work where completed, cache/fallback diagnostics, and optional resource observations. Camera history callbacks can contain a prefix measured before later event-tracking/annotation work; their `timing_scope` is preserved. A completed debug snapshot can contain later stages.
- Legacy `performance.total_processing_ms`: retained as a shared-frame alias with an explicit scope. It is not an exclusive fish cost.
- CUDA allocator observations: this process only; peaks are process-lifetime unless otherwise recorded. Other training-process memory/utilization is not attributed to an inspected fish. Collection neither initializes/synchronizes CUDA nor resets allocator peaks.

CPU OpenCV GrabCut, resize/morphology/components, native RGB features, PCA/geometry, and annotation are not automatically GPU-accelerated because model inference uses CUDA. Host-observed model-call timing is not a synchronized GPU kernel measurement. Enclosing segmentation and grading durations include their children; **do not add nested stages to wall time or sum repeated frame totals across fish**.

With Model 2 configured, live annotation renders current-frame quality evidence only. An interval gap triggers no mask solve just to draw an overlay and never borrows a stale mask on the new image. Existing tracked part-box rendering remains. The separate standalone diagnostic cadence remains available when no quality model is configured. Timing scopes preserve the existing persistence/FIFO ordering rather than moving database work into a misleading processing span.

Existing Class A/B/C/Rejected/Ungraded grouping and lazy per-fish sections remain. Advanced geometry and performance sections explain estimated masks, unavailable measurements, timing scopes, and actual cache counts. Missing historical telemetry condenses to an unavailable explanation rather than a long table of empty stages. The cache query is `qualitycheck1`; unrelated concurrent styling changes were not overwritten.

Backend CSV/XLSX adds **18 fields at the end** for estimated dimensions, sampling JSON, frame-performance JSON, GPU observations, scoped stage timings, and frame wall time. Browser CSV adds **seven fields after all legacy global headers**, including headers occurring only in later records. Existing names, ordering, grading columns, complete raw records, and measurement units remain available. Sampled candidates never fill legacy native-measurement or centimeter columns. Raw JSON retains the full provenance. Printable reports explain separate fish/frame scopes and nested costs. This is an append-only diagnostic schema extension, not a model-output or grading schema replacement.

## Automated validation and remaining limits

The pre-edit full baseline was **1,199 passed, 12 skipped, zero failures**, in 76.10 seconds, archived in [baseline_tests.log](../results/qa/qualitycheck/baseline_tests.log). Focused new policy/UI contracts passed 35 tests; their broader compatibility selection passed 153 tests. Segmentation and feature/camera methods record their focused runs separately.

**Final combined regression and isolated CPU browser results are pending the parent audit's final run.** This paragraph must be replaced with its actual counts and evidence paths before reporting completion. No final GPU-backed production verification is claimed here.

New coverage exercises bounded/native masks and cache settings, source/mask isolation, feature-arithmetic equivalence, sampling provenance, required Body/Head and optional Tail, ambiguity and unavailable paths, no-fish behavior, uncalibrated width, current-frame annotation cadence, timing relationships, allocator observation without initialization, append-only exports, and preservation of recorded grades/support.

Remaining requirements are independent native anatomical masks and reference lengths/widths, reviewed crack labels, physical calibration and held-out width-scoring validation, representative moving/overlapping fish video and camera trials, and sustained target-hardware load testing alongside realistic training/inspection workloads. Coarse native masks, dark or similar backgrounds, clipping, overlap, small transverse resolution, and curved fish remain reliability limits. No thesis-defense readiness or scientific release approval follows solely from these software tests.

The observed benchmark environment is Python 3.14.6, NumPy 2.5.4, and OpenCV 5.0.0. The existing runtime requirements bound OpenCV below 5; this pre-existing environment mismatch was not silently fixed by changing dependency declarations. Validation on declared deployment versions remains necessary.

## Exact implementation files and configuration

These paths differ from the captured qualitycheck baseline; earlier fixbody changes are not reclassified as new work:

| Area | Files |
| --- | --- |
| Bounded foreground extraction, cache-policy identity, geometry restrictions | [src/inference/preprocessing.py](../src/inference/preprocessing.py), [src/inference/fish_geometry_pipeline.py](../src/inference/fish_geometry_pipeline.py), [src/inference/fish_geometry.py](../src/inference/fish_geometry.py) |
| Shared native-pixel feature maps and exact arithmetic | new [src/features/runtime.py](../src/features/runtime.py), [src/features/color.py](../src/features/color.py), [src/features/texture.py](../src/features/texture.py), [src/inference/grading_engine.py](../src/inference/grading_engine.py) |
| Model 2 integration, stage accounting, and current-frame diagnostics | [src/inference/yolo_quality_model.py](../src/inference/yolo_quality_model.py), new [src/inference/stage_metrics.py](../src/inference/stage_metrics.py), [src/inference/frame_diagnostics.py](../src/inference/frame_diagnostics.py), [src/features/damage.py](../src/features/damage.py), [src/api/image_analysis.py](../src/api/image_analysis.py), [src/api/camera.py](../src/api/camera.py) |
| UI, evidence interpretation, append-only exports | [frontend/app.js](../frontend/app.js), [frontend/index.html](../frontend/index.html), [src/api/export.py](../src/api/export.py) |
| Reproducible recorded-output CPU pipeline | new [src/evaluation/qualitycheck_benchmark.py](../src/evaluation/qualitycheck_benchmark.py) |

New regression modules are [test_qualitycheck_bounded_masks.py](../tests/test_qualitycheck_bounded_masks.py), [test_quality_feature_context.py](../tests/test_quality_feature_context.py), [test_quality_camera_stages.py](../tests/test_quality_camera_stages.py), [test_quality_stage_metrics.py](../tests/test_quality_stage_metrics.py), [test_qualitycheck_policy_contract.py](../tests/test_qualitycheck_policy_contract.py), and [test_qualitycheck_ui_exports.py](../tests/test_qualitycheck_ui_exports.py). This report, [qualitycheck_segmentation.md](qualitycheck_segmentation.md), and the [feature/camera methods](../results/qa/qualitycheck/feature_camera_methods.md) document the work. Reproduction and benchmark helpers/data are retained under `results/qa/qualitycheck/`.

| Environment setting | Default | Behavior |
| --- | ---: | --- |
| `FISH_MASK_MAX_DIMENSION` | 640 | Bound the working-grid side. Zero explicitly requests the original native algorithm and disables both caps. |
| `FISH_MASK_MAX_PIXELS` | 200000 | Bound working-grid area. Zero disables the area cap while a positive side cap remains active. |

Invalid environment values fall back to documented defaults with recorded warnings; explicit invalid settings are rejected. New frame contexts capture immutable settings. A valid physical-calibration configuration requests native segmentation; calibration alone does not validate an estimated boundary. No new production package is required.

Reproduce model-free checks from the project directory using the existing test environment:

```powershell
python -B -m pytest -q -p no:cacheprovider tests
node --check frontend/app.js
```

For controlled CPU replays, the archived scripts are [pipeline_benchmark.py](../results/qa/qualitycheck/pipeline_benchmark.py), [segmentation_benchmark.py](../results/qa/qualitycheck/segmentation_benchmark.py), and [feature_benchmark.py](../results/qa/qualitycheck/feature_benchmark.py). They require their recorded input files and write new evidence; they do not run either model. Preserve archived measurements when comparing subsequent revisions.

The live GPU backend was **not restarted or reloaded during external Model 1 training**. Source changes and CPU validation are ready for review; activation in that already-loaded production process remains pending a suitable time after training permits its existing model reload. Browser validation for this change uses an isolated CPU test server rather than presenting that backend as newly verified. Model 1 training and checkpoint integration remain outside this task.
