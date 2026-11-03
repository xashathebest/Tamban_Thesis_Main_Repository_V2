# Analyze Media: main-view mask switch

Updated November 3, 2026. **Bounding Boxes | Fish Masks** switches the existing
main display. Bounding Boxes restores the same annotated image and source URL;
Fish Masks uses the existing native-coordinate mask renderer inside that image
area. No separate viewer is opened.

The mask-visibility checkbox, Model 1 boxes, assigned Model 2 parts, opacity
(including 40%), Fish ID highlight, zoom/Fit Image, review legend, and structural
overlay control remain available. Display changes do not modify the fish results.

## Why the switch could appear unresponsive

The radio control previously called only the synchronous renderer. If its source
image was not ready, there was no preparation action or visible progress. Older
responses with masks stored inside each fish also depended on the original upload
URL, which the analysis flow had already revoked. Image decoding had no timeout.

The switch now prepares recorded masks through one shared promise per current
file. A spinner and measured elapsed seconds remain visible while the source
image is loading. The shaded view appears when ready, provided the user has not
switched back to Boxes or selected another file. Boxes can be restored immediately
while preparation continues. Failures show the actual error, stop the spinner,
and restore the original result.

Recorded per-fish masks can recreate a temporary URL from the current uploaded
file; that URL is released after decoding. Parent/frame/native-dimension guards
still apply. Source decoding times out after 15 seconds instead of hanging.

Cached masks require no HTTP inference request. If this analysis contains no
recorded masks, the existing preview endpoint can generate them once, reusing
the analysis token and detector snapshot when available. It does not run Model 2
or grading. This necessary request has elapsed progress, cancellation, a
120-second timeout, and explicit setup/backend errors. Subsequent switches reuse
its result. Video bytes are never sent to the still-image preview endpoint.

## Validation

- Six preparation regressions cover elapsed progress, shared preparation,
  automatic display, switching back during loading, decode failure, revoked
  upload URLs, necessary one-time generation, and stale-source rejection.
- Six main-view regressions cover identical original-image restoration, all
  overlay controls, opacity/highlight/zoom, new-analysis resets, unavailable
  masks, recorded-mask reuse, and placement inside the original main viewer.
- The real-model HTTP/Chrome smoke passed 38 main checks and four lifecycle
  checks, plus the 390-pixel mobile layout assertion. It produced real shaded
  fish masks, exercised loading and decode errors, and kept Model 1 and Model 2
  at one call each and SAM at one image encoding throughout display changes.

See [the real-browser evidence](../results/qa/sam_features/actual_e2e.json),
[the main-view screenshot](../results/qa/sam_features/actual_preview_desktop.png),
[the colored mask output](../results/qa/sam_features/mobilesam_shaded.png), and
[the combined regression log](../results/qa/sam_features/final_tests.log).
Mask candidates remain unvalidated; these are software and rendering checks,
not anatomical or crack-accuracy measurements.

## UI implementation files

- `frontend/app.js`: main display, cached-mask preparation, progress/errors,
  one-time fallback, and lifecycle guards.
- `frontend/index.html`: main-view toggle, retained settings, inline loading
  indicator/cancel control, and updated asset versions.
- `frontend/styles.css`: loading indicator and main-view canvas placement.
- `tests/test_main_view_mask_toggle.py`, `tests/test_mask_view_preparation.py`:
  main-view and preparation regressions.
- The existing UI harness/assertions in `tests/test_sam_preview_ui.py` and
  `tests/test_sam_features_ui.py` accommodate the retained controls. The actual
  browser harness is `tests/sam_features_browser_smoke.py`.

Refresh an already open dashboard once to load the updated script and styles.
