import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import type {
  AgentStatus,
  InitialState,
  SkillMeta,
  OnboardingCompleteResponse,
} from '../../types'
import { register } from '../socket/messageRegistry'

interface AgentSliceState {
  name: string
  profilePictureUrl: string
  profilePictureHasCustom: boolean
  status: AgentStatus
  currentTask: { id: string; name: string } | null
  guiMode: boolean
  footageUrl: string | null
  skillMeta: SkillMeta
}

const initialState: AgentSliceState = {
  name: 'Agent',
  profilePictureUrl: '/api/agent-profile-picture',
  profilePictureHasCustom: false,
  status: { state: 'idle', message: 'Connecting...', loading: false },
  currentTask: null,
  guiMode: false,
  footageUrl: null,
  skillMeta: {
    internalWorkflowIds: [],
    internalSkillNames: [],
    reservedSkillNames: [],
  },
}

const agentSlice = createSlice({
  name: 'agent',
  initialState,
  reducers: {
    setStatus(state, action: PayloadAction<{ message: string; loading: boolean }>) {
      state.status.message = action.payload.message
      state.status.loading = action.payload.loading
    },
    setStatusState(state, action: PayloadAction<AgentStatus['state']>) {
      state.status.state = action.payload
    },
    setCurrentTask(state, action: PayloadAction<{ id: string; name: string } | null>) {
      state.currentTask = action.payload
    },
    setFootageUrl(state, action: PayloadAction<string | null>) {
      state.footageUrl = action.payload
    },
    setGuiMode(state, action: PayloadAction<boolean>) {
      state.guiMode = action.payload
    },
    setSkillMeta(state, action: PayloadAction<SkillMeta>) {
      state.skillMeta = action.payload
    },
    setName(state, action: PayloadAction<string>) {
      state.name = action.payload
    },
    setProfilePicture(state, action: PayloadAction<{ url: string; hasCustom: boolean }>) {
      state.profilePictureUrl = action.payload.url
      state.profilePictureHasCustom = action.payload.hasCustom
    },
  },
})

export const {
  setStatus,
  setStatusState,
  setCurrentTask,
  setFootageUrl,
  setGuiMode,
  setSkillMeta,
  setName,
  setProfilePicture,
} = agentSlice.actions

export default agentSlice.reducer

// --- inbound message handlers --------------------------------------------

register('init', (data, dispatch) => {
  const d = data as InitialState & {
    agentProfilePictureUrl?: string
    agentProfilePictureHasCustom?: boolean
  }
  dispatch(setName(d.agentName || 'Agent'))
  dispatch(setProfilePicture({
    url: d.agentProfilePictureUrl || '/api/agent-profile-picture',
    hasCustom: d.agentProfilePictureHasCustom ?? false,
  }))
  dispatch(setStatus({ message: d.status || 'Ready', loading: false }))
  dispatch(setStatusState(d.agentState || 'idle'))
  dispatch(setGuiMode(d.guiMode || false))
  dispatch(setCurrentTask(d.currentTask || null))
})

register('status_update', (data, dispatch) => {
  const { message, loading } = data as { message: string; loading: boolean }
  dispatch(setStatus({ message, loading }))
})

register('footage_update', (data, dispatch) => {
  const { image } = data as { image: string }
  dispatch(setFootageUrl(image))
})

register('footage_clear', (_data, dispatch) => {
  dispatch(setFootageUrl(null))
})

register('footage_visibility', (data, dispatch) => {
  const { visible } = data as { visible: boolean }
  dispatch(setGuiMode(visible))
})

register('skill_meta', (data, dispatch) => {
  const d = data as SkillMeta
  dispatch(setSkillMeta({
    internalWorkflowIds: d.internalWorkflowIds || [],
    internalSkillNames: d.internalSkillNames || [],
    reservedSkillNames: d.reservedSkillNames || [],
  }))
})

register('agent_profile_picture_upload', (data, dispatch) => {
  const r = data as { success: boolean; url?: string; has_custom?: boolean }
  if (r.success && r.url) {
    dispatch(setProfilePicture({ url: r.url, hasCustom: r.has_custom ?? true }))
  }
})

register('agent_profile_picture_remove', (data, dispatch) => {
  const r = data as { success: boolean; url?: string; has_custom?: boolean }
  if (r.success) {
    dispatch(setProfilePicture({
      url: r.url || '/api/agent-profile-picture',
      hasCustom: r.has_custom ?? false,
    }))
  }
})

register('onboarding_complete', (data, dispatch) => {
  const r = data as OnboardingCompleteResponse & {
    agentProfilePictureUrl?: string
    agentProfilePictureHasCustom?: boolean
  }
  if (!r.success) return
  if (r.agentName) dispatch(setName(r.agentName))
  if (r.agentProfilePictureUrl !== undefined) {
    dispatch(setProfilePicture({
      url: r.agentProfilePictureUrl,
      hasCustom: r.agentProfilePictureHasCustom ?? false,
    }))
  }
})
