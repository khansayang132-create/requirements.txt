# Accessibility (WCAG 2.2 AA target)

The legend says who can check each item: **[T]** `hallmark_check.py check`, **[R]** `hallmark_check.py render`, **[H]** a human only. Report every [H] item you didn't check as NOT RUN.

## Structure
- [T] `<html lang>` set; a meaningful `<title>` (1.3.1, 2.4.2, 3.1.1)
- [T] One `<main>`; `<nav>`, `<header>`, `<footer>` where they exist
- [T] Headings start at `h1` and don't skip levels. [H] Do they describe the sections?
- [H] Reading order in the DOM matches visual order (no CSS `order` tricks that reorder meaning)
- [T] No duplicate `id`s (they break `label for` and `aria-labelledby`)

## Names, labels, images
- [T] Every `button` and link has an accessible name (text, `aria-label`, or a child `img alt`)
- [T] Every input/select/textarea has a `<label>` (a placeholder is not a label)
- [T] Every `img` has `alt`; `alt=""` only when decorative. [H] Is the alt text right for the context?
- [H] Icon-only buttons have a name that says the action ("Hapus video", not "trash")
- [H] Error messages are text, tied to the field (`aria-describedby`), and say how to fix it (3.3.1, 3.3.3)

## Keyboard and focus
- [T] No `div`/`span onclick` without `role` + `tabindex`; use `<button>`
- [T][R] Focus is never hidden: no `outline:none` without a `:focus-visible` replacement; a visible ring on each control (2.4.7, 2.4.11)
- [T] No positive `tabindex`
- [T] Nothing focusable sits inside `aria-hidden="true"`
- [H] Whole journey works by keyboard; drawers/dialogs trap focus, close on Esc, return focus to the opener
- [H] Focused element is not covered by sticky headers or cookie bars (2.4.11)

## Visual
- [T] Text contrast ≥ 4.5:1 (≥ 3:1 for ≥ 24 px, or ≥ 18.66 px bold). The checker reads CSS `color`/`background` pairs and `var(--token)`s with their **first** value; check dark-mode values with `contrast`.
- [H] Non-text contrast ≥ 3:1: input borders, focus rings, icons that carry meaning (1.4.11)
- [H] Color is never the only signal (add an icon or a word) (1.4.1)
- [T] Zoom not blocked; [R] no sideways scroll at 390 px; [H] works at 200% zoom and at 320 px width (1.4.4, 1.4.10)
- [H] Text spacing override doesn't clip text (1.4.12)
- [T] No text under 12 px; body 16 px

## Motion and time
- [T] Animations/transitions have a `prefers-reduced-motion` rule
- [H] Nothing flashes more than 3 times a second; auto-moving content can be paused (2.2.2, 2.3.1)
- [H] Timeouts warn and can be extended

## Touch and input (2.2 additions)
- [H] Targets ≥ 24×24 px (2.5.8); aim for 44×44 on phones
- [H] Drag actions have a single-pointer alternative (2.5.7)
- [H] Don't ask for the same info twice in a flow (3.3.7); login has no cognitive test (3.3.8)

## ARIA
Native HTML first. Use ARIA only when no element does the job, and then follow the APG pattern completely (roles, states, keyboard). Bad ARIA is worse than none.

## What tools can't tell you
Whether a screen reader announces things sensibly, whether the language is plain, whether the flow makes sense to someone with a cognitive disability. Say so in the report; don't imply full conformance from automated passes.
