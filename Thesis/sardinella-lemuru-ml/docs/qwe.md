# TAMBAN THESIS — Advanced UI/UX Refinement, Interactive Fish Zoom, Grade-Based Colors & Analytics Dashboard

Act as a Senior UI/UX Designer, Frontend Engineer, Data Visualization Engineer, and Computer Vision Application Developer.

Perform a comprehensive UI/UX improvement of the existing Tamban Fish Inspection System, focusing on **Analyze Media, Live Inspection, fish visualization, zoom interactions, and Analytics**.

Implement all improvements directly in the existing repository. Do not merely provide suggestions.

**IMPORTANT: Preserve all existing AI models, grading rules, segmentation, anatomical evidence, geometry measurements, crack detection, camera settings, and working functionality.**

## 1. Fix Fish Colors to Represent Actual Grades

Currently, fish masks use arbitrary colors that do not correspond to their final AI classifications. This makes it difficult to identify which fish are Class A, B, C, Rejected, or Ungraded.

Change the visualization so the **color represents the actual final grade**.

Use this consistent color system throughout the application:

| Classification | Color |
|---|---|
| Class A | Green |
| Class B | Blue |
| Class C | Orange |
| Rejected | Red |
| Ungraded | Gray |

Apply these colors consistently to:

- Fish segmentation masks.
- Bounding-box outlines.
- Fish ID labels.
- Result cards and classification badges.
- Inspection History.
- Analytics charts and legends.

### Important behavior

- Read the grade directly from the actual final grading result.
- Never derive a grade from the mask color, confidence, or detection score.
- Do not replace the grade with "Review" or "Unvalidated."
- Keep mask reliability as a separate status indicator.
- If a fish is Ungraded, display gray even when its experimental mask looks reliable.
- If several fish share the same grade, use subtle shade differences, distinct outlines, and visible Fish IDs so neighboring fish remain distinguishable.
- Maintain enough transparency to see anatomical features beneath the mask.
- Preserve the existing opacity slider.

For example:

**Fish #1 · Class A** — Green mask

**Fish #2 · Class B** — Blue mask

**Fish #3 · Class C** — Orange mask

**Fish #4 · Rejected** — Red mask

**Fish #5 · Ungraded** — Gray mask

If mask ownership requires review, display a small warning icon separately without replacing the final classification.

Add a compact grade-color legend to the viewer.

## 2. Restore Zoom and Add Double-Click-to-Zoom for Individual Fish

The previous zoom functionality was removed or became inaccessible during the UI redesign.

Restore it and improve fish inspection interactions.

### Required interactions

**Single-click a fish**
- Select that fish.
- Highlight its mask or bounding box.
- Display its grading and anatomical evidence in the corresponding results panel.
- Do not automatically zoom.

**Double-click a fish**
- Automatically zoom into that specific fish.
- Center the selected fish in the viewer.
- Calculate the zoom region using its actual mask bounds or detection coordinates.
- Include a small amount of surrounding space for anatomical inspection.
- Keep the selected fish fully visible when possible.
- Preserve image quality and correct annotation alignment.
- Show its Head, Body, Tail, geometry, and crack overlays when enabled.

**Double-click again or click Fit Image**
- Return to the original fitted image when appropriate.

Also preserve manual zoom controls, panning, and the ability to reset the view.

### Technical requirements

- Implement actual fish-specific zoom, not just scaling the entire image without focusing on the selected fish.
- Use original-image coordinates.
- Support fish positioned horizontally, vertically, and diagonally.
- Handle overlapping fish carefully using reliable selection and hit-testing.
- If multiple masks overlap under the cursor, prioritize the selected fish or provide a clear disambiguation mechanism.
- Prevent double-clicking controls or empty areas from accidentally selecting a fish.
- Maintain mask, bounding-box, geometry-line, and crack-overlay alignment.
- Keep the original image aspect ratio.
- Support mouse double-click and touch double-tap where practical.
- Allow keyboard-accessible fish selection and zoom actions.

**Critical:** Zoom should happen only when the user explicitly double-clicks or uses a zoom control. Single-clicking should only select the fish.

Switching between Bounding Boxes and Fish Masks must retain the current selected fish and viewing state whenever possible.

Do not rerun Model 1, Model 2, or MobileSAM when zooming.

## 3. Redesign Analytics as a Dedicated Sidebar Page

The current Analytics and Session Analytics are essentially the same functionality, but users must scroll down the inspection page to access the charts.

**Consolidate them into one dedicated Analytics page accessible directly from the main sidebar.**

Use a sidebar structure similar to:

- Live Inspection
- Inspection History
- Review Queue
- **Analytics**
- Model
- Settings

