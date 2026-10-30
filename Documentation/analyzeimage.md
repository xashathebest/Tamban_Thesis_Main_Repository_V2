Please investigate and fix the accuracy issues in the **Analyze Image (Photo Upload)** feature of our Tamban Thesis system.

Currently, the predictions are inaccurate even when I upload images that were used during model training. I expect the model to recognize these images more reliably, so please investigate why the results are inconsistent.

**Tasks:**

1. **Recheck the trained model:** Verify that the Analyze Image feature loads the correct trained model, weights, class mappings, configurations, and preprocessing pipeline. Check whether the uploaded images are being processed the same way as during training and validation.

2. **Investigate prediction accuracy:** Identify why the model produces incorrect classifications, especially on training images. Check confidence thresholds, image resizing, normalization, detection outputs, and possible inconsistencies between training and inference.

3. **Verify feature extraction:** Based on my observations, the system does not appear to use the intended fish grading features. Review the existing documentation and implementation to identify the features that should be evaluated, including the **body, head, and tail**.

4. **Implement the intended grading logic:** Ensure the system actually extracts, evaluates, and uses the required visual features rather than relying on generic classifications or arbitrary predictions. Follow the documented grading criteria, including the intended feature weights: **Body (50%), Head (30%), and Tail (20%)**, with the specified redistribution when the tail is unavailable.

5. **Check the complete inference pipeline:** Trace the process from image upload → preprocessing → fish detection → feature extraction → grading → final prediction. Identify any missing, bypassed, or incorrectly implemented components.

6. **Validate the fixes:** Test the feature using training images, validation images, and previously unseen images. Compare the results against the actual ground-truth labels and report the accuracy and remaining errors. Do not assume that good performance on training images guarantees generalization.

**Important requirements:**
- Inspect the existing repository, trained models, and thesis documentation before making changes.
- Do not introduce hardcoded classifications or artificial confidence scores just to make predictions appear accurate.
- Ensure that the grading genuinely uses the intended features and documented methodology.
- If the trained model does not support feature-level grading, clearly identify the limitation and implement only a technically valid solution, explaining whether additional annotations or retraining are required.
- Keep the Analyze Image functionality consistent with the live camera inspection pipeline where applicable.
- Preserve existing working features and avoid unnecessary changes.

**Expected outcome:** A properly functioning Analyze Image feature that loads the correct model, processes uploaded images accurately, evaluates the intended fish grading features, and generates results supported by actual model predictions and grading logic.

After implementing the fixes, provide a summary of the root causes, code changes, verification results, and any remaining limitations.