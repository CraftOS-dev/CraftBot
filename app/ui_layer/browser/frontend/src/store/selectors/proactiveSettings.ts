import type { RootState } from '../index'

export const selectSchedulerEnabled = (state: RootState) => state.proactiveSettings.schedulerEnabled
export const selectSchedules = (state: RootState) => state.proactiveSettings.schedules
export const selectCronJobs = (state: RootState) => state.proactiveSettings.cronJobs
export const selectProactiveHasLoadedMode = (state: RootState) => state.proactiveSettings.hasLoadedMode
export const selectProactiveHasLoadedConfig = (state: RootState) => state.proactiveSettings.hasLoadedConfig
export const selectCronJobsLoaded = (state: RootState) => state.proactiveSettings.hasLoadedCronJobs
export const selectProactiveSchedule = (state: RootState) => state.proactiveSettings.schedule
export const selectHeartbeatOptions = (state: RootState) => state.proactiveSettings.heartbeatOptions
export const selectHeartbeatChecklist = (state: RootState) => state.proactiveSettings.heartbeatChecklist
