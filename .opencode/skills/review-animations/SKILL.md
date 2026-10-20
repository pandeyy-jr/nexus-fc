---
name: review-animations
description: Reviews animation and motion code against a high craft bar derived from Emil Kowalski's design engineering philosophy. Default to flagging; approval is earned.
---

# Reviewing Animations

## Ten Non-Negotiable Standards
1. Justified motion — every animation must answer "why does this animate?"
2. Frequency-appropriate — keyboard/100+/day actions get no animation
3. Responsive easing — entering/exiting uses `ease-out` or strong custom curve; no `ease-in` on UI
4. Sub-300ms UI — UI animations under 300ms
5. Origin & physical correctness — popovers scale from trigger; never `scale(0)` entrances
6. Interruptibility — rapidly-triggered motion must be interruptible (transitions/springs, not keyframes)
7. GPU-only properties — `transform`/`opacity` only
8. Accessibility — `prefers-reduced-motion` honored; hover gated behind media query
9. Asymmetric enter/exit — deliberate actions slow, system responses snap
10. Cohesion — motion matches component personality and product

## Aggressive Escalation Triggers (flag on sight)
- `transition: all`, `scale(0)`, `ease-in` on UI
- Animation on keyboard shortcut or 100+/day action
- UI duration > 300ms with no reason
- `transform-origin: center` on trigger-anchored popover
- Keyframes on toasts/toggles/rapid elements
- Animating layout properties (`width`/`height`/`margin`/`padding`/`top`/`left`)
- Missing `prefers-reduced-motion` on movement
- Ungated `:hover` motion
- Symmetric enter/exit timing on press-and-release or hold
- Everything-at-once entrance where stagger belongs

## Remedial Preference Hierarchy
1. Delete the animation
2. Reduce it (shorter duration, smaller transform)
3. Fix the easing (swap `ease-in`→`ease-out`/custom curve)
4. Fix origin/physicality (correct `transform-origin`; replace `scale(0)`)
5. Make it interruptible (keyframes→transitions/springs)
6. Move to GPU (layout props→`transform`/`opacity`)
7. Asymmetric timing
8. Polish (blur-masked crossfades, stagger, `@starting-style`, springs)
9. Accessibility & cohesion

## Output format
### Part 1 — Findings table
| Before | After | Why |
### Part 2 — Verdict (Block or Approve)
Close with explicit decision: Block or Approve.
