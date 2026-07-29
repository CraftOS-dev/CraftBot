import {
  Activity,
  Bot,
  BarChart3,
  Cpu,
  Globe,
  Hammer,
  Package,
  TrendingUp,
} from 'lucide-react'
import type { WidgetDefinition } from './types'
import { TaskStatsWidget } from './TaskStatsWidget'
import { TokenUsageWidget } from './TokenUsageWidget'
import { SystemResourcesWidget } from './SystemResourcesWidget'
import { UsagePatternsWidget } from './UsagePatternsWidget'
import { McpServersWidget } from './McpServersWidget'
import { SkillsWidget } from './SkillsWidget'
import { IntegrationsWidget } from './IntegrationsWidget'
import { ModelInfoWidget } from './ModelInfoWidget'
import { MascotWidget } from './MascotWidget'

// One entry per widget type. Phase 2 widgets (Agent Status, Living UI,
// Recent Activity, Logs, ...) are added here later — no other file in
// `layout/` needs to change to support a new widget.
export const WIDGET_REGISTRY: Record<string, WidgetDefinition> = {
  taskStats: {
    id: 'taskStats',
    title: 'Task Statistics',
    icon: Activity,
    description: 'Completed, failed, running tasks and success rate.',
    component: TaskStatsWidget,
    defaultLayout: { w: 4, h: 8, minW: 3, minH: 6 },
    singleton: true,
  },
  tokenUsage: {
    id: 'tokenUsage',
    title: 'Token Usage',
    icon: TrendingUp,
    description: 'Input/output/cached token totals and ratios.',
    component: TokenUsageWidget,
    defaultLayout: { w: 4, h: 8, minW: 3, minH: 6 },
    singleton: true,
  },
  systemResources: {
    id: 'systemResources',
    title: 'System Resources',
    icon: Cpu,
    description: 'CPU, memory, disk, thread pool and network I/O.',
    component: SystemResourcesWidget,
    defaultLayout: { w: 6, h: 9, minW: 4, minH: 7 },
    singleton: true,
  },
  usagePatterns: {
    id: 'usagePatterns',
    title: 'Usage Patterns',
    icon: BarChart3,
    description: 'Hourly request distribution and peak usage.',
    component: UsagePatternsWidget,
    defaultLayout: { w: 6, h: 9, minW: 4, minH: 7 },
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
    defaultLayout: { w: 4, h: 6, minW: 3, minH: 4 },
    singleton: true,
  },
  mascot: {
    id: 'mascot',
    title: 'Mascot',
    icon: Bot,
    description: 'The CraftBot mascot — reacts to agent activity.',
    component: MascotWidget,
    defaultLayout: { w: 4, h: 8, minW: 3, minH: 6 },
    singleton: true,
  },
}

export const WIDGET_IDS = Object.keys(WIDGET_REGISTRY)
