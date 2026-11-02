# TAMBAN THESIS — Integrate MobileSAM for Fish-Specific Mask Isolation & Feature Optimization

Act as a Senior Computer Vision Engineer, Machine Learning Engineer, Python Performance Engineer, and Full-Stack Developer.

## Primary objective

Implement and evaluate **MobileSAM as a lightweight fish-instance mask generation layer** in my existing Tamban Fish Quality Grading System.

My system currently uses:

- **Model 1 V2:** YOLO26s whole-fish detector, trained and validated successfully.
- **Model 2:** YOLO26m anatomical part detector and quality grading evidence for Head, Body, and Tail.
- **Feature extraction:** HSV/color, texture, body geometry, width analysis, crack candidates, and other structural evidence.
- **Existing segmentation:** OpenCV GrabCut, which is slow and frequently unable to isolate individual overlapping fish.

The system runs on an **NVIDIA GeForce RTX 2050 with 4 GB VRAM**.

I want MobileSAM to help isolate each detected fish into a reliable pixel-level mask using Model 1 V2's bounding boxes.

**Do not retrain or modify Model 1 V2 or Model 2. Do not change existing annotations. Do not assume MobileSAM automatically solves overlapping-fish ownership. Validate it before enabling it in the primary inspection workflow.**

## 1. Audit the existing segmentation pipeline

Inspect the actual repository and identify:

- Where Model 1 V2 generates whole-fish bounding boxes.
- How these boxes are transformed into Model 2 ROIs.
- How GrabCut currently isolates foreground.
- Why segmentation is repeatedly executed.
- How masks are cached and shared.
- How anatomical ownership is determined.
- How width, texture, and structural-damage features consume masks.
- How image, video, and live-camera analysis differ.

Identify exact performance bottlenecks and unreliable mask assumptions before modifying the pipeline.

## 2. Add MobileSAM as an optional segmentation backend

Implement MobileSAM as a modular segmentation service using a supported pretrained checkpoint and documented inference API.

Requirements:

- Keep the existing detector and part model unchanged.
- Load MobileSAM lazily and only when requested.
- Use Model 1 V2 bounding boxes as prompts.
- Reuse the image embedding for multiple fish within the same image whenever the backend supports it.
- Convert all coordinates correctly between original image, detector input, segmentation prompts, and Model 2 ROIs.
- Produce a separate candidate mask for each fish detection.
- Preserve the parent Fish ID and mask provenance.
- Avoid loading multiple MobileSAM instances.
- Do not generate a full-image embedding separately for every fish.
- Support CPU fallback and explicit GPU-memory checks.
- Avoid silently changing model thresholds or grading behavior.

Start with an experimental configuration such as:

`SEGMENTATION_BACKEND = "mobilesam_experimental"`

Keep the current validated behavior as the default until testing demonstrates that MobileSAM is accurate and practical.

## 3. Implement reliable mask ownership validation

MobileSAM-generated masks are candidates, not automatically trusted fish identities.

For each mask:

- Compare the mask against the intended Model 1 V2 detection.
- Check whether it includes neighboring fish.
- Compare overlapping masks for ownership conflicts.
- Evaluate anatomical continuity using the existing Head–Body–Tail association pipeline.
- Reject masks that merge multiple fish.
- Detect masks that omit significant visible sections of a fish.
- Reject fragmented or implausible silhouettes.
- Use positive and negative point prompts where reliable anatomical points are available.
- Do not invent prompt points when fish orientation or ownership is uncertain.
- Preserve ambiguous and unreliable states.

A part or pixel being inside a bounding box must never independently establish fish ownership.

Do not treat a high MobileSAM mask score as proof that the mask belongs to the correct fish.

## 4. Integrate masks with Model 2

Use validated fish-specific masks to improve anatomical ownership.

When Model 2 detects Head, Body, or Tail:

1. Normalize the anatomical detections to global image coordinates.
2. Compare each part against plausible neighboring fish and their candidate masks.
3. Evaluate mask overlap, spatial continuity, orientation, and anatomical consistency.
4. Assign each physical part to at most one fish.
5. Reject parts that are better explained by a neighboring fish.
6. Leave uncertain parts unassigned.

Preserve the established grading logic:

- Body: 50%
- Head: 30%
- Tail: 20%
- Body and Head are required.
- Tail is optional.
- Missing or ambiguous Tail redistributes weights to Body 62.5% and Head 37.5%.
- Uncertain required Head or Body ownership produces an Ungraded result.

Do not allow neighboring fish masks or anatomical parts to contaminate another fish's grading evidence.

## 5. Improve fish width and length measurements

Use validated masks to support orientation-aware geometry.

Implement or refine:

- Fish longitudinal-axis estimation.
- PCA-based orientation.
- Fish length along the principal axis.
- Transverse body-width profiles.
- Maximum and representative central-body width.
- Width-to-length ratio.
- Whole-fish versus Body-only measurements.
- Clipped and occluded silhouette detection.
- Measurement reliability reporting.

Prefer measurements from a reliably isolated Body mask rather than the entire fish rectangle.

Do not treat visible-pixel width and true anatomical width as equivalent when fish are occluded.

Keep Class C supporting points disabled until reference ranges and measurement reliability are validated.

## 6. Improve crack and structural-damage detection

Use trustworthy Body masks to restrict structural analysis to the correct fish.

Investigate:

