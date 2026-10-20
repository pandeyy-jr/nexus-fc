---
name: apple-design
description: Apple's approach to interface design and fluid, physical motion, translated for the web. Use for gesture-driven UI, spring animations, drag/swipe/sheet interactions, momentum and interruptible transitions, translucent materials and depth.
---

# Apple Design

## Core idea
An interface is fluid when it behaves like the physical world: respond instantly, move continuously, carry momentum, resist at boundaries, redirectable at any instant.

## 1. Response — kill latency
- Respond on pointer-down, not release
- Feedback continuously during interaction
- `:active { transform: scale(0.97); transition: transform 100ms ease-out; }`

## 2. Direct manipulation — 1:1 tracking
- Element stays glued to finger, respecting grab offset
- Use Pointer Events + `setPointerCapture`

## 3. Interruptibility — most important principle
- Never lock out input during transition
- Animate from presentation (current) value, never target value
- Springs for gesture-driven (can't grab/reverse keyframes mid-flight)

## 4. Behavior over animation — springs
| Interaction | Damping | Response |
| --- | --- | --- |
| Move/reposition | 1.0 | 0.4 |
| Rotation | 0.8 | 0.4 |
| Drawer/sheet | 0.8 | 0.3 |

Start at damping 1.0 (critically damped). Reserve bounce (~0.8) for momentum-driven gestures.

## 5. Velocity handoff
Continue at finger's exact velocity at gesture end. Normalize: `gestureVelocity / (target − current)`.

## 6. Momentum projection
Project resting position from release velocity, then snap to nearest target.
```js
project(v, d=0.998) = (v/1000) * d / (1 - d)
```

## 7. Spatial consistency
- Enter/exit same path
- Anchor to trigger (`transform-origin`)
- Mirror easing on reversible transitions

## 8. Rubber-banding — soft boundaries
Resist progressively at edges, don't hard-stop.

## 9. Materials & depth
- Translucent layers (`backdrop-filter: blur()`)
- Material weight encodes hierarchy
- Never stack light translucent on light translucent

## 10. Typography — optical sizing, tracking, leading
- Tracking is size-specific (tighten large text, body near 0)
- Leading tracks size inversely
- Default to system font

## Quick reference
| Need | Technique | Value |
| --- | --- | --- |
| Default UI spring | Critically damped | damping 1.0, response 0.3–0.4 |
| Momentum spring | Under-damped | damping ~0.8, response 0.3–0.4 |
| Gesture → spring velocity | Hand off release velocity | normalized or raw px/s |
| Flick landing | Project momentum | `current + (v/1000)·d/(1−d)` |
