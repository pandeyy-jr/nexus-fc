---
name: improve-animations
description: Survey a codebase's animation and motion code, then produce a prioritized audit and self-contained implementation plans. Read-only; plans improvements, does not apply them.
---

# Improving Animations

## Workflow
### Phase 1 — Recon (always first)
Map motion surface: stack, motion libraries, where motion lives, conventions, personality, frequency map.

### Phase 2 — Audit (parallel)
Audit against categories: purpose & frequency, easing & duration, physicality & origin, interruptibility, performance, accessibility, cohesion & tokens, missed opportunities.

### Phase 3 — Vet, prioritize, confirm
Re-read cited code for every finding. Present vetted findings table ordered by leverage. List missed opportunities separately. Wait for user selection before writing plans.

### Phase 4 — Write plans
One plan per finding, self-contained, exact file paths, exact target values from AUDIT.md. Write to `plans/NNN-short-slug.md`.

## Hard Rules
- Never modify source code. Plans only.
- Plans must be fully self-contained (exact cubic-bezier, duration, file path, code excerpt).
- Don't re-litigate settled decisions.
