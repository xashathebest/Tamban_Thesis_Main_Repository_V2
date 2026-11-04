# Colored Fish Masks evidence overlays

In **Analyze Media**, complete an analysis, select **Fish Masks**, then enable
**Show Measurements** or **Show Cracks** independently. Opacity, Fish ID,
zoom, boxes, assigned parts, and anatomical association annotations remain
available. These display controls reuse the recorded analysis.

Click a shaded fish or its visible bounding box to open that fish's zoom view.
The zoom view inherits the active mask, boxes, assigned parts, measurements,
cracks, and opacity settings. Its fish choices reuse the same cached image and
native coordinates, including recorded video snapshots. Scroll or use the zoom
buttons to zoom further, drag to pan, and press Escape to return to Analyze
Media. Clicking a crack candidate opens its evidence details.

A notice beside the checkboxes reports how many lines or candidates are shown,
or explains why the selected fish has no drawable evidence. A checked box can
correctly show an unavailable message when ownership, Body support, or native
coordinates were not recorded. Older results without measurement endpoints need
one new analysis after restarting a backend that was running before this feature
was installed. Checkbox changes never trigger that analysis.

The length overlay follows the computed silhouette centerline. Maximum Body
width and representative Body section overlays use actual transverse sections.
The representative scalar is the median of central Body sections; its overlay
shows the observed section nearest that median, labelled with its own width.
The width ratio is maximum Body width divided by fish length. Coordinates are
original-image pixels, including when the preview image is reduced or zoomed.

Expand a fish under the controls to inspect **Geometry** and **Structural
Damage**. Dashed measurement lines are **Estimated**. **Validated** requires
recorded measurement and ownership review. **Unavailable** explains missing
endpoints, source mismatches, failed ownership checks, or unreliable Body
association. A usable fish centerline can appear without Body width lines when
only Body evidence is unavailable. Numeric diagnostics can remain visible as
estimates even when unreliable placement prevents drawing them.

Crack candidates use outlines of retained original RGB support. Historical
results with only genuine candidate bounds display those bounds explicitly.
Click an outline or its **Inspect candidate** button for original-image location,
estimated size, severity, and validation status. Severity colors require explicit
validated severity for that candidate; a fish-wide severity does not label every
surface mark. No reliable crack evidence does **not** establish absence of cracks.
MobileSAM candidates without reviewed Body support may correctly have no crack
coordinates to draw. The zoom modal uses the same evidence and coordinate checks.

Neither model weights nor grading rules change. Old saved analyses without
measurement endpoints show an explanation and are never filled with invented
geometry or silently reanalyzed by an overlay toggle.

Validation includes backend geometry/contour checks, UI source and ownership
checks, and a model-free Chrome smoke test using synthetic display fixtures.
Fixtures verify software behavior; they do not validate fish measurements or
crack accuracy.
