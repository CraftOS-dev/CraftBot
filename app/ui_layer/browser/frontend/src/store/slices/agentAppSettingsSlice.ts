import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'
import i18n from '../../i18n/config'

// Project shape used by the Settings > Agent App tab. Distinct from the
// project shape used by `agentAppSlice` (which drives the main /agent-app
// page) — this one carries the per-project preferences exposed in Settings.
export interface AgentAppBackupStatus {
  lastAt?: number | null
  lastError?: string | null
  count?: number
  totalSize?: number
}

export interface AgentAppBackupEntry {
  filename: string
  ts: number // ms epoch
  trigger: 'scheduled' | 'pre_promote' | 'manual' | 'pre_delete' | 'pre_restore'
  size: number
}

// A deleted project's leftover backup dir: opaque id + the app's human name
// (from the store's meta.json sidecar; falls back to the id).
export interface AgentAppBackupOrphan {
  id: string
  name: string
}

export interface AgentAppSettingsProject {
  id: string
  name: string
  status: string
  port: number | null
  backendPort: number | null
  path: string
  projectType?: string
  autoLaunch: boolean
  logCleanup: boolean
  backupsEnabled: boolean
  backupInterval: 'hourly' | '6h' | 'daily' | 'weekly'
  backupKeep: number
  backupStatus?: AgentAppBackupStatus
}

interface AgentAppSettingsState {
  // Per-project settings list from `agent_app_settings_get`.
  projects: AgentAppSettingsProject[]
  hasLoadedProjects: boolean
  // Backup dirs of deleted projects (kept on delete by default — D5).
  backupOrphans: AgentAppBackupOrphan[]
  // Per-project backup archive list from `agent_app_backups_list`.
  backupsByProject: Record<string, AgentAppBackupEntry[]>
  // Per-project in-flight marker for "Back up now" / restore buttons.
  backupBusy: Record<string, boolean>
  // Outcome of the last restore per target project — surfaced inline so the
  // user sees "restoring… / restored / failed" instead of silence.
  backupRestoreResult: Record<string, { ok: boolean; message: string } | undefined>
}

const initialState: AgentAppSettingsState = {
  projects: [],
  hasLoadedProjects: false,
  backupOrphans: [],
  backupsByProject: {},
  backupBusy: {},
  backupRestoreResult: {},
}

const agentAppSettingsSlice = createSlice({
  name: 'agentAppSettings',
  initialState,
  reducers: {
    setSettings(
      state,
      action: PayloadAction<{
        projects: AgentAppSettingsProject[]
        backupOrphans: AgentAppBackupOrphan[]
      }>,
    ) {
      state.projects = action.payload.projects
      state.backupOrphans = action.payload.backupOrphans
      state.hasLoadedProjects = true
    },
    // Optimistic per-project setting flip so the control doesn't lag on the
    // round-trip back from the backend.
    updateProjectSetting(
      state,
      action: PayloadAction<{
        projectId: string
        setting:
          | 'autoLaunch'
          | 'logCleanup'
          | 'backupsEnabled'
          | 'backupInterval'
          | 'backupKeep'
        value: boolean | string | number
      }>,
    ) {
      const p = state.projects.find(x => x.id === action.payload.projectId)
      if (p) (p as any)[action.payload.setting] = action.payload.value
    },
    setProjectBackups(
      state,
      action: PayloadAction<{ projectId: string; backups: AgentAppBackupEntry[] }>,
    ) {
      state.backupsByProject[action.payload.projectId] = action.payload.backups
    },
    setBackupBusy(
      state,
      action: PayloadAction<{ projectId: string; busy: boolean }>,
    ) {
      state.backupBusy[action.payload.projectId] = action.payload.busy
      // A new operation clears the previous outcome message.
      if (action.payload.busy)
        state.backupRestoreResult[action.payload.projectId] = undefined
    },
    setBackupRestoreResult(
      state,
      action: PayloadAction<{
        projectId: string
        result: { ok: boolean; message: string }
      }>,
    ) {
      state.backupRestoreResult[action.payload.projectId] = action.payload.result
    },
  },
})

export const {
  setSettings,
  updateProjectSetting,
  setProjectBackups,
  setBackupBusy,
  setBackupRestoreResult,
} = agentAppSettingsSlice.actions

export default agentAppSettingsSlice.reducer

// --- inbound message handlers --------------------------------------------

register('agent_app_settings_get', (data, dispatch) => {
  const d = data as {
    success: boolean
    projects?: AgentAppSettingsProject[]
    backupOrphans?: AgentAppBackupOrphan[]
  }
  if (d.success)
    dispatch(
      setSettings({
        projects: d.projects || [],
        backupOrphans: d.backupOrphans || [],
      }),
    )
})

register('agent_app_backups_list', (data, dispatch) => {
  const d = data as { projectId?: string; backups?: AgentAppBackupEntry[] }
  if (d.projectId)
    dispatch(
      setProjectBackups({ projectId: d.projectId, backups: d.backups || [] }),
    )
})

// backup_now / restore results clear the busy flag; the archive list and
// settings status line arrive via the follow-up broadcasts the backend
// already sends (agent_app_backups_list; the card refetches settings).
register('agent_app_backup_now_result', (data, dispatch) => {
  const d = data as { projectId?: string }
  if (d.projectId)
    dispatch(setBackupBusy({ projectId: d.projectId, busy: false }))
})

register('agent_app_backup_restore_result', (data, dispatch) => {
  const d = data as {
    projectId?: string
    status?: string
    restored?: string
    errors?: string[]
  }
  if (d.projectId) {
    dispatch(setBackupBusy({ projectId: d.projectId, busy: false }))
    dispatch(
      setBackupRestoreResult({
        projectId: d.projectId,
        result:
          d.status === 'success'
            ? { ok: true, message: i18n.t('nav:slices.agentAppSettings.backupRestored') }
            : { ok: false, message: d.errors?.[0] || i18n.t('nav:slices.agentAppSettings.restoreFailed') },
      }),
    )
  }
})

// Project setting update response is intentionally not registered here: the
// backend's reply is only `{success, error?}` with no updated project payload,
// so the component refetches via `agent_app_settings_get` for authoritative
// state. The optimistic update is dispatched at the call site.
