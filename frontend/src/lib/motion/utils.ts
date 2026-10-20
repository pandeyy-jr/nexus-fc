/**
 * Motion preference helpers.
 *
 * Reuses the same reduced-motion sources already honoured by the app:
 *   - `prefers-reduced-motion: reduce` media query
 *   - `tactus_motion` localStorage toggle (set by the footer tact-switch)
 *
 * Never invents a second, conflicting setting.
 */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function motionOffFromLocalStorage(): boolean {
  if (typeof window === 'undefined') return false
  return localStorage.getItem('tactus_motion') === 'off'
}

export function shouldSkipMotion(): boolean {
  return prefersReducedMotion() || motionOffFromLocalStorage()
}
