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

/** A cron job from PROACTIVE.md's "Cron Jobs" section. */
export interface CronJob {
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

/** Heartbeat interval + planner schedules as Settings → Proactive edits them. */
export interface ProactiveSchedule {
  heartbeatMinutes: number
  dayPlannerTime: string
  weekPlannerDay: string
  weekPlannerTime: string
  monthPlannerDay: number
  monthPlannerTime: string
}

interface ProactiveSettingsState {
  schedulerEnabled: boolean
  schedules: ScheduleConfig[]
  cronJobs: CronJob[]
  schedule: ProactiveSchedule | null
  heartbeatOptions: number[]
  /** PROACTIVE.md's "Heartbeat" checklist; null until loaded. */
  heartbeatChecklist: string | null
  hasLoadedMode: boolean
  hasLoadedConfig: boolean
  hasLoadedCronJobs: boolean
}

const initialState: ProactiveSettingsState = {
  schedulerEnabled: true,
  schedules: [],
  cronJobs: [],
  schedule: null,
  heartbeatOptions: [],
  heartbeatChecklist: null,
  hasLoadedMode: false,
  hasLoadedConfig: false,
  hasLoadedCronJobs: false,
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
    setCronJobs(state, action: PayloadAction<CronJob[]>) {
      state.cronJobs = action.payload
      state.hasLoadedCronJobs = true
    },
    setCronJobEnabled(state, action: PayloadAction<{ jobId: string; enabled: boolean }>) {
      const job = state.cronJobs.find(x => x.id === action.payload.jobId)
      if (job) job.enabled = action.payload.enabled
    },
    setProactiveSchedule(
      state,
      action: PayloadAction<{ schedule: ProactiveSchedule; heartbeatOptions: number[] }>,
    ) {
      state.schedule = action.payload.schedule
      state.heartbeatOptions = action.payload.heartbeatOptions
    },
    setHeartbeatChecklist(state, action: PayloadAction<string>) {
      state.heartbeatChecklist = action.payload
    },
  },
})

export const {
  setSchedulerEnabled,
  setSchedules,
  setCronJobs,
  setCronJobEnabled,
  setProactiveSchedule,
  setHeartbeatChecklist,
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

register('cron_jobs_get', (data, dispatch) => {
  const d = data as { success: boolean; jobs: CronJob[] }
  if (d.success) dispatch(setCronJobs(d.jobs || []))
})

register('heartbeat_checklist_get', (data, dispatch) => {
  const d = data as { success: boolean; checklist?: string }
  if (d.success) dispatch(setHeartbeatChecklist(d.checklist ?? ''))
})

register('proactive_schedule_get', (data, dispatch) => {
  const d = data as Partial<ProactiveSchedule> & { success: boolean; heartbeatOptions?: number[] }
  if (
    !d.success
    || d.heartbeatMinutes === undefined
    || !d.dayPlannerTime
    || !d.weekPlannerDay
    || !d.weekPlannerTime
    || d.monthPlannerDay === undefined
    || !d.monthPlannerTime
  ) return
  dispatch(setProactiveSchedule({
    schedule: {
      heartbeatMinutes: d.heartbeatMinutes,
      dayPlannerTime: d.dayPlannerTime,
      weekPlannerDay: d.weekPlannerDay,
      weekPlannerTime: d.weekPlannerTime,
      monthPlannerDay: d.monthPlannerDay,
      monthPlannerTime: d.monthPlannerTime,
    },
    heartbeatOptions: d.heartbeatOptions ?? [],
  }))
})
