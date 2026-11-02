# TAMBAN THESIS — Feature Extraction Optimization, Accuracy Preservation & Final UI Polish

Act as a senior Computer Vision Engineer, Machine Learning Engineer, Python Performance Engineer, and UI/UX Engineer.

Perform a comprehensive code audit, optimization, and production-quality polish of the existing Tamban Fish Quality Grading System.

**IMPORTANT: Model 1 is currently undergoing Stage 2 training externally. Do not retrain, replace, modify, integrate, or change Model 1 checkpoints, model architecture, detection thresholds, or training files. Focus exclusively on the existing feature extraction, grading, segmentation, Model 2 integration, and inspection experience.**

## 1. Investigate and eliminate major processing bottlenecks

The latest inspection CSV reports approximately:

- Total processing: 160,054 ms
- Segmentation processing: 146,294 ms
- Mask preprocessing: 5,648 ms
- HSV processing: 1,153 ms
- Grading engine: 1,154 ms
- Model 2 inference: 117 ms
- Segmentation calls: 9
- Segmentation cache hits: 9

These represent one inspection sample, not an established performance average.

Trace the complete execution flow and identify exactly why segmentation is consuming most of the processing time.

Implement improvements where appropriate:

- Eliminate redundant GrabCut and foreground-segmentation executions.
- Segment each unique fish/frame/ROI only when necessary.
- Reuse validated masks across texture, geometry, discoloration, width analysis, and structural-damage analysis.
- Improve cache-key reliability and cache lifecycle management.
- Prevent expensive full-resolution operations when a correctly scaled ROI would provide equivalent measurements.
- Profile OpenCV operations, CPU/GPU transfers, preprocessing, and repeated image conversions.
- Reuse intermediate color-space transformations and feature maps.
- Use bounded parallelism or background processing only where thread safety and resource limits permit.
- Avoid excessive GPU consumption because Model 1 is currently training on the same machine.

Do not assume CUDA automatically accelerates OpenCV GrabCut. Identify whether each computational stage is genuinely CPU-bound or GPU-accelerated.

**Target:** Achieve a substantial measured speed improvement, initially aiming for at least 2–5× faster processing without sacrificing validated grading behavior. Treat this as an optimization objective, not a guaranteed result.

## 2. Refactor and consolidate feature extraction

Audit the entire feature-extraction pipeline, including:

- HSV color statistics
- Yellowish and brownish discoloration
- Dark-area percentages
- GLCM texture
- LBP texture
- Surface irregularities
- Structural damage and crack indicators
- Foreground segmentation
- Fish orientation and PCA
- Whole-fish and body geometry
- Relative body-width measurements

Identify redundant computations, unnecessary repeated masking, excessive memory allocations, and features that are calculated but never consumed.

Create a unified, reusable feature-extraction pipeline that computes each valid feature once and shares its results with all dependent components.

Maintain the coordinate spaces, mask ownership, measurement units, feature provenance, and reliability indicators. Never silently substitute a proxy measurement for a validated physical measurement.

## 3. Improve segmentation reliability

Review segmentation behavior in images containing:

- Multiple overlapping fish
- Clipped fish boundaries
- Dark backgrounds
- Uneven lighting
- Partially visible tails
- Similar-colored fish and backgrounds
- Small or crowded fish

Improve segmentation quality and efficiency while maintaining clear failure states.

Reuse trustworthy masks rather than generating new masks for every feature.

Where segmentation is unreliable, explicitly mark dependent measurements as unavailable or unreliable instead of producing misleading values.

Never assume overlapping foreground components belong to the same fish.

## 4. Polish anatomical geometry and width analysis

Improve the existing whole-fish, Body, Head, and Tail geometry pipeline.

Investigate:

- Bounding-box versus anatomical width
- PCA-based orientation estimation
- Central-body width measurements
- Mask-based maximum width
- Clipped-parent boundaries
- Part-to-parent associations
- Measurement reliability
- Overlapping-fish contamination

Produce accurate and explainable geometry diagnostics.

**Do not enable Class C width scoring unless validated calibration data and reliability requirements are satisfied.** The system must not invent normal width ranges or allow uncertain measurements to alter grading.

## 5. Improve structural damage and texture evidence

Audit whether crack detection, surface damage, texture, and discoloration features actually contribute meaningful evidence.

Ensure:

