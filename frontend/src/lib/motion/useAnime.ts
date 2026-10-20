import { useEffect, useRef } from 'react'
import { createScope } from 'animejs'
import type { Scope } from 'animejs'
export type { Scope }
import { shouldSkipMotion } from './utils'

/**
 * React hook for scoped Anime.js animations.
 *
 * Usage:
 *   const scope = useAnime((s) => {
 *     s.add(() => animate('.card', { opacity: [0, 1], translateY: [24, 0] }))
 *   }, [deps])
 *
 * The scope is automatically reverted on unmount or when deps change,
 * so animations never outlive their component and never fight React-owned DOM.
 *
 * Returns null when reduced motion is active — callers should treat that
 * as "animate nothing" and still render all content visibly.
 */
export function useAnime(
  setup: (scope: Scope) => void,
  deps: readonly unknown[] = [],
): Scope | null {
  const scopeRef = useRef<Scope | null>(null)

  useEffect(() => {
    if (shouldSkipMotion()) {
      scopeRef.current = null
      return undefined
    }

    const scope = createScope()
    scopeRef.current = scope

    scope.add(() => {
      setup(scope)
    })

    return () => {
      scope.revert()
      scopeRef.current = null
    }
  }, deps)

  return scopeRef.current
}
