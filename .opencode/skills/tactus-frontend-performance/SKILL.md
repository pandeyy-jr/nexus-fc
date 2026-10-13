---
name: tactus-frontend-performance
description: Rendering cost, bundle size, animation frame budgets, and image discipline for TACTUSBALL in frontend/. Use when animations jank, the bundle grows, lists render slowly, images shift layout, or choosing which property or driver to animate.
---

# TACTUSBALL Frontend Performance

## Purpose and triggering conditions
Keep every frame inside budget and every route lean. Trigger on jank reports, bundle growth, new dependencies, image/media work, or property/driver choices in `frontend/`.

## Required source files to inspect
- `frontend/src/style.css` (which properties animate; `transition: all`, layout props, blur radii).
- `frontend/src/main.tsx` (per-frame React state? listeners/observers/frames cleaned? large lists?).
- `frontend/package.json` + build output chunk sizes (28 modules today; JS ~279KB, CSS ~53KB — treat growth as a finding).
- `frontend/index.html` (preload discipline: hero image only).

## Decision procedure
1. Name the cause before changing code (property tier, busy main thread, per-frame re-render, inherited-variable recalc, oversized blur, missing cleanup).
2. Property tiers: composite-only (`transform`, `opacity`) default; paint-tier (`box-shadow`, `color`) needs a reason; layout-tier (`width/height/margin/top/left`) must become `transform`/`opacity` (`scale()` for growth, `translate()` for movement).
3. Driver: CSS/WAAPI for predetermined or busy-main-thread motion; JS rAF only with ref writes (never `setState` per frame); `will-change` only after observed shift/jank, on the animating element only.
4. Images: lazy below fold with explicit dimensions; hero preloaded once; prefer existing local JPGs over new assets.
5. Dependencies: no new runtime dependency without measured justification; tree-shake; report chunk deltas.

## Preferred and prohibited patterns
- Preferred: exact-property transitions; `filter: drop-shadow()` over animated `box-shadow`; blur ≤20px (2–5px to soften); passive listeners; cleanup in effect returns.
- Prohibited: `transition: all`; per-frame `setState`; animated inherited CSS variables driving child transforms; `will-change: *`; unmeasured dependency adds.

## Accessibility and performance constraints
Performance work must not break reduced-motion fallbacks or keyboard behavior. Mid-range phone is the bar, not the dev laptop; 120Hz halves the frame budget.

## Implementation and verification steps
1. Diagnose from code (property/driver/cleanup), fix the cause, not the symptom.
2. `npx tsc -b` + `npm run build`; record chunk sizes before/after.
3. Confirm with DevTools Performance + Animations panels on a real device where feel matters; state what was code-verified vs device-verified.

## Reference links
- Emil animation-performance: https://github.com/emilkowalski/skills/tree/main/skills/animation-performance (MIT)
- Lenis README (perf model reference): https://github.com/darkroomengineering/lenis (MIT)
- frontend-ai-skills `17-frontend-performance`, `51-animation-performance`: https://github.com/JustineBijuPaul/frontend-ai-skills (MIT)

## Exit criteria
Named cause fixed; no new unjustified bytes; cleanup verified; build green with recorded sizes.
