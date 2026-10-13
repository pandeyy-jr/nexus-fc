---
name: tactus-quality-review
description: Responsive layout, error-state, contract, and visual QA review for TACTUSBALL frontend changes in frontend/. Use when reviewing a frontend diff, auditing routes and states, checking API wiring, or running pre-commit quality gates.
---

# TACTUSBALL Frontend Quality Review

## Purpose and triggering conditions
Catch regressions before they land: layout, states, contracts, and honesty of the UI. Trigger on any frontend diff review, route audit, or pre-commit gate in `frontend/`.

## Required source files to inspect
- The diff under review (`git diff`, `git status`).
- `frontend/src/main.tsx` + `frontend/src/style.css` (routes, states, classes touched).
- Backend contracts for any touched integration (`nexus-backend/app/schemas/*`, endpoint files) — payloads and response shapes must match; never adapt the UI to a guessed shape.
- `frontend/package.json` (no new dependency without justification).

## Decision procedure
Apply in order; any fail is a finding:
1. **Motion standards** (the ten from Emil `review-animations`): justified, frequency-appropriate, strong easing, sub-300ms UI, correct origin, interruptible, GPU-only props, accessible, asymmetric timing, cohesive.
2. **Responsive**: 700px and 1000px breakpoints sane; no horizontal overflow; touch targets usable; no clipped cards.
3. **States**: every touched flow shows loading, empty, error, and success; disabled states during `busy`; no dead buttons/links; no inert controls.
4. **Contracts**: request/response field names verified against backend schemas; 401/422/503 paths render honest messages (e.g. Copilot `insufficient_evidence`/unconfigured stays truthful, never mocked green).
5. **Honesty**: no fabricated metrics, testimonials, model accuracy, endorsements, or completed operations; illustrative visuals labeled; unavailable providers stay unavailable.
6. **Security**: no secrets/keys in code or bundles; Supabase/Postgres access only via FastAPI + RBAC; no `VITE_*` secrets.
7. **Hygiene**: no unrelated files, no generated artifacts committed, `git diff --check` clean.

## Preferred and prohibited patterns
- Preferred: small diffs; token extension over forks; exact-property transitions; findings cited as `file:line`.
- Prohibited: weakening tests/assertions to pass; claiming verification that didn't run; rewriting working components for appearance alone.

## Accessibility and performance constraints
Route findings through `tactus-accessibility-motion` and `tactus-frontend-performance`; performance regressions (chunk growth, new deps) need numbers.

## Implementation and verification steps
1. Review against the seven checks above; file findings with severity.
2. Run `npx tsc -b`, `npm run build`, and relevant backend tests when backend files changed.
3. State browser QA explicitly: completed (routes, sizes, console) or NOT RUN with a manual checklist.

## Reference links
- Emil review-animations: https://github.com/emilkowalski/skills/tree/main/skills/review-animations (MIT)
- frontend-ai-skills `63-frontend-code-review`, `54-visual-regression`: https://github.com/JustineBijuPaul/frontend-ai-skills (MIT)

## Exit criteria
Verdict (approve/block) with tiered findings; checks actually run reported; manual QA either done or checklist-provided.
