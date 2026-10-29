# Design contract: <product / screen>

Mark every line **[confirmed]** (said by the user, or found in code or data) or **[assumed]**.

## Purpose
<One sentence: what this helps a person get done.>

## Users
- Primary: <who, context, device, language>
- Secondary: <optional>
- Accessibility needs known or likely: <e.g. low vision, one-handed phone use, screen reader>

## Core journeys
1. <user goal> → <steps> → <done when…>

## Primary action (per screen)
| Screen | Primary action | Secondary actions |
|---|---|---|

## Requirements
- Functional: <what it must do>
- Non-functional: <performance budget, offline, languages, browsers, privacy>
- Accessibility: WCAG 2.2 AA unless stated otherwise
- Technical constraints: <framework, existing design system, hosting>

## States to design
Loading · empty · error · success · disabled · long content · no network

## Acceptance criteria (each one checkable)
- [ ] `hallmark_check.py check` → 0 errors
- [ ] `hallmark_check.py render` → no sideways scroll at 390 px, no console errors, focus visible
- [ ] <journey 1 completes by keyboard only>
- [ ] <task-specific criterion>

## Open questions / assumptions to validate with real users
- <assumption> → <how to test it>