Do not maintain two separate, duplicated analytics interfaces.

Remove the redundant Session Analytics section from the bottom of Live Inspection once its functionality has been successfully migrated.

Preserve all existing calculations, graphs, filters, and analytics capabilities.

### Analytics page layout

Create a professional dashboard with a compact header, session/date filters, summary cards, and interactive charts.

Show the most important information immediately without requiring extensive scrolling.

Use a responsive dashboard grid.

### Overview cards

Display:

- Total inspected fish.
- Total inspection sessions.
- Graded fish count and percentage.
- Ungraded fish count and percentage.
- Class A count.
- Class B count.
- Class C count.
- Rejected count.

Use actual data from saved inspection sessions.

Cards should be compact, consistent, and visually easy to scan.

### Required visualizations

**A. Fish Grade Distribution**
- Interactive doughnut or pie chart.
- Class A, B, C, Rejected, and Ungraded.
- Use the same grade colors as the fish masks.
- Show counts and percentages.
- Clicking a category filters relevant fish records.

**B. Inspection Activity**
- Line or area chart showing the number of fish inspected over time.
- Support hourly, daily, weekly, and monthly views when data is available.

**C. Graded vs. Ungraded**
- Bar or stacked chart showing grading coverage.
- Clearly distinguish graded, Ungraded, and Rejected results.

**D. Anatomical Detection and Association**
- Head detection and acceptance.
- Body detection and acceptance.
- Tail detection and acceptance.
- Show raw detections separately from successfully assigned anatomical parts where the data supports it.

**E. Common Ungraded Reasons**
- Horizontal bar chart ranking reasons fish could not be graded.
- Examples include missing required Head evidence, missing Body evidence, ambiguous ownership, and clipping issues.
- Use actual recorded reasons only.

**F. Session Performance**
- AI processing FPS over time, where recorded.
- Average image processing time.
- Fish inspected per minute.
- Available detection confidence and grading-support distributions.

Distinguish camera preview FPS from AI processing FPS.

**G. Session Comparison**
- Compare fish counts and grade distributions across selected inspection sessions.
- Support meaningful comparisons without mixing duplicate fish observations with unique fish records.

Do not fabricate missing performance or classification data.

## 4. Add Fullscreen Viewing for Every Analytics Graph

Each chart should have a small **Expand / Fullscreen icon** in its upper-right corner.

When clicked:

- Expand that particular graph to fullscreen.
- Hide unrelated dashboard elements.
- Resize the graph to use the available screen space.
- Preserve labels, legends, axes, tooltips, and interactions.
- Allow changing relevant filters while the graph is expanded.
- Support mouse hover, chart selection, and zooming where appropriate.
- Allow exiting with ESC or a minimize icon.
- Restore the chart to its original position without losing selections.

Use the browser Fullscreen API when supported, with a reliable fallback.

Do not merely enlarge a card while leaving the entire dashboard visible.

Also support exporting charts as PNG where practical, and exporting underlying data as CSV.

## 5. Make Analytics Easy to Navigate Without Excessive Scrolling

Organize Analytics into compact dashboard sections or tabs such as:

**Overview | Grade Analysis | Model Evidence | Performance**

The default Overview should present the most important KPI cards and charts within the initial desktop viewport whenever practical.

- Use a compact sticky filter bar.
- Avoid enormous chart containers.
- Avoid unnecessary blank spaces.
- Avoid excessive vertical gaps.
- Allow switching between analytics sections without scrolling through every chart.
- Preserve each tab's filter selections.
- Make charts responsive to available space.
- Use readable tooltips, legends, and meaningful chart titles.

Add a **Session Selector** with:

- All Sessions.
- Latest Session.
- Individual saved sessions.
- Custom Date Range.

All displayed analytics must update consistently according to the selected scope.

The dashboard must retrieve real persisted inspection data.

## 6. Connect Analytics to Inspection History

Make Analytics and Inspection History work together.

When users click a chart category or session:

- Navigate to or filter the corresponding inspection records.
- Preserve the selected session and classification filters.
- Allow viewing individual Fish IDs.
- Open the fish's complete grading and anatomical evidence where available.
- Allow returning to Analytics without losing the dashboard state.

For example, clicking the **Ungraded** section of a chart should show the relevant Ungraded fish records, not a generic page.

Keep Inspection History independently usable when the camera is offline.

Ensure unique fish counts and session durations are accurate.

## 7. Further Refine Analyze Media UI

The Analyze Media interface still has unnecessary spacing and an awkward floating toolbar.

Improve it further:

