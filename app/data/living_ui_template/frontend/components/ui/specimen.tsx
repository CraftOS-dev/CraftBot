/**
 * Specimen — DEV-ONLY offscreen render of hidden overlay content
 * (SYSTEM-MANAGED — do not edit).
 *
 * While a Living UI is being CREATED, the construction view showcases each
 * freshly built component by screenshotting its real rendered DOM (see
 * agent/devBuildMode.ts). Overlay presets (Modal, Drawer) render nothing
 * while closed, so their content — usually the most interesting components,
 * like forms — would never have DOM to capture. When closed, they render
 * their children through this instead: mounted in the real tree (real
 * context, real data), positioned far off-screen, ignored by the reveal
 * engine and design metrics via the data-cb-specimen marker.
 *
 * In production builds this renders nothing at all.
 */

import { Component, ReactNode } from 'react'

// Layout width the offscreen content is given for capture — matches the
// default overlay panel width so screenshots look like the real thing.
const SPECIMEN_WIDTH_PX = 560

class SpecimenBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  componentDidCatch() {
    /* a specimen must never break the app — render nothing instead */
  }
  render() {
    return this.state.failed ? null : this.props.children
  }
}

export function Specimen({ children }: { children: ReactNode }) {
  if (!import.meta.env.DEV) return null
  return (
    <div
      data-cb-specimen="1"
      aria-hidden="true"
      style={{
        position: 'fixed',
        left: -12000,
        top: 0,
        width: SPECIMEN_WIDTH_PX,
        pointerEvents: 'none',
        zIndex: -1,
      }}
    >
      <SpecimenBoundary>{children}</SpecimenBoundary>
    </div>
  )
}
