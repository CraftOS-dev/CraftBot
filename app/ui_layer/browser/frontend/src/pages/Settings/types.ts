import React from 'react'
import {
  Settings,
  Brain,
  Database,
  Cpu,
  Plug,
  Package,
  Globe,
  Box,
} from 'lucide-react'

export type SettingsCategory =
  | 'general'
  | 'proactive'
  | 'memory'
  | 'model'
  | 'mcps'
  | 'skills'
  | 'integrations'
  | 'living_ui'

export interface SettingsCategoryItem {
  id: SettingsCategory
  label: string
  icon: React.ReactNode
}

// --- Multi-account integrations (Manage modal) ------------

// One account row in a multi-account integration's ``integration_info``
// payload (and in the accounts-mutation result broadcasts).
export interface ManagedAccount {
  identity: string
  alias: string | null
  isPrimary: boolean
  listen: boolean
}

// Locally staged (uncommitted) edits for one integration's accounts.
// Keyed by integration id in component state; committed as a single
// ``integration_apply_account_changes`` request on "Save changes".
export interface StagedAccountEdits {
  // Identities marked for disconnect on save.
  disconnect: string[]
  // Staged new primary identity; null = keep the real primary.
  primary: string | null
  // Staged alias overrides, keyed by identity (null clears the alias).
  aliases: Record<string, string | null>
  // Staged listen-flag overrides, keyed by identity.
  listen: Record<string, boolean>
}

// ``changes`` payload of an ``integration_apply_account_changes`` request.
export interface AccountChanges {
  disconnect: string[]
  primary: string | null
  aliases: Record<string, string | null>
  listen: Record<string, boolean>
}

// Result broadcast for ``integration_accounts_add``. Broadcast to every
// connected client — correlate by requestId before treating as your own.
export interface IntegrationAccountsAddResult {
  id: string
  requestId: string
  ok: boolean
  message?: string
  accounts?: ManagedAccount[]
}

// Result broadcast for ``integration_apply_account_changes``.
export interface IntegrationApplyAccountChangesResult {
  id: string
  requestId: string
  ok: boolean
  accounts?: ManagedAccount[]
  error?: string
}

export const categories: SettingsCategoryItem[] = [
  {
    id: 'general',
    label: 'General',
    icon: React.createElement(Settings, { size: 18 }),
  },
  {
    id: 'proactive',
    label: 'Proactive',
    icon: React.createElement(Brain, { size: 18 }),
  },
  {
    id: 'memory',
    label: 'Memory',
    icon: React.createElement(Database, { size: 18 }),
  },
  {
    id: 'model',
    label: 'Model',
    icon: React.createElement(Cpu, { size: 18 }),
  },
  {
    id: 'mcps',
    label: 'MCPs',
    icon: React.createElement(Plug, { size: 18 }),
  },
  {
    id: 'skills',
    label: 'Skills',
    icon: React.createElement(Package, { size: 18 }),
  },
  {
    id: 'integrations',
    label: 'Integrations',
    icon: React.createElement(Globe, { size: 18 }),
  },
  {
    id: 'living_ui',
    label: 'Living UI',
    icon: React.createElement(Box, { size: 18 }),
  },
]
