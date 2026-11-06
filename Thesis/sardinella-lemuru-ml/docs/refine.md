# TAMBAN THESIS — Refine Analyze Media UI/UX, Fix Overflow, and Maximize Inspection Space

Act as a Senior UI/UX Designer and Frontend Engineer.

Perform a comprehensive UI/UX refinement of the existing **Analyze Media** workspace. The current 70/30 layout is better, but the interface still has excessive spacing, oversized controls, overflowing toolbar text, wasted screen space, and unnecessary scrolling.

**Implement improvements directly in the repository. Focus on refining the existing interface rather than rebuilding it.**

## 1. Fix the Viewer Toolbar

The current floating viewer toolbar has an oversized, overflowing "Fullscreen" label.

- Replace the text button with a compact **Maximize/Minimize icon**.
- Position it in the upper-right corner of the media viewer.
- Use an accessible tooltip and aria-label.
- Fix overflow, incorrect flex sizing, and toolbar clipping.
- Use compact icons or appropriately sized controls for Fit/Fill, zoom, and fullscreen.
- Prevent controls from overlapping each other or covering important fish annotations.
- Keep the toolbar visually polished with subtle transparency.

## 2. Make the Fish Viewer the Main Focus

- Maximize the actual available image/video viewing area.
- Use `object-fit: contain` or equivalent fitting logic by default.
- Ensure the entire original image is visible without internal scrolling at Fit mode.
- Preserve correct aspect ratio, image coordinates, and annotation alignment.
- Support zoom and pan when explicitly selected.
- Avoid cropping fish unintentionally.
- Use responsive viewport-based sizing rather than arbitrary fixed heights.
- Remove unnecessary empty areas around the media.

The user should immediately see the complete fish image after uploading or analyzing it.

## 3. Make Uploading Much More Compact

The current media upload section consumes too much screen space.

**Before upload:**
- Show a compact, attractive dropzone with an upload icon, Browse Files action, and brief supported-format text.
- Avoid large empty upload containers.

**After upload:**
- Collapse into a clean single-row toolbar.
- Display a shortened filename and file size.
- Keep Replace, Remove, and Run Analysis available.
- Show clear processing status and elapsed time.
- Use appropriate button sizes, spacing, and alignment.
- Handle long filenames with truncation and tooltips.

Reduce unnecessary padding and avoid overly wide gaps between actions.

## 4. Improve the Two-Panel Workspace

Keep the existing resizable 70% viewer / 30% results layout, but optimize how space is used.

**Viewer panel**
- Prioritize the media.
- Reduce excessive card headers and vertical padding.
- Keep important overlay controls organized.
- Make the full image visible in Fit mode.

**Results panel**
- Before analysis, avoid a huge empty panel; use a compact helpful state or allow the viewer to expand into the unused space.
- After analysis, restore the results panel automatically.
- Preserve the existing Results by Final Grade cards and colors.
- Make individual fish selection prominent.
- Display selected fish evidence in compact, organized sections.
- Use expandable details for lengthy technical explanations.

Keep both panels synchronized when selecting Fish IDs.

## 5. Improve Overlay Controls

Preserve every existing control:

- Bounding Boxes / Fish Masks.
- Mask opacity.
- Fish ID highlighting.
- Model 2 anatomical overlays.
- Geometry measurements.
- Crack candidates.
- Zoom, pan, and fullscreen.
- Overlay reliability indicators.

Organize these into a compact, intuitive toolbar with optional expandable advanced settings.

Do not remove functionality just to reduce visual clutter.

## 6. Fix Scrolling and Responsive Behavior

- Eliminate unnecessary nested scrollbars.
- Avoid horizontal overflow.
- Ensure Fit Image never requires scrolling to see the entire original image.
- Use independent scrolling only where genuinely necessary, such as lengthy fish evidence.
- Maintain appropriate sticky controls.
- Make desktop, laptop, tablet, and mobile layouts responsive.
- Prevent the floating toolbar from expanding beyond its container.

Test specifically at 1366×768, 1920×1080, and smaller viewport sizes.

## 7. Improve Visual Consistency

Maintain the existing Tamban design language.

Refine:

- Button dimensions and alignment.
- Icon sizing.
- Text hierarchy.
- Card spacing.
- Margins and padding.
- Border radii.
- Hover and focus states.
- Loading and empty states.
- Grade labels and mask-review indicators.
- Viewer and results alignment.

Prioritize a clean, modern inspection workspace rather than excessive decorative styling.

## 8. Validate Through Actual Browser Testing

Inspect the actual rendered UI, not just its CSS.

Verify:

1. The fullscreen icon is correctly sized and positioned.
2. No toolbar text or icon overflows.
3. Upload controls remain compact before and after file selection.
4. The full fish photograph fits inside the viewer.
5. Zoom and pan work without misaligning annotations.
6. The viewer remains the dominant visual element.
7. The results panel is accessible without excessive scrolling.
8. Fish selection synchronizes with the correct evidence.
9. The 70/30 split is resizable.
10. Every existing mask, geometry, crack, and grading control continues working.
11. Layouts remain polished at different screen resolutions.

Capture and inspect browser screenshots before and after implementation. Fix any visual defects found rather than relying only on automated test success.

## Final Objective

Make Analyze Media **compact, intuitive, visually balanced, and inspection-focused**.

The desired experience is:

**Choose an image → Instantly see the complete image → Run analysis → Click a fish → View its results without unnecessary scrolling.**

The fish viewer must receive the most visual attention, with a compact upload toolbar, clean annotation controls, a properly sized fullscreen icon, and an efficient results panel.

**Do not modify AI models, segmentation logic, grading rules, or backend calculations. Preserve all existing working functionality.**