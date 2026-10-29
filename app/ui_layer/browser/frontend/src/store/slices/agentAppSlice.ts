import { createSlice, current, isDraft, PayloadAction } from '@reduxjs/toolkit'
import { reconcileIframes, removeIframe } from '../../features/agentApps/frameHost'
import { setConnected } from './connectionSlice'
import type {
  AgentAppProject,
  AgentAppTriggerConsent,
  AgentAppTriggerBlocked,
  AgentAppStatus,
  AgentAppStatusUpdate,
  AgentAppStateUpdate,
  AgentAppListResponse,
  AgentAppCreateResponse,
  AgentAppLaunchResponse,
  AgentAppStopResponse,
  AgentAppDeleteResponse,
  AgentAppBuildEvent,
} from '../../types'
import { register } from '../socket/messageRegistry'
import { getSocketClient } from '../socket/socketInstance'
import { findIndexInDraft } from './draftSearch'

// Local types — these aren't in src/types but the backend sends them.
// Shape mirrors the agent's todo tool: content is the imperative label,
// active_form the present-continuous label shown while in progress.
export interface AgentAppTodo {
  id: string
  content?: string
  active_form?: string
  status: 'pending' | 'in_progress' | 'completed'
}

// Kept in sync with the backend ring buffer (_BUFFER_MAX in
// construction_events.py) so replay + live never exceed what the server holds.
const MAX_BUILD_EVENTS = 200

// Authoritative "built so far" counts for the summary chips. Persisted
// separately from the (capped, paced) event feed so a flood of read/search
// events can never evict the writes that carried the snapshot.
export interface AgentAppSnapshot {
  collections: number
  components: number
  routes: number
}

interface AgentAppState {
  blockedTriggerRequests: Record<string, AgentAppTriggerBlocked>
  triggerReviewId: string | null
  dismissedTriggerReviews: Record<string, string>
  triggerConsentRequest: { projectId: string; requestId: string; allow: boolean } | null
  triggerConsentError: { projectId: string; message: string } | null
  triggerConsentApproval: { projectId: string; requestId: string } | null
  projects: AgentAppProject[]
  creating: AgentAppStatusUpdate | null
  todos: Record<string, AgentAppTodo[]>
  buildEvents: Record<string, AgentAppBuildEvent[]>
  snapshots: Record<string, AgentAppSnapshot>
  activeId: string | null
  states: Record<string, AgentAppStateUpdate['state']>
  // True until the first project list after a (re)connect replaces the
  // projects wholesale (see setProjects).
  listIsAuthoritative: boolean
  catalogLoaded: boolean
}

// Statuses the browser learns from live events, not from the saved list.
const IN_FLIGHT_STATUSES = new Set<AgentAppStatus>(['creating', 'launching', 'stopping'])

// Whether the saved server status ends an in-flight one.
function settlesInFlight(inFlight: AgentAppStatus, server: AgentAppStatus): boolean {
  if (server === 'error') return true
  return inFlight === 'stopping' ? server === 'stopped' : server === 'running'
}

const initialState: AgentAppState = {
  blockedTriggerRequests: {},
  triggerReviewId: null,
  dismissedTriggerReviews: {},
  triggerConsentRequest: null,
  triggerConsentError: null,
  triggerConsentApproval: null,
  listIsAuthoritative: true,
  catalogLoaded: false,
  projects: [],
  creating: null,
  todos: {},
  buildEvents: {},
  snapshots: {},
  activeId: null,
  states: {},
}

function clearResolvedTriggerBlock(state: AgentAppState, projectId: string, consent: AgentAppTriggerConsent) {
  const blocked = state.blockedTriggerRequests[projectId]
  if (blocked && (blocked.consent.revision !== consent.revision || !consent.required
    || consent.triggers.some(trigger => trigger.name === blocked.trigger && trigger.change === 'approved'))) {
    delete state.blockedTriggerRequests[projectId]
  }
}

