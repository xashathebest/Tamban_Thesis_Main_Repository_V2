# Responsive and keyboard review

The current stopped-camera view was captured at 375, 390, 768, 1280, 1366, and 1920 CSS pixels by `tests/navigation_qa_smoke.py`. The `13_navigation_*.png` files in this directory show those simulated views. Earlier screenshots in `qa/final/` predate the single-Start adjustment, but there are no earlier 375- or 768-pixel screenshots for a matching before/after comparison.

- Headless Chrome exercised keyboard activation of Live, History, Review, Model and Expert, Settings and Export, and Escape closing the dialogs at all six widths.
- The test checked one visible Settings and Export entry at each width and no document-level horizontal overflow.
- Simulated stopped, starting, running, stopping and errored states each show one Start action; disabled states and Stop behavior were also checked.
- Existing focus-visible and reduced-motion styles, semantic labels, modal inert background and text verdict cues were reviewed in `qa/final/16_responsive.md`.
- Actual screen-reader use, contrast measurement, full tab and focus-trap audits, browser zoom, live-video overlay alignment, real hardware and first-time operator testing remain unverified. These checks do not establish accessibility conformance.
