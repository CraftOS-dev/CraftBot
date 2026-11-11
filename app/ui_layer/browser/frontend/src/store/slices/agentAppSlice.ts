import { createSlice, PayloadAction } from '@reduxjs/toolkit'
import { reconcileFrameworkIframes, frameworkFrameId, removeIframe } from '../../features/agentApps/frameHost'
import { setConnected } from './connectionSlice'
import type { FrameworkRegistryApp, FrameworkConnectedApp, FrameworkRegistryResponse, FrameworkAppView, FrameworkOpenResponse, FrameworkLifecycleResult } from '../../types'
import { register } from '../socket/messageRegistry'

// Local types — these aren't in src/types but the backend sends them.
// Shape mirrors the agent's todo tool: content is the imperative label,
// active_form the present-continuous label shown while in progress.
export interface AgentAppTodo {
  id: string
  content?: string
  active_form?: string
  status: 'pending' | 'in_progress' | 'completed'
}

// Authoritative "built so far" counts for the summary chips. Persisted
// separately from the (capped, paced) event feed so a flood of read/search
// events can never evict the writes that carried the snapshot.
export interface AgentAppSnapshot {
  collections: number
  components: number
  routes: number
}

interface AgentAppState {
  frameworkResolvedViews: Record<string, FrameworkAppView>
  frameworkSessions: Record<string, string>
  frameworkViews: Record<string, AgentAppState['frameworkView']>
  frameworkLifecycle: Record<string, FrameworkLifecycleResult>
  frameworkView: {
    requestId: string | null
    path: string
    appId: string
    status: 'idle' | 'loading' | 'success' | 'error'
    data: FrameworkAppView | null
    code: string | null
    message: string | null
  }
  framework: {
    hasSnapshot: boolean
    apps: FrameworkRegistryApp[]
    aliases: Record<string, string>
    connected: FrameworkConnectedApp[]
    status: 'idle' | 'loading' | 'success' | 'error'
    error: string | null
    warning: string | null
  }
  todos: Record<string, AgentAppTodo[]>
}

const initialState: AgentAppState = {
  frameworkResolvedViews: {},
  frameworkSessions: {},
  frameworkViews: {},
  frameworkLifecycle: {},
  frameworkView: { requestId: null, path: '', appId: '', status: 'idle', data: null, code: null, message: null },
  framework: { apps: [], aliases: {}, connected: [], status: 'idle', error: null, warning: null, hasSnapshot: false },
  todos: {},
}