const agentAppSlice = createSlice({
  name: 'agentApp',
  initialState,
  reducers: {
    receiveTriggerBlocked(state, action: PayloadAction<AgentAppTriggerBlocked>) {
      const blocked = action.payload
      state.projects = state.projects.map(p => p.id === blocked.projectId ? { ...p, triggerConsent: blocked.consent } : p)
      // One notification per app/review revision, even after its toast is
      // dismissed. A successful allowance or a new revision starts a new group.
      if (state.blockedTriggerRequests[blocked.projectId]?.consent.revision !== blocked.consent.revision) {
        state.blockedTriggerRequests[blocked.projectId] = blocked
      }
      clearResolvedTriggerBlock(state, blocked.projectId, blocked.consent)
    },
    openTriggerReview(state, action: PayloadAction<string | null>) {
      state.triggerReviewId = action.payload
      state.triggerConsentError = null
    },
    dismissTriggerReview(state, action: PayloadAction<{ projectId: string; revision: string }>) {
      const { projectId, revision } = action.payload
      // Session-only suppression: no permission changes, and a new revision
      // still prompts. This also lets the app open after a failed save.
      state.dismissedTriggerReviews[projectId] = revision
      if (state.triggerReviewId === projectId) state.triggerReviewId = null
      if (state.triggerConsentError?.projectId === projectId) state.triggerConsentError = null
    },
    savingTriggerConsent(state, action: PayloadAction<{ projectId: string; requestId: string; allow: boolean }>) {
      state.triggerReviewId = action.payload.projectId
      state.triggerConsentRequest = action.payload
      state.triggerConsentError = null
      state.triggerConsentApproval = null
    },
    receiveTriggerConsent(state, action: PayloadAction<{ projectId: string; requestId?: string; consent?: AgentAppTriggerConsent; success: boolean; error?: string }>) {
      const result = action.payload
      const pending = state.triggerConsentRequest
      // Snapshots are shared across clients; completion/error state belongs
      // only to the browser decision that produced this response.
      if (result.consent) {
        state.projects = state.projects.map(p => p.id === result.projectId ? { ...p, triggerConsent: result.consent } : p)
        clearResolvedTriggerBlock(state, result.projectId, result.consent)
      }
      if (!pending || pending.projectId !== result.projectId || pending.requestId !== result.requestId) return
      if (pending.allow && result.success && !result.error && result.consent && !result.consent.required) {
        state.triggerConsentApproval = { projectId: pending.projectId, requestId: pending.requestId }
      }
      state.triggerConsentRequest = null
      state.triggerConsentError = result.error ? { projectId: result.projectId, message: result.error } : null
      if (result.success) {
        if (state.triggerReviewId === result.projectId) state.triggerReviewId = null
        delete state.dismissedTriggerReviews[result.projectId]
      }
    },
    setProjects(state, action: PayloadAction<AgentAppProject[]>) {
      for (const projectId of Object.keys(state.blockedTriggerRequests)) {
        const project = action.payload.find(p => p.id === projectId)
        if (!project) delete state.blockedTriggerRequests[projectId]
        else if (project.triggerConsent) clearResolvedTriggerBlock(state, projectId, project.triggerConsent)
      }
      state.catalogLoaded = true
      // The list is the server's saved state, which says "stopped" until a
      // build or launch actually finishes; the in-flight state is only known
      // from live events. A refetch mid-launch (any tab's change triggers
      // one) must not flip the page to "not running", so in-flight states
      // stay until their own event (ready, error, launch/stop reply) settles
      // them. The first list after a (re)connect is taken as-is: events may
      // have been missed while disconnected.
      if (state.listIsAuthoritative) {
        state.projects = action.payload
        state.listIsAuthoritative = false
        return
      }
      const inFlight = new Map(
        state.projects.filter(p => IN_FLIGHT_STATUSES.has(p.status)).map(p => [p.id, p.status]),
      )
      state.projects = action.payload.map(p => {
        const live = inFlight.get(p.id)
        return live && !settlesInFlight(live, p.status) ? { ...p, status: live } : p
      })
    },
    addProject(state, action: PayloadAction<AgentAppProject>) {
      // Upsert by id: the import/marketplace flows first add a "creating"
      // placeholder, then re-broadcast the same id with real data once the
      // import completes. Replacing in place keeps a single tab. A running
      // project keeps its live status and address (never downgraded by a late
      // event) but still takes renames, icon changes and other fields.
      const incoming = action.payload
      if (incoming.triggerConsent) clearResolvedTriggerBlock(state, incoming.id, incoming.triggerConsent)
      const idx = findIndexInDraft(state.projects, p => p.id === incoming.id)
      if (idx === -1) {
        state.projects.push(incoming)
      } else {
        const existing = state.projects[idx]
        state.projects[idx] = existing.status === 'running'
          ? { ...incoming, status: existing.status, url: existing.url, port: existing.port, readyAt: existing.readyAt }
          : incoming
      }
    },
    applyStatus(state, action: PayloadAction<AgentAppStatusUpdate>) {
      const status = action.payload
      state.creating = status
      state.projects = state.projects.map(p => {
        if (p.id !== status.projectId) return p
        // Never downgrade a running project back to creating/ready on a
        // late status event.
        if (p.status === 'running') return p
        return { ...p, status: status.phase === 'launching' ? 'ready' : 'creating' }
      })
    },
    markReady(state, action: PayloadAction<{ projectId: string; url: string; port: number; sessionId?: string; triggerConsent?: AgentAppTriggerConsent }>) {
      const { projectId, url, port, sessionId, triggerConsent } = action.payload
      if (triggerConsent) clearResolvedTriggerBlock(state, projectId, triggerConsent)
      state.creating = null
      delete state.buildEvents[projectId]
      delete state.snapshots[projectId]
      state.projects = state.projects.map(p =>
        p.id === projectId
          ? {
              ...p,
              status: 'running',
              url,
              port,
              // Every ready event stamps a fresh version: the app iframe keys
              // its src on it, so a promote/relaunch forces a real fetch of
              // index.html instead of the browser's heuristically-cached copy
              // (which kept showing the previous build after deploys).
              readyAt: Date.now(),
              ...(sessionId ? { sessionId } : {}),
              ...(triggerConsent ? { triggerConsent } : {}),
            }
          : p,
      )
    },
    markRunning(state, action: PayloadAction<{ projectId: string; url?: string; port?: number; triggerConsent?: AgentAppTriggerConsent }>) {
      const { projectId, url, port, triggerConsent } = action.payload
      if (triggerConsent) clearResolvedTriggerBlock(state, projectId, triggerConsent)
      delete state.buildEvents[projectId]
      delete state.snapshots[projectId]
      state.projects = state.projects.map(p =>
        p.id === projectId ? { ...p, status: 'running', url, port, readyAt: Date.now(), ...(triggerConsent ? { triggerConsent } : {}) } : p,
      )
    },
    // Optimistic transition set the instant the user clicks Launch, so the UI
    // reacts immediately instead of looking frozen until the backend responds.
    markLaunching(state, action: PayloadAction<{ projectId: string }>) {
      state.projects = state.projects.map(p =>
        p.id === action.payload.projectId && p.status !== 'running'
          ? { ...p, status: 'launching' }
          : p,
      )
    },
    // Launch failed — clear the optimistic 'launching' spinner and revert to
    // 'stopped' so the Launch button returns and the user can retry (rather
    // than landing on the terminal creation-error screen).
    markLaunchFailed(state, action: PayloadAction<{ projectId: string; error?: string }>) {
      const { projectId, error } = action.payload
      state.projects = state.projects.map(p =>
        p.id === projectId ? { ...p, status: 'stopped', error: error || p.error } : p,
      )
    },
    // Optimistic transition set the instant the user clicks Stop. Keeps url/port
    // so a failed stop can revert cleanly to 'running'.
    markStopping(state, action: PayloadAction<{ projectId: string }>) {
      state.projects = state.projects.map(p =>
        p.id === action.payload.projectId && p.status === 'running'
          ? { ...p, status: 'stopping' }
          : p,
      )
    },
    // Stop failed — the project is still up, so revert to 'running' (url/port
    // were preserved by markStopping).
    markStopFailed(state, action: PayloadAction<{ projectId: string }>) {
      state.projects = state.projects.map(p =>
        p.id === action.payload.projectId ? { ...p, status: 'running' } : p,
      )
    },
    markStopped(state, action: PayloadAction<{ projectId: string }>) {
      state.projects = state.projects.map(p =>
        p.id === action.payload.projectId
          ? { ...p, status: 'stopped', url: undefined, port: undefined }
          : p,
      )
    },
    removeProject(state, action: PayloadAction<{ projectId: string }>) {
      const id = action.payload.projectId
      delete state.blockedTriggerRequests[id]
      state.projects = state.projects.filter(p => p.id !== id)
      delete state.todos[id]
      delete state.buildEvents[id]
      delete state.snapshots[id]
      delete state.states[id]
      if (state.activeId === id) state.activeId = null
    },
    setTodos(state, action: PayloadAction<{ projectId: string; todos: AgentAppTodo[] }>) {
      state.todos[action.payload.projectId] = action.payload.todos
    },
    // One live build event from the read-only construction observer. Dedupe by
    // id (replay + live can overlap on reconnect) and cap to the ring size.
    appendBuildEvent(
      state,
      action: PayloadAction<{ projectId: string; event: AgentAppBuildEvent }>,
    ) {
      const { projectId, event } = action.payload
      // Persist the authoritative snapshot the moment it arrives, so the chips
      // survive event eviction/pacing (they read this, not the feed).
      if (event.snapshot) state.snapshots[projectId] = event.snapshot
      const stored = state.buildEvents[projectId]
      // Plain array, so the dedupe scan and copy don't proxy every event.
      const list = stored ? (isDraft(stored) ? current(stored) : stored) : []
      if (list.some(e => e.id === event.id)) return
      const next = [...list, event]
      state.buildEvents[projectId] =
        next.length > MAX_BUILD_EVENTS ? next.slice(-MAX_BUILD_EVENTS) : next
    },
    // Replay on (re)connect: replace the whole feed with the server's buffer.
    setBuildEvents(
      state,
      action: PayloadAction<{ projectId: string; events: AgentAppBuildEvent[] }>,
    ) {
      const { projectId, events } = action.payload
      state.buildEvents[projectId] = events.slice(-MAX_BUILD_EVENTS)
      for (let i = events.length - 1; i >= 0; i--) {
        if (events[i].snapshot) {
          state.snapshots[projectId] = events[i].snapshot!
          break
        }
      }
    },
    setProjectState(state, action: PayloadAction<AgentAppStateUpdate>) {
      state.states[action.payload.projectId] = action.payload.state
    },
    setActiveId(state, action: PayloadAction<string | null>) {
      state.activeId = action.payload
    },
    setCreating(state, action: PayloadAction<AgentAppStatusUpdate | null>) {
      state.creating = action.payload
    },
    markError(state, action: PayloadAction<{ projectId: string; error: string }>) {
      const { projectId, error } = action.payload
      state.creating = null
      state.projects = state.projects.map(p =>
        p.id === projectId ? { ...p, status: 'error', error } : p,
      )
    },
  },
  extraReducers: (builder) => {
    // Events may be missed while disconnected; trust the next list fully.
    builder.addCase(setConnected, (state, action) => {
      if (!action.payload) {
        state.listIsAuthoritative = true
        state.catalogLoaded = false
        state.triggerConsentRequest = null
        state.triggerConsentApproval = null
      }
    })
  },
})

