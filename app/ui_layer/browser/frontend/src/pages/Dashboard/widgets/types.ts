import type { ComponentType } from 'react'
import type { LucideIcon } from 'lucide-react'

/**
 * A widget's starting size and its resize ceiling, both in *minimum units*:
 * 1 = the shared minimum tile (WIDGET_MIN_CELLS grid cells square), so
 * `{ w: 1.5, h: 1 }` is 3 cells by 2. Fractions are fine as long as they land
 * on a whole cell — `unitsToCells` rounds.
 *
 * There is no per-widget minimum: every widget shares the square floor in
 * layout/constants.ts. Maximums do not have to be square, and a widget whose
 * `max.h` equals 1 simply can't be resized vertically.
 */
export interface WidgetSizing {
  default: { w: number; h: number }
  max: { w: number; h: number }
}

export interface WidgetDefinition {
  id: string
  /** i18n key for the widget's title (e.g. 'dashboard:registry.tokenUsage.title'). */
  titleKey: string
  icon: LucideIcon
  /** i18n key for the Add-Widget picker description (e.g. 'dashboard:registry.tokenUsage.description'). */
  descriptionKey?: string
  component: ComponentType
  /** Optional small badge rendered in the title bar (e.g. a live count). */
  headerBadge?: ComponentType
  sizing: WidgetSizing
  /**
   * Drop the widget body's padding so the content reaches the card's interior
   * edges. For widgets that draw their own full-bleed surface (the Mascot's
   * scene) rather than laying out on the shared background.
   */
  bleed?: boolean
  /** Phase 1: every widget is a singleton — at most one instance per layout. */
  singleton?: boolean
}
