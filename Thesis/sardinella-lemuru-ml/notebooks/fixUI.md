# TAMBAN THESIS — Add Bounding Box / Fish Mask Toggle to Main Analyze Media Viewer

Fix the Analyze Media interface with a minimal, targeted UI improvement.

**IMPORTANT: Do not remove, simplify away, or redesign existing working controls. Preserve all current features and functionality.**

## What I want

Currently, Analyze Media displays the original image with Model 1 bounding boxes. A separate mask inspector displays the same image with MobileSAM-generated, shaded fish masks.

I want to switch between these two visualizations **directly inside the main Analyze Media image viewer**, without opening a separate inspector.

Add a simple toggle above the main image:

**Bounding Boxes | Fish Masks**

### 1. Bounding Boxes mode

- Show the existing annotated image exactly as it currently appears.
- Preserve Model 1 V2 detection boxes, Fish IDs, and grading information.
- Keep existing selection and interaction behavior.
- Make this the default view.

### 2. Fish Masks mode

When I select **Fish Masks**:

- Replace the bounding-box visualization in the same main viewer with the existing MobileSAM mask visualization.
- Display the actual shaded fish silhouettes, exactly like the current experimental mask inspector.
- Use each fish's existing unique color.
- Preserve the actual mask outlines and Fish IDs.
- Use the already-generated masks from the current analysis.
- Do not rerun MobileSAM merely because I switched display modes.
- Do not change the grading results.

Switching back to **Bounding Boxes** should immediately restore the original bounding-box visualization.

## 3. PRESERVE ALL EXISTING MASK SETTINGS

This is especially important.

**Do not remove any of these working controls:**

- Fish masks visibility
- Model 1 bounding-box visibility
- Assigned Model 2 parts visibility
- Mask opacity slider
- Fish ID highlight dropdown
- Zoom controls, including Fit Image
- Mask review indicators and explanations
- Individual fish selection
- Existing annotation interactions

The opacity slider must still allow me to adjust mask transparency, including the existing 40% setting.

The Highlight dropdown must still let me inspect an individual fish.

The Zoom controls must remain functional.

The Model 2 parts option must remain available.

If the new Boxes/Masks toggle controls the primary visualization, preserve the existing overlay controls as secondary display settings so I can still customize what appears.

**Do not replace multiple existing features with a single toggle. The toggle is an addition, not a removal.**

## 4. Reuse the existing implementation

Inspect the current MobileSAM mask inspector and reuse its working:

- Mask rendering component
- Fish colors
- Mask coordinates
- Opacity controls
- Highlight logic
- Zoom behavior
- Overlay controls
- Mask reliability statuses

Prefer extracting shared UI logic into reusable components instead of duplicating the mask viewer.

The main viewer and existing inspector should use consistent mask data and rendering behavior.

Do not create a completely new segmentation pipeline.

## 5. Maintain correct state and performance

- Generate MobileSAM masks during analysis using the existing workflow.
- Cache the results for the current analysis.
- Make switching between views instant.
- Do not rerun Model 1, Model 2, MobileSAM, or feature extraction when toggling.
- Clear previous masks and annotations when a new image is analyzed.
- Prevent stale results from previous analyses.
- Keep overlays aligned during resizing and zoom.
- Preserve existing image and video analysis behavior.
- Handle unavailable masks with a clear explanation rather than displaying stale masks.

## 6. Keep the UI clean

Place the new toggle near the main image viewer, for example:

`View: [Bounding Boxes] [Fish Masks]`

Keep the existing annotation controls accessible directly beside or beneath the toggle.

When Fish Masks is selected, display the mask-specific settings naturally without hiding or deleting functionality.

Do not introduce unnecessary panels, popups, duplicate image previews, or additional steps.

## 7. Verify the implementation

Test that:

1. Bounding Boxes displays the existing original image annotation view.
2. Fish Masks displays the existing shaded MobileSAM visualization in that exact same viewer.
3. Switching modes is instant and requires no new inference.
4. The opacity slider still works.
5. Fish highlighting still works.
6. Zoom still works.
7. Assigned Model 2 parts still display correctly.
8. Mask reliability indicators remain visible.
9. Reanalyzing media clears previous annotations.
10. Model 1, Model 2, and grading results remain unchanged.

Implement the changes directly in the existing repository, run relevant UI tests, and report modified files.

**NON-NEGOTIABLE: Do not remove existing functionality, settings, or controls. Do not redesign the entire Analyze Media interface. Only add the main-view toggle and reuse the working mask visualization.**

**FINAL OBJECTIVE:** Let me switch between the original bounding-box view and the shaded fish-mask view in the same main Analyze Media viewer, while retaining every existing opacity, highlighting, zoom, annotation, and mask inspection setting.
