/** Persist identities only: app content and runtime state belong to the app domain. */
export interface PanelAppsState {
  projectIds: string[]
  selectedProjectId: string | null
}

export const emptyPanelApps: PanelAppsState = { projectIds: [], selectedProjectId: null }

export function isPanelAppsState(value: unknown): value is PanelAppsState {
  if (!value || typeof value !== 'object') return false
  const state = value as PanelAppsState
  return Array.isArray(state.projectIds) && state.projectIds.length <= 100
    && state.projectIds.every(id => typeof id === 'string' && id.length > 0 && id.length <= 256)
    && new Set(state.projectIds).size === state.projectIds.length
    && (state.selectedProjectId === null || typeof state.selectedProjectId === 'string' && state.projectIds.includes(state.selectedProjectId))
}

export function attachPanelApp(state: PanelAppsState, id: string): PanelAppsState {
  if (!id || id.length > 256 || !state.projectIds.includes(id) && state.projectIds.length >= 100) return state
  return { projectIds: state.projectIds.includes(id) ? state.projectIds : [...state.projectIds, id], selectedProjectId: id }
}

export function retainPanelApps(state: PanelAppsState, keep: (id: string) => boolean): PanelAppsState {
  const projectIds = state.projectIds.filter(keep)
  if (projectIds.length === state.projectIds.length) return state
  const index = state.projectIds.indexOf(state.selectedProjectId ?? '')
  return { projectIds, selectedProjectId: projectIds.includes(state.selectedProjectId ?? '')
    ? state.selectedProjectId : projectIds[Math.min(Math.max(0, index), projectIds.length - 1)] ?? null }
}
