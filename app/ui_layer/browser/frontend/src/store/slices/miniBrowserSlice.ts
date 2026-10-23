import { createEntityAdapter, createSlice, type EntityState, type PayloadAction } from '@reduxjs/toolkit'
import type {
  MiniBrowserActivity,
  MiniBrowserError,
  MiniBrowserEvent,
  MiniBrowserEventLevel,
  MiniBrowserLastFrame,
  MiniBrowserOwnerKind,
  MiniBrowserSettings,
  MiniBrowserStatePayload,
  MiniBrowserStatus,
  MiniBrowserTab,
  MiniBrowserVaultEntry,
  MiniBrowserVaultStatus,
  MiniBrowserViewport,
} from '../../types'
import { register } from '../socket/messageRegistry'

// Mini Browser: every chat session has a browser of its own, shown in that
// chat's browser panel. State is kept per session (`views`); tabs live in one
// table (tab ids are unique across every session's browser), each tagged with
// its session. `activity` says, for every session, whether its browser runs
// and whether an agent is browsing in it (the chat's panel opens on that).
//
// Only low-frequency state lives here (lifecycle, tabs, vault, results).
// Screencast frames and the agent's pointer arrive many times a second and
// are deliberately NOT stored: the live view subscribes to them directly and
// paints them without a React render (components/MiniBrowser/live/).
//
// Every payload is parsed defensively — the backend is a separate process
// and a malformed field must degrade to a sane default, never crash a render.

const MAX_EVENTS = 20
const MAX_EVENT_MESSAGE_CHARS = 2000
const MAX_INSTALL_LINES = 200
const MAX_INSTALL_LINE_CHARS = 500
// A copied page selection is handed to the system clipboard and then dropped;
// the cap only guards against a pathological payload.
const MAX_CLIPBOARD_CHARS = 1_000_000

export const miniBrowserTabsAdapter = createEntityAdapter<MiniBrowserTab>()
export const miniBrowserVaultAdapter = createEntityAdapter<MiniBrowserVaultEntry>()

/** A `mini_browser_event`, numbered so views can tell new ones from old. */
export interface MiniBrowserEventEntry extends MiniBrowserEvent {
  seq: number
}

export interface MiniBrowserInstallState {
  /** Output of the current or last Chromium install, oldest first. */
  lines: string[]
  /** Bumped whenever an install finishes. */
  doneSeq: number
  /** Outcome of the last finished install; null until one finished. */
  ok: boolean | null
  error: MiniBrowserError | null
}

export interface MiniBrowserNavResultState {
  seq: number
  ok: boolean
  error: MiniBrowserError | null
}

export interface MiniBrowserVaultResultState {
  seq: number
  /** 'add' | 'update' | 'delete' | 'reset' */
  op: string
  ok: boolean
  error: MiniBrowserError | null
}

export interface MiniBrowserVaultState {
  /** A list reply arrived at least once. */
  loaded: boolean
  entries: EntityState<MiniBrowserVaultEntry, string>
  status: MiniBrowserVaultStatus | null
  error: MiniBrowserError | null
  result: MiniBrowserVaultResultState | null
}

/** One session's browser, as its panel shows it. */
export interface MiniBrowserSessionView {
  status: MiniBrowserStatus
  error: MiniBrowserError | null
  adblock: boolean | null
  viewedTabId: string | null
  follow: boolean
  viewport: MiniBrowserViewport | null
  settings: MiniBrowserSettings
  /** The session's tabs, in strip order (entities in `tabs`). */
  tabIds: string[]
  navResult: MiniBrowserNavResultState | null
}

interface MiniBrowserSliceState {
  /** Per session id; a session appears once its state was reported. */
  views: Record<string, MiniBrowserSessionView>
  /** Every session's tabs (each names its session). */
  tabs: EntityState<MiniBrowserTab, string>
  /** Per session id: its browser runs / an agent browses in it. */
  activity: Record<string, MiniBrowserActivity>
  /** Per session id: where its browser left off (none when there is no
   *  picture to show). */
  lastFrames: Record<string, MiniBrowserLastFrame>
  install: MiniBrowserInstallState
  eventSeq: number
  /** The most recent events (oldest first), capped at MAX_EVENTS. */
  events: MiniBrowserEventEntry[]
  /** Reply to the last copy request; cleared once written to the clipboard.
   *  `requestId` names the request it answers. */
  clipboard: { seq: number; text: string; requestId: string | null } | null
  vault: MiniBrowserVaultState
}