- Replace the oversized "Fullscreen" text with a compact maximize icon.
- Fix overlapping and overflowing toolbar text.
- Keep Fit, zoom, and fullscreen controls compact.
- Minimize the media upload toolbar height.
- Display a truncated filename with file details and Replace/Remove actions.
- Keep Run Analysis prominent but not oversized.
- Preserve the resizable 70/30 viewer/results layout.
- Automatically fit the entire image within the viewer.
- Eliminate unnecessary internal image scrolling.
- Make the viewer occupy the majority of available space.
- Keep the selected fish's grading evidence immediately accessible.

Before analysis, minimize or collapse the empty results panel so more room is available for the image.

After analysis, show the Results by Final Grade layout.

Keep geometry and crack evidence inside each fish's result card rather than displaying duplicate standalone lists.

## 8. Improve the Live Inspection UI

Apply the same visual consistency to the Live Inspection camera.

- Make the camera feed prominent.
- Preserve true fullscreen functionality.
- Keep fullscreen, Fit/Fill, and settings controls in a compact floating toolbar.
- Improve status presentation.
- Keep Start/Stop Inspection easy to access.
- Avoid duplicate controls.
- Preserve camera exposure/EV settings.
- Preserve Model selection and camera source selection.
- Maintain accurate detection overlay alignment.
- Keep essential inspection statistics visible without requiring users to scroll to the bottom.

Move detailed analytics to the dedicated Analytics sidebar page instead of duplicating the same graphs inside Live Inspection.

## 9. Improve Overall Visual Design

Maintain the Tamban branding and light theme, but refine the interface to look like a professional inspection platform.

Focus on:

- Consistent grade colors everywhere.
- Compact and readable controls.
- Better information hierarchy.
- Clear active and selected states.
- Smooth but restrained transitions.
- Professional interactive charts.
- Responsive card grids.
- Consistent typography and icon sizing.
- Better spacing.
- Accessible contrast.
- Clear empty, loading, and error states.
- Reduced scrolling.
- Accurate tooltips and explanations.

Use animations only where they improve interaction, such as chart expansion, panel resizing, fish selection, and zoom transitions.

Avoid animations that reduce inspection performance.

## 10. Preserve Existing Functionality

Do not remove:

- Model 1 V2 detection.
- Model 2 anatomical grading.
- MobileSAM segmentation.
- Bounding Boxes / Fish Masks toggle.
- Mask opacity control.
- Fish highlighting.
- Geometry measurements.
- Crack overlays.
- Model 2 part visualization.
- Camera exposure/EV adjustments.
- Live camera inspection.
- Image/video analysis.
- Session recording.
- Inspection History.
- CSV/PDF export.
- Existing grading logic.

Do not retrain models or change grading thresholds.

All visualizations must reflect the actual final results.

## 11. Comprehensive Browser Testing

Perform real browser-based testing at 1366×768, 1920×1080, and smaller screen sizes.

Verify:

1. Fish masks use colors corresponding to their actual final grades.
2. Bounding-box colors match those same grades.
3. Ungraded fish are not incorrectly displayed as Class A/B/C.
4. Mask-review status remains independent of grading.
5. Single-click selects a fish without zooming.
6. Double-click zooms into the correct fish.
7. Fit Image restores the complete image.
8. Fish masks and annotations remain aligned after zooming.
9. Overlay switching does not rerun AI inference.
10. Analytics appears directly in the sidebar.
11. Duplicate Session Analytics sections are removed after successful migration.
12. Dashboard counts match stored inspection records.
13. Charts respond correctly to session and date filters.
14. Each graph can enter and exit fullscreen.
15. Clicking a chart category opens the correct related records.
16. Charts and dashboard layouts work on smaller screens.
17. Media upload, fullscreen viewing, and existing controls remain functional.
18. No new overflowing toolbars, unwanted scrollbars, or large empty containers are introduced.

Capture actual browser screenshots, inspect the layout, and fix visible defects.

Report modified files, tests completed, screenshots where available, and remaining limitations.

## Final Objective

Create a polished, professional, and highly interactive Tamban inspection platform.

The desired workflow is:

**Live Inspection / Analyze Media → See fish colored by their actual grades → Single-click to inspect evidence → Double-click to zoom into that specific fish → Open Analytics directly from the sidebar → Explore session statistics through interactive, fullscreen graphs.**

The fish viewer should be the centerpiece of inspection, while Analytics should be a dedicated, easily accessible dashboard—not something users must scroll down to find.

**NON-NEGOTIABLE:** Preserve existing models, accurate classifications, evidence validation, camera controls, segmentation, session records, and all functional features. Do not invent grades or analytics, and do not improve appearance at the expense of inspection reliability.