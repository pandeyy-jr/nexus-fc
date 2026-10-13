# TACTUSBALL Reference Inventory — Frontend Motion & Interaction

Verified source URLs, selected techniques with implementation targets, and
rejections with reasons. Nothing here is copied wholesale; techniques are
adapted to the graphite/lime TACTUSBALL system. Upstream licenses respected
(MIT unless noted).

## Studied and partially adopted

- **Emil Kowalski Skills** (MIT) — https://github.com/emilkowalski/skills
  - `skills/animate/SKILL.md` — build sequence, cheapest-tool ladder, strong
    bezier/duration tables → project motion tokens + press values.
  - `skills/find-animation-opportunities/SKILL.md` — restraint gate + required
    rejections → audit format used for this repo's motion decisions.
  - `skills/review-animations/SKILL.md` — ten standards → QA checklist.
  - `skills/improve-animations/SKILL.md` — audit-then-plan; adapted (we audit
    then implement directly per task scope).
  - `skills/animation-performance/SKILL.md` — composite-only props,
    off-main-thread, no per-frame React state → performance rules.
- **LottieFiles motion-design-skill** (MIT) —
  https://github.com/LottieFiles/motion-design-skill — Corporate personality
  archetype, duration tables, stagger budgets → brand motion identity.
- **Lenis** (MIT) — https://github.com/darkroomengineering/lenis —
  **Rejected**: anchor links, modals, and native scroll suffice; smooth-scroll
  wrapper risks anchor/modal fights for zero needed gain.
- **Motion for React** — https://motion.dev/docs/react — reviewed overview.
  **Not installed**: press/modal/reveal needs are CSS-solvable; install only
  for springs, layout animation, or exit animations with justification.
- **frontend-ai-skills** (MIT) —
  https://github.com/JustineBijuPaul/frontend-ai-skills — router contract
  (`70-frontend-skill-router`), scroll-m storytelling, micro-interactions;
  70-skill bundle **not installed** (selection pollution; distilled instead).
- **Temlis sports templates** — https://www.temlis.com/subcategories/sports-websites
  (marketplace index reviewed; live previews gated) — principles only:
  oversized editorial headlines, sticky visual preview, restrained dark
  surfaces. Nothing copied.
- **MotionSites** — https://motionsites.ai/motionsite (reviewed; prompt
  marketplace, no reusable source) — principle adopted: restraint-first,
  typography-led motion. Academy/lesson pages not reviewed.

## Evaluated and rejected

- **Aceternity UI** — https://ui.aceternity.com/components ;
  catalog https://ui.aceternity.com/ai-recommendations (snapshot verified
  8/10 listed slugs: spotlight, glowing-effect, card-spotlight,
  moving-border, sticky-scroll-reveal, hero-parallax, apple-cards-carousel,
  background-gradient; `animated-tabs` and `3d-card-effect` not found in the
  snapshot). Rejected: glow/gradient-heavy idiom conflicts with AGENTS.md
  rules; no dependency added.
- **DavidHDev Canvas UI** — https://github.com/DavidHDev/canvas-ui and
  https://canvasui.dev/ (README reviewed; MIT + Commons Clause). Full-page
  WebGL effects over live DOM need Chrome flags/origin trial, fight
  reduced-motion simplicity, and serve no dashboard need. Rejected.
- **Alibaba canvas-ui** — https://github.com/alibaba/canvas-ui (README
  reviewed): a canvas-based React UI *renderer* (DOM-like scene tree drawn
  in canvas). Fundamentally wrong direction for an accessible DOM app.
  Rejected. (Distinct project from DavidHDev Canvas UI above.)
- **Spline / react-spline** — https://github.com/splinetool/react-spline
  (README reviewed, MIT) + https://docs.spline.design/. Integration understood
  (lazy `<Spline scene>`, `onLoad`, `emitEvent`). Rejected: **no scene asset
  exists — no URL fabricated**. Connection point documented: a future scene
  belongs in a lazy boundary on the marketing hero with a static fallback.
- **SkeuDesign** — https://skeudesign.com/ (reviewed: a paid PNG icon
  library + AI studio, not a control library; no toggle examples available).
  Extracted principles only (tactile track/thumb geometry, press/release
  states, focus/disabled handling) for the original CSS switch primitive.
- **Three.js / R3F / GSAP ScrollTrigger / Lottie / WAAPI-deep-dives** —
  inventoried via official docs (https://threejs.org/manual/,
  https://r3f.docs.pmnd.rs/, https://gsap.com/docs/v3/Plugins/ScrollTrigger/,
  https://lottiefiles.com/,
  https://developer.mozilla.org/en-US/docs/Web/API/Web_Animations_API);
  deferred until a decision needs them. No 3D, pinned-sequence, licensed
  vector-asset, or programmatic-animation requirement exists today.

## Technique → component map (implemented)

- CSS transitions (exact props, token curves/durations) → buttons, links,
  launcher ball, modal entrances, reveals.
- rAF scroll-progress mapping (clamped, reversible) → hero flight ball.
- IntersectionObserver reveals → marketing sections.
- SMIL `animateMotion` (decorative SVG lanes, hidden under reduced motion) →
  stadium strip, pitch pass lane.
- Original CSS tactile switch → footer motion toggle (this inventory's
  skeu-principle application).
