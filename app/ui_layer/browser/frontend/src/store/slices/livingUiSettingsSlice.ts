import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'

// Project shape used by the Settings > Living UI tab. Distinct from the
// project shape used by `livingUiSlice` (which drives the main /living-ui
// page) — this one carries the per-project preferences exposed in Settings.
export interface LivingUIBackupStatus {
  lastAt?: number | null
  lastError?: string | null
  count?: number
  totalSize?: number
}

export interface LivingUIBackupEntry {
  filename: string
  ts: number // ms epoch
  trigger: 'scheduled' | 'pre_promote' | 'manual' | 'pre_delete'
  size: number
}

// A deleted project's leftover backup dir: opaque id + the app's human name
// (from the store's meta.json sidecar; falls back to the id).
export interface LivingUIBackupOrphan {
  id: string
  name: string
}

export interface LivingUISettingsProject {
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
  backupStatus?: LivingUIBackupStatus
}

interface LivingUiSettingsState {
  // Per-project settings list from `living_ui_settings_get`.
  projects: LivingUISettingsProject[]
  hasLoadedProjects: boolean
  // Backup dirs of deleted projects (kept on delete by default — D5).
  backupOrphans: LivingUIBackupOrphan[]
  // Per-project backup archive list from `living_ui_backups_list`.
  backupsByProject: Record<string, LivingUIBackupEntry[]>
  // Per-project in-flight marker for "Back up now" / restore buttons.
  backupBusy: Record<string, boolean>
}

const initialState: LivingUiSettingsState = {
  projects: [],
  hasLoadedProjects: false,
  backupOrphans: [],
  backupsByProject: {},
  backupBusy: {},
}

const livingUiSettingsSlice = createSlice({
  name: 'livingUiSettings',
  initialState,
  reducers: {
    setSettings(
      state,
      action: PayloadAction<{
        projects: LivingUISettingsProject[]
        backupOrphans: LivingUIBackupOrphan[]
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
      action: PayloadAction<{ projectId: string; backups: LivingUIBackupEntry[] }>,
    ) {
      state.backupsByProject[action.payload.projectId] = action.payload.backups
    },
    setBackupBusy(
      state,
      action: PayloadAction<{ projectId: string; busy: boolean }>,
    ) {
      state.backupBusy[action.payload.projectId] = action.payload.busy
    },
  },
})

export const {
  setSettings,
  updateProjectSetting,
  setProjectBackups,
  setBackupBusy,
} = livingUiSettingsSlice.actions

export default livingUiSettingsSlice.reducer

// --- inbound message handlers --------------------------------------------

register('living_ui_settings_get', (data, dispatch) => {
  const d = data as {
    success: boolean
    projects?: LivingUISettingsProject[]
    backupOrphans?: LivingUIBackupOrphan[]
  }
  if (d.success)
    dispatch(
      setSettings({
        projects: d.projects || [],
        backupOrphans: d.backupOrphans || [],
      }),
    )
})

register('living_ui_backups_list', (data, dispatch) => {
  const d = data as { projectId?: string; backups?: LivingUIBackupEntry[] }
  if (d.projectId)
    dispatch(
      setProjectBackups({ projectId: d.projectId, backups: d.backups || [] }),
    )
})

// backup_now / restore results clear the busy flag; the archive list and
// settings status line arrive via the follow-up broadcasts the backend
// already sends (living_ui_backups_list; the card refetches settings).
register('living_ui_backup_now_result', (data, dispatch) => {
  const d = data as { projectId?: string }
  if (d.projectId)
    dispatch(setBackupBusy({ projectId: d.projectId, busy: false }))
})

register('living_ui_backup_restore_result', (data, dispatch) => {
  const d = data as { projectId?: string }
  if (d.projectId)
    dispatch(setBackupBusy({ projectId: d.projectId, busy: false }))
})

// Project setting update response is intentionally not registered here: the
// backend's reply is only `{success, error?}` with no updated project payload,
// so the component refetches via `living_ui_settings_get` for authoritative
// state. The optimistic update is dispatched at the call site.
