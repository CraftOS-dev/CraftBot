import {
  Activity,
  Bot,
  BarChart3,
  Cpu,
  Globe,
  Hammer,
  History,
  Layers,
  Package,
  TrendingUp,
} from 'lucide-react'
import type { WidgetDefinition } from './types'
import { TaskStatsWidget, TaskStatsHeaderBadge } from './TaskStatsWidget'
import { TokenUsageWidget, TokenUsageHeaderBadge } from './TokenUsageWidget'
import { SystemResourcesWidget } from './SystemResourcesWidget'
import { UsagePatternsWidget, UsagePatternsHeaderBadge } from './UsagePatternsWidget'
import { McpServersWidget } from './McpServersWidget'
import { SkillsWidget } from './SkillsWidget'
import { IntegrationsWidget } from './IntegrationsWidget'
import { ModelInfoWidget } from './ModelInfoWidget'
import { MascotWidget } from './MascotWidget'
import { AgentStatusWidget } from './AgentStatusWidget'
import { LivingUIWidget } from './LivingUIWidget'
import { RecentActivityWidget } from './RecentActivityWidget'

// One entry per widget type. Phase 2 widgets (Agent Status, Living UI,
// Recent Activity, Logs, ...) are added here later — no other file in
// `layout/` needs to change to support a new widget.
//
// Every widget shares the same resize floor — `minW: 3, minH: 5` — so the grid
// has one consistent smallest tile rather than a different one per widget. Keep
// it that way when adding widgets: make the content fit 3x5 (see the density
// rules in widgets.module.css) instead of raising the minimum for one widget.
// `w`/`h` are just starting sizes and are free to vary.
//
// These minima are authoritative at runtime, not only at seed time — layout/
// normalizeLayouts.ts re-applies them to stored layouts on every read, so
// editing them here does reach people who already have a saved dashboard.
export const WIDGET_REGISTRY: Record<string, WidgetDefinition> = {
  taskStats: {
    id: 'taskStats',
    title: 'Task Statistics',
    icon: Activity,
    description: 'Completed, failed, running tasks and success rate.',
    component: TaskStatsWidget,
    headerBadge: TaskStatsHeaderBadge,
    defaultLayout: { w: 4, h: 8, minW: 3, minH: 5 },
    singleton: true,
  },
  tokenUsage: {
    id: 'tokenUsage',
    title: 'Token Usage',
    icon: TrendingUp,
    description: 'Input/output/cached token totals and ratios.',
    component: TokenUsageWidget,
    headerBadge: TokenUsageHeaderBadge,
    defaultLayout: { w: 4, h: 8, minW: 3, minH: 5 },
    singleton: true,
  },
  systemResources: {
    id: 'systemResources',
    title: 'System Resources',
    icon: Cpu,
    description: 'CPU, memory, disk, thread pool and network I/O.',
    component: SystemResourcesWidget,
    defaultLayout: { w: 6, h: 6, minW: 3, minH: 5 },
    singleton: true,
  },
  usagePatterns: {
    id: 'usagePatterns',
    title: 'Usage Patterns',
    icon: BarChart3,
    description: 'Hourly request distribution and peak usage.',
    component: UsagePatternsWidget,
    headerBadge: UsagePatternsHeaderBadge,
    defaultLayout: { w: 6, h: 9, minW: 3, minH: 5 },
    singleton: true,
  },
  mcpServers: {
    id: 'mcpServers',
    title: 'MCP Servers',
    icon: Hammer,
    description: 'Connected servers, call volume, top tools.',
    component: McpServersWidget,
    defaultLayout: { w: 4, h: 7, minW: 3, minH: 5 },
    singleton: true,
  },
  skills: {
    id: 'skills',
    title: 'Skills',
    icon: Package,
    description: 'Enabled skills, invocation counts, top skills.',
    component: SkillsWidget,
    defaultLayout: { w: 4, h: 7, minW: 3, minH: 5 },
    singleton: true,
  },
  integrations: {
    id: 'integrations',
    title: 'Integrations',
    icon: Globe,
    description: 'Connected integrations and call volume.',
    component: IntegrationsWidget,
    defaultLayout: { w: 4, h: 7, minW: 3, minH: 5 },
    singleton: true,
  },
  modelInfo: {
    id: 'modelInfo',
    title: 'Model Information',
    icon: Bot,
    description: 'Active provider, model name and model ID.',
    component: ModelInfoWidget,
    defaultLayout: { w: 4, h: 6, minW: 3, minH: 5 },
    singleton: true,
  },
  mascot: {
    id: 'mascot',
    title: 'Mascot',
    icon: Bot,
    description: 'The CraftBot mascot — reacts to agent activity.',
    component: MascotWidget,
    defaultLayout: { w: 4, h: 8, minW: 3, minH: 5 },
    singleton: true,
  },
  agentStatus: {
    id: 'agentStatus',
    title: 'Agent Status',
    icon: Activity,
    description: 'Live status, uptime, currently running tasks, last error.',
    component: AgentStatusWidget,
    defaultLayout: { w: 4, h: 8, minW: 3, minH: 5 },
    singleton: true,
  },
  livingUi: {
    id: 'livingUi',
    title: 'Living UI',
    icon: Layers,
    description: 'Installed and running Living UIs.',
    component: LivingUIWidget,
    defaultLayout: { w: 4, h: 7, minW: 3, minH: 5 },
    singleton: true,
  },
  recentActivity: {
    id: 'recentActivity',
    title: 'Recent Activity',
    icon: History,
    description: 'Most recent actions across all sessions, with timing and tokens.',
    component: RecentActivityWidget,
    defaultLayout: { w: 6, h: 10, minW: 3, minH: 5 },
    singleton: true,
  },
}

export const WIDGET_IDS = Object.keys(WIDGET_REGISTRY)
