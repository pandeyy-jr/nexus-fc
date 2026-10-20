---
name: animation-performance
description: Keep web animations inside the frame budget — animate composite-only properties, keep motion off the main thread, find the cause when animation drops frames.
---

# Animation Performance

## Frame Budget
60fps = 16.7ms per frame. 120Hz = 8ms. Design against 8ms.

## Property tiers
| Tier | Properties | Cost |
| --- | --- | --- |
| Composite only | `transform`, `opacity`, `filter`, `clip-path`, `background-color` | Cheapest (GPU) |
| Paint + composite | `box-shadow`, `border-radius`, `color` | No re-measure, redraw per frame |
| Layout + paint + composite | `width`, `height`, `padding`, `margin`, `top`, `left`, `border-width` | Most expensive |

## Swapping down a tier
| Instead of | Animate |
| --- | --- |
| `width`/`height`/`padding` | `scale()` |
| `top`/`left`/`margin` | `translate()` |
| `display`/`visibility` | `opacity` |
| `box-shadow` | `filter: drop-shadow()` |

## Where it runs
- JS + rAF → Main thread (can jank under load)
- CSS transitions/keyframes → Can be hardware-accelerated
- WAAPI (`element.animate()`) → Can be hardware-accelerated

## React: Don't animate through state
Use `ref.current.style.transform` instead of `setState` every frame.

## Two traps
1. Inherited CSS variables driving child transforms (recalc storm)
2. Animated `blur()` above 20px (expensive in Safari)

## `will-change`
Add only after seeing pixel shifts or measured dropped frames. On the animating element only.

## Symptom table
| Problem | Solution |
| --- | --- |
| Stutters | `transform`/`opacity`, not layout properties |
| Shadow choppy | `filter: drop-shadow()` |
| Jank during navigation/loading | Move to CSS or WAAPI |
| Framer Motion `x`/`y` drops frames | Full `transform` string |
| React re-renders per frame | Write to ref.style, not state |
| Drag lags as list grows | Stop animating inherited CSS variable |
| Blur lags | Keep animated blur under 20px |

## Workflow
1. Find what animates (driver, properties, plays during)
2. Diagnose (properties → busy main thread → per-frame state → growing content → CSS variables → blur)
3. Report (cause, before/after, verified from code vs needs recording)
