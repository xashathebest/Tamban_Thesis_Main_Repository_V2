# Working on-demand fish-mask preview

Implemented from `notebooks/sam.md` on November 2, 2026. **Inspect fish masks**
now makes a real API request and displays shaded MobileSAM candidates over the
matching original image. The preview is optional and does not change grading,
body-width measurements, or crack evidence.

## Root cause and repair

The checkpoint was already installed, the supported CPU backend worked, and
the running server advertised MobileSAM capability. The original button only
opened the existing per-fish zoom viewer. It neither generated masks nor made
a segmentation request, and it remained disabled unless the user had already
run an analysis with the experimental checkbox enabled. There was no separate
all-fish original-image shaded-mask preview. The previous synthetic browser
test verified rendering contracts but did not establish this missing path.

The button now works directly after choosing an image, or after an ordinary
analysis. It calls `POST /api/segmentation/preview` with the actual file bytes
and `X-Filename`. After photo analysis, it also sends the optional
`X-Preview-Analysis-Token` returned by `/api/analyze-image`. No candidate polygon
is invented from a detector rectangle.

When a valid token is supplied, the backend reuses that analysis's Model 1
boxes, Fish IDs, and assigned Model 2 evidence. Otherwise it runs the unchanged
Model 1 detector once to obtain prompts. **Neither path reruns Model 2,
GrabCut, the weighted grader, metrology, or crack extraction.** One lazy
MobileSAM service computes one image embedding and processes the fish prompts
sequentially, retaining original-coordinate mask provenance.

The token cache contains only detection/part metadata, never uploaded images
or mutable grading state. It holds at most 32 snapshots for five minutes.
Tokens are bound to the raw uploaded-byte SHA-256, original decoded frame
shape, and Model 1 object/checkpoint/settings signature. Mismatched, expired,
or changed-detector tokens return HTTP 409. The endpoint preserves the existing
upload limits, inference locks, and strict Model 1 integrity setting; unavailable
whole-fish detection is an explicit HTTP 503 rather than an invented prompt.

The response records original image dimensions and hash, a canonical
unannotated JPEG preview, per-fish boxes/assigned parts, compact mask contours,
foreground counts, ownership-check results, and backend timing/setup status.
Empty, full-image, nearly rectangular, or unrenderable foreground cannot count
as a usable silhouette. `generated`, `unavailable`, and `no_fish` are distinct
outcomes. Backend setup/inference errors and the checkpoint setup command are
shown instead of a success message when no usable mask is returned.

## Using the viewer

Open **Analyze Media**, choose a photo, expand **Experimental fish masks**, and
click **Inspect fish masks**. Running ordinary analysis first allows prompt
and assigned-part reuse; it is not required to generate a preview.

The viewer uses different colors, 40% default opacity, thin contours, Fish ID
labels, review markers, and a per-fish legend. Controls show/hide masks, Model 1
boxes, and assigned Model 2 parts, adjust opacity, select a single fish or all
fish, and zoom. Model 2 annotations are off by default. Unassigned diagnostic
boxes are not presented as a selected fish's owned anatomy.

Masks and original-image coordinates are drawn through one canvas transform.
The canonical preview handles original orientation, native dimensions, display
resizing, and the backing-grid cap explicitly. Parent/frame/dimension mismatches
withhold overlays. New analyses, file changes, image/video switches, closing the
workspace, failed requests, and cancellations clear prior masks. Request-version
and file-identity checks prevent late responses from repainting another image.
The mask request has a live elapsed timer, separate reported backend segmentation
seconds, explicit errors, and a cancel control.

Direct on-demand preview is for images. Uploaded video continues using its
separately recorded per-fish source-frame evidence; the photo button does not
pretend to segment an arbitrary current video frame.

## Actual model, API, and browser proof

The explicit [CPU/Chrome smoke harness](../tests/sam_preview_browser_smoke.py)
loaded the unchanged real Model 1 V2 and Model 2 checkpoints in an isolated
ephemeral API process, analyzed a real project photograph, then requested actual
MobileSAM masks through HTTP and exercised the actual browser canvas.

**33 named checks and the mobile layout assertion passed.** Evidence includes:

- Nine real detector boxes, nine returned candidate masks, nine accepted polygon
  entries, nine distinct colors, nonrectangular silhouette vertices, and exactly
  one real MobileSAM encoder call for all prompts.
- The analyzed-image token reused existing boxes: Model 1 = 1, Model 2 = 1,
  GrabCut = 9 before and after preview. The preview added no calls to those
  stages and did not mutate the serialized grading results.
- Inspecting before any analysis also worked, calling Model 1 once, Model 2
  zero times, GrabCut zero times, and the SAM encoder once.
- Real shaded pixels, hide/show, two distinct selected-fish outputs, and opacity
  changes were captured. Source hash and 640 x 640 native dimensions matched.
  At a 390-pixel mobile viewport, document and scroll widths were both 390;
  the responsive canvas was 318 pixels wide.
- An actual malformed image produced a visible decode error. Selection changes,
  image/video switches, and canceling an old request cleared the overlay.