const DEFAULT_SETTINGS: MiniBrowserSettings = { humanlike: true, showCursor: true }

/** Same keys, same primitive values (for the flat objects in this slice). */
function shallowEqual(a: object | null, b: object | null): boolean {
  if (a === b) return true
  if (!a || !b) return false
  const ra = a as Record<string, unknown>
  const rb = b as Record<string, unknown>
  const keys = Object.keys(ra)
  return keys.length === Object.keys(rb).length && keys.every(key => Object.is(ra[key], rb[key]))
}

const sameIds = (a: readonly string[], b: readonly string[]): boolean =>
  a.length === b.length && a.every((id, i) => id === b[i])

const initialState: MiniBrowserSliceState = {
  views: {},
  tabs: miniBrowserTabsAdapter.getInitialState(),
  activity: {},
  lastFrames: {},
  install: { lines: [], doneSeq: 0, ok: null, error: null },
  eventSeq: 0,
  events: [],
  clipboard: null,
  vault: {
    loaded: false,
    entries: miniBrowserVaultAdapter.getInitialState(),
    status: null,
    error: null,
    result: null,
  },
}

const miniBrowserSlice = createSlice({
  name: 'miniBrowser',
  initialState,
  reducers: {
    // The backend re-sends a session's whole state on every change.
    // Unchanged parts keep their identity, so a title change in one tab
    // re-renders only what shows that tab — not the whole panel.
    applyState(state, action: PayloadAction<MiniBrowserStatePayload>) {
      const p = action.payload
      const previous = state.views[p.sessionId]
      const ids = p.tabs.map(tab => tab.id)
      const keep = new Set(ids)
      for (const id of previous?.tabIds ?? []) {
        if (!keep.has(id)) {
          delete state.tabs.entities[id]
        }
      }
      for (const tab of p.tabs) {
        if (!shallowEqual(state.tabs.entities[tab.id] ?? null, tab)) state.tabs.entities[tab.id] = tab
      }
      const allIds = state.tabs.ids.filter(id => id in state.tabs.entities)
      for (const id of ids) {
        if (!allIds.includes(id)) allIds.push(id)
      }
      if (!sameIds(state.tabs.ids, allIds)) state.tabs.ids = allIds

      if (!previous) {
        state.views[p.sessionId] = {
          status: p.status,
          error: p.error,
          adblock: p.adblock,
          viewedTabId: p.viewedTabId,
          follow: p.follow,
          viewport: p.viewport,
          settings: p.settings,
          tabIds: ids,
          navResult: null,
        }
        return
      }
      previous.status = p.status
      if (!shallowEqual(previous.error, p.error)) previous.error = p.error
      previous.adblock = p.adblock
      previous.viewedTabId = p.viewedTabId
      previous.follow = p.follow
      if (!shallowEqual(previous.viewport, p.viewport)) previous.viewport = p.viewport
      if (!shallowEqual(previous.settings, p.settings)) previous.settings = p.settings
      if (!sameIds(previous.tabIds, ids)) previous.tabIds = ids
    },
    /** `mini_browser_activity`: a snapshot replaces every entry, an update
     *  changes the sessions it names. */
    activityReceived(
      state,
      action: PayloadAction<{ sessions: MiniBrowserActivity[]; snapshot: boolean }>,
    ) {
      if (action.payload.snapshot) state.activity = {}
      for (const entry of action.payload.sessions) {
        const current = state.activity[entry.sessionId]
        if (!shallowEqual(current ?? null, entry)) state.activity[entry.sessionId] = entry
      }
    },
    /** `mini_browser_last_frame`: a session's picture of where its browser
     *  left off, or none (`frame` null). */
    lastFrameReceived(
      state,
      action: PayloadAction<{ sessionId: string; frame: MiniBrowserLastFrame | null }>,
    ) {
      const { sessionId, frame } = action.payload
      if (frame) state.lastFrames[sessionId] = frame
      else delete state.lastFrames[sessionId]
    },
    eventReceived(state, action: PayloadAction<MiniBrowserEvent>) {
      state.eventSeq += 1
      state.events.push({ ...action.payload, seq: state.eventSeq })
      if (state.events.length > MAX_EVENTS) state.events.splice(0, state.events.length - MAX_EVENTS)
    },
    /** The user asked for an install: start a fresh log. */
    installRequested(state) {
      state.install.lines = []
      state.install.ok = null
      state.install.error = null
    },
    installLine(state, action: PayloadAction<string>) {
      state.install.lines.push(action.payload)
      if (state.install.lines.length > MAX_INSTALL_LINES) {
        state.install.lines.splice(0, state.install.lines.length - MAX_INSTALL_LINES)
      }
    },
    installFinished(state, action: PayloadAction<{ ok: boolean; error: MiniBrowserError | null }>) {
      state.install.doneSeq += 1
      state.install.ok = action.payload.ok
      state.install.error = action.payload.error
    },
    navResultReceived(
      state,
      action: PayloadAction<{ sessionId: string; ok: boolean; error: MiniBrowserError | null }>,
    ) {
      const view = state.views[action.payload.sessionId]
      if (!view) return
      view.navResult = {
        seq: (view.navResult?.seq ?? 0) + 1,
        ok: action.payload.ok,
        error: action.payload.error,
      }
    },
    navResultDismissed(state, action: PayloadAction<string>) {
      const view = state.views[action.payload]
      if (view) view.navResult = null
    },
    clipboardReceived(state, action: PayloadAction<{ text: string; requestId: string | null }>) {
      state.clipboard = {
        seq: (state.clipboard?.seq ?? 0) + 1,
        text: action.payload.text,
        requestId: action.payload.requestId,
      }
    },
    /** The copied text reached the system clipboard (or was given up on). */
    clipboardConsumed(state) {
      if (state.clipboard) state.clipboard.text = ''
    },
    vaultListReceived(
      state,
      action: PayloadAction<{
        entries: MiniBrowserVaultEntry[]
        status: MiniBrowserVaultStatus | null
        error: MiniBrowserError | null
      }>,
    ) {
      state.vault.loaded = true
      miniBrowserVaultAdapter.setAll(state.vault.entries, action.payload.entries)
      state.vault.status = action.payload.status
      state.vault.error = action.payload.error
    },
    vaultResultReceived(
      state,
      action: PayloadAction<{ op: string; ok: boolean; error: MiniBrowserError | null }>,
    ) {
      state.vault.result = { seq: (state.vault.result?.seq ?? 0) + 1, ...action.payload }
    },
    /** A session was deleted: forget its browser. */
    sessionForgotten(state, action: PayloadAction<string>) {
      const view = state.views[action.payload]
      if (view) {
        for (const id of view.tabIds) delete state.tabs.entities[id]
        state.tabs.ids = state.tabs.ids.filter(id => id in state.tabs.entities)
        delete state.views[action.payload]
      }
      delete state.activity[action.payload]
      delete state.lastFrames[action.payload]
    },
  },
})

