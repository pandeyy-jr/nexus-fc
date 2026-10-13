# TACTUSBALL Frontend Research Index

How upstream motion/design knowledge informed `.opencode/skills/tactus-*`.
Nothing below is copied wholesale: skill content is original, written for this
repo. Upstream text is referenced, not redistributed.

Conventions: **Reviewed** = read directly for this project. **Inventoried** =
catalogued via official docs/listing; deep review deferred until a decision
needs it. Instagram carousel images: **unavailable** — no post URL was ever
provided in the task, so no carousel repository could be identified; no names
invented.

## Emil Kowalski Skills — https://github.com/emilkowalski/skills (MIT, 2026)

| Source | Status | What it offers | Used for |
|---|---|---|---|
| `skills/animate/SKILL.md` | Reviewed | Build sequence: gate → purpose → cheapest tool → transform/opacity → strong beziers/durations → interruption/exit → reduced-motion+hover gating | `tactus-motion-router` ladder, `tactus-micro-interactions` values |
| `skills/find-animation-opportunities/SKILL.md` | Reviewed | Restraint-first sweep; 4-question gate; required rejections section | Phase E audit shape (opportunities + rejections below) |
| `skills/review-animations/SKILL.md` | Reviewed | Ten non-negotiable standards; escalation triggers; tiered verdict | `tactus-quality-review` checks 1–2 |
| `skills/improve-animations/SKILL.md` | Reviewed | Audit-then-plan workflow (read-only plans) | Adapted: this repo audits then implements directly per task |
| `skills/animation-performance/SKILL.md` | Reviewed | Composite-only props; off-main-thread; no per-frame React state; `will-change` last | `tactus-frontend-performance` |
| `skills/apple-design`, `mobile-native`, `break-ui`, `pick-ui-library`, `prototype`, `animation-vocabulary`, `animate-expo`, `ask-sonner` | Inventoried via repo README | Apple motion principles; mobile web pitfalls; worst-case-data QA; library picking; prototyping; vocabulary | Referenced in skills; not deep-reviewed (no current need) |

Maintenance: single-author, active (2026). Dependency: none (markdown only).
Install avoided on purpose: vendoring 15 skills would pollute agent selection;
project-local skills distill only what this repo needs.

## Frontend AI Skills — https://github.com/JustineBijuPaul/frontend-ai-skills (MIT)

70 skills; installer targets global/editor paths (not used — project-local
`.opencode/skills/` chosen instead so rules travel with the repo).

| Source | Status | Note |
|---|---|---|
| `70-frontend-skill-router` | Reviewed | Smallest-skill routing + implementation/quality contract; mirrors our router shape |
| `27-scroll-storytelling` | Reviewed | Contract-heavy; thin on values — Emil + LottieFiles carry the values |
| `37-micro-interactions` | Reviewed | Same; values live in Emil/LottieFiles sources |
| Remaining 67 (core/animation/3D/quality sets) | Inventoried via catalog table | Category map informed our 8-skill split; deep review deferred |

Maintenance: community PR-driven. Dependency: none (content only).

## Motion Design Skill — https://github.com/LottieFiles/motion-design-skill (MIT)

Reviewed: `SKILL.md` core (8-step checklist, three pillars, personality
archetypes, duration/easing tables, choreography, 1/3 rules, troubleshooting).
`director/` + `patterns/` + `reference/` inventoried via file listing.
TACTUSBALL personality: Corporate/Corporate-premium. Maintenance: LottieFiles
org. No install (content adapted, not vendored).

## Lenis — https://github.com/darkroomengineering/lenis (MIT)

Reviewed: README (features, settings, anchor/nested-scroll handling,
reduced-motion support, limitations). **Decision: rejected for TACTUSBALL**
— anchor links, modals, and native scroll suffice; smooth-scroll wrapper
risks anchor/modal fights for zero needed gain. Reconsider only for
WebGL-synced scroll scenes.

## Motion for React — https://motion.dev/docs/react (reviewed overview)

Declarative, WAAPI-backed, springs/layout/exit/gestures. **Decision: not
installed** — current needs (press feedback, modal entrances, reveals) are
CSS-solvable; install only with a spring/layout/exit requirement.

## GSAP + ScrollTrigger — https://gsap.com/docs/v3/ (inventoried)

Imperative timelines, pinned sequences. **Decision: rejected for now** —
bundle + React friction unjustified; current scroll needs are
progress-mapping + reveals. Reconsider only for pinned multi-scene timelines.

## Three.js / React Three Fiber — inventoried via official docs links

https://threejs.org/manual/ · https://r3f.docs.pmnd.rs/ — **rejected**: no
scene needs true 3D; see `tactus-3d-experiences` for the gate.

## Lottie — inventoried (https://lottiefiles.com/)

**Rejected**: no licensed animation asset available; CSS/SVG suffice.

## Web Animations API — inventoried standard

https://developer.mozilla.org/en-US/docs/Web/API/Web_Animations_API —
available natively when programmatic CSS-performance control is needed;
not needed today.

## Rejected techniques (with reasons)

Lenis (anchor/modal risk, no need) · GSAP/ScrollTrigger (bundle + friction,
no pinned sequences) · Motion (no spring/layout/exit need) · Three.js/R3F
(no true 3D need, bundle/GPU cost) · Lottie (no licensed asset) ·
cursor effects/particles/WebGL decoration (task-prohibited) ·
`transition: all`, `scale(0)`, `ease-in` on UI, layout-property animation,
per-frame React state (Emil escalation triggers — never ship).
