import type { AnimationParams } from 'animejs'

/**
 * TACTUSBALL motion tokens — mirrors the CSS tokens in style.css
 * so Anime.js and CSS share a single source of truth for curves/durations.
 */
export const MOTION_TOKENS = {
  duration: {
    fast: 160,   // press / micro feedback
    med: 240,    // modal / control transitions
    story: 600,  // marketing section reveals
    entrance: 700, // hero / first-touch sequences
  },
  easing: {
    out: 'cubic-bezier(0.23, 1, 0.32, 1)',
    inOut: 'cubic-bezier(0.77, 0, 0.175, 1)',
  },
  stagger: {
    tight: 40,   // dense lists (match rows, memory items)
    standard: 80, // feature sections, cards
    loose: 140,   // hero copy, sparse elements
  },
} as const

/**
 * Typed animation preset. `targets` is intentionally omitted — callers
 * supply targets at call site so each preset stays reusable across scopes.
 */
export type MotionPreset = Omit<AnimationParams, 'targets'> & {
  /** Optional per-item delay derived from index (for stagger sequences). */
  delay?: (index: number) => number
}

/** Fade up from below — general purpose entrance. */
export const fadeInUp: MotionPreset = {
  opacity: [0, 1],
  translateY: [24, 0],
  duration: MOTION_TOKENS.duration.entrance,
  easing: MOTION_TOKENS.easing.out,
}

/** Simple fade in — for overlays, modals, subtle state changes. */
export const fadeIn: MotionPreset = {
  opacity: [0, 1],
  duration: MOTION_TOKENS.duration.entrance,
  easing: MOTION_TOKENS.easing.out,
}

/** Subtle scale + fade — for cards and controlled surfaces. */
export const subtleScaleIn: MotionPreset = {
  scale: [0.96, 1],
  opacity: [0, 1],
  duration: MOTION_TOKENS.duration.med,
  easing: MOTION_TOKENS.easing.out,
}

/** Modal/dialog entrance — short, crisp, no travel. */
export const modalEnter: MotionPreset = {
  opacity: [0, 1],
  scale: [0.97, 1],
  duration: MOTION_TOKENS.duration.fast,
  easing: MOTION_TOKENS.easing.out,
}

/** Section reveal — marketing storytelling, longer and softer. */
export const sectionReveal: MotionPreset = {
  opacity: [0, 1],
  translateY: [30, 0],
  duration: MOTION_TOKENS.duration.story,
  easing: MOTION_TOKENS.easing.out,
}

/** Factory: per-item delay for stagger reveals. */
export const staggerDelay = (staggerMs: number) => (index: number) => index * staggerMs