export const {
  applyState,
  activityReceived,
  lastFrameReceived,
  eventReceived,
  installRequested,
  installLine,
  installFinished,
  navResultReceived,
  navResultDismissed,
  clipboardReceived,
  clipboardConsumed,
  vaultListReceived,
  vaultResultReceived,
  sessionForgotten,
} = miniBrowserSlice.actions

export default miniBrowserSlice.reducer

// --- payload parsing -------------------------------------------------------

type Dict = Record<string, unknown>

const isDict = (v: unknown): v is Dict => typeof v === 'object' && v !== null && !Array.isArray(v)
const str = (v: unknown, fallback = ''): string => (typeof v === 'string' ? v : fallback)
const optStr = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null)
const bool = (v: unknown, fallback = false): boolean => (typeof v === 'boolean' ? v : fallback)
const optBool = (v: unknown): boolean | null => (typeof v === 'boolean' ? v : null)
const finite = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const clip = (text: string, max: number): string => (text.length > max ? `${text.slice(0, max)}…` : text)

const STATUSES: readonly MiniBrowserStatus[] = ['stopped', 'starting', 'ready', 'installing', 'error']
// A site icon is only ever an inline image (the backend loads it): a remote
// URL would make the app fetch arbitrary hosts.
const FAVICON = /^data:image\/(?:png|x-icon|gif|jpeg|webp|svg\+xml);base64,[A-Za-z0-9+/=]+$/
const OWNER_KINDS: readonly MiniBrowserOwnerKind[] = ['user', 'main', 'session', 'subagent']
const LEVELS: readonly MiniBrowserEventLevel[] = ['info', 'warning', 'error']

/** `{code, title, message}` from the backend, or null when absent/empty. */
export function parseMiniBrowserError(v: unknown): MiniBrowserError | null {
  if (typeof v === 'string') {
    return v ? { code: 'MINI_BROWSER_INTERNAL', title: '', message: v } : null
  }
  if (!isDict(v)) return null
  const code = str(v.code)
  const title = str(v.title)
  const message = str(v.message)
  if (!code && !title && !message) return null
  return { code: code || 'MINI_BROWSER_INTERNAL', title, message }
}

