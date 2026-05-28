import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'

export interface SkillConfig {
  name: string
  description: string
  enabled: boolean
  user_invocable: boolean
  action_sets: string[]
  source: string
}

interface SkillsSettingsState {
  skills: SkillConfig[]
  total: number
  enabled: number
  hasLoaded: boolean
}

const initialState: SkillsSettingsState = {
  skills: [],
  total: 0,
  enabled: 0,
  hasLoaded: false,
}

const skillsSettingsSlice = createSlice({
  name: 'skillsSettings',
  initialState,
  reducers: {
    setSkills(state, action: PayloadAction<{ skills: SkillConfig[]; total?: number; enabled?: number }>) {
      state.skills = action.payload.skills
      state.total = action.payload.total ?? action.payload.skills.length
      state.enabled = action.payload.enabled ?? action.payload.skills.filter(s => s.enabled).length
      state.hasLoaded = true
    },
    setEnabled(state, action: PayloadAction<{ name: string; enabled: boolean }>) {
      const entry = state.skills.find(s => s.name === action.payload.name)
      if (entry) {
        const was = entry.enabled
        entry.enabled = action.payload.enabled
        if (was !== action.payload.enabled) {
          state.enabled += action.payload.enabled ? 1 : -1
        }
      }
    },
    removeSkill(state, action: PayloadAction<string>) {
      const entry = state.skills.find(s => s.name === action.payload)
      state.skills = state.skills.filter(s => s.name !== action.payload)
      state.total = Math.max(0, state.total - 1)
      if (entry?.enabled) state.enabled = Math.max(0, state.enabled - 1)
    },
  },
})

export const { setSkills, setEnabled, removeSkill } = skillsSettingsSlice.actions
export default skillsSettingsSlice.reducer

register('skill_list', (data, dispatch) => {
  const d = data as { success: boolean; skills?: SkillConfig[]; total?: number; enabled?: number }
  if (d.success && d.skills) {
    dispatch(setSkills({ skills: d.skills, total: d.total, enabled: d.enabled }))
  }
})
