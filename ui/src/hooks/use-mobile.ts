import * as React from "react"

const MOBILE_BREAKPOINT = 768

const QUERY = `(max-width: ${MOBILE_BREAKPOINT - 1}px)`

function subscribe(onChange: () => void) {
  const mql = window.matchMedia(QUERY)
  mql.addEventListener("change", onChange)
  return () => mql.removeEventListener("change", onChange)
}

/**
 * True when the viewport is narrower than the mobile breakpoint.
 *
 * Uses `useSyncExternalStore` rather than an effect that calls `setState`:
 * the media query is external state React should subscribe to, and setting
 * state synchronously inside an effect causes the cascading re-render the
 * React Compiler rules flag. It also removes the first-paint flash, since
 * the value is read during render instead of after mount.
 */
export function useIsMobile() {
  return React.useSyncExternalStore(
    subscribe,
    () => window.innerWidth < MOBILE_BREAKPOINT,
    // Server render has no viewport; assume desktop, matching the previous
    // behaviour where the state began undefined and coerced to false.
    () => false,
  )
}
