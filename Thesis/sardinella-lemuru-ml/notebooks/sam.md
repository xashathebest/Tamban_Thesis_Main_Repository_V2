# TAMBAN THESIS — Make MobileSAM Functional and Display Shaded Fish Masks

Act as a Senior Full-Stack Developer, Computer Vision Engineer, and UI/UX Engineer.

My Tamban system currently displays an **Experimental fish masks** section with an **Inspect fish masks** button. However, the feature does not appear to work, and no visible segmentation masks or shaded fish overlays appear on the image.

**Your task is to diagnose and implement a fully working end-to-end MobileSAM segmentation preview, not just its interface.**

## 1. Find why MobileSAM is not working

Inspect the existing implementation and verify:

- Whether the MobileSAM checkpoint is actually installed and configured.
- Whether the backend successfully loads the correct MobileSAM model.
- Whether clicking Inspect fish masks triggers a real API request.
- Whether Model 1 V2 bounding boxes are passed correctly as segmentation prompts.
- Whether MobileSAM generates nonempty pixel masks.
- Whether mask outputs are serialized and returned to the frontend.
- Whether the frontend receives and renders those masks.
- Whether coordinate scaling or canvas layering makes masks invisible.

Use a supported Ultralytics MobileSAM API and compatible `mobile_sam.pt` checkpoint.

Do not silently replace it with standard SAM or another large model. If checkpoint installation fails, display the actual error and clear setup instructions.

## 2. Implement real fish-mask generation

Use the existing Model 1 V2 detections.

For each analyzed image:

1. Obtain all detected fish bounding boxes in original-image coordinates.
2. Load MobileSAM lazily.
3. Encode the image once and reuse the image features across multiple fish prompts where supported.
4. Generate a separate candidate segmentation mask for each fish.
5. Convert all masks to original-image coordinates.
6. Associate each candidate mask with the originating Model 1 Fish ID.
7. Return masks in a compact format, such as polygons or compressed mask encoding.
8. Report errors clearly when masks cannot be produced.

Use actual model-generated masks, not rectangles filled with color or fabricated polygon outlines.

Validate that masks contain meaningful foreground pixels and do not cover the entire rectangle by default.

## 3. Build the missing shaded-mask UI

Implement an actual segmentation visualization layer inside Analyze Media.

When I click **Inspect fish masks**, I want to see:

- The original uploaded fish image.
- A different translucent color applied to each detected fish's mask.
- Mask boundaries that follow the fish silhouette.
- Optional thin colored mask contours.
- A Fish ID label associated with each mask.
- Visible indication of unreliable or overlapping masks.

Use approximately 35–45% mask opacity by default so the original fish remains visible.

Provide these controls:

- Show/hide fish masks.
- Show/hide Model 1 bounding boxes.
- Show/hide Model 2 anatomical annotations.
- Adjust mask opacity.
- Select an individual Fish ID to highlight only that mask.

Ensure the rendering works on desktop and mobile, including resized images.

Do not display the same generic overlay for every fish.

## 4. Correct rendering and analysis lifecycle

Masks must align perfectly with the image.

Handle:

- Original resolution versus display resolution.
- Image zoom and resizing.
- Canvas/SVG coordinate scaling.
- Changing images.
- Reanalyzing the same image.
- Switching between image and video.
- Browser refresh.
- Failed or canceled requests.

When a new analysis begins, clear previous image masks and annotations.

Prevent old requests from overwriting new analysis results.

The mask preview must reflect the exact image that was analyzed.

## 5. Add visible status and processing time

Replace silent failures with clear status messages.

Examples:

- "Loading MobileSAM..."
- "Generating fish masks..."
- "Generated 7 candidate masks."
- "3 masks require review due to overlapping fish."
- "MobileSAM checkpoint unavailable."
- "Segmentation failed: [actual error]."

Display actual elapsed segmentation time in seconds.

Never display success if the backend returned no usable masks.

## 6. Respect fish ownership and grading safeguards

These masks are experimental candidates.

Do not assume a generated mask reliably isolates one fish merely because it looks correct.

Detect and report:

- Masks merging neighboring fish.
- Multiple masks covering the same visible region.
- Unusually large or fragmented masks.
- Masks inconsistent with the originating fish.
- Uncertain ownership in severe overlaps.

Do not allow candidate masks to change final grades, body-width measurements, or crack results until they are validated.

Preserve Model 1 V2 and Model 2 exactly as they are.

## 7. Optimize for my RTX 2050 (4 GB VRAM)

Do not run MobileSAM repeatedly for every bounding box using separate image encodings.

Reuse the image embedding and process prompts efficiently.

Avoid loading multiple segmentation model instances.

Monitor GPU memory and catch CUDA out-of-memory errors.

Keep MobileSAM optional and off by default.

Do not run expensive GrabCut segmentation again for the same fish merely to generate this preview.

Report actual segmentation latency and memory consumption where measurable.

## 8. Prove that the feature works

Do not stop after implementing the UI.

Run an end-to-end smoke test using actual fish images.

Verify:

1. The model loads successfully.
2. The API receives real bounding boxes.
3. MobileSAM produces valid mask pixel arrays.
4. The backend returns usable masks.
5. The frontend renders visible translucent fish silhouettes.
6. Different fish receive distinguishable masks.
7. Selecting Fish #N highlights the correct mask.
8. New analyses clear old masks.
9. Overlapping fish are flagged where isolation is unreliable.
10. Model 1 and Model 2 inference still work.

Save at least one actual generated overlay image and provide the local output path for inspection.

Compare the original image, bounding-box-only output, and MobileSAM mask overlay.

If the environment cannot run MobileSAM, do not invent successful test results. Report the blocker and the exact remaining setup requirements.

## Final objective

Make **Inspect fish masks** a fully operational feature that generates and displays real, visually shaded, fish-specific candidate segmentation masks using MobileSAM and Model 1 V2 detections.

The result must be visible, interactive, reliable about uncertainty, and properly connected from backend inference to frontend visualization.

Do not retrain models, modify annotation datasets, or enable experimental masks for automatic grading.

Implement the corrections directly in the repository and report the files changed, successful tests, performance measurements, and remaining limitations.