const agentAppSlice = createSlice({
  name: 'agentApp',
  initialState,
  reducers: {
    receiveFrameworkTheme(state, action: PayloadAction<Pick<FrameworkRegistryApp, 'path' | 'id' | 'uiTheme'>>) {
      const app = state.framework.apps.find(app => app.path === action.payload.path && app.id === action.payload.id)
      if (app) app.uiTheme = action.payload.uiTheme
    },
    receiveFrameworkAttachment(state, action: PayloadAction<{ path: string; appId: string; sessionId: string }>) {
      const { path, appId, sessionId } = action.payload
      state.frameworkSessions[frameworkAppKey(path, appId)] = sessionId
    },
    invalidateFrameworkView(state, action: PayloadAction<{ path: string; appId: string }>) {
      delete state.frameworkResolvedViews[frameworkAppKey(action.payload.path, action.payload.appId)]
    },
    receiveFrameworkLifecycle(state, action: PayloadAction<FrameworkLifecycleResult>) {
      const result = action.payload
      const key = frameworkAppKey(result.path, result.appId)
      const previous = state.frameworkLifecycle[key]
      if (result.status !== 'running' && previous?.status === 'running' && previous.requestId !== result.requestId) return
      state.frameworkLifecycle[key] = result
      if (result.status === 'running') {
        delete state.frameworkResolvedViews[key]
        for (const [requestId, view] of Object.entries(state.frameworkViews)) {
          if (view.path === result.path && view.appId === result.appId) delete state.frameworkViews[requestId]
        }
      }
      if (result.status === 'running' && result.operation === 'stop') removeIframe(frameworkFrameId(result.path, result.appId))
      if (result.status === 'running' && state.frameworkView.path === result.path && state.frameworkView.appId === result.appId) {
        state.frameworkView.requestId = null
        state.frameworkView.status = 'idle'
      }
    },
    requestFrameworkOpen(state, action: PayloadAction<{ requestId: string; path: string; appId: string }>) {
      const previous = state.frameworkView
      const same = previous.path === action.payload.path && previous.appId === action.payload.appId
      state.frameworkView = { ...action.payload, status: 'loading', data: same ? previous.data : null, code: null, message: null }
      state.frameworkViews[action.payload.requestId] = { ...state.frameworkView }
    },
    cancelFrameworkOpen(state, action: PayloadAction<string>) {
      delete state.frameworkViews[action.payload]
      if (state.frameworkView.requestId === action.payload) {
        state.frameworkView.requestId = null
        state.frameworkView.status = 'idle'
      }
    },
    receiveFrameworkOpen(state, action: PayloadAction<FrameworkOpenResponse>) {
      const result = action.payload
      const view = state.frameworkViews[result.requestId] || state.frameworkView
      if (view.requestId !== result.requestId || view.status !== 'loading') return
      view.status = result.status
      if (result.status === 'success' && result.data.id === view.appId && result.data.path === view.path) {
        view.data = result.data
        state.frameworkResolvedViews[frameworkAppKey(view.path, view.appId)] = result.data
      } else {
        delete state.frameworkResolvedViews[frameworkAppKey(view.path, view.appId)]
        view.status = 'error'
        view.data = null
        view.code = result.status === 'error' ? result.code : 'identity_changed'
        view.message = result.status === 'error' ? result.message : null
      }
      if (state.frameworkView.requestId === result.requestId) state.frameworkView = { ...view }
    },
    receiveFrameworkList(state, action: PayloadAction<FrameworkRegistryResponse>) {
      const result = action.payload
      // Keep the last authoritative list usable during a background refresh.
      if (result.status === 'loading' && state.framework.hasSnapshot) return
      state.framework.status = result.status
      if (result.status === 'success') {
        state.framework.hasSnapshot = true
        const registered = new Set(result.data.apps.map(app => frameworkAppKey(app.path, app.id)))
        const running = new Set(result.data.apps.filter(app => app.status === 'running').map(app => frameworkAppKey(app.path, app.id)))
        for (const key of Object.keys(state.frameworkResolvedViews)) {
          const app = result.data.apps.find(app => frameworkAppKey(app.path, app.id) === key)
          const previous = state.framework.apps.find(app => frameworkAppKey(app.path, app.id) === key)
          if (!running.has(key) || (app?.port !== previous?.port)) {
            delete state.frameworkResolvedViews[key]
            if (app?.port !== previous?.port && app) removeIframe(frameworkFrameId(app.path, app.id))
          }
        }
        for (const key of Object.keys(state.frameworkSessions)) {
          if (!registered.has(key)) delete state.frameworkSessions[key]
        }
        reconcileFrameworkIframes(result.data.apps)
        state.framework.apps = result.data.apps
        state.framework.aliases = result.data.aliases || {}
        state.framework.connected = result.data.connected
        state.framework.error = null
        state.framework.warning = result.stderr?.trim() || null
      } else if (result.status === 'error') {
        // Keep the last successful snapshot, explicitly marked stale in the UI.
        state.framework.error = result.message
      }
    },
    setTodos(state, action: PayloadAction<{ projectId: string; todos: AgentAppTodo[] }>) {
      state.todos[action.payload.projectId] = action.payload.todos
    },
  },
  extraReducers: (builder) => {
    // Events may be missed while disconnected; trust the next list fully.
    builder.addCase(setConnected, (state, action) => {
      if (!action.payload) {
        state.frameworkResolvedViews = {}
        state.frameworkSessions = {}
        state.frameworkViews = {}
        for (const operation of Object.values(state.frameworkLifecycle)) {
          if (operation.status === 'running') operation.status = 'unknown'
        }
        state.frameworkView.requestId = null
        state.frameworkView.status = 'idle'
        state.framework.status = 'idle'
      }
    })
  },
})
export const { receiveFrameworkTheme, receiveFrameworkAttachment, invalidateFrameworkView, receiveFrameworkLifecycle, requestFrameworkOpen, cancelFrameworkOpen, receiveFrameworkOpen, receiveFrameworkList, setTodos } = agentAppSlice.actions

export default agentAppSlice.reducer

export function frameworkAppKey(path: string, id: string) { return JSON.stringify([path, id]) }

// --- inbound message handlers --------------------------------------------

register('agent_app_framework_lifecycle', (data, dispatch) => {
  dispatch(receiveFrameworkLifecycle(data as FrameworkLifecycleResult))
})

register('agent_app_framework_open', (data, dispatch) => {
  dispatch(receiveFrameworkOpen(data as FrameworkOpenResponse))
})

register('agent_app_framework_list', (data, dispatch) => {
  dispatch(receiveFrameworkList(data as FrameworkRegistryResponse))
})

register('agent_app_todos', (data, dispatch) => {
  const u = data as { projectId: string; todos: AgentAppTodo[] }
  dispatch(setTodos(u))
})
