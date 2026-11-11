import type { RootState } from '../index'

export const selectSchedulerEnabled = (state: RootState) => state.proactiveSettings.schedulerEnabled
export const selectSchedules = (state: RootState) => state.proactiveSettings.schedules
export const selectProactiveTasks = (state: RootState) => state.proactiveSettings.tasks
export const selectProactiveHasLoadedMode = (state: RootState) => state.proactiveSettings.hasLoadedMode
export const selectProactiveHasLoadedConfig = (state: RootState) => state.proactiveSettings.hasLoadedConfig
export const selectProactiveHasLoadedTasks = (state: RootState) => state.proactiveSettings.hasLoadedTasks
export const selectProactiveSchedule = (state: RootState) => state.proactiveSettings.schedule
export const selectHeartbeatOptions = (state: RootState) => state.proactiveSettings.heartbeatOptions
