# Annotation management completion and QA

The library is served at `/annotations`. The V2 application runs separately from
the older application on port 8000; its local URL is
`http://127.0.0.1:8001/annotations`. Existing external application data is not
overwritten or moved.

The designated primary dataset is **Fish Annotations Cleaned**: 345 original
images and 4,867 annotations from `Fish_Annotations_Cleaned.zip`, registered as
`fish-annotations-cleaned-dbf50ab47c1d`. The retained **V2 COCO v7** collection has
910 images and 9,723 annotations. All saved datasets contains 1,255 images and
14,590 annotations; the selector keeps their counts and exports separate.

## 1. UI components

- Dashboard with persisted image/object counts and approval progress.
- Dataset selector, filename search, status filters, date/name/status sorting,
  24-image pagination, lazy thumbnails, and multiselect.
- Completed Annotations gallery for saved images with object annotations.
- Original-image SVG review viewer with real polygon/RLE masks, class labels,
  optional boxes, zoom/pan/fit, fish groups, and bidirectional object selection.
- Class and fish-association editing, polygon drawing/redrawing, vertex edits,
  mask coordinate editing, object deletion, individual review, and Undo/Redo.
- Whole-image review/approval/rejection and approval of reviewed selections.
- Autosave/manual save, failure retry, recoverable browser drafts, immutable
  saved-version preview and restore.
- Current/selected/all/approved JSON downloads and dataset ZIP packages.
- Collapsed class manager and canonical validation/COCO/YOLO export panel.

## 2. Reused components

All adapters use `src/annotation/store.py` and its single SQLite workspace.
`src/annotation/masks.py` handles exact COCO masks; the existing annotation
automation callback generates new predictions. The inline review and learning
adapters use that same workspace. Existing FastAPI static serving, LAN
authentication/CSRF, source taxonomy, and canonical validation/export are reused.
The inspection dashboard's `app.js` and shared `styles.css` were not rewritten.

## 3. Modified existing files

- `frontend/index.html`: entry link and coordinated inline review assets.
- `src/api/app.py`: additive workspace routes and coordinated automation/review
  integration; detection and segmentation implementation files remain intact.
- `.gitignore`: excludes generated local annotation data and QA artifacts.

## 4. Added management files

- `frontend/annotations.html`, `frontend/annotations.css`,
  `frontend/annotations.js`: standalone management workspace.
- `src/api/annotation_library.py`: management facade over canonical persistence.
- `frontend/annotations-training.js` and `.css`: coordinated canonical class and
  training-export controls.
- `tests/test_annotation_library.py`, `tests/test_annotation_library_datasets.py`,
  and `tests/test_annotation_library_ui.py`: API, dataset separation, and
  executable JavaScript coverage.
- `tests/annotation_library_fixture_server.py`,
  `tests/annotation_library_browser_smoke.py`, and
  `tests/annotation_library_dataset_browser.py`: isolated editable fixture and
  optional real-browser acceptance, including read-only primary/secondary checks.
- `docs/annotation_library.md` and this report.

The parallel automation/review work adds the shared store, exact-mask helpers,
inline review, and learning modules documented in their respective reports.
These are reused rather than independently recreated by the library.

## 5. Preserved features and data

Existing live inspection, camera processing, model choices, detector/segmenter
implementations, grading, and history/export paths remain available. Source
dataset annotations are immutable. A SHA-256 comparison of all 915 original V2
source files found no changes. Repeating the V2 import added zero records, skipped
all 910 existing records, and reported zero errors. There are 907 V2 images with
9,723 object annotations and three source images with no object labels; their
empty annotation lists are preserved.

## 6. Saving and actual storage

Default root:
`Thesis/sardinella-lemuru-ml/dataset/annotation_workspace/`.

The authoritative database is `annotations.sqlite3`; canonical images, original
files, PNG masks, baseline snapshots, and immutable revision JSON files are
stored beneath that same root. `FISH_ANNOTATION_ROOT` overrides it consistently
for all annotation adapters. New uploads are deduplicated; saves reuse immutable
image and mask artifacts. Version checks reject stale editors. Transactional
failures leave the prior database revision available.

Browser drafts supplement server persistence. They can be downloaded separately
as recovery drafts and are never presented as saved training exports.

## 7. JSON contract and export choices

The versioned `dataset` descriptor records export time, scope, image/object
counts, coordinate system, box format, and mask format. `images` contains image
IDs, filenames, dimensions, saved revisions, statuses, review states, timestamps,
class definitions, source metadata, and annotations. Each annotation contains
its annotation/object ID, fish association, canonical class ID/name, xywh pixel
box, real COCO polygon/RLE segmentation, confidence when known, source, statuses,
timestamps, and preserved pipeline/source fields. Original source category IDs
and names remain available alongside the canonical class registry.

Scopes are current image, selected images, all saved annotations in the chosen
dataset, and approved images in the chosen dataset. Choose All saved datasets
explicitly to export across collections. Package export includes JSON, canonical
images, original image files, and available exact PNG masks. JSON is validated
before download. Failed exports report an error; missing package files are not
silently omitted. Canonical training exports remain a separate explicit action.

## 8. QA evidence

