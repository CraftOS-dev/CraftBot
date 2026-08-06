import type { Layout } from 'react-grid-layout'
import { COLS } from './constants'
import { boundsFor, seedItem } from './normalizeLayouts'
import type { Breakpoint, BreakpointLayouts, NamedLayout } from './types'
import { WIDGET_REGISTRY } from '../widgets/registry'

// Visual order for the seed/default layout — roughly mirrors the original
// monolithic dashboard's panel order. Agent Status leads (replacing the
// old page header's prominence); Mascot and the Phase 2 widgets (Recent
// Activity, Living UI) are woven in alongside their closest thematic
// neighbors.
const DEFAULT_ORDER = [
  'agentStatus',
  'taskStats',
  'tokenUsage',
  'mascot',
  'recentActivity',
  'systemResources',
  'usagePatterns',
  'mcpServers',
  'skills',
  'integrations',
  'livingUi',
  'modelInfo',
]

// DEFAULT_ORDER is a hand-maintained second copy of the registry's widget ids,
// so a widget renamed or removed from the registry without updating it would
// otherwise throw here — during a useState initializer, i.e. mid-render — and
// white-screen the whole page. Degrade to the widgets that do exist instead,
// matching the guard DashboardGrid already applies to stored layouts.
const KNOWN_ORDER = () => DEFAULT_ORDER.filter(id => WIDGET_REGISTRY[id])

// Simple left-to-right shelf packing over each widget's registry starting size,
// clamped into the breakpoint's square bounds by `seedItem`.
// `compactType="vertical"` on the grid self-corrects any minor gaps on first
// render, so this only needs to produce a reasonable, non-overlapping
// starting arrangement.
function buildBreakpointLayout(bp: Breakpoint): Layout[] {
  const cols = COLS[bp]
  let x = 0
  let rowY = 0
  let rowHeight = 0
  const items: Layout[] = []

  for (const id of KNOWN_ORDER()) {
    const item = seedItem(id, boundsFor(bp, id))
    if (x + item.w > cols) {
      x = 0
      rowY += rowHeight
      rowHeight = 0
    }
    items.push({ ...item, x, y: rowY })
    x += item.w
    rowHeight = Math.max(rowHeight, item.h)
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
    widgetIds: KNOWN_ORDER(),
    layouts: buildDefaultLayouts(),
    createdAt: now,
    updatedAt: now,
  }
}
