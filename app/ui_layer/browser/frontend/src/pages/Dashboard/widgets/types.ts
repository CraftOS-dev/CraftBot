import type { ComponentType } from 'react'
import type { LucideIcon } from 'lucide-react'

/**
 * Starting size only, in grid cells. There are no per-widget minimums or
 * maximums: every widget shares one square floor and ceiling, which lives in
 * `layout/constants.ts` as SIZE_BOUNDS.
 */
export interface WidgetDefaultLayout {
  w: number
  h: number
}

export interface WidgetDefinition {
  id: string
  title: string
  icon: LucideIcon
  description?: string
  component: ComponentType
  /** Optional small badge rendered in the title bar (e.g. a live count). */
  headerBadge?: ComponentType
  defaultLayout: WidgetDefaultLayout
  /** Phase 1: every widget is a singleton — at most one instance per layout. */
  singleton?: boolean
}
