Redesign and simplify the **Camera Capture** and **Inspection History** pages of my Tamban Inspection System. The current UI is unnecessarily complicated, with excessive settings, descriptions, headings, and scrolling. I want a clean, modern, minimal interface focused on actual functionality.

### 1. Camera Capture — Complete UI Simplification

Replace the existing complicated interface with a simple camera application.

**Essential features:**
- **Camera Selection:** Detect available cameras and let me choose which camera to use through a simple dropdown. Display actual camera names when supported, not just device indices.
- **Live Preview:** Show a large, responsive camera preview with good proportions.
- **Manual Capture:** One prominent "Capture Photo" button that immediately takes a photo using the selected camera.
- **Automatic Timestamp:** Every captured photo must automatically record the correct local date and time.
- **Google Drive Saving:** Automatically upload each captured photo to the existing configured Google Drive folder. Keep the original image resolution and quality.
- **Recent Photos:** Display captured photos in a compact gallery below the camera, showing thumbnails, capture times, and upload status.
- **Camera Controls:** Only essential controls such as choosing, opening, closing, and refreshing the camera list.
- **Save Reliability:** Keep a local copy until Google Drive confirms the upload. If an upload fails, show a clear status and allow retrying without losing the photo.

**Remove from the main interface:**
- Automatic collection timers, intervals, countdowns, and photo targets.
- Manual collection-session forms and unnecessary metadata fields.
- Operator tags, specimen confirmation, annotation checklists, and bulk review controls.
- Camera technical diagnostics and readback panels.
- Long explanations about research protocols, hardware isolation, OAuth, and storage.
- Excessive headings, informational paragraphs, and duplicate status indicators.

Do not require creating a collection session before capturing. Generate any necessary internal session IDs and provenance metadata automatically without requiring user input.

Keep Google Drive authentication and advanced configuration under Settings, not in the main Camera Capture interface. Use the existing authorized destination rather than introducing a new storage system.

### 2. Inspection History — Simplify the Layout

The current Inspection History page contains redundant headings such as "Durable inspection records," "Saved Inspections," and "Every run, in one place."

Remove these unnecessary sections and explanations.

Use:
- One heading: **Inspection History**
- Compact search and filter controls.
- A clean, organized list of saved inspection sessions and fish results.
- Expandable details for viewing individual inspection evidence.
- Existing export functionality in a compact location.

Make the records immediately visible without requiring excessive scrolling.

### 3. UI/UX Design Requirements

- Use a clean, modern, professional dashboard design consistent with the Tamban system.
- Prioritize functionality over explanatory text.
- Use compact controls, consistent spacing, subtle borders, and clear visual hierarchy.
- Avoid unnecessarily large cards, empty spaces, and oversized headings.
- Keep the main camera controls visible without scrolling on a standard desktop screen.
- Make the interface responsive.
- Use simple status indicators such as "Camera Ready," "Saving," "Saved to Drive," or "Upload Failed."
- Remove redundant UI elements rather than merely hiding them behind more dropdowns.

### 4. Functional Requirements

This must be a functional redesign, not just a visual mockup.

- Verify that camera selection and actual camera switching work.
- Handle conflicts with Live Inspection safely without breaking its functionality.
- Preserve original captured image quality.
- Ensure timestamps are recorded accurately.
- Verify that Google Drive uploads actually succeed and retain the correct folder destination.
- Never show a photo as successfully uploaded until Google Drive confirms it.
- Preserve existing inspection records, data storage, and underlying inference functionality.
- Remove unnecessary UI and dependencies without disrupting unrelated features.

**Overall goal:** Camera Capture should feel like a simple camera application, not a research administration dashboard. I should be able to open the page, choose a camera, take a photo, and have it automatically saved to Google Drive with a timestamp. Everything else should stay out of the way.