- Feature computations are correct and reproducible.
- Outputs are explicitly identified as measured, estimated, unavailable, or unreliable.
- Feature results are associated with the correct fish and anatomical part.
- Unvalidated crack indicators are not presented as confirmed physical defects.
- No unsupported feature automatically changes the final grade.

Preserve the established grading logic:

- Body: 50%
- Head: 30%
- Tail: 20%
- Body and Head are required for a final verdict.
- Tail is optional; when absent, redistribute its weight proportionally to Body and Head.
- Ambiguous part associations must not produce unjustified grades.

Do not silently change grading rules or model confidence values.

## 6. Optimize image and video inspection

Audit both uploaded-photo analysis and live/video inspection.

Improve:

- End-to-end processing latency
- Repeated frame analysis
- Per-fish caching
- Image resizing and preprocessing
- Video frame scheduling
- Model 2 inference reuse
- GPU memory usage
- Preview responsiveness
- Annotation rendering
- FPS measurement accuracy
- Tracking stability

Keep expensive optional features from unnecessarily blocking the entire inspection interface.

For video, prioritize timely processing and stable fish identities over repeatedly analyzing outdated frames.

Preserve correct fish counting and prevent phantom Fish IDs when no fish is detected.

Do not artificially display high FPS or hide slow processing. Report real measured performance.

## 7. Polish the inspection UI/UX

Improve the existing interface without unnecessarily redesigning the entire application.

Focus on:

- Clearer fish inspection results
- More readable bounding-box annotations
- Cleaner Class A, B, C, Rejected, and Ungraded result cards
- Expandable feature evidence with understandable explanations
- Accurate processing indicators
- Helpful unavailable/unreliable states
- Responsive image/video preview
- Consistent spacing, typography, and status colors
- Cleaner progress feedback during long-running operations

Show concise primary results by default and place advanced feature diagnostics in expandable sections.

Avoid redundant information, unnecessary visual clutter, and displaying raw technical measurements without explanations.

Preserve the existing user workflows and styling conventions.

## 8. Add trustworthy performance instrumentation

Implement detailed per-stage timing for:

1. Model 2 inference
2. Foreground segmentation
3. Mask preprocessing
4. HSV/color extraction
5. Texture extraction
6. Structural damage analysis
7. Geometry and width analysis
8. Grading
9. Annotation rendering
10. Total inspection processing

Track cache hits, misses, actual segmentation executions, GPU memory use where measurable, and fallback frequency.

Clearly distinguish total wall-clock time from overlapping or nested operation timings so stages are not double-counted.

Benchmark before and after optimization using the same images, hardware, precision, and configuration.

Maintain the existing CSV exports and deployment evidence schemas wherever practical. Document any necessary schema changes.

## 9. Regression testing and validation

Create or update automated tests covering:

- Single-fish images
- Multiple overlapping fish
- Missing optional Tail
- Missing required Body or Head
- Ambiguous part associations
- Unreliable masks
- Clipped fish
- Dark and low-contrast images
- Unsupported width calibration
- No fish detected
- Duplicate or repeated frames
- Failure and fallback paths

Verify that performance optimizations do not silently degrade feature validity, anatomical ownership, grading reliability, or export correctness.

Compare original and optimized outputs with appropriate numerical tolerances. Investigate meaningful differences rather than forcing results to match.

Avoid GPU-intensive testing while external Model 1 training is active.

## 10. Implementation and deliverables

Work directly in the existing repository.

First inspect the implementation and identify the actual bottlenecks. Then implement fixes in logically separated stages, prioritizing high-impact changes.

Do not simply generate a report or a list of recommendations. Make concrete code improvements and validate them.

At completion, provide:

- A summary of the bottlenecks discovered
- Files modified and why
- Before-and-after performance measurements
- Verified feature extraction improvements
- Remaining reliability limitations
- Automated test results
- Any compatibility or configuration changes
- Outstanding requirements for real-world thesis validation

**Non-negotiable requirements:**

- Preserve Model 1 and its ongoing training.
- Do not delete or overwrite existing checkpoints.
- Do not fabricate feature evidence or grading confidence.
- Do not enable uncalibrated geometric scoring.
- Do not sacrifice valid grading behavior solely for FPS.
- Do not hide failures or unsupported features.
- Do not claim an optimization succeeded without measurable evidence.
- Preserve working features and avoid introducing unnecessary complexity.

**Final objective:** Transform the current Tamban feature-extraction and grading pipeline into a faster, cleaner, reliable, well-instrumented, and thesis-defense-ready system, while keeping Model 1 completely untouched until its separate training and evaluation are finished.
