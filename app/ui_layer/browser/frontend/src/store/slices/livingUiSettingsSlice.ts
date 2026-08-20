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
}

const initialState: LivingUiSettingsState = {
  projects: [],
  hasLoadedProjects: false,
}

const livingUiSettingsSlice = createSlice({
  name: 'livingUiSettings',
  initialState,
  reducers: {
    setSettings(state, action: PayloadAction<LivingUISettingsProject[]>) {
      state.projects = action.payload
      state.hasLoadedProjects = true
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

export const { setSettings, updateProjectSetting } =
  livingUiSettingsSlice.actions

export default livingUiSettingsSlice.reducer

// --- inbound message handlers --------------------------------------------

register('living_ui_settings_get', (data, dispatch) => {
  const d = data as { success: boolean; projects?: LivingUISettingsProject[] }
  if (d.success) dispatch(setSettings(d.projects || []))
})

// Project setting update response is intentionally not registered here: the
// backend's reply is only `{success, error?}` with no updated project payload,
// so the component refetches via `living_ui_settings_get` for authoritative
// state. The optimistic update is dispatched at the call site.
