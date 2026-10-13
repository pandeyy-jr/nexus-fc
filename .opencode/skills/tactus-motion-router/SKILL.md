---
name: tactus-motion-router
description: Route TACTUSBALL frontend motion requests to the smallest correct skill and technique. Use when asked to animate anything, add motion, fix jank, review animation code, audit UI motion, or choose between CSS, WAAPI, Motion, GSAP, Lenis, Three.js, or Lottie in this repository.
---

# TACTUSBALL Motion Router

## Purpose and triggering conditions
Decide **whether** something should animate and **which technique** to use, before any code is written. Trigger on any request containing animate, motion, transition, scroll effect, parallax, 3D, smooth scroll, Lottie, or "feel alive" in `frontend/`.

## Required source files to inspect
- `frontend/src/main.tsx`, `frontend/src/style.css` (the entire UI surface).
- `frontend/package.json` (installed packages — React + Vite only as of 2026-10).
- `.opencode/skills/RESEARCH.md` (source index, licenses, version notes).

## Decision procedure
1. **Gate first.** Frequency tier: 100+/day or keyboard-initiated → no animation, stop. Tens/day → near-imperceptible only. Occasional → standard. Rare/first-time → delight budget. No named purpose (feedback, spatial consistency, state indication, preventing a jarring change, explanation, delight)? Stop.
2. **Route by need** (cheapest fitting technique wins):
   - Hover/press/color/class toggle → `tactus-micro-interactions` (CSS transitions).
   - Mount entry, no JS state → CSS `@starting-style`.
   - Predetermined motion under load → CSS keyframes.
   - Programmatic CSS-performance control → WAAPI (`element.animate()`).
   - Scroll progress mapping, reveals → `tactus-cinematic-scroll` (rAF + IntersectionObserver; already the app pattern).
   - Springs, layout animation, exit animation, gestures → propose Motion for React (`tactus-micro-interactions`), install only with justification.
   - Pinned multi-scene timelines → propose GSAP + ScrollTrigger (not installed; needs justification).
   - Smooth scrolling feel → **reject Lenis** (anchor links, modals, native scroll suffice; see research index).
   - True 3D scenes → `tactus-3d-experiences` (default: reject; Three.js/R3F unjustified today).
   - Vector character animation with a licensed asset → Lottie (no asset today; reject otherwise).
   - Jank/dropped frames → `tactus-frontend-performance`.
   - Review of a diff → `tactus-quality-review` (applies the ten standards).
   - Whole-codebase audit → plan-only output, then implement per plan.
3. **Cross-check constraints** via `tactus-accessibility-motion` (reduced motion + hover gating ship with the work) and `tactus-frontend-design` (tokens, personality).

## Preferred and prohibited patterns
- Preferred: one skill per task; smallest technique; extend `--ease-*`/duration tokens; `transform`/`opacity` only.
- Prohibited: installing competing libraries for one job; `transition: all`; `scale(0)`; `ease-in` on UI; layout-property animation; per-frame React state; motion without reduced-motion handling.

## Accessibility and performance constraints
Every routed task inherits: `prefers-reduced-motion` gentler variant, `@media (hover:hover) and (pointer:fine)` gating for hover motion, no layout thrash, cleanup of listeners/observers/frames.

## Implementation and verification steps
1. State the gate result (tier + purpose) in one line.
2. Name the routed skill + technique + values (curve, duration, properties).
3. Implement; run `npx tsc -b` and `npm run build` in `frontend/`.
4. Feel-check anything judged from code alone (slow motion, DevTools animation inspector, real device for gestures); say what remains manual.

## Reference links
- Emil `animate`: https://github.com/emilkowalski/skills/tree/main/skills/animate (MIT)
- Emil `find-animation-opportunities`: https://github.com/emilkowalski/skills/tree/main/skills/find-animation-opportunities (MIT)
- LottieFiles motion-design: https://github.com/LottieFiles/motion-design-skill (MIT)
- frontend-ai-skills `70-frontend-skill-router`: https://github.com/JustineBijuPaul/frontend-ai-skills (MIT)

## Exit criteria
Routing stated up front; no redundant installs; constraints attached; build green; manual feel-checks listed, never claimed.
