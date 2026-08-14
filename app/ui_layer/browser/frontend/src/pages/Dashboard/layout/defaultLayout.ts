import type { Layout } from 'react-grid-layout'
import { boundsFor, seedItem } from './normalizeLayouts'
import type { Breakpoint, BreakpointLayouts, NamedLayout } from './types'
import { WIDGET_REGISTRY } from '../widgets/registry'

/**
 * The seed/default arrangement — and what "Reset layout" restores.
 *
 * A hero composition: the CraftBot intro widget sits 2x2 at the top-left, with
 * the stat cards (Token Usage / System Resources / Usage Patterns over Task
 * Statistics / Skills / Model Information) filling the columns beside it, and
 * a bottom row of MCP Servers, Integrations, and Living UI next to a 2-wide
 * Mascot scene. Narrower breakpoints keep the hero on top and reflow the 1x1
 * cards in pairs.
 *
 * Recent Activity deliberately isn't here: it's hidden by default and only
 * appears when added via the Add Widget modal.
 *
 * Explicit coordinates, not shelf packing: packing by each widget's default
 * size leaves holes wherever row heights disagree (a taller neighbor blocks
 * vertical compaction under a shorter one), which is exactly the scattered
 * layout that made "reset" look like a no-op.
 */
type Placement = { id: string; x: number; y: number; w: number; h: number }

const DEFAULT_PLACEMENT: Record<Breakpoint, Placement[]> = {
  lg: [
    { id: 'craftBotIntro', x: 0, y: 0, w: 2, h: 2 },
    { id: 'tokenUsage', x: 2, y: 0, w: 1, h: 1 },
    { id: 'systemResources', x: 3, y: 0, w: 1, h: 1 },
    { id: 'usagePatterns', x: 4, y: 0, w: 1, h: 1 },
    { id: 'taskStats', x: 2, y: 1, w: 1, h: 1 },
    { id: 'skills', x: 3, y: 1, w: 1, h: 1 },
    { id: 'modelInfo', x: 4, y: 1, w: 1, h: 1 },
    { id: 'mcpServers', x: 0, y: 2, w: 1, h: 1 },
    { id: 'integrations', x: 1, y: 2, w: 1, h: 1 },
    { id: 'livingUi', x: 2, y: 2, w: 1, h: 1 },
    { id: 'mascot', x: 3, y: 2, w: 2, h: 1 },
  ],
  md: [
    { id: 'craftBotIntro', x: 0, y: 0, w: 2, h: 2 },
    { id: 'tokenUsage', x: 2, y: 0, w: 1, h: 1 },
    { id: 'systemResources', x: 3, y: 0, w: 1, h: 1 },
    { id: 'taskStats', x: 2, y: 1, w: 1, h: 1 },
    { id: 'skills', x: 3, y: 1, w: 1, h: 1 },
    { id: 'usagePatterns', x: 0, y: 2, w: 1, h: 1 },
    { id: 'modelInfo', x: 1, y: 2, w: 1, h: 1 },
    { id: 'mcpServers', x: 2, y: 2, w: 1, h: 1 },
    { id: 'integrations', x: 3, y: 2, w: 1, h: 1 },
    { id: 'livingUi', x: 0, y: 3, w: 1, h: 1 },
    { id: 'mascot', x: 1, y: 3, w: 2, h: 1 },
  ],
  sm: [
    { id: 'craftBotIntro', x: 0, y: 0, w: 2, h: 2 },
    { id: 'tokenUsage', x: 0, y: 2, w: 1, h: 1 },
    { id: 'systemResources', x: 1, y: 2, w: 1, h: 1 },
    { id: 'taskStats', x: 0, y: 3, w: 1, h: 1 },
    { id: 'skills', x: 1, y: 3, w: 1, h: 1 },
    { id: 'usagePatterns', x: 0, y: 4, w: 1, h: 1 },
    { id: 'modelInfo', x: 1, y: 4, w: 1, h: 1 },
    { id: 'mcpServers', x: 0, y: 5, w: 1, h: 1 },
    { id: 'integrations', x: 1, y: 5, w: 1, h: 1 },
    { id: 'livingUi', x: 0, y: 6, w: 2, h: 1 },
    { id: 'mascot', x: 0, y: 7, w: 2, h: 1 },
  ],
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

// DEFAULT_PLACEMENT is a hand-maintained second copy of the registry's widget
// ids, so a widget renamed or removed from the registry without updating it
// would otherwise throw here — during a useState initializer, i.e. mid-render —
// and white-screen the whole page. Degrade to the widgets that do exist
// instead, matching the guard DashboardGrid already applies to stored layouts.
const DEFAULT_WIDGET_IDS = () =>
  DEFAULT_PLACEMENT.lg.map(p => p.id).filter(id => WIDGET_REGISTRY[id])

function buildBreakpointLayout(bp: Breakpoint): Layout[] {
  const items: Layout[] = []
  const seen = new Set<string>()

  for (const p of DEFAULT_PLACEMENT[bp]) {
    if (!WIDGET_REGISTRY[p.id]) continue
    const bounds = boundsFor(bp, p.id)
    seen.add(p.id)
    items.push({
      i: p.id,
      x: p.x,
      y: p.y,
      w: clamp(p.w, bounds.minW, bounds.maxW),
      h: clamp(p.h, bounds.minH, bounds.maxH),
      ...bounds,
    })
  }

  // A widget placed on lg but forgotten on this breakpoint would get RGL's
  // 1x1 fallback — below every widget's minimum. Seed it at the bottom
  // instead, same as normalizeLayouts does for stored layouts.
  for (const id of DEFAULT_WIDGET_IDS()) {
    if (seen.has(id)) continue
    items.push(seedItem(id, boundsFor(bp, id)))
  }

  return items
}

export function buildDefaultLayouts(): BreakpointLayouts {
  return {
    lg: buildBreakpointLayout('lg'),
    md: buildBreakpointLayout('md'),
    sm: buildBreakpointLayout('sm'),
  }
}

export function createDefaultLayout(now: number = Date.now()): NamedLayout {
  return {
    id: 'default',
    name: 'Default',
    widgetIds: DEFAULT_WIDGET_IDS(),
    layouts: buildDefaultLayouts(),
    createdAt: now,
    updatedAt: now,
  }
}