export const {
  receiveTriggerBlocked,
  openTriggerReview,
  dismissTriggerReview,
  savingTriggerConsent,
  receiveTriggerConsent,
  setProjects,
  addProject,
  applyStatus,
  markReady,
  markRunning,
  markLaunching,
  markLaunchFailed,
  markStopping,
  markStopFailed,
  markStopped,
  removeProject,
  setTodos,
  appendBuildEvent,
  setBuildEvents,
  setProjectState,
  setActiveId,
  setCreating,
  markError,
} = agentAppSlice.actions

export default agentAppSlice.reducer

// --- inbound message handlers --------------------------------------------

register('agent_app_list', (data, dispatch, getState) => {
  const r = data as AgentAppListResponse
  if (r.success && r.projects) {
    dispatch(setProjects(r.projects))
    reconcileIframes(getState().agentApp.projects)
  }
})

register('agent_app_create', (data, dispatch) => {
  const r = data as AgentAppCreateResponse & { stylePack?: string }
  if (r.success && r.project) {
    dispatch(addProject(r.project))
    // Seed the per-project theme with the wizard's choice so the app opens
    // in the selected style pack (the Theme modal can still override later).
    if (r.stylePack && r.stylePack !== 'craftbot') {
      try {
        localStorage.setItem(`agentapp-theme-${r.project.id}`, r.stylePack)
      } catch { /* storage unavailable — cosmetic only */ }
    }
  }
})

