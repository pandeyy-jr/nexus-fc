---
name: find-animation-opportunities
description: Search a codebase or UI for places that don't animate but should, and reject everything that shouldn't. Read-only; proposes motion with exact values, does not implement.
---

# Finding Animation Opportunities

## The Gate (all four questions, in order)
### 1. Frequency
| Frequency | Verdict |
| --- | --- |
| 100+ times/day | Reject. No animation. Ever. |
| Tens of times/day | Reject or near-imperceptible only |
| Occasional | Eligible |
| Rare / first-time | Eligible |

Keyboard-initiated actions are a disqualifier.

### 2. Purpose
Name one: Feedback, Spatial consistency, State indication, Preventing jarring change, Explanation, Delight.

### 3. Speed
Must work within standard budgets (UI under 300ms).

### 4. Function
Motion must help, not hinder. Functional data should not move for style.

## Hunt list
- Pressable elements with no `:active` state → `scale(0.97)`, `transition: transform 160ms ease-out`
- Destructive actions with plain click → hold-to-confirm fill
- Content that swaps/appears/vanishes instantly → fade/scale entrances
- Accordions that snap open → height + opacity transition
- List items added/removed with no bridge → enter/exit transitions
- Panels/popovers with no trigger connection → origin-aware scale
- Toast/sheet exiting different way than entered → symmetric path
- Grid/list popping in all at once → 30–80ms stagger
- Draggable elements snapping with no physics → springs

## Output format
### Part 1 — Opportunities table
| # | Location | Today | Purpose | Frequency | Suggested motion |
### Part 2 — Rejected candidates (REQUIRED)
2–5 places considered but not suggested, with gate question that killed it.
### Part 3 — Verdict
Short paragraph on motion needs, highest-leverage suggestion.
