Improve the existing **Analyze Media → Colored Fish Masks** viewer by adding visual overlays for fish geometry measurements and structural crack evidence.

The latest CSV confirms the system has experimental fish-length and width-ratio calculations, but most measurements are unreliable, and no cracks have been validated.

**Implement the following directly in the existing UI:**

1. **Length & Width Overlay:** When enabled, draw a line along each selected fish's actual longitudinal axis to visualize estimated length. Draw perpendicular lines showing maximum Body width and representative Body width wherever those measurements are available. Display pixel measurements and width-to-length ratios beside the fish.

2. **Crack Detection Overlay:** Highlight actual detected crack candidates on the corresponding fish using thin, visible outlines. Differentiate minor, moderate, and major cracks only when severity evidence exists. Clicking a candidate should show its location, estimated size, severity, and validation status.

3. **Add overlay controls:** Preserve the existing Bounding Boxes / Fish Masks toggle, opacity slider, Fish ID highlighting, zoom, and anatomical annotations. Add independent **Show Measurements** and **Show Cracks** checkboxes so I can enable or disable each visualization.

4. **Display evidence per fish:** Add compact Geometry and Structural Damage sections showing measured length, Body width, width ratio, abnormal-width status, crack evidence, and whether any feature contributed to grading.

5. **Handle unavailable evidence correctly:** Clearly distinguish **Estimated**, **Validated**, and **Unavailable** measurements. Never draw fabricated measurement lines, invent crack locations, or interpret "No reliable crack evidence" as "No cracks." Explain why evidence is unavailable, particularly when MobileSAM ownership or Body association is unreliable.

6. **Correct coordinate alignment:** Render measurements and crack locations in original-image coordinates and keep them accurate during scaling, zooming, and Fish ID selection. If the backend does not return the necessary measurement endpoints or crack coordinates, expose the real computed geometry rather than inventing display positions.

7. **Preserve existing functionality:** Do not retrain or modify Model 1 V2 or Model 2, remove existing controls, or change grading rules. Reuse completed analysis results without rerunning models when overlays are toggled.

**Final objective:** Make it possible to visually inspect each fish's estimated length, maximum Body width, width ratio, and genuine crack evidence directly on its shaded MobileSAM mask, with clear reliability indicators and no misleading annotations.