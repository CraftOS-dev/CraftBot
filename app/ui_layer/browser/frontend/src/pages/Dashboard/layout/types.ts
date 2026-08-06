import type { Layout } from 'react-grid-layout'

export type Breakpoint = 'lg' | 'md' | 'sm'

export type BreakpointLayouts = Record<Breakpoint, Layout[]>

export interface NamedLayout {
  id: string
  name: string
  /** Registry ids present on this layout. */
  widgetIds: string[]
  layouts: BreakpointLayouts
  createdAt: number
  updatedAt: number
}

export interface DashboardLayoutsStorage {
  /**
   * Storage *shape* version — bumped only when existing numbers change
   * meaning, which needs a real conversion (see migrateLayouts.ts). Constraint
   * drift is not a shape change; normalizeLayouts re-applies bounds on every
   * read instead.
   *
   * 1 → 2: 12 columns and fixed 32px rows became 10 columns and square cells.
   */
  version: number
  layouts: NamedLayout[]
}
