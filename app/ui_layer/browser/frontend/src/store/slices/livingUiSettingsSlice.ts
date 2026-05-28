import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'

// Project shape used by the Settings > Living UI tab. Distinct from the
// project shape used by `livingUiSlice` (which drives the main /living-ui
// page) — this one carries the per-project preferences exposed in Settings.
export interface LivingUISettingsProject {
  id: string
  name: string
  status: string
  port: number | null
  backendPort: number | null
  path: string
  autoLaunch: boolean
  logCleanup: boolean
}

interface LivingUiSettingsState {
  // Per-project settings list from `living_ui_settings_get`.
  projects: LivingUISettingsProject[]
  hasLoadedProjects: boolean

  // Contents of GLOBAL_LIVING_UI.md. Source of truth for design prefs and
  // global rules. Loaded via `agent_file_read` filtered on the filename.
  globalConfig: string
  hasLoadedGlobalConfig: boolean
}

const initialState: LivingUiSettingsState = {
  projects: [],
  hasLoadedProjects: false,
  globalConfig: '',
  hasLoadedGlobalConfig: false,
}

const livingUiSettingsSlice = createSlice({
  name: 'livingUiSettings',
  initialState,
  reducers: {
    setSettings(state, action: PayloadAction<LivingUISettingsProject[]>) {
      state.projects = action.payload
      state.hasLoadedProjects = true
    },
    setGlobalConfig(state, action: PayloadAction<string>) {
      state.globalConfig = action.payload
      state.hasLoadedGlobalConfig = true
    },
    // Optimistic per-project setting flip so the toggle doesn't lag on the
    // round-trip back from the backend.
    updateProjectSetting(
      state,
      action: PayloadAction<{
        projectId: string
        setting: 'autoLaunch' | 'logCleanup'
        value: boolean
      }>,
    ) {
      const p = state.projects.find(x => x.id === action.payload.projectId)
      if (p) p[action.payload.setting] = action.payload.value
    },
  },
})

export const { setSettings, setGlobalConfig, updateProjectSetting } =
  livingUiSettingsSlice.actions

export default livingUiSettingsSlice.reducer

// --- inbound message handlers --------------------------------------------

register('living_ui_settings_get', (data, dispatch) => {
  const d = data as { success: boolean; projects?: LivingUISettingsProject[] }
  if (d.success) dispatch(setSettings(d.projects || []))
})

// `agent_file_read` is shared across settings tabs (GeneralSettings handles
// USER.md / AGENT.md / SOUL.md). Filter strictly by filename so we only
// react to our own file.
register('agent_file_read', (data, dispatch) => {
  const d = data as { filename: string; content: string; success: boolean }
  if (d.filename === 'GLOBAL_LIVING_UI.md' && d.success) {
    dispatch(setGlobalConfig(d.content))
  }
})

// Same filename filter applies to restore (returns the freshly-reset content).
register('agent_file_restore', (data, dispatch) => {
  const d = data as { filename: string; content: string; success: boolean }
  if (d.filename === 'GLOBAL_LIVING_UI.md' && d.success) {
    dispatch(setGlobalConfig(d.content))
  }
})

// Project setting update response is intentionally not registered here: the
// backend's reply is only `{success, error?}` with no updated project payload,
// so the component refetches via `living_ui_settings_get` for authoritative
// state. The optimistic update is dispatched at the call site.
