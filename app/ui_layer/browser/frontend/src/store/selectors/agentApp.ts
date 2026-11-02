import type { RootState } from '../index'
import type { AgentAppProject } from '../../types'

export const selectNeedsTriggerReview = (state: RootState, project: AgentAppProject) =>
  !!project.triggerConsent?.needsReview
  && state.agentApp.dismissedTriggerReviews[project.id] !== project.triggerConsent.revision

export const selectTriggerReviewProject = (state: RootState) =>
  state.agentApp.projects.find(project => project.id === state.agentApp.triggerReviewId)
  || state.agentApp.projects.find(project => project.status === 'running' && selectNeedsTriggerReview(state, project))

export const selectAgentAppProjects = (state: RootState) =>
  state.agentApp.projects

export const selectAgentAppCreating = (state: RootState) =>
  state.agentApp.creating

export const selectAgentAppTodos = (state: RootState) =>
  state.agentApp.todos

export const selectAgentAppBuildEvents = (state: RootState) =>
  state.agentApp.buildEvents

export const selectAgentAppSnapshots = (state: RootState) =>
  state.agentApp.snapshots

export const selectActiveAgentAppId = (state: RootState) =>
  state.agentApp.activeId

export const selectAgentAppStates = (state: RootState) =>
  state.agentApp.states

export const selectAgentAppCatalogLoaded = (state: RootState) => state.agentApp.catalogLoaded
