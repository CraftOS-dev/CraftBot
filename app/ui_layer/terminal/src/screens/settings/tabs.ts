/**
 * The settings tabs, in the browser's order. Each tab is its own module
 * under ./tabs and gets its focus, size and key routing from tabContext.
 */
import type { ComponentType } from 'react'
import { GeneralTab } from './tabs/GeneralTab'
import { ProactiveTab } from './tabs/ProactiveTab'
import { MemoryTab } from './tabs/MemoryTab'
import { ModelTab } from './tabs/ModelTab'
import { McpTab } from './tabs/McpTab'
import { SkillsTab } from './tabs/SkillsTab'
import { IntegrationsTab } from './tabs/IntegrationsTab'
import { CredentialsTab } from './tabs/CredentialsTab'
import { AgentAppsTab } from './tabs/AgentAppsTab'

export type SettingsTabId =
  | 'general'
  | 'proactive'
  | 'memory'
  | 'model'
  | 'mcp'
  | 'skills'
  | 'integrations'
  | 'credentials'
  | 'agentApps'

export interface SettingsTab {
  id: SettingsTabId
  /** i18n key in the tui namespace. */
  label: string
  component: ComponentType
}

export const SETTINGS_TABS: SettingsTab[] = [
  { id: 'general', label: 'settings.tabs.general', component: GeneralTab },
  { id: 'proactive', label: 'settings.tabs.proactive', component: ProactiveTab },
  { id: 'memory', label: 'settings.tabs.memory', component: MemoryTab },
  { id: 'model', label: 'settings.tabs.model', component: ModelTab },
  { id: 'mcp', label: 'settings.tabs.mcp', component: McpTab },
  { id: 'skills', label: 'settings.tabs.skills', component: SkillsTab },
  { id: 'integrations', label: 'settings.tabs.integrations', component: IntegrationsTab },
  { id: 'credentials', label: 'settings.tabs.credentials', component: CredentialsTab },
  { id: 'agentApps', label: 'settings.tabs.agentApps', component: AgentAppsTab },
]