function parseTab(v: unknown, sessionId: string): MiniBrowserTab | null {
  if (!isDict(v)) return null
  const id = str(v.id)
  if (!id) return null
  const owner = optStr(v.owner)
  const rawKind = str(v.ownerKind)
  const ownerKind = (OWNER_KINDS as readonly string[]).includes(rawKind)
    ? (rawKind as MiniBrowserOwnerKind)
    : owner ? 'session' : 'user'
  return {
    id,
    sessionId,
    url: str(v.url, 'about:blank'),
    title: str(v.title),
    loading: bool(v.loading),
    owner,
    ownerLabel: str(v.ownerLabel),
    ownerKind,
    parentOwner: optStr(v.parentOwner),
    busy: bool(v.busy),
    userControl: bool(v.userControl),
    canGoBack: bool(v.canGoBack),
    canGoForward: bool(v.canGoForward),
    crashed: bool(v.crashed),
    favicon: typeof v.favicon === 'string' && FAVICON.test(v.favicon) ? v.favicon : null,
  }
}

function parseViewport(v: unknown): MiniBrowserViewport | null {
  if (!isDict(v)) return null
  const width = finite(v.width)
  const height = finite(v.height)
  return width && height && width > 0 && height > 0 ? { width, height } : null
}

function parseStatus(v: unknown): MiniBrowserStatus {
  const raw = str(v)
  return (STATUSES as readonly string[]).includes(raw) ? (raw as MiniBrowserStatus) : 'stopped'
}

/** A session's `mini_browser_state`; null without a session id. */
export function parseMiniBrowserState(v: unknown): MiniBrowserStatePayload | null {
  if (!isDict(v)) return null
  const sessionId = optStr(v.sessionId)
  if (!sessionId) return null
  const tabs: MiniBrowserTab[] = []
  const seen = new Set<string>()
  if (Array.isArray(v.tabs)) {
    for (const raw of v.tabs) {
      const tab = parseTab(raw, sessionId)
      if (tab && !seen.has(tab.id)) {
        seen.add(tab.id)
        tabs.push(tab)
      }
    }
  }
  const settings = isDict(v.settings) ? v.settings : {}
  const viewedTabId = optStr(v.viewedTabId)
  return {
    sessionId,
    status: parseStatus(v.status),
    error: parseMiniBrowserError(v.error),
    adblock: optBool(v.adblock),
    viewedTabId: viewedTabId && seen.has(viewedTabId) ? viewedTabId : null,
    follow: bool(v.follow, true),
    viewport: parseViewport(v.viewport),
    tabs,
    settings: {
      humanlike: bool(settings.humanlike, DEFAULT_SETTINGS.humanlike),
      showCursor: bool(settings.showCursor, DEFAULT_SETTINGS.showCursor),
    },
  }
}

function parseActivity(v: unknown): MiniBrowserActivity | null {
  if (!isDict(v)) return null
  const sessionId = optStr(v.sessionId)
  if (!sessionId) return null
  return { sessionId, status: parseStatus(v.status), browsing: bool(v.browsing) }
}

function parseEvent(v: unknown): MiniBrowserEvent | null {
  if (!isDict(v)) return null
  const kind = str(v.kind)
  if (!kind) return null
  const rawLevel = str(v.level)
  const event: MiniBrowserEvent = {
    kind,
    level: (LEVELS as readonly string[]).includes(rawLevel) ? (rawLevel as MiniBrowserEventLevel) : 'info',
    message: clip(str(v.message), MAX_EVENT_MESSAGE_CHARS),
    sessionId: optStr(v.sessionId),
  }
  const tabId = optStr(v.tabId)
  const path = optStr(v.path)
  const code = optStr(v.code)
  const title = optStr(v.title)
  if (tabId) event.tabId = tabId
  if (path) event.path = path
  if (typeof v.dangerous === 'boolean') event.dangerous = v.dangerous
  if (code) event.code = code
  if (title) event.title = clip(title, 200)
  return event
}

const timestamp = (v: unknown): string | number | null =>
  typeof v === 'string' && v !== '' ? v : finite(v)

function parseVaultEntry(v: unknown): MiniBrowserVaultEntry | null {
  if (!isDict(v)) return null
  const id = str(v.id)
  if (!id) return null
  return {
    id,
    site: str(v.site),
    username: str(v.username),
    label: str(v.label),
    kind: v.kind === 'api_key' || v.kind === 'secure_note' ? v.kind : 'login',
    group: v.group === 'work' || v.group === 'personal' ? v.group : 'other',
    createdAt: timestamp(v.createdAt),
    updatedAt: timestamp(v.updatedAt),
    lastUsedAt: timestamp(v.lastUsedAt),
  }
}

