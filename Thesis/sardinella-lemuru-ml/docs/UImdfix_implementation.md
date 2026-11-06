# Live Inspection and Analyze Media implementation

Implemented the instructions in `UImdfix.md`. Existing uncommitted repository changes were retained. No trained models, segmentation algorithms, grading rules, or grading thresholds were changed by this work.

## Viewer behavior

- Browser fullscreen now targets `live-media-stage` or `upload-media-stage`, rather than the camera card or analysis dialog. Only the media and floating toolbar appear in fullscreen. ESC or the minimize icon restores the workspace.
- Both viewers provide Fit, Fill, zoom and pan. Fit displays the complete frame; Fill preserves aspect ratio and allows panning across cropped content. Media, native-coordinate canvas annotations and fish hit targets use matching geometry.
- Fullscreen changes retain the same media nodes, stream URLs, playback and cached analysis. Unsupported or denied Fullscreen API requests use an expanded viewer fallback.
- Fullscreen keyboard navigation stays inside the viewer. The camera-settings shortcut exits fullscreen before opening its drawer.

## Workspace changes

- Live Inspection uses a larger viewer, compact model/source/status toolbar, one primary Start/Stop action and secondary Reset/Analyze actions. Camera settings and viewer controls sit inside the image. The redundant webcam shortcut remains in the DOM with its existing handler; source selection and Start provide its existing operation.
- Analyze Media defaults to a 70/30 viewer/results split. Drag the separator, use arrow keys (Shift for larger steps), or double-click to reset it. Tablet/mobile layouts stack the panels and use the media's aspect ratio.
- Upload selection collapses to a compact toolbar with filename, type, thumbnail, replace/remove, analysis action and elapsed processing status. Video files receive a first-frame thumbnail when the browser decodes them.
- Secondary overlay controls and technical explanations are expandable. Existing boxes/masks, opacity, anatomical annotations, geometry, cracks, reliability evidence, grading groups and exports remain available.
- Image and results selection synchronize. Highlighting one fish no longer prevents directly selecting another visible fish in the source image.
- The modal locks background scrolling; the media canvas has no internal scrolling. Desktop results retain one scrollable evidence pane; stacked layouts use the modal's outer scroll.

## Camera state

`LiveFrameStatus` independently records acquired frames and successful processing completions. `/api/status/live` exposes freshness, capture resolution, capture FPS and processing FPS even when optional runtime diagnostics are disabled. The UI distinguishes connecting, preview, AI processing, paused processing, stalled capture, stopping, disconnected and error states. Rates count frames in the preceding second; browser MJPEG load events are not presented as capture FPS. Failed processing fallbacks no longer inflate the successful-processing counter.

## Validation

- **218 pytest tests passed** across 23 targeted camera, lifecycle, exposure, native-coordinate geometry, masks, grading presentation, upload, model selector, session and export modules.
- `node --check frontend/app.js` passed; changed tracked files passed `git diff --check`.
- **56 camera-workspace Chrome checks passed**, using trusted mouse/keyboard input, a real local MJPEG stream, a generated native 1280×720 video, and cached synthetic fish evidence.
- The existing inspection-workspace browser suite passed **23 checks**; the anatomical-overlay browser suite passed **23 checks**.
- Responsive checks covered 1366×768, 1920×1080, 1024×700, 768×1024 and 390×844. Browser checks exercised true fullscreen dimensions, ESC, keyboard focus, Fit/Fill, 640×480 and 1280×720 coordinate alignment, mask zoom/pan, synchronized selection, mouse/keyboard resizing, thumbnails, overlays and action routing.
- The live fixture kept one MJPEG connection through fullscreen and continued delivering frames. Native video playback advanced through fullscreen. Display changes made no inference requests and preserved recorded grading. No browser runtime exceptions were recorded.
- After screenshot-guided refinement, the desktop analysis media stage measured 447px high at 1366×768 versus 307px in the initial redesigned layout; at 1024×700 it grew from 180px to 379px. These are fixture-layout measurements, not a comparison against the original repository UI.

### Evidence

- [Browser results](../results/qa/camera_workspace/camera_workspace_browser.json)
- [Desktop analysis](../results/qa/camera_workspace/upload_1366x768.png)
- [Mobile analysis](../results/qa/camera_workspace/upload_390x844.png)
- [Live inspection](../results/qa/camera_workspace/live_1366x768.png)
- [Viewer fullscreen](../results/qa/camera_workspace/upload_fullscreen.png)
- [Video fullscreen](../results/qa/camera_workspace/video_fullscreen.png)

Run the browser suites explicitly from the project directory:

```powershell
$env:TAMBAN_CHROME_NO_SANDBOX = '1' # Required in this execution sandbox.
python -B tests/camera_workspace_browser_smoke.py
python -B tests/inspection_workspace_browser_smoke.py
python -B tests/anatomical_debug_browser_smoke.py
```

The tests use temporary Chrome profiles and do not start the inference backend. This environment's project virtual environment could not read some installed packages; validation used the working global Python installation at `C:/Users/User/AppData/Local/Python/pythoncore-3.14-64/python.exe`.

### Limits

Physical webcam/driver behavior, GPU/model throughput, real fish accuracy and other browsers were not exercised. Backend freshness and rate states were tested with deterministic fixtures; the MJPEG/video checks validate uninterrupted display, not live model execution. Native fullscreen depends on browser support and permission.

## Files changed for this request

- `frontend/index.html`, `frontend/app.js`, new `frontend/camera-workspace.css`
- `src/api/app.py`, `src/api/camera.py`, new `src/api/live_frame_status.py`
- New `tests/camera_workspace_browser_smoke.py`, `tests/test_live_frame_status.py`, `tests/test_media_viewer_geometry.py`
- Updated `tests/anatomical_debug_browser_smoke.py`, `tests/inspection_workspace_browser_smoke.py`, `tests/test_fish_click_zoom.py`, `tests/test_inspection_grade_workspace_ui.py`, `tests/test_session_totals_ui.py`
- This implementation report; browser JSON and screenshots under `results/qa/`
