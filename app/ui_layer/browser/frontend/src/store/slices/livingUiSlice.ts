import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import type {
  LivingUIProject,
  LivingUIStatusUpdate,
  LivingUIStateUpdate,
  LivingUIListResponse,
  LivingUICreateResponse,
  LivingUILaunchResponse,
  LivingUIStopResponse,
  LivingUIDeleteResponse,
} from '../../types'
import { register } from '../socket/messageRegistry'
import { getSocketClient } from '../socket/socketInstance'

// Local types — these aren't in src/types but the backend sends them.
export interface LivingUITodo {
  id: string
  title: string
  completed: boolean
  assignee?: string
}

// A question the agent asked (send_message with wait_for_user_reply) mirrored
// onto the creation screen so the user can answer without the chat open. The
// on-screen answer is posted back as a reply targeting `sessionId`.
export interface LivingUIPendingQuestion {
  sessionId: string
  message: string
}

interface LivingUiState {
  projects: LivingUIProject[]
  creating: LivingUIStatusUpdate | null
  todos: Record<string, LivingUITodo[]>
  activeId: string | null
  states: Record<string, LivingUIStateUpdate['state']>
  pendingQuestions: Record<string, LivingUIPendingQuestion>
}

const initialState: LivingUiState = {
  projects: [],
  creating: null,
  todos: {},
  activeId: null,
  states: {},
  pendingQuestions: {},
}

const livingUiSlice = createSlice({
  name: 'livingUi',
  initialState,
  reducers: {
    setProjects(state, action: PayloadAction<LivingUIProject[]>) {
      state.projects = action.payload
    },
    addProject(state, action: PayloadAction<LivingUIProject>) {
      // Upsert by id: the import/marketplace flows first add a "creating"
      // placeholder, then re-broadcast the same id with real data once the
      // import completes. Replacing in place keeps a single tab. Never
      // downgrade a project that's already running.
      const incoming = action.payload
      const idx = state.projects.findIndex(p => p.id === incoming.id)
      if (idx === -1) {
        state.projects.push(incoming)
      } else if (state.projects[idx].status !== 'running') {
        state.projects[idx] = incoming
      }
    },
    applyStatus(state, action: PayloadAction<LivingUIStatusUpdate>) {
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
    markReady(state, action: PayloadAction<{ projectId: string; url: string; port: number }>) {
      const { projectId, url, port } = action.payload
      state.creating = null
      delete state.pendingQuestions[projectId]
      state.projects = state.projects.map(p =>
        p.id === projectId ? { ...p, status: 'running', url, port } : p,
      )
    },
    markRunning(state, action: PayloadAction<{ projectId: string; url?: string; port?: number }>) {
      const { projectId, url, port } = action.payload
      state.projects = state.projects.map(p =>
        p.id === projectId ? { ...p, status: 'running', url, port } : p,
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
      state.projects = state.projects.filter(p => p.id !== id)
      delete state.todos[id]
      delete state.states[id]
      delete state.pendingQuestions[id]
      if (state.activeId === id) state.activeId = null
    },
    setTodos(state, action: PayloadAction<{ projectId: string; todos: LivingUITodo[] }>) {
      state.todos[action.payload.projectId] = action.payload.todos
    },
    setProjectState(state, action: PayloadAction<LivingUIStateUpdate>) {
      state.states[action.payload.projectId] = action.payload.state
    },
    setActiveId(state, action: PayloadAction<string | null>) {
      state.activeId = action.payload
    },
    setCreating(state, action: PayloadAction<LivingUIStatusUpdate | null>) {
      state.creating = action.payload
    },
    markError(state, action: PayloadAction<{ projectId: string; error: string }>) {
      const { projectId, error } = action.payload
      state.creating = null
      delete state.pendingQuestions[projectId]
      state.projects = state.projects.map(p =>
        p.id === projectId ? { ...p, status: 'error', error } : p,
      )
    },
    setPendingQuestion(
      state,
      action: PayloadAction<{ projectId: string; sessionId: string; message: string }>,
    ) {
      const { projectId, sessionId, message } = action.payload
      state.pendingQuestions[projectId] = { sessionId, message }
    },
    clearPendingQuestion(state, action: PayloadAction<{ projectId: string }>) {
      delete state.pendingQuestions[action.payload.projectId]
    },
  },
})

export const {
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
  setProjectState,
  setActiveId,
  setCreating,
  markError,
  setPendingQuestion,
  clearPendingQuestion,
} = livingUiSlice.actions

export default livingUiSlice.reducer

// --- inbound message handlers --------------------------------------------

register('living_ui_list', (data, dispatch) => {
  const r = data as LivingUIListResponse
  if (r.success && r.projects) dispatch(setProjects(r.projects))
})

register('living_ui_create', (data, dispatch) => {
  const r = data as LivingUICreateResponse
  if (r.success && r.project) dispatch(addProject(r.project))
})

register('living_ui_status', (data, dispatch) => {
  dispatch(applyStatus(data as LivingUIStatusUpdate))
})

register('living_ui_ready', (data, dispatch, getState) => {
  const ready = data as { projectId: string; url: string; port: number }
  const exists = getState().livingUi.projects.some(p => p.id === ready.projectId)
  if (exists) {
    dispatch(markReady(ready))
  } else {
    // Project not in list yet — clear creating state and refresh the list.
    dispatch(setCreating(null))
    getSocketClient().send('living_ui_list')
  }
})

register('living_ui_launch', (data, dispatch) => {
  const r = data as LivingUILaunchResponse
  if (!r.projectId) return
  if (r.success) {
    dispatch(markRunning({ projectId: r.projectId, url: r.url, port: r.port }))
  } else {
    // Clear the optimistic 'launching' state so the UI doesn't hang on the spinner.
    dispatch(markLaunchFailed({ projectId: r.projectId, error: r.error }))
  }
})

register('living_ui_stop', (data, dispatch) => {
  const r = data as LivingUIStopResponse
  if (!r.projectId) return
  if (r.success) {
    dispatch(markStopped({ projectId: r.projectId }))
  } else {
    // Stop failed — revert the optimistic 'stopping' back to 'running'.
    dispatch(markStopFailed({ projectId: r.projectId }))
  }
})

register('living_ui_delete', (data, dispatch) => {
  const r = data as LivingUIDeleteResponse
  if (r.success && r.projectId) {
    dispatch(removeProject({ projectId: r.projectId }))
  }
})

register('living_ui_todos', (data, dispatch) => {
  const u = data as { projectId: string; todos: LivingUITodo[] }
  dispatch(setTodos(u))
})

register('living_ui_question', (data, dispatch) => {
  const u = data as { projectId: string; sessionId?: string; message?: string }
  if (u.projectId && u.sessionId && u.message) {
    dispatch(setPendingQuestion({ projectId: u.projectId, sessionId: u.sessionId, message: u.message }))
  } else if (u.projectId) {
    dispatch(clearPendingQuestion({ projectId: u.projectId }))
  }
})

register('living_ui_state_update', (data, dispatch) => {
  dispatch(setProjectState(data as LivingUIStateUpdate))
})

register('living_ui_error', (data, dispatch) => {
  dispatch(markError(data as { projectId: string; error: string }))
})

// `living_ui_data_changed` has no state — it just nudges the iframe pool to
// reload. Handled in WebSocketContext where scheduleRefreshIframe is imported.
