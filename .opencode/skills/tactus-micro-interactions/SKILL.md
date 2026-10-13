---
name: tactus-micro-interactions
description: Buttons, cards, dialogs, form controls, focus, press, loading, and state feedback for TACTUSBALL in frontend/src. Use when adding hover or press states, modal and dialog motion, form validation feedback, toggles, or interactive state changes.
---

# TACTUSBALL Micro-Interactions

## Purpose and triggering conditions
Make every interactive element feel tactile and legible with near-imperceptible, fast feedback. Trigger on buttons, links, cards, dialogs, inputs, selects, toggles, and state-feedback work in `frontend/`.

## Required source files to inspect
- `frontend/src/main.tsx` (existing forms: login, copilot, upload, lab; modal open/close state).
- `frontend/src/style.css` (existing `:hover`, transitions, `.motion-off` and reduced-motion blocks).
- `frontend/package.json` (no animation libs — CSS transitions are the default tool).

## Decision procedure
1. Name the purpose: feedback, spatial consistency, state indication, or preventing a jarring change. Else stop.
2. Frequency check: nav/side-links (tens/day) → color/background only, no transform. Occasional (modals, lab runs, uploads) → standard 150–250ms motion.
3. Tool: CSS transitions naming exact properties. Springs/layout/exit animations → propose Motion for React only with justification (not installed).
4. Values: press `:active { transform: scale(0.97) }`, `transition: transform 160ms <strong-ease-out>`; entrances `scale(0.95–0.97)` + `opacity: 0`, `ease-out`, never `scale(0)`; modals centered (exempt from trigger-origin rule).
5. Curves/durations from tokens: add `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)`-style tokens to `:root` if missing; extend, never fork.

## Preferred and prohibited patterns
- Preferred: exact-property transitions; full keyboard operability (Escape closes modals — already implemented); visible `:focus-visible`; disabled states during `busy`; inline field errors; `aria-expanded`/`aria-pressed` where toggled.
- Prohibited: `transition: all`; `ease-in` on UI; ungated `:hover` transforms; transform on high-frequency nav; keyframes on rapidly-triggered elements (use transitions so interruptions retarget); hover-only affordances on touch.

## Accessibility and performance constraints
Gate hover motion behind `@media (hover:hover) and (pointer:fine)`; reduced-motion keeps opacity/color, drops movement; transform/opacity only (GPU); no per-frame React state.

## Implementation and verification steps
1. Implement initial/hover/focus-visible/active/disabled/error states together — never hover alone.
2. Verify keyboard path (Tab, Enter/Space, Escape) and touch (no sticky hovers).
3. `npx tsc -b` + `npm run build`; list feel-checks needing a browser (press timing, modal entrance).

## Reference links
- Emil `animate` (values, recipes): https://github.com/emilkowalski/skills/tree/main/skills/animate (MIT)
- LottieFiles motion-design state-feedback patterns: https://github.com/LottieFiles/motion-design-skill (MIT)
- frontend-ai-skills `37-micro-interactions`: https://github.com/JustineBijuPaul/frontend-ai-skills (MIT)

## Exit criteria
All interaction states shipped together; hover gated; reduced-motion covered; transform/opacity only; build green.
