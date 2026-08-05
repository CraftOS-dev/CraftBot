import type { RootState } from '../index'
import type { SessionRunState } from '../slices/agentSlice'

export const selectAgentName = (state: RootState) => state.agent.name
export const selectAgentProfilePictureUrl = (state: RootState) =>
  state.agent.profilePictureUrl
export const selectAgentProfilePictureHasCustom = (state: RootState) =>
  state.agent.profilePictureHasCustom
export const selectAgentStatus = (state: RootState) => state.agent.status
export const selectGuiMode = (state: RootState) => state.agent.guiMode
export const selectFootageUrl = (state: RootState) => state.agent.footageUrl
export const selectSkillMeta = (state: RootState) => state.agent.skillMeta
export const selectSessionRunState = (
  state: RootState,
  sessionId: string,
): SessionRunState => state.agent.runStateBySession[sessionId] ?? 'idle'
export const selectSessionBusy = (state: RootState, sessionId: string) =>
  state.agent.runStateBySession[sessionId] !== undefined
