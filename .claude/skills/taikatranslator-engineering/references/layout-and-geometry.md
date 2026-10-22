# Layout and geometry

## The canonical coordinate system

| Property | Value |
|---|---|
| Type | `NormalizedBox(x, y, width, height)` |
| Range | every value in [0, 1] of the **displayed** page |
| Origin | top-left; x right, y down |
| Rotation | already applied (the page as a reader sees it) |
| Conversion | only at boundaries: provider → normalized (`CoordinateNormalizer`), normalized → points/twips/EMU (`NormalizedBox.toPoints`, `DocxAssembler`) |
| Comparison | always with a tolerance (`approxEquals(other, 1e-9)`), never `equals` |

If the existing code uses pixels or points internally, **don't change the field meaning**. Add an adapter at the boundary and test that both paths give the same box.

## Units cheat sheet

| Unit | Per inch | Where |
|---|---|---|
| PDF point | 72 | PDFBox, PDF page sizes (Letter 612 × 792, A4 595.28 × 841.89) |
| Azure page unit | 1 (inch) or pixels | `pages[].unit` |
| Pixel | DPI-dependent (assume 96 only when the image has no DPI, and say so) | images, renders |
| Twip | 1440 | DOCX page size and margins (`w:pgSz`, `w:pgMar`): Letter 12240 × 15840, A4 11906 × 16838 |
| Half-point | 144 | raw `w:sz` font size in DOCX XML (POI `setFontSize` takes points) |
| EMU | 914,400 | DOCX drawing/image extents (`wp:extent cx/cy`) |

## Rotation

PDF `/Rotate` is clockwise degrees the viewer applies (0, 90, 180, 270). For a box in unrotated normalized space:

| Rotate | x' | y' | w' | h' |
|---|---|---|---|---|
| 90 | 1 − (y + h) | x | h | w |
| 180 | 1 − (x + w) | 1 − (y + h) | w | h |
| 270 | y | 1 − (x + w) | h | w |

Four 90° turns return the original box (there's a test). Azure's `angle` is text skew, not `/Rotate`. Get `/Rotate` from PDFBox (`PDPage.getRotation()`), and check whether the provider already returned coordinates in displayed orientation before applying it twice. Test with a rotated fixture page.

## Invalid geometry

| Case | Result |
|---|---|
| No polygon | `MISSING_COORDINATES` |
| Odd count or < 2 points | `MALFORMED_POLYGON` |
| NaN / ∞ | `NON_FINITE_VALUE` |
| Zero width or height | `ZERO_AREA` |
| Overflow ≤ tolerance (default 1% of the page) | clamped + recovery note in the report |
| Overflow > tolerance or negative | `OUT_OF_PAGE` |
| "Normalized" values > 1.5 | `UNIT_MISMATCH` (probably pixels) |
| Missing/zero/NaN page size, rotation not a multiple of 90, unknown unit | `MISSING_PAGE_METADATA` / `INVALID_PAGE_METADATA` |

What the pipeline does with an error is a policy decision for the ticket: fail the document, or drop the block with a warning. Either way it is visible in the report. It never quietly places the block at (0,0).

## Text fitting

`TextFitter` searches sizes from `maxSize` down to `minSize` in `step` increments and returns the first size where the greedy word-wrapped text fits the box width **and** `lines × size × lineSpacing ≤ height`.

Guarantees, each covered by a test: finite positive size inside [min, max]; no character dropped (long words hard-break by code point, so emoji and surrogate pairs stay whole); explicit `\n` kept; overflow flagged with a warning at `minSize`; same input, same output.

### Measuring
- **Production:** `AwtTextMeasurer` with the **same font family the DOCX declares**. If the font isn't installed, Java substitutes one and the fit is wrong: record `resolvedFamily()` in the report and install the fonts in the container.
- **Tests:** `FixedAdvanceMeasurer`, deterministic on every machine.
- **Fallback:** a character-count ratio is the same as `FixedAdvanceMeasurer`. Fine for estimates, wrong for decisions about proportional fonts. Seen in the starter kit's own render: the 0.5 em measurer overestimates width for a proportional font, so the fitted line came out smaller than needed.

### Sensible limits
| Block | max | min |
|---|---|---|
| Title | source size (≈ 20) | 12 |
| Heading | source size (≈ 14) | 10 |
| Body | source size (≈ 11) | 8 for reading, 7 hard floor |
| Table cell | source size (≈ 10) | 6 |

Below the floor, keep the size and let the text flow (in flow layout) or record overflow (in fixed layout). Never go below the floor to make the warning disappear.

### Expansion
Spanish, French, German and Portuguese commonly run 15–35% longer than English, and short strings (labels, table headers) can double. Plan per block type:
1. Shrink within limits (above).
2. Allow the box to grow downward when the layout is flow-based (DOCX paragraphs usually are).
3. For fixed-position layouts (text boxes, absolutely positioned frames), widen into free space on the right if the neighbouring region is empty.
4. Otherwise: overflow warning in the report, visual check flags it.

## Fonts

Declare the font on every run. Without a declaration each renderer picks its own default, so the size the fitter chose was measured for a different font than the one drawn, and visual baselines differ between machines. The kit declares **Calibri** (what Word users have) and measures with **Carlito**, an open font with identical metrics that installs on Linux servers (`fonts-crosextra-carlito`). Same pairing for Cambria ↔ Caladea; Arial ↔ Liberation Sans; Times New Roman ↔ Liberation Serif. Record the measuring font that actually resolved in the report (`measurerFont`).

## Tables

- Horizontal merges: `w:gridSpan` on the anchor, covered cells removed from the row. Vertical merges: `w:vMerge restart` then `continue` in the cells below. A block merge uses both.
- Give rows an at-least height from the source geometry. A row made only of merge continuations has no content of its own, and LibreOffice collapsed it to zero height in the kit's render while every structure test passed.
- Merged-away cells hold "" in the canonical grid and are never sent for translation.

## Headers, footers, page numbers

Provider roles `pageHeader`/`pageFooter` go into the DOCX header/footer parts once (they repeat on every page of the source), not into the body. `pageNumber` becomes a `PAGE` field; copying page 1's "1" prints "1" on every page.

## Flow versus fixed layout in DOCX

- **Flow** (paragraphs and tables in reading order): robust, editable, reflows with expansion. Positions are approximate. The starter kit uses this.
- **Fixed** (text boxes/frames at exact coordinates): visually faithful, but fragile to expansion and hard to edit.

A good default: flow for body text and tables, fixed only for elements whose position carries meaning (stamps, signatures, logos, form fields). Whatever you choose, write it in `docs/architecture.md`, because it decides what the visual gate can expect.
