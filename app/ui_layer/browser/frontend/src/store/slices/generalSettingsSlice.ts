import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'

// Agent identity (name, theme, profile pic) is already in agentSlice. This
// slice covers the General tab's other cacheable pieces: the three agent
// markdown files (lazily loaded when the Advanced section opens) and the
// update-check result.

type AgentFileName = 'USER.md' | 'AGENT.md' | 'SOUL.md'

interface GeneralSettingsState {
  userMd: string
  agentMd: string
  soulMd: string
  hasLoadedUserMd: boolean
  hasLoadedAgentMd: boolean
  hasLoadedSoulMd: boolean
  updateChecked: boolean
  updateAvailable: boolean
  latestVersion: string
}

const initialState: GeneralSettingsState = {
  userMd: '',
  agentMd: '',
  soulMd: '',
  hasLoadedUserMd: false,
  hasLoadedAgentMd: false,
  hasLoadedSoulMd: false,
  updateChecked: false,
  updateAvailable: false,
  latestVersion: '',
}

const generalSettingsSlice = createSlice({
  name: 'generalSettings',
  initialState,
  reducers: {
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
    setUpdateInfo(state, action: PayloadAction<{ updateAvailable: boolean; latestVersion: string }>) {
      state.updateAvailable = action.payload.updateAvailable
      state.latestVersion = action.payload.latestVersion
      state.updateChecked = true
    },
  },
})

export const { setAgentFile, setUpdateInfo } = generalSettingsSlice.actions
export default generalSettingsSlice.reducer

// Multi-handler: GeneralSettings cares about USER.md, AGENT.md, SOUL.md.
// (LivingUISettings registers its own agent_file_read handler for the
// GLOBAL_LIVING_UI.md filename — handlers are additive.)
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
  const d = data as { updateAvailable: boolean; latestVersion: string }
  dispatch(setUpdateInfo({ updateAvailable: d.updateAvailable, latestVersion: d.latestVersion }))
})
