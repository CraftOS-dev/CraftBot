import type { RootState } from '../index'

export const selectDashboardMetrics = (state: RootState) =>
  state.dashboard.metrics

export const selectFilteredMetricsCache = (state: RootState) =>
  state.dashboard.filteredCache