register('agent_app_status', (data, dispatch) => {
  dispatch(applyStatus(data as AgentAppStatusUpdate))
})

register('agent_app_ready', (data, dispatch, getState) => {
  const ready = data as { projectId: string; url: string; port: number; sessionId?: string; triggerConsent?: AgentAppTriggerConsent }
  const exists = getState().agentApp.projects.some(p => p.id === ready.projectId)
  if (exists) {
    dispatch(markReady(ready))
  } else {
    // Project not in list yet — clear creating state and refresh the list.
    dispatch(setCreating(null))
    getSocketClient().send('agent_app_list')
  }
})

register('agent_app_launch', (data, dispatch) => {
  const r = data as AgentAppLaunchResponse
  if (!r.projectId) return
  if (r.success) {
    dispatch(markRunning({ projectId: r.projectId, url: r.url, port: r.port, triggerConsent: r.triggerConsent }))
  } else {
    // Clear the optimistic 'launching' state so the UI doesn't hang on the spinner.
    dispatch(markLaunchFailed({ projectId: r.projectId, error: r.error }))
  }
})

register('agent_app_stop', (data, dispatch) => {
  const r = data as AgentAppStopResponse
  if (!r.projectId) return
  if (r.success) {
    dispatch(markStopped({ projectId: r.projectId }))
    removeIframe(r.projectId)
  } else {
    // Stop failed — revert the optimistic 'stopping' back to 'running'.
    dispatch(markStopFailed({ projectId: r.projectId }))
  }
})

