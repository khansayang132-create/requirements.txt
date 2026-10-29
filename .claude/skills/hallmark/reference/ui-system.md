# UI system: deciding the look so it serves the task

Decide per product, from the design contract. If the project has a design system, use it and skip to *States*.

## 1. Hierarchy before style
1. List what's on the screen. Rank it by what the user needs first for the **primary action**.
2. Rank 1 gets size, weight and position. Rank 2–3 are clearly secondary. The rest is quiet or behind a click.
3. Squint test: blur the screenshot. Can you still spot the primary action and the page's purpose?

## 2. Typography
- One family (two at most: display + text). System stacks are fine and fast.
- A modular scale, e.g. 14 / 16 / 20 / 24 / 32 / 40. Body 16 px on phones, line-height 1.5, measure 45–75 characters.
- Weight and size carry hierarchy, not color alone.
- For Bahasa Indonesia and other long-word languages, test the longest real string; don't design around Lorem ipsum.

## 3. Spacing and layout
- 4- or 8-px spacing scale (4, 8, 12, 16, 24, 32, 48, 64). Use the scale only.
- Related items sit closer together than unrelated ones (proximity carries grouping).
- Mobile first: single column, 16 px gutters. Add columns when content needs them, not because the screen is wide. Cap reading width.
- Breakpoints come from the content (where it starts to look wrong), commonly ~640 / ~1024 px.

## 4. Color
Define **roles**, not paint: `--bg`, `--surface`, `--text`, `--text-muted`, `--border`, `--accent`, `--accent-text`, `--danger`, `--success`, `--focus`.
- One accent for primary actions and focus. Status colors only for status.
- Check every text/background pair with `hallmark_check.py contrast`, in both light and dark themes.
- Dark mode: redefine the roles under `@media (prefers-color-scheme: dark)`; don't just invert.

## 5. Tokens
Put type, spacing, radius, color roles, shadow and motion durations in one place (CSS custom properties, Tailwind theme, or the project's token file). Components read tokens and never hand-type values. A token file only exists if something reads it.

## 6. Components and states
For each component, specify: purpose, anatomy, variants (as few as possible), and **states**: default, hover, focus-visible, active/pressed, disabled, loading, error, selected. Plus content rules (max length, truncation, empty).

Screen-level states:
- **Loading**: skeleton or progress that matches the final layout. No spinners over 1 s without a message.
- **Empty**: say why it's empty and give the next action.
- **Error**: what happened, in plain words, plus a way out (retry, edit, contact). Keep the user's input.
- **Success**: confirm what changed and what happens next.

## 7. Interaction and motion
- Feedback within 100 ms for every press.
- Motion explains a change (where something came from or went). Duration 150–250 ms, ease-out. Under `prefers-reduced-motion: reduce`, use a fade or nothing.
- Destructive actions: an inline confirm or an undo, not a surprise modal.

## 8. Anti-patterns (remove on sight)
Gradients and glass for their own sake · low-contrast "elegant" grey text · tiny text · inconsistent spacing · several equal-weight buttons · icons with no labels · carousels hiding key content · fake buttons or placeholder links · generic hero + three cards with no reason tied to the product · motion with no meaning.

## Product-type notes
- **Dashboards / analytics**: the question each view answers goes in the title; numbers with units and time range; the `dataviz` skill for charts.
- **Forms**: one column, labels above fields, inline validation after blur, the submit button says the outcome ("Simpan jadwal").
- **Admin / internal tools**: density is fine, clarity isn't optional; tables need sticky headers, sort and an empty state.
- **E-commerce**: price, availability and total cost are never hidden; checkout is short and has no surprises.
- **Developer tools**: copyable commands, exact errors, keyboard shortcuts with a visible list.
