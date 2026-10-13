---
name: tactus-3d-experiences
description: Evaluate and gate selective 3D and WebGL use (Three.js, React Three Fiber, shaders) for TACTUSBALL in frontend/src. Use when 3D, WebGL, models, shaders, or immersive scenes are proposed. Default verdict is rejection unless a scene truly needs 3D.
---

# TACTUSBALL 3D Experiences

## Purpose and triggering conditions
Decide whether a proposed 3D/WebGL scene earns its bundle, GPU, and maintenance cost. Trigger on any 3D/model/shader/immersive-scene request in `frontend/`. Default answer: no.

## Required source files to inspect
- `frontend/package.json` (three, @react-three/fiber, drei are NOT installed).
- `frontend/src/main.tsx` + `frontend/src/style.css` (confirm the need can't be met with SVG/CSS/canvas).
- `.opencode/skills/RESEARCH.md` (inventoried 3D sources and their costs).

## Decision procedure
1. Ask: does the scene require true 3D (rotatable models, depth, lighting, shaders)? Marketing tactility, pitch diagrams, and ball flights do not — SVG/CSS/canvas already serve them here.
2. If yes, demand: a licensed/owned asset pipeline, a lazy-load boundary (`React.lazy` + Suspense, route- or section-level), a static fallback image, device capability gating, and a bundle budget (<150KB gz for the 3D chunk or explicit approval).
3. Prefer composition: `@react-three/fiber` + `drei` helpers over hand-rolled WebGL; custom GLSL only for effects impossible otherwise.
4. Dispose everything: geometries, materials, textures, render targets, loops on unmount.

## Preferred and prohibited patterns
- Preferred: lazy boundaries, static fallbacks, capability gating, instancing for repeated geometry, capped pixel ratio.
- Prohibited: 3D for decoration on the operational dashboard; blocking first paint on a 3D chunk; unguarded fullscreen canvases on mobile; shipping without a fallback.

## Accessibility and performance constraints
Reduced-motion shows the static fallback, never the scene. Keyboard users get equivalent content. No layout shift when the chunk loads (reserve space). Mobile defaults to fallback unless the scene is the point.

## Implementation and verification steps
1. Record the rejected alternatives and why (SVG/CSS/canvas sufficed).
2. If approved: install minimal packages, lazy boundary, fallback, disposal.
3. `npx tsc -b` + `npm run build`; report chunk sizes; device-test on a mid-range phone (manual).

## Reference links
- Three.js manual (inventoried): https://threejs.org/manual/
- React Three Fiber docs (inventoried): https://r3f.docs.pmnd.rs/
- frontend-ai-skills 3D set 41–45/48/51 (inventoried): https://github.com/JustineBijuPaul/frontend-ai-skills (MIT)
- Emil animation-performance (GPU/disposal rules): https://github.com/emilkowalski/skills/tree/main/skills/animation-performance (MIT)

## Exit criteria
Written rejection with reasons, or an approved lazy, fallback-covered, disposed scene with measured bundle cost.
