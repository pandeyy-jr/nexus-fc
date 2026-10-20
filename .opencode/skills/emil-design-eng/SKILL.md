---
name: emil-design-eng
description: Emil Kowalski's design engineering philosophy — UI polish, component design, animation decisions, and invisible details that make software feel great. Priority skill for TACTUSBALL redesign.
---

# Design Engineering

## Core Philosophy

### Taste is trained, not innate
Good taste is not personal preference. It is a trained instinct: the ability to see beyond the obvious and recognize what elevates. Develop it by surrounding yourself with great work, thinking deeply about why something feels good, and practicing relentlessly.

When building UI, don't just make it work. Study why the best interfaces feel the way they do. Reverse engineer animations. Inspect interactions. Be curious.

### Unseen details compound
Most details users never consciously notice. That is the point. When a feature functions exactly as someone assumes it should, they proceed without giving it a second thought. That is the goal.

> "All those unseen details combine to produce something that's just stunning, like a thousand barely audible voices all singing in tune." - Paul Graham

Every decision exists because the aggregate of invisible correctness creates interfaces people love without knowing why.

### Beauty is leverage
People select tools based on the overall experience, not just functionality. Good defaults and good animations are real differentiators. Beauty is underutilized in software. Use it as leverage to stand out.

## Review Format (Required)
When reviewing UI code, use a markdown table with Before/After/Why columns:

| Before | After | Why |
| --- | --- | --- |
| `transition: all 300ms` | `transition: transform 200ms ease-out` | Specify exact properties; avoid `all` |
| `transform: scale(0)` | `transform: scale(0.95); opacity: 0` | Nothing appears from nothing |
| `ease-in` on dropdown | `ease-out` with custom curve | `ease-in` feels sluggish; `ease-out` gives instant feedback |
| No `:active` state on button | `transform: scale(0.97)` on `:active` | Buttons must feel responsive to press |

## Animation Decision Framework

### 1. Should this animate at all?
| Frequency | Decision |
| --- | --- |
| 100+ times/day | No animation. Ever. |
| Tens of times/day | Remove or drastically reduce |
| Occasional (modals, drawers, toasts) | Standard animation |
| Rare/first-time (onboarding, celebrations) | Delight budget |

Never animate keyboard-initiated actions.

### 2. What is the purpose?
Valid purposes: feedback, spatial consistency, state indication, explanation, preventing jarring changes, delight.

### 3. Easing
Custom curves from easing.dev/easings.co:
```css
--ease-out: cubic-bezier(0.23, 1, 0.32, 1);
--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);
--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);
```
Never use `ease-in` on UI.

### 4. Duration
| Element | Duration |
| --- | --- |
| Button press | 100-160ms |
| Tooltips, popovers | 125-200ms |
| Dropdowns, selects | 150-250ms |
| Modals, drawers | 200-500ms |

UI animations under 300ms.

## Component Building Principles
- Buttons: `:active { transform: scale(0.97) }` with `transition: transform 160ms ease-out`
- Never animate from `scale(0)` — start from `scale(0.95)` + `opacity: 0`
- Popovers scale from trigger (`transform-origin`); modals stay centered
- CSS transitions over keyframes for interruptible UI
- `@starting-style` for entry without JS
- Blur (under 20px) to mask imperfect crossfades

## Reduced Motion & Accessibility
```css
@media (prefers-reduced-motion: reduce) { ... } /* gentler, not zero */
@media (hover: hover) and (pointer: fine) { ... } /* gate hover motion */
```

## Reference links
- Emil Kowalski skills: https://github.com/emilkowalski/skills (MIT)
- easing.dev: https://easing.dev/
- easings.co: https://easings.co/
