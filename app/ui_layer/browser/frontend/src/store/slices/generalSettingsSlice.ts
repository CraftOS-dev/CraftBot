import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'

// Agent identity (name, theme, profile pic) is already in agentSlice. This
// slice covers the General tab's other cacheable pieces: the saved form
// values, the three agent markdown files (lazily loaded when the Advanced
// section opens) and the update-check result.

type AgentFileName = 'USER.md' | 'AGENT.md' | 'SOUL.md'

/** The General form's saved values, as the server reports them. */
export interface GeneralSettingsValues {
  agentName: string
  language: string
}

interface GeneralSettingsState {
  settings: GeneralSettingsValues | null
  userMd: string
  agentMd: string
  soulMd: string
  hasLoadedUserMd: boolean
  hasLoadedAgentMd: boolean
  hasLoadedSoulMd: boolean
  updateChecked: boolean
  updateAvailable: boolean
  latestVersion: string
  // Set only when the checkout is off the main update channel; names the
  // branch so the UI can explain why no update is offered.
  updateBranch: string
}

const initialState: GeneralSettingsState = {
  settings: null,
  userMd: '',
  agentMd: '',
  soulMd: '',
  hasLoadedUserMd: false,
  hasLoadedAgentMd: false,
  hasLoadedSoulMd: false,
  updateChecked: false,
  updateAvailable: false,
  latestVersion: '',
  updateBranch: '',
}

const generalSettingsSlice = createSlice({
  name: 'generalSettings',
  initialState,
  reducers: {
    applySettings(state, action: PayloadAction<Partial<GeneralSettingsValues>>) {
      const { agentName, language } = action.payload
      state.settings = {
        agentName: agentName ?? state.settings?.agentName ?? '',
        language: language ?? state.settings?.language ?? '',
      }
    },
    setAgentFile(state, action: PayloadAction<{ filename: AgentFileName; content: string }>) {
      const { filename, content } = action.payload
      if (filename === 'USER.md') {
        state.userMd = content
        state.hasLoadedUserMd = true
      } else if (filename === 'AGENT.md') {
        state.agentMd = content
        state.hasLoadedAgentMd = true
      } else if (filename === 'SOUL.md') {
        state.soulMd = content
        state.hasLoadedSoulMd = true
      }
    },
    setUpdateInfo(
      state,
      action: PayloadAction<{ updateAvailable: boolean; latestVersion: string; updateBranch: string }>
    ) {
      state.updateAvailable = action.payload.updateAvailable
      state.latestVersion = action.payload.latestVersion
      state.updateBranch = action.payload.updateBranch
      state.updateChecked = true
    },
    resetUpdateCheck(state) {
      state.updateChecked = false
      state.updateAvailable = false
      state.latestVersion = ''
      state.updateBranch = ''
    },
  },
})

export const { applySettings, setAgentFile, setUpdateInfo, resetUpdateCheck } = generalSettingsSlice.actions
export default generalSettingsSlice.reducer

// `theme` in these payloads is ignored: the theme is a local UI preference
// (ThemeContext) and the backend value is a hard-coded placeholder.
register('settings_get', (data, dispatch) => {
  const d = data as { success: boolean; settings?: { agentName?: string; language?: string } }
  if (d.success && d.settings) {
    dispatch(applySettings({ agentName: d.settings.agentName, language: d.settings.language }))
  }
})

// A save from any tab echoes the saved values; apply them at once rather
// than waiting for the refetch its resource change triggers.
register('settings_update', (data, dispatch) => {
  const d = data as { success: boolean; settings?: { agentName?: string; language?: string } }
  if (d.success && d.settings) {
    dispatch(applySettings({ agentName: d.settings.agentName, language: d.settings.language }))
  }
})

// Multi-handler: GeneralSettings cares about USER.md, AGENT.md, SOUL.md.
// Filter strictly by filename so other tabs' agent_file_read traffic is
// ignored (handlers are additive across slices).
register('agent_file_read', (data, dispatch) => {
  const d = data as { filename: string; content: string; success: boolean }
  if (!d.success) return
  if (d.filename === 'USER.md' || d.filename === 'AGENT.md' || d.filename === 'SOUL.md') {
    dispatch(setAgentFile({ filename: d.filename as AgentFileName, content: d.content }))
  }
})

register('agent_file_restore', (data, dispatch) => {
  const d = data as { filename: string; content: string; success: boolean }
  if (!d.success) return
  if (d.filename === 'USER.md' || d.filename === 'AGENT.md' || d.filename === 'SOUL.md') {
    dispatch(setAgentFile({ filename: d.filename as AgentFileName, content: d.content }))
  }
})

register('update_check_result', (data, dispatch) => {
  const d = data as { updateAvailable: boolean; latestVersion: string; branch?: string | null }
  dispatch(setUpdateInfo({
    updateAvailable: d.updateAvailable,
    latestVersion: d.latestVersion,
    updateBranch: d.branch ?? '',
  }))
})
