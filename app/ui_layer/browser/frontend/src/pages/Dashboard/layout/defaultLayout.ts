import type { Layout } from 'react-grid-layout'
import { boundsFor, seedItem } from './normalizeLayouts'
import type { Breakpoint, BreakpointLayouts, NamedLayout } from './types'
import { WIDGET_REGISTRY } from '../widgets/registry'

/**
 * The seed/default arrangement — and what "Reset layout" restores.
 *
 * This is the ORIGINAL pre-revamp dashboard (the monolithic DashboardPage this
 * branch replaced): eight equal-sized panels flowing five per row, in its
 * exact source order — Task Statistics, Token Usage, System Resources, Usage
 * Patterns, MCP Servers, Skills, Integrations, Model Information. One grid
 * cell IS one of those panels (see WIDGET_MIN_CELLS), so every widget seeds at
 * 1x1 and the lg row holds exactly the original five; narrower breakpoints
 * reflow to fewer per row, same as the old CSS grid did.
 *
 * The widgets this revamp introduced (Mascot, Recent Activity, Living UI)
 * weren't part of that dashboard, so they trail after the original eight in
 * the flow instead of being woven into it.
 *
 * Explicit coordinates, not shelf packing: packing by each widget's default
 * size leaves holes wherever row heights disagree (a taller neighbor blocks
 * vertical compaction under a shorter one), which is exactly the scattered
 * layout that made "reset" look like a no-op.
 */
type Placement = { id: string; x: number; y: number; w: number; h: number }

const ORIGINAL_ORDER = [
  'taskStats',
  'tokenUsage',
  'systemResources',
  'usagePatterns',
  'mcpServers',
  'skills',
  'integrations',
  'modelInfo',
]

// Recent Activity deliberately isn't here: it's hidden by default and only
// appears when added via the Add Widget modal. Living UI takes the slot it
// used to occupy.
const REVAMP_EXTRAS = ['mascot', 'livingUi']

// Uniform 1x1 cards flowed left-to-right, one per column — the same reflow
// the old dashboard's repeat(5, 1fr) / 4 / 2 container queries produced.
function flow(ids: string[], perRow: number): Placement[] {
  return ids.map((id, i) => ({
    id,
    x: i % perRow,
    y: Math.floor(i / perRow),
    w: 1,
    h: 1,
  }))
}

const ALL_IDS = [...ORIGINAL_ORDER, ...REVAMP_EXTRAS]

const DEFAULT_PLACEMENT: Record<Breakpoint, Placement[]> = {
  lg: flow(ALL_IDS, 5), // 5 per row, the original full-width look
  md: flow(ALL_IDS, 4),
  sm: flow(ALL_IDS, 2),
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