register('agent_app_delete', (data, dispatch) => {
  const r = data as AgentAppDeleteResponse
  if (r.success && r.projectId) {
    dispatch(removeProject({ projectId: r.projectId }))
    removeIframe(r.projectId)
  }
})

register('agent_app_todos', (data, dispatch) => {
  const u = data as { projectId: string; todos: AgentAppTodo[] }
  dispatch(setTodos(u))
})

register('agent_app_build_event', (data, dispatch) => {
  const u = data as { projectId: string; event: AgentAppBuildEvent }
  if (u.projectId && u.event) dispatch(appendBuildEvent(u))
})

register('agent_app_build_events_replay', (data, dispatch) => {
  const u = data as { projectId: string; events: AgentAppBuildEvent[] }
  if (u.projectId && Array.isArray(u.events)) dispatch(setBuildEvents(u))
})

register('agent_app_state_update', (data, dispatch) => {
  dispatch(setProjectState(data as AgentAppStateUpdate))
})

register('agent_app_error', (data, dispatch) => {
  dispatch(markError(data as { projectId: string; error: string }))
})


register('agent_app_trigger_consent', (data, dispatch) => {
  dispatch(receiveTriggerConsent(data as { projectId: string; requestId?: string; consent?: AgentAppTriggerConsent; success: boolean; error?: string }))
})

register('agent_app_trigger_blocked', (data, dispatch) => {
  dispatch(receiveTriggerBlocked(data as AgentAppTriggerBlocked))
})
