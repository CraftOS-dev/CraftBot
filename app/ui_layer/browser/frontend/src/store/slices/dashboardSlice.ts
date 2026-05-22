import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import type {
  DashboardMetrics,
  FilteredDashboardMetrics,
  MetricsTimePeriod,
} from '../../types'
import { register } from '../socket/messageRegistry'

interface DashboardState {
  metrics: DashboardMetrics | null
  // Per-period cache. Each card on the dashboard requests its own period
  // and the most recent response is kept here so the UI doesn't refetch on
  // every remount.
  filteredCache: Record<MetricsTimePeriod, FilteredDashboardMetrics | null>
}

const initialState: DashboardState = {
  metrics: null,
  filteredCache: {
    '1h': null,
    '1d': null,
    '1w': null,
    '1m': null,
    'total': null,
  },
}

const dashboardSlice = createSlice({
  name: 'dashboard',
  initialState,
  reducers: {
    setMetrics(state, action: PayloadAction<DashboardMetrics | null>) {
      state.metrics = action.payload
    },
    setFilteredMetrics(state, action: PayloadAction<FilteredDashboardMetrics>) {
      state.filteredCache[action.payload.period] = action.payload
    },
  },
})

export const { setMetrics, setFilteredMetrics } = dashboardSlice.actions
export default dashboardSlice.reducer

// --- inbound message handlers --------------------------------------------

register('init', (data, dispatch) => {
  const d = data as { dashboardMetrics?: DashboardMetrics } | undefined
  if (d?.dashboardMetrics) dispatch(setMetrics(d.dashboardMetrics))
})

register('dashboard_metrics', (data, dispatch) => {
  dispatch(setMetrics(data as DashboardMetrics))
})

register('dashboard_filtered_metrics', (data, dispatch) => {
  dispatch(setFilteredMetrics(data as FilteredDashboardMetrics))
})
