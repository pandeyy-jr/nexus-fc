---
name: tactus-frontend-design
description: Art direction, composition, typography, color, spacing, and design-system consistency for TACTUSBALL pages in frontend/src. Use when styling pages, choosing type or color, laying out sections, adding components, or reviewing visual consistency.
---

# TACTUSBALL Frontend Design

## Purpose and triggering conditions
Keep every interface cinematic, premium, and football-specific: graphite/dark surfaces, electric-lime accents, editorial typography, deliberate composition, Apple-level restraint. Trigger on styling, layout, component, or visual-review work in `frontend/`.

## Required source files to inspect
- `frontend/src/style.css` (tokens on `:root`: `--ink`, `--paper`, `--lime`, `--green`, `--line`, `--muted`; type: Barlow Condensed display + DM Sans body).
- `frontend/src/main.tsx` (existing components and class names — reuse, don't fork).
- `frontend/index.html` (title, meta, fonts, hero preload).
- `.opencode/skills/RESEARCH.md` (Temlis-informed principles; nothing copied).

## Decision procedure
1. Identify the surface: **marketing** (cinematic, expressive) vs **operational dashboard** (fast, dense, readable). Dashboard clarity always beats decoration.
2. Compose with existing tokens and components first. New token only if no token fits; document it in `:root`.
3. Typography: Barlow Condensed for oversized display headlines, DM Sans for UI/body. Hierarchy via size/weight/spacing, never decoration.
4. Accent discipline: electric lime (`--lime`) for calls-to-action, live states, and key data points only. Restrained whites/greys elsewhere.
5. Imagery: real football photography with cinematic cropping; label illustrative visuals as illustrative.
6. Check the AGENTS.md frontend rules (no purple/blue gradients, gradient hero text, emoji headings, glassmorphism excess, neon, generic 3-card layouts, fake testimonials/metrics, purposeless animation, low-contrast dark UI, buzzword copy).

## Preferred and prohibited patterns
- Preferred: fine borders, controlled shadows, consistent radii, negative space, pitch-grid/tactical-line motifs, semantic HTML, real data with loading/error/empty states.
- Prohibited: fabricating metrics, testimonials, logos, endorsements, model accuracy; neon glow; gradient text; generic SaaS templates; cursor gimmicks; perpetual floating elements.

## Accessibility and performance constraints
Contrast must stay legible on dark surfaces; touch targets ≥44px where feasible; images lazy-load below the fold (`loading="lazy"`, explicit dimensions to avoid layout shift); hero image preloaded once (already in `index.html`).

## Implementation and verification steps
1. Reuse existing classes; add minimal scoped classes only.
2. Verify responsive behavior at 700px and 1000px breakpoints (existing media queries).
3. Run `npx tsc -b` and `npm run build` in `frontend/`.
4. State what needs human eyes (imagery crop, type rhythm) — never claim visual perfection from code alone.

## Reference links
- LottieFiles motion-design personality archetypes (TACTUSBALL: Corporate/Corporate-premium): https://github.com/LottieFiles/motion-design-skill (MIT)
- Emil apple-design: https://github.com/emilkowalski/skills/tree/main/skills/apple-design (MIT)
- Temlis sports templates (research only, no copying): https://www.temlis.com/subcategories/sports-websites

## Exit criteria
No new visual language invented; tokens extended not forked; no fabricated content; build green; responsive + contrast sanity stated.
