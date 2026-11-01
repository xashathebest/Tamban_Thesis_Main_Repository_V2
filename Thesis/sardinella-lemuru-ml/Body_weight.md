Enhance the existing Tamban Fish Inspection System by adding a **Relative Body Width Analysis and Class C Supporting Score**, reusing the image measurements that the system already calculates.

**Important: Do not rebuild the current image measurement system or retrain either model.** The application already extracts Model 1 whole-fish bounding-box dimensions and Model 2 Body, Head, and Tail dimensions, along with existing color and brightness diagnostics. Reuse the underlying measurement data.

### 1. Derive relative body width

For every detected fish with reliable Model 1 and Model 2 Body evidence:

- Retrieve the existing whole-fish bounding-box width and height.
- Retrieve the associated Body bounding-box width and height.
- Preserve the original pixel dimensions.
- For approximately horizontal or vertical fish, calculate an initial body-width proxy:

Relative Width Proxy = min(Body Width, Body Height) / max(Whole Fish Width, Whole Fish Height)

- Recognize that this is only a bounding-box proxy, not a true anatomical width measurement.
- Use head/tail orientation evidence and reliable geometric information where available to improve the estimate.
- Do not assume this formula is reliable for diagonal, overlapping, clipped, or badly associated fish.
- If Body evidence is unavailable or unreliable, return "Unavailable" instead of guessing.

### 2. Introduce Class C supporting points

Create a configurable 0–10 point system where abnormally high relative body width can provide additional evidence for Class C.

Use validated, labeled individual-fish measurements to establish the expected normal range and the threshold at which widening becomes abnormal.

Once calibrated:
- Normal relative width: 0 points.
- Slight abnormality: 1–3 points.
- Moderate abnormality: 4–6 points.
- Significant abnormality: 7–9 points.
- Extreme abnormality: 10 points.

Use continuous scoring based on the validated thresholds rather than assigning arbitrary cutoffs.

Until those thresholds are validated, calculate and display the width proxy, but mark the score as "Not calibrated" and do not apply points to the final grade.

### 3. Integrate with the existing grading framework

Maintain the existing weights:

- Body: 50%
- Head: 30%
- Tail: 20%

Width-based points should be supplementary Class C evidence within the Body component, not an additional grading component.

Prevent double-counting, normalize class scores correctly, and cap any influence so width alone cannot automatically classify a fish as Class C.

Provide a feature toggle for enabling or disabling the scoring contribution. Keep the influence disabled until validated against labeled samples.

### 4. Improve the existing fish measurement cards

Do not create another separate lengthy interface.

Inside each existing expandable fish card, add a compact "Body Width Analysis" subsection showing:

- Whole-fish bounding-box dimensions
- Body bounding-box dimensions
- Relative width proxy
- Measurement reliability
- Normal reference range, once calibrated
- Width abnormality classification
- Class C supporting points
- Whether the score contributed to the final grade

Continue to show the existing color, brightness, saturation, and other image diagnostics without duplicating their calculations.

### 5. Validate and export

- Test the derived measurements against manually reviewed individual fish.
- Verify the correct Model 1–Model 2 associations.
- Check horizontal, vertical, diagonal, overlapping, and clipped fish.
- Compare Class C precision, recall, and false-positive rates with and without width-based scoring.
- Preserve the existing results when width evidence is missing.
- Include the width analysis, scoring contribution, threshold configuration, and reliability status in PDF and CSV exports.

Inspect the existing repository and reuse its current measurement utilities, grading services, and user-interface components. Make the smallest reliable changes necessary without disrupting the detection, tracking, or existing Body/Head/Tail grading system.