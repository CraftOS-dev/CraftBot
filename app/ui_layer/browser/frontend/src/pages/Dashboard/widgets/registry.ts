// Widget icons mirror the Settings page's category icons (Settings/types.ts)
// where a matching category exists — Cpu for Model, Plug for MCPs, Package
// for Skills, Globe for Integrations, Box for Living UI — and every icon is
// used by exactly one widget, so no two headers ever read as the same thing.
import {
  Activity,
  Bot,
  BarChart3,
  Box,
  Cpu,
  Gauge,
  Globe,
  History,
  Package,
  Plug,
  TrendingUp,
} from 'lucide-react'
import type { WidgetDefinition } from './types'
import { TaskStatsWidget, TaskStatsHeaderBadge } from './TaskStatsWidget'
import { TokenUsageWidget, TokenUsageHeaderBadge } from './TokenUsageWidget'
import { SystemResourcesWidget } from './SystemResourcesWidget'
import { UsagePatternsWidget } from './UsagePatternsWidget'
import { McpServersWidget } from './McpServersWidget'
import { SkillsWidget } from './SkillsWidget'
import { IntegrationsWidget } from './IntegrationsWidget'
import { ModelInfoWidget } from './ModelInfoWidget'
import { MascotWidget } from './MascotWidget'
import { LivingUIWidget } from './LivingUIWidget'
import { RecentActivityWidget } from './RecentActivityWidget'

// One entry per widget type. Adding or removing a widget is this file plus
// (if it should ship pre-placed) DEFAULT_ORDER in layout/defaultLayout.ts —
// no other file in `layout/` needs to change. A widget dropped from here also
// disappears from anyone's stored layout: normalizeLayouts discards grid items
// whose id the registry no longer knows.
//
// `sizing` is in cards: 1 = one original dashboard panel (the shared minimum
// tile — see WIDGET_MIN_CELLS in layout/constants.ts), so `{ w: 2, h: 1 }` is
// two cards wide and one tall. The floor is shared and square; the ceiling is
// per-widget and need not be, because a widget with two stat tiles and three
// list rows goes empty long before one with a chart does. `max.h: 1` is
// deliberate where it appears — that widget resizes width-only.
//
// Both bounds are authoritative at runtime, not only at seed time — layout/
// normalizeLayouts.ts re-applies them to stored layouts on every read, so
// editing them does reach people who already have a saved dashboard, with no
// migration to write.
export const WIDGET_REGISTRY: Record<string, WidgetDefinition> = {
  taskStats: {
    id: 'taskStats',
    title: 'Task Statistics',
    icon: Activity,
    description: 'Completed, failed, running tasks and success rate.',
    component: TaskStatsWidget,
    headerBadge: TaskStatsHeaderBadge,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 1 } },
    singleton: true,
  },
  tokenUsage: {
    id: 'tokenUsage',
    title: 'Token Usage',
    icon: TrendingUp,
    description: 'Input/output/cached token totals and ratios.',
    component: TokenUsageWidget,
    headerBadge: TokenUsageHeaderBadge,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 1 } },
    singleton: true,
  },
  systemResources: {
    id: 'systemResources',
    title: 'System Resources',
    icon: Gauge,
    description: 'CPU, memory, disk, thread pool and network I/O.',
    component: SystemResourcesWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 1 } },
    singleton: true,
  },
  usagePatterns: {
    id: 'usagePatterns',
    title: 'Usage Patterns',
    icon: BarChart3,
    description: 'Hourly request distribution and peak usage.',
    component: UsagePatternsWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 2 } },
    singleton: true,
  },
  mcpServers: {
    id: 'mcpServers',
    title: 'MCP Servers',
    icon: Plug,
    description: 'Connected servers, call volume, top tools.',
    component: McpServersWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 2 } },
    singleton: true,
  },
  skills: {
    id: 'skills',
    title: 'Skills',
    icon: Package,
    description: 'Enabled skills, invocation counts, top skills.',
    component: SkillsWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 2 } },
    singleton: true,
  },
  integrations: {
    id: 'integrations',
    title: 'Integrations',
    icon: Globe,
    description: 'Connected integrations and call volume.',
    component: IntegrationsWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 2 } },
    singleton: true,
  },
  modelInfo: {
    id: 'modelInfo',
    title: 'Model Information',
    icon: Cpu,
    description: 'Active provider, model name and model ID.',
    component: ModelInfoWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 1 } },
    singleton: true,
  },
  mascot: {
    id: 'mascot',
    title: 'Mascot',
    icon: Bot,
    description: 'The CraftBot mascot — reacts to agent activity.',
    component: MascotWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 3, h: 2 } },
    // The mascot draws its own scene edge to edge; the shared body padding
    // would show as a band of card background around it.
    bleed: true,
    singleton: true,
  },
  livingUi: {
    id: 'livingUi',
    title: 'Living UI',
    icon: Box,
    description: 'Installed and running Living UIs.',
    component: LivingUIWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 2 } },
    singleton: true,
  },
  recentActivity: {
    id: 'recentActivity',
    title: 'Recent Activity',
    icon: History,
    description: 'Most recent actions across all sessions, with timing and tokens.',
    component: RecentActivityWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 2 } },
    singleton: true,
  },
}

export const WIDGET_IDS = Object.keys(WIDGET_REGISTRY)
