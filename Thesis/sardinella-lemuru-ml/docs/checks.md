# TAMBAN THESIS — Complete UI/UX Redesign, Interactive Inspection Workspace, Session History & Analytics

Act as a Senior UI/UX Designer, Full-Stack Developer, and Computer Vision Application Engineer.

Redesign and improve the Tamban Fish Inspection System to make it professional, intuitive, responsive, and suitable for real inspection operations and thesis demonstrations.

Implement all improvements directly in the existing repository. Preserve Model 1 V2, Model 2, grading rules, segmentation, and working functionality.

## 1. Interactive Analyze Media Workspace

Replace the long, scroll-heavy Analyze Media modal with a responsive two-panel inspection workspace.

**Left panel — Fish visualization**
- Display the complete image/video using Fit Image by default.
- Preserve Bounding Boxes / Fish Masks, opacity, zoom, pan, highlighting, Model 2 parts, measurement overlays, and crack overlays.
- Support fullscreen viewing.
- Allow clicking an individual fish to select it.

**Right panel — Fish results**
- Preserve the existing Results by Final Grade design with Class A, B, C, Rejected, and Ungraded groups.
- Display the selected fish's grading, anatomical evidence, geometry, cracks, and mask reliability together.
- Synchronize fish selection between the viewer and result cards.
- Avoid excessive page scrolling and nested scrollbars.

## 2. Correct Fish Labels and Color Meanings

**Important: The current fish visualization displays labels such as "Fish #4 · review" instead of showing the actual grading result. Fix this.**

Every detected fish should display its **actual final classification**, taken directly from the grading engine.

Examples:
- Fish #1 · Class A
- Fish #2 · Class B
- Fish #3 · Class C
- Fish #4 · Rejected
- Fish #5 · Ungraded

Never replace the actual grade with generic labels such as "review," "unvalidated," or "needs attention."

Use a consistent, accessible color system:

| Final classification | Display color |
|---|---|
| Class A | Green |
| Class B | Blue |
| Class C | Orange |
| Rejected | Red |
| Ungraded | Gray |

Apply these colors consistently to fish labels, bounding-box outlines, mask outlines, result cards, and grade indicators.

**Keep the fish-mask fills visually distinguishable by Fish ID**, especially when fish overlap. Do not force neighboring fish to share identical mask colors simply because they have the same grade.

Add a compact legend explaining the grade colors.

**Important distinction:** Grading status and mask reliability are different concepts.

- **Final Grade:** Class A, B, C, Rejected, or Ungraded.
- **Mask Reliability:** Validated, Estimated, or Requires Review.

Display the final grade as the primary fish label.

If a mask requires review, show that separately using a small warning icon or tooltip, without replacing the grade.

For example: **Fish #4 · Class B** with a separate mask-review warning.

If the final grade is genuinely unavailable, display **Ungraded** with its actual reason. Never invent a grade based on mask colors or detection confidence.

## 3. Group Geometry and Crack Evidence Inside Fish Results

Keep the existing Results by Final Grade layout.

Remove the separate repetitive Geometry and Crack Evidence accordion list above the results, and move the information into each fish's result card.

Provide organized sections for Overview, Model 1/Model 2 Evidence, Geometry, Crack Detection, Mask Reliability, and Grading Explanation.

Show length, Body width, width-to-length ratio, abnormal-width evidence, detected crack candidates, severity when validated, and actual grading contributions.

Clearly label evidence as Validated, Estimated, or Unavailable.

Keep explanations concise with optional expanded technical diagnostics.

## 4. Improve Media Upload and Fullscreen Viewing

Redesign the media upload interface with drag-and-drop, Browse Files, a visible preview, replace/remove controls, file details, clear progress, and errors.

Keep the upload area compact after selection.

Add fullscreen viewing to both Analyze Media and the Live Conveyor camera, preserving masks, boxes, annotations, geometry, cracks, zoom, and pan without restarting inference.

## 5. Redesign Inspection History

Organize Inspection History by saved session rather than a large generic filter form.

Display session cards or rows showing date, start/end time, duration, fish count, grade distribution, and status.

Clicking a session opens its fish results grouped by final grade.

Allow searching/filtering by Fish ID, session, date, grade, and verdict.

Support CSV/PDF export for individual fish and complete sessions.

Keep history accessible even when the camera is offline.

## 6. Automatically Save Sessions After One Minute

Persist live inspection sessions after at least 60 seconds of accumulated active inspection time.

Save session metadata, fish records, timestamps, classifications, and available evidence.

Handle camera disconnections, zero-fish sessions, application restarts, and duplicate detection prevention.

Never overwrite previous sessions.

## 7. Add Dedicated Analytics Navigation

Add an Analytics page to the sidebar.

Include actual data-driven charts for session activity, total inspected fish, grade distribution, graded versus Ungraded rates, anatomical evidence availability, common Ungraded reasons, model support, and processing performance.

Support filtering by session and date range, with drill-down to the underlying fish records.

Never use fabricated analytics.

## 8. Improve Data Retrieval, Performance, and Visual Consistency

Audit session persistence, data fetching, filtering, pagination, fish identity, overlays, and CSV/PDF exports.

Ensure fish labels, mask overlays, analytics, and result cards all reference the same final-grade data.

Improve responsive layout, spacing, typography, loading states, error handling, and keyboard accessibility.

Preserve existing controls and cached inference results.

## 9. Validate the Implementation

Test interactive fish selection, accurate grade labels and colors, separate mask-review status, fullscreen behavior, responsive layout, media upload, session saving, history retrieval, analytics, and exports.

Ensure toggling overlays does not rerun inference and UI changes do not alter grading.

Report modified files, actual test results, and remaining limitations.

## Final Objective

Create a professional inspection interface where users can upload or capture fish, run analysis, immediately see each fish's **actual final grade with a meaningful color**, select any fish to view its complete evidence, and review saved sessions and analytics.

**Non-negotiable:** Never confuse experimental mask reliability with fish quality classification. Preserve all models, grading logic, existing controls, and verified data.