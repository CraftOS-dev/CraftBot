// Widget icons mirror the Settings page's category icons (Settings/types.ts)
// where a matching category exists — Cpu for Model, Plug for MCPs, Package
// for Skills, Globe for Integrations, Box for Agent App — and every icon is
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
  Sparkles,
  TrendingUp,
} from 'lucide-react'
import type { WidgetDefinition } from './types'
import { CraftBotIntroWidget } from './CraftBotIntroWidget'
import { TaskStatsWidget, TaskStatsHeaderBadge } from './TaskStatsWidget'
import { TokenUsageWidget, TokenUsageHeaderBadge } from './TokenUsageWidget'
import { SystemResourcesWidget } from './SystemResourcesWidget'
import { UsagePatternsWidget } from './UsagePatternsWidget'
import { McpServersWidget } from './McpServersWidget'
import { SkillsWidget } from './SkillsWidget'
import { IntegrationsWidget } from './IntegrationsWidget'
import { ModelInfoWidget } from './ModelInfoWidget'
import { MascotWidget } from './MascotWidget'
import { AgentAppWidget } from './AgentAppWidget'
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
  craftBotIntro: {
    id: 'craftBotIntro',
    titleKey: 'dashboard:registry.craftBotIntro.title',
    icon: Sparkles,
    descriptionKey: 'dashboard:registry.craftBotIntro.description',
    component: CraftBotIntroWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 2 } },
    singleton: true,
  },
  taskStats: {
    id: 'taskStats',
    titleKey: 'dashboard:registry.taskStats.title',
    icon: Activity,
    descriptionKey: 'dashboard:registry.taskStats.description',
    component: TaskStatsWidget,
    headerBadge: TaskStatsHeaderBadge,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 1 } },
    singleton: true,
  },
  tokenUsage: {
    id: 'tokenUsage',
    titleKey: 'dashboard:registry.tokenUsage.title',
    icon: TrendingUp,
    descriptionKey: 'dashboard:registry.tokenUsage.description',
    component: TokenUsageWidget,
    headerBadge: TokenUsageHeaderBadge,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 1 } },
    singleton: true,
  },
  systemResources: {
    id: 'systemResources',
    titleKey: 'dashboard:registry.systemResources.title',
    icon: Gauge,
    descriptionKey: 'dashboard:registry.systemResources.description',
    component: SystemResourcesWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 1 } },
    singleton: true,
  },
  usagePatterns: {
    id: 'usagePatterns',
    titleKey: 'dashboard:registry.usagePatterns.title',
    icon: BarChart3,
    descriptionKey: 'dashboard:registry.usagePatterns.description',
    component: UsagePatternsWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 2 } },
    singleton: true,
  },
  mcpServers: {
    id: 'mcpServers',
    titleKey: 'dashboard:registry.mcpServers.title',
    icon: Plug,
    descriptionKey: 'dashboard:registry.mcpServers.description',
    component: McpServersWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 2 } },
    singleton: true,
  },
  skills: {
    id: 'skills',
    titleKey: 'dashboard:registry.skills.title',
    icon: Package,
    descriptionKey: 'dashboard:registry.skills.description',
    component: SkillsWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 2 } },
    singleton: true,
  },
  integrations: {
    id: 'integrations',
    titleKey: 'dashboard:registry.integrations.title',
    icon: Globe,
    descriptionKey: 'dashboard:registry.integrations.description',
    component: IntegrationsWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 2 } },
    singleton: true,
  },
  modelInfo: {
    id: 'modelInfo',
    titleKey: 'dashboard:registry.modelInfo.title',
    icon: Cpu,
    descriptionKey: 'dashboard:registry.modelInfo.description',
    component: ModelInfoWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 1 } },
    singleton: true,
  },
  mascot: {
    id: 'mascot',
    titleKey: 'dashboard:registry.mascot.title',
    icon: Bot,
    descriptionKey: 'dashboard:registry.mascot.description',
    component: MascotWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 3, h: 2 } },
    // The mascot draws its own scene edge to edge; the shared body padding
    // would show as a band of card background around it.
    bleed: true,
    singleton: true,
  },
  agentApp: {
    id: 'agentApp',
    titleKey: 'dashboard:registry.agentApp.title',
    icon: Box,
    descriptionKey: 'dashboard:registry.agentApp.description',
    component: AgentAppWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 2 } },
    singleton: true,
  },
  recentActivity: {
    id: 'recentActivity',
    titleKey: 'dashboard:registry.recentActivity.title',
    icon: History,
    descriptionKey: 'dashboard:registry.recentActivity.description',
    component: RecentActivityWidget,
    sizing: { default: { w: 1, h: 1 }, max: { w: 2, h: 2 } },
    singleton: true,
  },
}

export const WIDGET_IDS = Object.keys(WIDGET_REGISTRY)