The pre-change model-free baseline passed 2,487 tests with 12 expected skips.
The coordinated broad regression run passed 2,664 tests, with 12 skips and 127
passing subtests. The final full run passed 2,752 tests in 99.73 seconds,
with 12 skips and 127 passing subtests; one unrelated plotting test was blocked
when Windows Application Control refused Matplotlib's `_image` DLL. That full
run is not reported as entirely passing. Its log and JUnit report are
`results/qa/annotation_workflow/final_boundary_capture_regression.log` and `.xml`.
Library API and executable JavaScript coverage passed 71 focused tests in 11.07 seconds,
with one existing Starlette/httpx deprecation warning. The final commands and
browser results are recorded below. A subsequent seven-case discovery check also
passed, including rejection of explicit `dataset_id: null` rather than falling
back to a different source dataset.

The latest real Chrome fixture run passed all 12 checks with zero JavaScript
errors. It includes long class names at a 390-pixel mobile viewport, actual
pointer mask selection/drawing, server-backed save/reload, failed-save retry,
review states, real downloads, and canonical class/training controls. A previous
read-only check also opened the actual V2 library and verified that its inspected
document remained identical.

The final primary-dataset Chrome run passed all six checks with zero JavaScript
errors or mutation attempts. It verified primary 345/4,867, secondary 910/9,723,
and All 1,255/14,590; completed/search/pagination; the original photograph; and
all ten RLE overlays on the inspected 3,840 by 2,160 image against independent
pixel hashes. Current, selected, and all-primary JSON downloads were read back.
The full primary download contained all 345 images, 4,867 real segmentations,
and the original source categories (160,868,421 bytes as formatted JSON).
Approved-only correctly reported a visible 422 with no download because no
primary images have yet been approved in this workspace. Browsing and exporting
left the inspected native document, every saved revision, and API document
exactly unchanged. Evidence: `results/qa/annotation_library/primary-dataset-browser.json`.

Visual follow-up fixed overlapping whole-fish/part labels without changing mask
coordinates. Chrome verified four non-overlapping label backings at fit and zoom,
selection and label toggles, with no JavaScript errors. The 12 executable
JavaScript checks also passed again after that rendering change.

The focused commands use the installed Python interpreter (the machine's plain
`python` command points to a Windows Store shim):

```powershell
& 'C:/Users/User/AppData/Local/Python/bin/python.exe' -B -m pytest -q tests/test_annotation_library.py tests/test_annotation_library_ui.py tests/test_annotation_library_datasets.py --basetemp ../tmp/annotation-library-qa
node --check frontend/annotations.js
node --check frontend/annotations-training.js
```

For optional browser acceptance, use the local Playwright test installation,
start `tests/annotation_library_fixture_server.py`, and run
`tests/annotation_library_browser_smoke.py --include-actual-library`. The fixture
server uses only its isolated temporary workspace on port 8766.
For a separate read-only primary/secondary check, run
`tests/annotation_library_dataset_browser.py --run` against the normal app on
port 8001 after source indexing is complete.

API coverage includes search/filter/pagination, class/mask edits, independent
fish, persisted restart/history, failed-save rollback, stale-version conflicts,
review invalidation, atomic bulk approval, JSON scopes and mask readback,
original metadata preservation, missing/corrupt artifacts, and ZIP contents.
Executable JavaScript checks cover asynchronous save ordering, draft retention,
history races, precise RLE selection, captured redraw targets, vertex recovery,
Undo/Redo, selected-object approval, untouched peers, and the shared panel bridge.

Real-browser acceptance uses only disposable synthetic data for edits, simulated
save failures, and approvals. The actual persistent application is checked
read-only. Browser evidence and screenshots live in the ignored
`results/qa/annotation_library/` directory. The runner intentionally refuses to
perform fixture mutations on a different origin.

The real V2 all-saved JSON export was read back successfully: 907 image records,
9,723 annotations, and 9,723 nonempty real segmentations; 24,525,888 JSON bytes in
4.768 seconds on this machine. Dashboard and one 24-image page took about
0.61/0.65 seconds in the same API check. These are observations on this dataset,
not throughput guarantees.

## 9. Limits

- Imported anatomical parts without source fish IDs remain Unassigned until a
  reviewer creates/selects the appropriate whole-fish annotation.
- The secondary V2 source contains many rectangular masks. The UI preserves
  their actual geometry; it does not assert their boundary accuracy.
- RLE masks preserve holes/islands. Replacing one with a drawn polygon is an
  explicit complete-mask replacement; previous versions remain available.
- Browser-local recovery depends on browser storage and received edit events.
  A stale draft is retained for download rather than applied over a newer save.
- Gallery image loading is paginated. Dataset summary/list operations still
  inspect stored metadata; very large collections beyond those measured here
  need separate scale testing. JSON is fully validated before download, so very
  large exports require corresponding server memory.
- The older application on port 8000 belongs to a different repository and
  remains intact. Its entire external image library is not silently merged into
  this workspace.
- Browser checks establish UI and data-integrity behavior, not scientific model
  accuracy or improved future prediction quality.
- The final broad test run encountered a Windows Application Control block on
  an unrelated Matplotlib DLL; no operating-system policy was changed.