- Dark-line candidates
- Surface discontinuities
- Fracture-like regions
- Boundary tears
- Discoloration mistaken for cracks
- Scale texture mistaken for defects
- Neighboring fish edges mistaken for cracks
- Shadows and low-light artifacts

Generate explainable candidate evidence with locations, measurements, and reliability status.

Do not label unvalidated crack candidates as confirmed structural defects.

Do not automatically change grades based on uncalibrated crack features.

Compare crack-candidate detection with manually reviewed examples before enabling grading contributions.

## 7. Optimize performance for RTX 2050 (4 GB VRAM)

The system already uses two neural-network models. Adding MobileSAM must not cause excessive latency or GPU out-of-memory errors.

Implement:

- Sequential GPU inference where appropriate.
- Lazy model loading.
- Shared image embeddings across prompts.
- Mask caching per image, Fish ID, and detection version.
- Reuse of validated masks across all feature extractors.
- Bounded batch processing.
- GPU memory monitoring.
- Inference-mode execution.
- Optional FP16 only after numerical and performance validation.
- Explicit cleanup of temporary GPU tensors.
- Reliable CPU fallback when practical.
- No duplicate GrabCut and MobileSAM execution unless explicitly benchmarking them.

For live video:

- Avoid running MobileSAM for every fish on every frame.
- Reuse trustworthy masks across tracked frames only when identity and geometry remain valid.
- Recompute masks when fish move, overlap significantly, or mask reliability deteriorates.
- Never reuse a stale mask for a different Fish ID.

**The initial objective is to improve segmentation quality while reducing or at least controlling total inspection latency. Do not claim a speed improvement without measuring it.**

## 8. Benchmark before enabling MobileSAM

Create an isolated benchmark using representative images from my existing project.

Include:

- Isolated fish
- Two overlapping fish
- Severely overlapping fish
- Multiple fish in one image
- Dark lighting
- Uneven lighting
- Fish partially outside the image
- Neighboring Head inside another fish's rectangle
- Neighboring Tail inside another fish's rectangle

Compare:

1. Existing GrabCut segmentation
2. MobileSAM candidate segmentation
3. Existing lightweight geometry/association without additional segmentation

Measure:

- Total processing time
- Segmentation time
- Peak GPU memory
- Number of successful fish-specific masks
- Invalid or merged masks
- Part-ownership correctness
- Width measurement reliability
- Crack-candidate localization
- Impact on grading coverage

Use manually reviewed masks or expert-verified ownership labels where available. If reliable ground truth is unavailable, explicitly report qualitative findings rather than inventing accuracy percentages.

## 9. Improve the UI for debugging and inspection

Add an optional segmentation visualization mode to Analyze Media.

Allow users to view:

- Original image
- Model 1 V2 bounding boxes
- MobileSAM fish mask overlays
- Model 2 anatomical detections
- Verified versus unreliable masks
- Overlapping mask conflicts

When selecting Fish #N, highlight only its own candidate mask and verified anatomical parts.

Display concise explanations for unreliable segmentation, such as:

"Fish mask unreliable — neighboring fish overlap detected."

Ensure every analysis resets old overlays and results correctly.

Display real elapsed analysis time in seconds and maintain an accurate breakdown of segmentation time.

Keep the UI polished and avoid cluttering the main grading results.

## 10. Regression testing and safety

Add tests for:

- Correct Model 1 box-to-MobileSAM prompt conversion.
- Fish mask mapped back to original-image coordinates.
- Multiple fish sharing one image embedding.
- Neighboring fish mask contamination.
- Mask ownership conflicts.
- Unreliable or unavailable masks.
- Model 2 anatomical association.
- Optional Tail handling.
- Required Body and Head evidence.
- Width measurements using verified masks.
- Crack extraction restricted to correct Body pixels.
- No fish detected.
- Repeated image analysis.
- Video frame and Fish ID changes.
- GPU out-of-memory fallback.
- Existing GrabCut fallback behavior.

Do not introduce regressions in Model 1 V2 detection, Model 2 grading, camera operation, exports, or tracking.

## 11. Deliverables

Implement the experimental integration directly in the repository.

At completion, provide:

- Files modified.
- MobileSAM checkpoint and dependency information.
- How box prompts and shared image embeddings are handled.
- Mask validation and rejection rules.
- Before-and-after example visualizations.
- Segmentation timing and peak GPU memory measurements.
- Impact on width and crack evidence.
- Model 2 ownership compatibility results.
- Regression test outcomes.
- Unresolved problems and proposed next steps.

Do not describe unfinished functionality as completed.

Do not enable MobileSAM as the default backend unless benchmark evidence supports its reliability, resource usage, and compatibility.

## Non-negotiable constraints

- Preserve Model 1 V2 and Model 2 weights.
- Preserve original training datasets and annotations.
- Do not retrain either model.
- Do not automatically accept masks solely because they were generated successfully.
- Do not allow unreliable masks to affect grading.
- Do not introduce heavy SAM models by default.
- Do not claim 100% successful separation of overlapping fish.
- Do not sacrifice real-time responsiveness for optional measurements.
- Do not fabricate benchmark results.

**FINAL OBJECTIVE:** Add a lightweight, benchmarked, optional MobileSAM segmentation layer guided by Model 1 V2, enabling more reliable per-fish masks, stronger Model 2 anatomical ownership, improved width and crack analysis, and faster or resource-controlled inspection on an RTX 2050 with 4 GB VRAM.
