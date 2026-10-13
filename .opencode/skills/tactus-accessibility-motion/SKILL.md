---
name: tactus-accessibility-motion
description: Keyboard support, touch behavior, reduced-motion alternatives, focus management, and contrast for TACTUSBALL motion and interactive UI in frontend/src. Use when adding any animation or interactive control, auditing accessibility, or fixing focus, touch, or motion-sensitivity issues.
---

# TACTUSBALL Accessibility & Motion

## Purpose and triggering conditions
Every interaction works by keyboard and touch, and no one gets motion sickness from the interface. Trigger on any animation, dialog, form, nav, or motion-sensitivity work in `frontend/`.

## Required source files to inspect
- `frontend/src/main.tsx` (keyboard handlers, focus management, `autoFocus`, modal open/close, touch handlers).
- `frontend/src/style.css` (existing `@media (prefers-reduced-motion: reduce)`, `.motion-off`, `:focus-visible`, `:hover` gating).
- `frontend/index.html` (lang, title, meta).

## Decision procedure
1. Keyboard first: every mouse path needs Tab reachability, Enter/Space activation, visible `:focus-visible`, and Escape dismissal for dialogs (login + Copilot modals already implement this — extend the pattern, don't fork it).
2. Reduced motion: `prefers-reduced-motion: reduce` keeps opacity/color comprehension transitions, drops movement/position changes; the `.motion-off` footer toggle must kill the same set; `animateMotion` SVG motion hides under both.
3. Touch: gate hover-driven motion behind `@media (hover: hover) and (pointer: fine)`; no hover-only affordances; touch targets ≥44px where feasible; no sticky tap highlights.
4. Contrast and labels: `aria-label` on icon-only buttons, `aria-expanded`/`aria-pressed` on toggles, `role="status"`/`role="alert"` on async feedback, sufficient contrast on dark surfaces.
5. Motion toggle persistence (`tactus_motion` in localStorage) and session intro flag must keep working.

## Preferred and prohibited patterns
- Preferred: restrained `:focus-visible` outlines in brand tones; programmatic focus into opened dialogs; focus return on close where cheap; semantic buttons/labels/inputs.
- Prohibited: removing outlines without replacement; keyboard traps; hover-only controls; parallax that can't be disabled; autoplaying motion with no static fallback.

## Accessibility and performance constraints
Reduced-motion variants must never be heavier than the motion they replace. Focus styles must survive brand theming (test on dark + light surfaces).

## Implementation and verification steps
1. Implement keyboard, touch, focus, and reduced-motion handling together with the feature — never as a follow-up.
2. Walk the keyboard path manually where possible (Tab order, traps, Escape); state when no browser was available.
3. `npx tsc -b` + `npm run build`.

## Reference links
- frontend-ai-skills `11-accessibility`, `50-motion-accessibility`: https://github.com/JustineBijuPaul/frontend-ai-skills (MIT)
- LottieFiles motion-design context-adaptation: https://github.com/LottieFiles/motion-design-skill (MIT)
- Web Animations API, MDN (inventoried standard): https://developer.mozilla.org/en-US/docs/Web/API/Web_Animations_API

## Exit criteria
Keyboard-complete paths; gated hover; reduced-motion + toggle parity; labeled controls; announced async feedback; build green.
