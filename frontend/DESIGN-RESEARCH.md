# TACTUSBALL — Design Research Document

## Method
Studied actual reference sources (not copied wholesale). Techniques adapted to graphite/lime TACTUSBALL system. Upstream licenses respected (MIT unless noted).

## Studied & Partially Adopted

| Source | URL | Technique Observed | Problem It Solves | Where in TACTUSBALL | Implementation | Accessibility/Performance | Why Selected |
|--------|-----|-------------------|-------------------|---------------------|----------------|---------------------------|--------------|
| Emil Kowalski Skills | https://github.com/emilkowalski/skills | Build sequence, bezier/duration tables, restraint gate | Animation timing, easing, component polish | All motion work | Motion tokens, press values, `@starting-style`, `transform`/`opacity` only | Reduced-motion, hover gating, GPU-only props | Industry-standard animation philosophy; already referenced in project |
| Emil `emil-design-eng` | https://github.com/emilkowalski/skills/tree/main/skills/emil-design-eng | UI polish, unseen details, beauty as leverage | Component craft, tactile feedback | All components | `:active scale(0.97)`, origin-aware popovers, `@starting-style` | Reduced-motion, pointer gating | Priority skill per task requirements |
| Emil `animate` | https://github.com/emilkowalski/skills/tree/main/skills/animate | Animation construction: gate, purpose, tool, curve, duration | Correct animation ingredient selection | New motion sequences | CSS transitions, WAAPI, Anime.js scopes | Cheapest tool, interruptibility | Authoritative construction framework |
| Emil `review-animations` | https://github.com/emilkowalski/skills/tree/main/skills/review-animations | Ten non-negotiable standards, escalation triggers | Animation QA, blocking bad motion | Motion review | Before/After table, verdict Block/Approve | All 10 standards applied | High craft bar for motion |
| Emil `animation-performance` | https://github.com/emilkowalski/skills/tree/main/skills/animation-performance | Composite-only props, frame budget, JS-vs-CSS thread | Drop-frame prevention | All animations | `transform`/`opacity`, WAAPI, `will-change` only after observed jank | Mid-range phone bar, 120Hz budget | Performance-critical for dashboard |
| Emil `apple-design` | https://github.com/emilkowalski/skills/tree/main/skills/apple-design | Fluid interfaces, springs, 1:1 tracking, interruptibility | Physical-feeling gesture/motion | Gestures, modals, draggables | Critically damped springs, velocity handoff, rubber-banding | Reduced-motion variants | Fluid interaction standard |
| Emil `animation-vocabulary` | https://github.com/emilkowalski/skills/tree/main/skills/animation-vocabulary | Motion effect naming glossary | Precise motion terminology | Design communication | Stagger, origin-aware, crossfade, rubber-banding | N/A | Naming precision |
| LottieFiles motion-design | https://github.com/LottieFiles/motion-design-skill | Corporate personality archetype, duration tables | Brand motion identity | Motion language | Stagger budgets, duration tables | Reduced-motion fallback | Brand personality reference |
| MotionSites | https://motionsites.ai/motionsite | Restraint-first, typography-led motion | Avoiding over-animation | Landing page storytelling | Signature experiences, not dozens of effects | Perceptual performance | Restraint principle adopted |
| Anime.js v4 | https://animejs.com/documentation/ | Coordinated timelines, staggered reveals, scoped animation | Multi-element choreography | Landing hero sequence, workspace entrances | `createScope()`, `useAnime()`, named imports, `scope.revert()` | `shouldSkipMotion()` hook, tree-shaking | Already integrated, v4 stable |

## Evaluated & Rejected

| Source | URL | Reason for Rejection |
|--------|-----|---------------------|
| Aceternity UI | https://ui.aceternity.com/components | Glow/gradient-heavy idiom conflicts with AGENTS.md rules; no dependency added |
| DavidHDev Canvas UI | https://github.com/DavidHDev/canvas-ui | Full-page WebGL over live DOM needs Chrome flags; fights reduced-motion; no dashboard need |
| Alibaba canvas-ui | https://github.com/alibaba/canvas-ui | Canvas-based React renderer; wrong direction for accessible DOM app |
| Spline / react-spline | https://github.com/splinetool/react-spline | No scene asset exists; no URL fabricated; future lazy boundary only |
| SkeuDesign | https://skeudesign.com | Paid PNG icon library + AI studio; not a control library; principles only |
| Lenis | https://github.com/darkroomengineering/lenis | Anchor links/modals/native scroll suffice; risks anchor/modal fights |
| Motion for React | https://motion.dev/docs/react | Not installed; CSS-solvable for press/modal/reveal needs |
| GSAP + ScrollTrigger | https://gsap.com/docs/v3/Plugins/ScrollTrigger/ | Deferred; no pinned-sequence requirement today |
| Three.js / R3F | https://threejs.org/manual/ | Deferred; no 3D requirement today |
| Lottie | https://lottiefiles.com/ | Deferred; no licensed vector asset today |

## Technique → Component Map (Current)

- CSS transitions (exact props, token curves/durations) → buttons, links, launcher ball, modal entrances, reveals
- Anime.js `animate()` + `createScope()` → feature explorer stagger reveals, Command Center cards, Lab result, Copilot answer, Match Library rows, Club Memory items, Decision Replay rows, Player Intelligence detail
- rAF scroll-progress (clamped, reversible) → hero flight ball
- IntersectionObserver reveals → marketing sections
- SMIL `animateMotion` (hidden under reduced motion) → stadium strip, pitch pass lane
- CSS tactile switch → footer motion toggle

## Figma MCP Status
- Config created at `.opencode/mcp.json` pointing to `https://mcp.figma.com/mcp`
- **BLOCKED**: OAuth sign-in flow required; cannot complete without user interaction
- No Figma file ID available; no design-file contents retrieved
- Continuing with verified repository + reference research

## Reference URLs Actually Inspected
1. https://github.com/emilkowalski/skills — Emil Kowalski skills repo (MIT)
2. https://github.com/emilkowalski/skills/tree/main/skills/emil-design-eng — Design engineering philosophy
3. https://github.com/emilkowalski/skills/tree/main/skills/animate — Animation construction
4. https://github.com/emilkowalski/skills/tree/main/skills/review-animations — Animation review standards
5. https://github.com/emilkowalski/skills/tree/main/skills/animation-performance — Animation performance
6. https://github.com/emilkowalski/skills/tree/main/skills/apple-design — Apple fluid interface design
7. https://github.com/emilkowalski/skills/tree/main/skills/animation-vocabulary — Motion naming glossary
8. https://github.com/LottieFiles/motion-design-skill — Motion design personality
9. https://motionsites.ai/motionsite — Restraint-first motion examples
10. https://animejs.com/documentation/ — Anime.js v4 official docs
11. https://github.com/juliangarnier/anime — Anime.js source (MIT)
12. https://ui.aceternity.com/components — Aceternity UI (evaluated, rejected)
13. https://developers.figma.com/docs/figma-mcp-server/ — Figma MCP docs
14. https://github.com/SupremeIdeas/frontend-design-taste-skill — Taste skill (evaluated)
