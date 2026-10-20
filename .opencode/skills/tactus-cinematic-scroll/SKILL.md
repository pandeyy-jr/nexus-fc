---
name: tactus-cinematic-scroll
description: Scroll-driven storytelling, scroll-progress mapping, reveals, and pinned sequences for TACTUSBALL marketing pages in frontend/src. Use when building scroll-linked motion, fixing scroll progress math, adding reveals, or evaluating ScrollTrigger, Lenis, or video-scrubbing.
---

# TACTUSBALL Cinematic Scroll

## Purpose and triggering conditions
Scroll progress drives scenes on marketing pages (hero ball flight, section reveals); dashboard scroll stays native and instant. Trigger on scroll-linked work in `frontend/`.

## Required source files to inspect
- `frontend/src/main.tsx` (existing rAF scroll loop, `IntersectionObserver` reveals, `animateMotion` SVG ball paths).
- `frontend/src/style.css` (`.reveal`, keyframes, reduced-motion blocks).
- `frontend/package.json` (no scroll libraries installed — keep it that way without justification).

## Decision procedure
1. Gate per `tactus-motion-router`: marketing explanation → eligible; dashboard data → reject.
2. Progress mapping must be **reversible and jump-free**: clamp segment index (never let `findIndex` return an unchecked `-1`), normalize by `scrollHeight - innerHeight`, interpolate within the segment. Scrolling up reverses the same timeline.
3. Reveals: `IntersectionObserver` + CSS classes (current pattern). Sticky/pinned multi-scene timelines: only then evaluate GSAP + ScrollTrigger or Anime.js timelines (`frontend/src/lib/motion`); default to reject (bundle + imperative React friction).
4. Smooth-scroll feel: **reject Lenis** — anchor links (`#system`, `#story`), modals, and native scroll suffice; Lenis risks anchor/modal fights for zero needed gain.
5. Video scrubbing / image sequences: only with licensed, optimized assets; none exist today — reject until assets + justification exist.
6. Cleanup: observers disconnected, rAF cancelled, scroll/resize listeners removed (current pattern in effect cleanups).

## Preferred and prohibited patterns
- Preferred: rAF-throttled progress math writing to `ref.style` (never per-frame React state), `transform`/`opacity` only, `preserveAspectRatio="none"` SVG paths for fluid lanes, `prefers-reduced-motion` static fallbacks.
- Prohibited: per-frame `setState`; layout-property animation; unclamped segment math; Lenis/GSAP installs without a pinned-sequence requirement; scroll-blocking overlays; autoplay audio.

## Accessibility and performance constraints
Reduced-motion: static end-state, no `animateMotion` (existing `@media` + `.motion-off` blocks). Touch: no hover-dependent scroll cues. Keep scroll handlers `passive`; keep work per frame to style writes on refs.

## Implementation and verification steps
1. Extend existing tokens/loops; no parallel scroll systems.
2. Verify segment math at progress 0, mid, and 1 (especially end-of-page).
3. `npx tsc -b` + `npm run build`; note that true scroll feel needs a browser + real device check.

## Reference links
- Emil `animate` (tool ladder, property rules): https://github.com/emilkowalski/skills/tree/main/skills/animate (MIT)
- frontend-ai-skills `27-scroll-storytelling`: https://github.com/JustineBijuPaul/frontend-ai-skills (MIT)
- Lenis docs (evaluated, rejected for now): https://github.com/darkroomengineering/lenis (MIT)
- GSAP ScrollTrigger (evaluated, rejected for now): https://gsap.com/docs/v3/Plugins/ScrollTrigger/

## Exit criteria
Reversible, clamped, jump-free scroll mapping; listeners cleaned; no new scroll libraries; reduced-motion fallback present; build green.
