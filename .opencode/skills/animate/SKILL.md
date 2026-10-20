---
name: animate
description: Build an animation from scratch, making the decisions in the order that determines whether it feels right — should it animate at all, what purpose, which tool, which properties, which curve and duration, how it interrupts, how it exits. Writes the implementation.
---

# Building Animations

## Hard Rules
1. Run the sequence in order. Steps 1 and 2 gate everything.
2. No approximated values — every curve, duration, and spring config comes from the tables.
3. Extend the codebase's tokens, don't fork them.
4. Reduced motion and hover gating ship with the animation.
5. Cheapest tool that works. Don't install a motion library for a fade.

## The Build Sequence

### 1. Should this animate at all?
| Frequency | Verdict |
| --- | --- |
| 100+ times/day | Reject. No animation. Ever. |
| Tens of times/day | Reject, or near-imperceptible motion only |
| Occasional | Eligible — standard animation |
| Rare / first-time | Eligible — delight budget |

Keyboard-initiated actions are a disqualifier.

### 2. Purpose (name one)
- Feedback — confirming the interface heard the user
- Spatial consistency — showing where something came from or went
- State indication — making a state change legible
- Preventing a jarring change — bridging content that teleports
- Explanation — demonstrating how a feature works (marketing/onboarding only)
- Delight — only at Rare/first-time tier

### 3. Tool — cheapest that works
| Need | Tool |
| --- | --- |
| Hover, press, color, state toggle | CSS transition |
| Entry on mount, no JS state | CSS `@starting-style` |
| Predetermined motion, must stay smooth under load | CSS animation |
| Programmatic control, CSS performance, no library | WAAPI (`element.animate()`) |
| Springs, layout, exit, gesture-driven | Motion (motion.dev) |

CSS animations beat JS under load — they run off the main thread.

### 4. Properties
- `transform` and `opacity` only (skip layout/paint, GPU)
- Never `scale(0)` — start from `scale(0.9–0.97)` + `opacity: 0`
- `transform-origin` at trigger for popovers; modals centered
- Percentages in `translate()` (relative to element's own size)
- Never drive child transform from parent CSS variable

### 5. Easing and duration
| Situation | Easing |
| --- | --- |
| Entering/exiting | `ease-out` |
| Moving/morphing on screen | `ease-in-out` |
| Hover/color change | `ease` |
| Constant motion | `linear` |

Built-in easings are too weak. Use:
```css
--ease-out: cubic-bezier(0.23, 1, 0.32, 1);
--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);
```
Never `ease-in` on UI.

Duration:
| Element | Duration |
| --- | --- |
| Button press | 100–160ms |
| Tooltips, popovers | 125–200ms |
| Dropdowns, selects | 150–250ms |
| Modals, drawers | 200–500ms |

UI under 300ms.

Springs: `{ type: "spring", duration: 0.5, bounce: 0.2 }` or `{ type: "spring", mass: 1, stiffness: 100, damping: 10 }`

### 6. Interruption and exit
- Transitions, not keyframes, for rapidly-triggered elements
- Springs for gestures (carry velocity through interruption)
- Exit the way it entered (symmetric paths)
- Asymmetric timing: slow deliberate phase, snappy system response

### 7. Reduced motion and pointer gating — ship with every animation

## Never Ship
| Never | Instead |
| --- | --- |
| `transition: all` | Name exact properties |
| `transform: scale(0)` entrance | `scale(0.95)` + `opacity: 0` |
| `ease-in` on UI | `ease-out` or custom curve |
| Built-in `ease-out` on deliberate animation | `cubic-bezier(0.23, 1, 0.32, 1)` |
| Animation on keyboard/100+/day action | No animation |
| UI duration over 300ms | 150–250ms |
| `transform-origin: center` on popover | `var(--transform-origin)` |
| Keyframes on toasts/toggles | CSS transitions |
| Animating `width`/`height`/`margin`/`padding`/`top`/`left` | `transform`/`opacity` |
| Ungated `:hover` motion | `@media (hover: hover) and (pointer: fine)` |
| Missing `prefers-reduced-motion` | Gentler variant |
