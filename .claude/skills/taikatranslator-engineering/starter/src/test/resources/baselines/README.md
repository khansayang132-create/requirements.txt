# Visual baselines

`service-agreement.ES/` is the reviewed rendering of `target/e2e-evidence/service-agreement.ES.docx`
(LibreOffice 24.2.7.2, pdftoppm 24.02.0, 72 dpi, Carlito for Calibri; versions in `manifest.json`).
It was checked by eye before commit: header in the header part, merged "Honorarios" row, page-number field,
all text in Carlito.

Rules:
- Regenerate only with a reason, on the same image CI uses, and look at the new page before committing:
  `python scripts/visual_diff.py baseline target/e2e-evidence/service-agreement.ES.docx --baseline src/test/resources/baselines/service-agreement.ES`
- A baseline change is a reviewed change. Say in the commit what changed on the page and why.
- The CI job `taika-visual` compares against this folder; its diff images are uploaded as `taika-visual-diff`.
