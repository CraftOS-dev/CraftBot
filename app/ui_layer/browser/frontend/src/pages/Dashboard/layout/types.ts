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
  version: 1
  layouts: NamedLayout[]
}
