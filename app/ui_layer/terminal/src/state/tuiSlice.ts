/**
 * Terminal-only state: what the browser has no equivalent for.
 *
 * Which session the chat shows, which full-screen screen is open (a stack:
 * Esc goes back one level), toasts, and what the edition handshake reported.
 */
import { createSlice, type PayloadAction } from '@reduxjs/toolkit'

export type ScreenId =
  | 'sessions'
  | 'palette'
  | 'help'
  | 'transcript'
  | 'settings'
  | 'memory'
  | 'workspace'
  | 'dashboard'
  | 'browser'
  | 'apps'
  | 'app'
  | 'appCreate'
  | 'onboarding'

export interface ScreenEntry {
  id: ScreenId
  /** Screen-specific argument, e.g. the Agent App project id. */
  arg?: string
}

export interface Toast {
  id: string
  message: string
  tone: 'info' | 'success' | 'error'
  /** Milliseconds since epoch after which it disappears; null = until dismissed. */
  expiresAt: number | null
}

export interface HelloInfo {
  protocol: number
  edition: string
  version: string
}

export interface SubagentLink {
  parentId: string | null
  agentType: string
  state: string
}

interface TuiState {
  activeSessionId: string
  /** Sub-agents by id, with the session (or sub-agent) that spawned them. */
  subagents: Record<string, SubagentLink>
  screens: ScreenEntry[]
  toasts: Toast[]
  hello: HelloInfo | null
  /** Shown once per launch until dismissed. */
  firstRunCardDismissed: boolean
  todoPanelOpen: boolean
  quitArmedAt: number | null
}

const initialState: TuiState = {
  activeSessionId: 'main',
  subagents: {},
  screens: [],
  toasts: [],
  hello: null,
  firstRunCardDismissed: false,
  todoPanelOpen: false,
  quitArmedAt: null,
}

let toastSeq = 0

const tuiSlice = createSlice({
  name: 'tui',
  initialState,
  reducers: {
    setActiveSession(state, action: PayloadAction<string>) {
      state.activeSessionId = action.payload
    },
    openScreen(state, action: PayloadAction<ScreenEntry>) {
      const top = state.screens[state.screens.length - 1]
      if (top && top.id === action.payload.id && top.arg === action.payload.arg) return
      state.screens.push(action.payload)
    },
    replaceScreen(state, action: PayloadAction<ScreenEntry>) {
      state.screens[Math.max(0, state.screens.length - 1)] = action.payload
    },
    closeScreen(state) {
      state.screens.pop()
    },
    closeAllScreens(state) {
      state.screens = []
    },
    pushToast: {
      reducer(state, action: PayloadAction<Toast>) {
        state.toasts = [...state.toasts.filter(t => t.id !== action.payload.id), action.payload].slice(-2)
      },
      prepare(message: string, tone: Toast['tone'] = 'info', ttlMs: number | null = 4000, id?: string) {
        return {
          payload: {
            id: id ?? `toast-${++toastSeq}`,
            message,
            tone,
            expiresAt: ttlMs === null ? null : Date.now() + ttlMs,
          },
        }
      },
    },
    dismissToast(state, action: PayloadAction<string>) {
      state.toasts = state.toasts.filter(t => t.id !== action.payload)
    },
    expireToasts(state, action: PayloadAction<number>) {
      state.toasts = state.toasts.filter(t => t.expiresAt === null || t.expiresAt > action.payload)
    },
    setHello(state, action: PayloadAction<HelloInfo>) {
      state.hello = action.payload
    },
    dismissFirstRunCard(state) {
      state.firstRunCardDismissed = true
    },
    toggleTodoPanel(state) {
      state.todoPanelOpen = !state.todoPanelOpen
    },
    armQuit(state, action: PayloadAction<number | null>) {
      state.quitArmedAt = action.payload
    },
    linkSubagent(state, action: PayloadAction<{ subId: string } & SubagentLink>) {
      const { subId, ...link } = action.payload
      state.subagents[subId] = link
    },
  },
})

export const {
  setActiveSession,
  openScreen,
  replaceScreen,
  closeScreen,
  closeAllScreens,
  pushToast,
  dismissToast,
  expireToasts,
  setHello,
  dismissFirstRunCard,
  toggleTodoPanel,
  armQuit,
  linkSubagent,
} = tuiSlice.actions

export default tuiSlice.reducer
