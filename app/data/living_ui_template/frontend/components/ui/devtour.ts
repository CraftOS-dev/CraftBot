/**
 * Dev-tour registration (SYSTEM-MANAGED — do not edit)
 *
 * While CraftBot is BUILDING this app, the reveal engine (agent/devBuildMode,
 * dev server only) briefly opens hidden surfaces — modals, drawers, menus,
 * inactive tabs — so the user watches every built component appear, not just
 * the resting page. Overlay presets register an open/close handle here.
 *
 * Production builds: import.meta.env.DEV is false and the registry global
 * never exists, so every call is a no-op. Fail-silent by design.
 */

import { useEffect, useRef } from 'react'

export interface DevSurfaceHandle {
  /** Surface family — 'modal' | 'drawer' | 'menu' | 'tab'. */
  kind: string
  label: () => string
  show: () => void
  hide: () => void
  /** The surface's rendered DOM (portals live outside #root, so the tour
   * captures them directly). null = inline in #root, engine handles it. */
  node: () => HTMLElement | null
}

interface DevSurfaceRegistry {
  register: (handle: DevSurfaceHandle) => () => void
}

/** Register this surface with the build-time tour. All callbacks are read
 * through a ref so the registration itself is stable across re-renders. */
export function useDevSurface(
  kind: string,
  label: string,
  show: () => void,
  hide: () => void,
  node: () => HTMLElement | null = () => null,
) {
  const current = useRef({ label, show, hide, node })
  current.current = { label, show, hide, node }

  useEffect(() => {
    if (!import.meta.env.DEV) return
    const registry = (window as unknown as { __CB_DEV_SURFACES__?: DevSurfaceRegistry })
      .__CB_DEV_SURFACES__
    if (!registry?.register) return
    try {
      return registry.register({
        kind,
        label: () => current.current.label,
        show: () => current.current.show(),
        hide: () => current.current.hide(),
        node: () => current.current.node(),
      })
    } catch {
      return undefined /* the tour is cosmetic — never break the app */
    }
  }, [kind])
}
