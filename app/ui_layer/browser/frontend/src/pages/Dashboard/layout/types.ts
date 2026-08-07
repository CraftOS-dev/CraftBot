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
   * Storage schema version (see STORAGE_VERSION in constants.ts). Anything
   * stored under a different version is discarded on read and the dashboard
   * reseeds — there is no migration. Constraint drift is not a version bump;
   * normalizeLayouts re-applies bounds on every read instead.
   */
  version: number
  layouts: NamedLayout[]
}
