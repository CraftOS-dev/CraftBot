import type { ComponentType } from 'react'
import type { LucideIcon } from 'lucide-react'

export interface WidgetDefaultLayout {
  w: number
  h: number
  minW?: number
  minH?: number
}

export interface WidgetDefinition {
  id: string
  title: string
  icon: LucideIcon
  description?: string
  component: ComponentType
  defaultLayout: WidgetDefaultLayout
  /** Phase 1: every widget is a singleton — at most one instance per layout. */
  singleton?: boolean
}