function parseVaultStatus(v: unknown): MiniBrowserVaultStatus | null {
  if (!isDict(v)) return null
  return {
    ok: bool(v.ok, true),
    unreadable: bool(v.unreadable),
    protection: v.protection === 'dpapi' ? 'dpapi' : 'file',
  }
}

/** 'mini_browser_vault_add' → 'add'; plain op names pass through. */
const normalizeVaultOp = (op: string): string => op.replace(/^mini_browser_vault_/, '')

// --- inbound message handlers --------------------------------------------

register('mini_browser_state', (data, dispatch) => {
  const parsed = parseMiniBrowserState(data)
  if (parsed) dispatch(applyState(parsed))
})

register('mini_browser_activity', (data, dispatch) => {
  if (!isDict(data)) return
  const sessions: MiniBrowserActivity[] = []
  if (Array.isArray(data.sessions)) {
    for (const raw of data.sessions) {
      const entry = parseActivity(raw)
      if (entry) sessions.push(entry)
    }
  }
  dispatch(activityReceived({ sessions, snapshot: data.snapshot === true }))
})

// Only an inline JPEG is accepted: a remote URL would make the app fetch
// arbitrary hosts.
const LAST_FRAME_IMAGE = /^data:image\/jpeg;base64,[A-Za-z0-9+/=]+$/

register('mini_browser_last_frame', (data, dispatch) => {
  if (!isDict(data)) return
  const sessionId = optStr(data.sessionId)
  if (!sessionId) return
  const width = finite(data.width)
  const height = finite(data.height)
  const image = str(data.image)
  const frame: MiniBrowserLastFrame | null =
    LAST_FRAME_IMAGE.test(image) && width && height && width > 0 && height > 0
      ? { image, width, height, url: str(data.url), title: str(data.title) }
      : null
  dispatch(lastFrameReceived({ sessionId, frame }))
})

register('mini_browser_event', (data, dispatch) => {
  const event = parseEvent(data)
  if (event) dispatch(eventReceived(event))
})

register('mini_browser_install_progress', (data, dispatch) => {
  if (!isDict(data)) return
  const line = str(data.line).trim()
  if (line) dispatch(installLine(clip(line, MAX_INSTALL_LINE_CHARS)))
  if (data.done === true) {
    const error = parseMiniBrowserError(data.error)
    dispatch(installFinished({ ok: bool(data.ok, !error) && !error, error }))
  }
})

register('mini_browser_nav_result', (data, dispatch) => {
  if (!isDict(data)) return
  const sessionId = optStr(data.sessionId)
  if (!sessionId) return
  const error = parseMiniBrowserError(data.error)
  dispatch(navResultReceived({ sessionId, ok: bool(data.ok, !error) && !error, error }))
})

register('mini_browser_clipboard', (data, dispatch) => {
  if (!isDict(data)) return
  const text = str(data.text)
  const requestId = typeof data.requestId === 'string' && data.requestId ? data.requestId : null
  dispatch(clipboardReceived({
    text: text.length > MAX_CLIPBOARD_CHARS ? text.slice(0, MAX_CLIPBOARD_CHARS) : text,
    requestId,
  }))
})

register('mini_browser_vault_list', (data, dispatch) => {
  if (!isDict(data)) return
  const entries: MiniBrowserVaultEntry[] = []
  if (Array.isArray(data.entries)) {
    for (const raw of data.entries) {
      const entry = parseVaultEntry(raw)
      if (entry) entries.push(entry)
    }
  }
  dispatch(vaultListReceived({
    entries,
    status: parseVaultStatus(data.status),
    error: parseMiniBrowserError(data.error),
  }))
})

register('mini_browser_vault_result', (data, dispatch) => {
  if (!isDict(data)) return
  const error = parseMiniBrowserError(data.error)
  dispatch(vaultResultReceived({
    op: normalizeVaultOp(str(data.op)),
    ok: bool(data.ok, !error) && !error,
    error,
  }))
})

// A deleted session's browser is gone with it (the backend deletes it too).
register('session_deleted', (data, dispatch) => {
  const sessionId = isDict(data) ? optStr(data.sessionId) : null
  if (sessionId) dispatch(sessionForgotten(sessionId))
})
