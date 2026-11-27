# Annotation library

The annotation workspace opens at `/annotations` from **Annotation Library** in
the inspection navigation. It uses the same annotation store as automation and
the inline human review queue. The live grading database and inference pipeline
retain their existing behavior.

## Working with annotations

The workspace has Dashboard, Annotate, Completed Annotations, Dataset, and Export
views. The dataset selector defaults to the designated primary dataset. Choose
another dataset or All saved datasets to reopen secondary collections. The
cleaned archive is the primary reference; the V2 COCO source remains separately
accessible. Selecting a dataset also scopes dashboard counts and archival
all/approved exports. Selected images never silently pull in a different dataset.

Use **Discover existing annotations** in Dataset to index or resume the selected
registered source. With All saved datasets selected, discovery uses the primary
source. It does not import a different collection or accept arbitrary file paths.
Importing is idempotent and does not rewrite source images or annotation files. Existing
annotations can be reopened without running inference. Uploading an image stores
its original; AI annotation is an explicit action using the existing automation.

Imported anatomical parts do not have a known fish association unless the
original data records one. Assign those parts to a fish explicitly in the editor.
An absent mask is not replaced with a bounding-box polygon. Review the actual
source masks: the secondary V2 dataset contains many rectangular masks, so
their presence does not establish accurate anatomical boundaries.

## Persistence

The canonical annotation workspace defaults to
`dataset/annotation_workspace/` beneath the application project. Configure
`FISH_ANNOTATION_ROOT` to change this location. Automation, review, and the library
must use this same root. Keep this directory when moving or backing up the app.
The library facade does not create a second annotation database.

`annotations.sqlite3` is the authoritative revision index. `images/` retains
original uploads, `pixels/` retains the canonical pixels used for annotation
coordinates, `masks/` contains content-addressed PNG masks, `baselines/` retains
original annotation snapshots, `revisions/` contains immutable JSON recovery
artifacts, and `exports/` contains explicitly requested training packages. Saves
reuse existing image artifacts rather than copying the entire dataset.

Saving uses the canonical store's version checks and immutable revision history.
The UI keeps a recoverable local draft while submitting meaningful changes to
the server with a 600 ms debounce. Requests are serialized, so edits made during
a save use the confirmed next revision. **Saved** means the persistence request succeeded. A failed request
leaves the draft available for retry. A revision conflict requires reloading and
reviewing the latest stored version; a stale editor must not overwrite it.

Local browser drafts supplement server persistence. They are not backups, and
private browsing or clearing browser storage can remove them. Changes that never
reach the browser's change handlers cannot be recovered.

## JSON contract

Library JSON exports contain a `dataset` descriptor and an `images` array. Each
image includes its stable ID, original filename, pixel dimensions, status,
review status, revision, timestamps, categories, and annotations. Annotation
records retain stable annotation/object IDs, class ID and name, fish association,
confidence when available, source, review state, and source metadata.

Bounding boxes use original-image pixels in `[x, y, width, height]` order.
Segmentation uses COCO polygon rings (`[[x1, y1, x2, y2, ...], ...]`) or COCO
run-length encoding (`{"size": [height, width], "counts": [...]}`). RLE is
column-major and preserves holes and disconnected regions. Neither image zoom
nor thumbnail dimensions change saved coordinates.

The canonical class registry is authoritative for edited annotations. Source
COCO category IDs and source records must remain in exported metadata alongside
the registry mapping; do not confuse them with zero-based model class IDs.
For imported objects, the original record and category definition are retained
at `annotation.metadata.workspace_fields.original_annotation` and
`annotation.metadata.workspace_fields.source_category`. Original image fields
are at `image.metadata.source_record`.
Unknown timestamps or associations remain unknown rather than fabricated.
Application creation timestamps describe ingestion into the library; original
capture/creation metadata remains in the source records when available.

Exports read saved server records. Available scopes are the current image,
selected images, all saved annotations, and approved annotations. JSON encoding
rejects non-finite values. A dataset package includes the JSON and the
corresponding original images; failures must be reported rather than silently
omitting files. Packaging is an explicit export operation and does not copy the
dataset on each save.

Large JSON exports reuse a verified baseline snapshot and image index once per
source file. Registry classes and selected revisions come from a consistent
SQLite snapshot. A missing or corrupt required package artifact aborts the
download. Plain JSON exports include the saved segmentation itself, even when no
PNG representation is requested.

The separate collapsed training panel reuses canonical validation and
COCO/YOLO conversion. It includes original manual references and newly approved
work; unreviewed predictions are excluded. Preserve the selected dataset and
source split when exporting. A lossless COCO/PNG export supports disconnected
masks and holes; an unsupported YOLO segmentation conversion reports the problem
instead of changing the mask.

## QA

See [the completion and QA report](annotation_library_qa.md) for the implemented
components, modified files, acceptance checks, storage verification, and limits.