- CUDA remained uninitialized; protected Model 1/Model 2 hashes matched before
  and after the test. The existing port-8000 service was not used for inference
  or modified by this isolated smoke test.

| Observed CPU request | Segmentation | Backend total | Model 1 |
| --- | ---: | ---: | ---: |
| Reuse after ordinary analysis | 1,348.304 ms | 1,395.478 ms | Reused; 0 ms |
| Standalone preview, model already loaded | 1,009.262 ms | 1,172.039 ms | 122.767 ms |

These are single observed request measurements, not a repeated speed comparison
or GPU benchmark. Backend totals include mask validation and original-preview
encoding but exclude request decode, network, and browser rendering. The first
request recorded a 181.965 ms MobileSAM load. GPU memory and RTX 2050 performance
were not measured. The existing CPU-default, FP32, singleton, shared-embedding,
memory-preflight, and OOM-fallback behavior remains described in
[the MobileSAM integration report](mobilesam_integration.md).

Inspect the [original / boxes / actual shaded-mask comparison](../results/qa/sam_preview/original_boxes_masks.comparison.png),
[actual shaded overlay](../results/qa/sam_preview/mobilesam_shaded.png),
[desktop browser](../results/qa/sam_preview/actual_preview_desktop.png),
[mobile browser](../results/qa/sam_preview/actual_preview_mobile.png),
[full assertion/response record](../results/qa/sam_preview/actual_e2e.json), and
[detailed visual review](../results/qa/sam_preview/actual_e2e_review.md).

## Model 2 false-positive concern

A concrete display issue was reproduced: the ordinary fish zoom viewer drew
unassigned or ambiguous Model 2 diagnostic boxes inside each overlapping fish
crop. One physical candidate could appear in several fish viewers, despite not
being owned grading evidence. The ordinary viewer now draws assigned parts
only. Raw outputs and rejected/ambiguous association evidence remain recorded.

The [Model 2 investigation](model2_falsepositive_audit.md) compares the actual
old and current detector methods/outputs and reruns all 17 test-export images.
The current detector results match the saved pre-MobileSAM evaluation exactly:
53 unmatched class-aware predictions at confidence 0.25, 190 matched boxes,
35 missed annotations, and mAP50 0.548903. Confidence, input size, class mapping,
NMS behavior, model weights, and annotations were not changed to hide output.
This supports a display correction and reproduces existing detector errors;
it does not establish that every recently reported false positive is solved.
The development export also has known training overlap and does not supply an
independent accuracy claim. A recent failing original image with reviewed part
ownership would support a separate precision investigation.

## Changed files and remaining limits

Additional implementation changes for `sam.md` are:

- `src/api/app.py`: preview endpoint, bounded token metadata, and photo token.
- `src/api/segmentation_preview.py`: cache, native candidate generation, usable
  silhouette checks, original preview, status, timing, and conservative flags.
- `frontend/app.js`, `frontend/index.html`, `frontend/styles.css`: real button
  request, separate shaded viewer/controls/lifecycle, assigned-only fish overlay.
- `tests/test_sam_preview_api.py`, `tests/test_sam_preview_ui.py`: regression
  tests; `tests/sam_preview_browser_smoke.py`: actual model/browser smoke.
- This report, `docs/model2_falsepositive_audit.md`, and the separate QA artifacts
  document the reproduction. README/progress notes link the implemented feature.

The [combined regression log](../results/qa/sam_preview/final_tests.log) records
**1,453 passed, 12 skipped, zero failures, 7 warnings, and 127 subtests in 35.34
seconds**, separately from the explicit real-model browser smoke above.
Earlier Featureenhance work remains listed in its own report; existing user
changes were preserved.

## Running dashboard verification

The port-8000 process still held the old API, without the preview endpoint.
After regression checks, only the identified stopped Tamban dashboard was
reloaded using its existing Python executable and `-m src.api` entry point.
No training process was stopped. The new route is available at
`http://127.0.0.1:8000`; Model 1 and Model 2 are ready on their original CUDA
device, with Model 2 confidence 0.25 and input size 768 preserved. Refresh an
already open browser tab to load the new interface.

A real [request to the reloaded dashboard](../results/qa/sam_preview/live_preview.json)
also generated nine native candidates with one image embedding. This standalone
request had no Model 2 snapshot, so all nine required ownership review. MobileSAM
ran on CPU: segmentation was 1,417.272 ms; the existing Model 1 CUDA call took
1,886.501 ms including its first-call work. These are single request observations,
not warmed GPU benchmarks. [Reload status](../results/qa/sam_preview/after_reload_status.json)
records the loaded route and preserved configuration.

Candidates remain **unvalidated**. Eight of the nine masks in the smoke image
required review. One false-positive Model 1 prompt covers the white image
border and SAM produces a broad background candidate there, visibly marked for
review. A successful request or attractive contour does not prove fish identity.
The engineering-pass candidate is also not independently validated. No expert
instance masks, ownership labels, anatomical measurements, crack labels, or
width calibration were fabricated. No retraining or annotation edits were made.
