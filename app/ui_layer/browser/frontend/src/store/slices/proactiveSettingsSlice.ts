import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { register } from '../socket/messageRegistry'

export interface ScheduleConfig {
  id: string
  name: string
  schedule: string
  enabled: boolean
  priority: number
  payload?: { type: string; frequency?: string; scope?: string }
}

export interface ProactiveTask {
  id: string
  name: string
  frequency: string
  instruction: string
  enabled: boolean
  priority: number
  permissionTier: number
  time?: string
  day?: string
  runCount: number
  lastRun?: string
  nextRun?: string
  outcomeHistory: Array<{ timestamp: string; result: string; success: boolean }>
}

interface ProactiveSettingsState {
  schedulerEnabled: boolean
  schedules: ScheduleConfig[]
  tasks: ProactiveTask[]
  hasLoadedMode: boolean
  hasLoadedConfig: boolean
  hasLoadedTasks: boolean
}

const initialState: ProactiveSettingsState = {
  schedulerEnabled: true,
  schedules: [],
  tasks: [],
  hasLoadedMode: false,
  hasLoadedConfig: false,
  hasLoadedTasks: false,
}

const proactiveSettingsSlice = createSlice({
  name: 'proactiveSettings',
  initialState,
  reducers: {
    setSchedulerEnabled(state, action: PayloadAction<boolean>) {
      state.schedulerEnabled = action.payload
      state.hasLoadedMode = true
    },
    setSchedules(state, action: PayloadAction<ScheduleConfig[]>) {
      state.schedules = action.payload
      state.hasLoadedConfig = true
    },
    setTasks(state, action: PayloadAction<ProactiveTask[]>) {
      state.tasks = action.payload
      state.hasLoadedTasks = true
    },
    setTaskEnabled(state, action: PayloadAction<{ taskId: string; enabled: boolean }>) {
      const t = state.tasks.find(x => x.id === action.payload.taskId)
      if (t) t.enabled = action.payload.enabled
    },
  },
})

export const {
  setSchedulerEnabled,
  setSchedules,
  setTasks,
  setTaskEnabled,
} = proactiveSettingsSlice.actions

export default proactiveSettingsSlice.reducer

register('proactive_mode_get', (data, dispatch) => {
  const d = data as { success: boolean; enabled: boolean }
  if (d.success) dispatch(setSchedulerEnabled(d.enabled))
})

register('proactive_mode_set', (data, dispatch) => {
  const d = data as { success: boolean; enabled: boolean }
  if (d.success) dispatch(setSchedulerEnabled(d.enabled))
})

register('scheduler_config_get', (data, dispatch) => {
  const d = data as { success: boolean; config?: { schedules: ScheduleConfig[] } }
  if (d.success && d.config) dispatch(setSchedules(d.config.schedules || []))
})

register('scheduler_config_update', (data, dispatch) => {
  const d = data as { success: boolean; config?: { schedules: ScheduleConfig[] } }
  if (d.success && d.config) dispatch(setSchedules(d.config.schedules || []))
})

register('proactive_tasks_get', (data, dispatch) => {
  const d = data as { success: boolean; tasks: ProactiveTask[] }
  if (d.success) dispatch(setTasks(d.tasks || []))
})
