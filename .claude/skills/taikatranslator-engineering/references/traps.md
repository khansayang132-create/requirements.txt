# Traps

Failure modes for this kind of pipeline, the starred ones hit while building and verifying the starter kit. Check new work against this list.

## Hit while building the kit ★

1. ★ **Exact equality on doubles.** The same region from pixels and from inches differed in the 17th digit and `assertEquals(box, box)` failed. Use `NormalizedBox.approxEquals(other, 1e-9)`.
2. ★ **URL regex swallowing the full stop.** `https?://\S+` captured `https://example.com/help.`; the placeholder then carried the sentence's period. The pattern now refuses trailing `.,;:!?)]}'"`.
3. ★ **"Never overwrite" with `ATOMIC_MOVE`.** On Linux an atomic rename replaces an existing target silently, so check-then-move races. Publish without overwrite uses a hard link, which fails if the target exists.
4. ★ **Marking a gate passed because the step didn't run.** The first draft of the reference pipeline recorded the visual gate as `passed: true, "NOT RUN"`. Not-run is a `SKIPPED` stage, never a passed gate.
5. ★ **Structure passed, page still wrong.** All structure tests passed while the rendered page showed the expanded Spanish line at 7.5 pt: fitted with a fixed-advance (character-count) measurer that overestimates proportional text. Only looking at the render showed it. Production fitting uses real font metrics; the visual gate stays separate.
6. ★ **Test arithmetic, not code, was wrong.** "Three 60,000-char texts need three batches" is false under a 120 KiB cap (two fit). When a test fails, check the expectation before "fixing" correct code.

## Providers
7. Treating Azure `pages[].unit` as pixels for PDFs (it's inches) → every box in the top-left corner.
8. Rotating by Azure `angle` (text skew) as if it were PDF `/Rotate`.
9. Emitting table text twice: Azure lists cell paragraphs in `paragraphs` too.
10. Retrying the Azure **submit** after a timeout or 5xx → duplicate billable analyses. Only the poll is idempotent.
11. Retrying DeepL **456** (quota) in a loop. It won't recover until the quota resets.
12. Sending bare `EN`/`PT` as a DeepL target, or a variant (`EN-US`) as a source.
13. `tag_handling=xml` without escaping `&`/`<` → "A & B" becomes an XML error or vanishes.
14. Restoring placeholders from the engine's output instead of the original token list. The engine may "translate" `{name}`.
15. Trusting `Retry-After` without a cap. One bad header parks the job for hours.
16. Free keys (`:fx`) against the Pro host, or the reverse: 403, looks like an auth bug.

## Layout and DOCX
17. Font size from character count alone for proportional fonts: wrong in both directions.
18. Font substitution: the measuring font isn't installed in the container, so Java substitutes one and every fit is off. Record the resolved family.
19. Shrinking below a readable floor to silence an overflow warning.
20. Twips vs half-points vs EMU vs points confusion (see the units table in `layout-and-geometry.md`).
21. Comparing DOCX files byte-for-byte. ZIP timestamps differ every run.
22. Assuming `new XWPFDocument()` has styles: `setStyle("Title")` writes the id even if the style isn't defined; Word falls back to Normal. Add a styles part (or a template DOCX) when appearance matters.
23. Writing `sectPr` before body content. It must be the last child of the body.
24. Losing line breaks: `\n` in a run's text is not a break in Word. Use `addBreak()`.

## Process and evidence
25. "The process exited 0" reported as "the translation is correct". Six gates, six results.
26. A PASS recorded from a previous commit's run.
27. Mocks that were never compared with a real response, presented as provider behaviour. Mark synthetic mocks as synthetic.
28. Live tests that silently pass when the key is missing. They must skip with a reason.
29. Baselines regenerated on a different machine/LibreOffice version, then "visual regression" fails on every glyph. Same CI image for both.
30. Customer documents in test fixtures or in logs.
31. Moving packages around "to match the target structure" before the existing code is understood and covered by tests.
32. Different Java versions in `maven.compiler.release`, CI and production. Pin and check all three (the kit's enforcer rule catches the build side).
