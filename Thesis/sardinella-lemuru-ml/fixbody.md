# Tamban AI Inspection — Performance, Geometry & Structural Defect Optimization

Conduct a comprehensive audit and optimization of the existing Tamban AI inspection system to improve processing speed, fish measurement accuracy, structural defect detection, and overall reliability across image uploads, video uploads, and live-camera inspection.

**Primary objective:** Achieve maximum safe processing speed while improving measurement reliability and crack detection, without sacrificing existing functionality, model performance, or grading accuracy.

## 1. Full Pipeline Audit & Profiling

Inspect the existing implementation before making changes. Identify bottlenecks and reliability issues involving:

- Model 1 fish detection and Model 2 body/head/tail detection.
- Image preprocessing, segmentation, and GrabCut processing.
- Fish height, length, width, and body-width calculations.
- Feature masks, texture analysis, crack and fracture detection.
- Fish tracking, part-to-parent association, and grading.
- Backend processing, memory usage, and UI rendering.

Use the latest inspection CSV as diagnostic evidence. Establish baseline timings, detection results, and grading outputs before modifying the pipeline.

## 2. Safe Performance Optimization

Implement improvements that preserve existing accuracy and functionality:

- Enable CUDA acceleration where supported, with reliable CPU fallback.
- Load AI models once and reuse them across inspections.
- Evaluate FP16 inference, enabling it only after numerical validation.
- Batch compatible operations and eliminate duplicate inference calls.
- Cache preprocessing, segmentation masks, and extracted features using safe, correctly scoped cache keys.
- Parallelize independent processing stages without disrupting fish tracking or result consistency.
- Optimize image/video decoding, memory management, and backend-to-frontend updates.
- Preserve the image detail required for reliable crack and width analysis.
- Keep the UI responsive during lengthy inspections.

Do not skip required processing, lower model quality, or remove existing analysis features merely to improve FPS.

## 3. Accurate Fish Length, Height & Width Analysis

Fix unreliable geometric measurements caused by overlapping fish, clipped segmentation, inconsistent orientation, and incorrect body-to-fish associations.

- Improve validated per-fish segmentation and isolate individual fish accurately.
- Calculate true silhouette length along the fish's principal axis.
- Calculate maximum body width perpendicular to that axis.
- Retain bounding-box dimensions as fallback diagnostics, clearly labeled as approximations.
- Account for rotated fish, partial visibility, and overlapping detections.
- Ensure body measurements belong to the correct parent fish.
- Calculate normalized width-to-length ratios and measurement reliability.
- Visualize measured axes, endpoints, body boundaries, and measurement values.
- Report measurements in pixels unless physical calibration is available.

Do not allow unreliable or uncalibrated width measurements to modify final grades.

## 4. Feature Mask & Structural Crack Detection

Investigate why structural damage analysis can access a runtime GrabCut mask while texture analysis reports `no_validated_fish_mask_in_runtime`.

- Trace mask generation, validation, storage, and usage across the entire pipeline.
- Reuse validated per-fish masks where technically appropriate.
- Distinguish segmentation masks from edge maps and texture feature masks.
- Improve crack, fracture, tear, and structural discontinuity localization.
- Filter noise caused by natural fish texture, shadows, fins, scales, and segmentation boundaries.
- Cross-reference suspected cracks against original image evidence.
- Estimate crack length, location, severity, and confidence only where reliable.
- Display suspected damage using accurate visual overlays.
- Distinguish **No reliable evidence**, **Suspected Damage**, and **Validated Damage**.
- Export geometry and structural defect evidence alongside existing results.

Do not treat noisy edges as confirmed cracks or apply automatic grading penalties without validation.

## 5. Preserve Existing Grading Logic

Maintain the existing Model 1 and Model 2 workflows and the established grading weights:

- Body: 50%
- Head: 30%
- Tail: 20%
- Redistribute tail weight proportionally when the tail is unavailable and valid body/head evidence exists.

Preserve classification thresholds, confidence safeguards, fish IDs, tracking consistency, and existing Ungraded conditions.

Do not force classifications when required evidence is missing. Width and crack evidence must remain supporting diagnostics until validated against reference measurements and expert labels.

## 6. Benchmarking & Regression Protection

Before and after optimization:

- Test identical images, videos, and live-camera scenarios.
- Compare detection counts, bounding boxes, part associations, fish IDs, final grades, confidence scores, and structural evidence.
- Benchmark CPU/GPU utilization, inference times, segmentation times, and end-to-end processing latency.
- Evaluate measurement improvements against annotated reference fish.
- Identify changes caused by intentional reliability fixes separately from performance-only changes.
- Detect numerical deviations, unexpected classification changes, and false structural damage detections.
- Roll back optimizations that introduce regressions or reduce reliability.

Do not claim accuracy improvements without supporting validation results.

## 7. UI/UX & Diagnostics

Improve evidence presentation without redesigning unrelated components.

Display:
- Fish length, body width, and width-to-length ratio.
- Measurement reliability and failure reasons.
- Suspected crack locations and supporting overlays.
- Processing speed, inference latency, and hardware acceleration status.
- Clear explanations whenever measurements or features are unavailable.

Keep the interface lightweight, responsive, and consistent with the existing design.

## 8. Final Deliverables

Implement the verified improvements directly into the existing codebase and provide:

1. Summary of issues discovered and fixes applied.
2. Before-and-after processing benchmarks.
3. Measurement and crack-detection validation findings.
4. Regression test results.
5. Remaining limitations and calibration requirements.
6. Files modified and any necessary setup instructions.

**Non-negotiable:** Do not retrain, replace, or downgrade either model. Do not modify validated grading rules, disable functional features, or fabricate measurements. Reuse the existing architecture wherever possible and avoid unnecessary dependencies or large-scale rewrites.

**Final goal:** A faster, more reliable, and scientifically defensible Tamban AI inspection system with improved fish geometry measurements, structural defect evidence, and preserved grading integrity.