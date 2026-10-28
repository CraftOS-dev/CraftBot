/**
 * Writes the active session's final units into the terminal's scrollback,
 * each exactly once.
 *
 * The terminal shows one conversation at a time. Opening a session (a
 * switch, a new chat, a cleared conversation, a redraw) clears the screen
 * and the scrollback, then prints the welcome card, a divider and the
 * session's recent units (fetching its history first when this connection
 * has not loaded it yet); after that only newer units follow. A per-session
 * cursor remembers what was written. It lives outside React, so it survives
 * the chat root unmounting while a full-screen screen is open: units that
 * finished meanwhile are written when the chat comes back. A new chat that
 * the backend turns into a real session keeps its cursor (adoptSession), so
 * nothing prints twice.
 */
import { groupOf, renderSessionDivider, renderUnit, renderWelcome, type Group } from '../render/transcript'
import { buildUnits, type Unit } from './timeline'
import { requestHistory } from './intents'
import { selectSessionHistoryStatus, selectSessionMessages } from '../../../browser/frontend/src/store/selectors/messages'
import { selectSessionActivity } from '../../../browser/frontend/src/store/selectors/activity'
import { selectSessionBusy } from '../../../browser/frontend/src/store/selectors/agent'
import { selectSessionById } from '../../../browser/frontend/src/store/selectors/sessions'
import { onInboundMessage } from '../../../browser/frontend/src/store/socket/socketMiddleware'
import { store, type RootState } from '../state/store'
import i18n from '../platform/i18n'
import { tone } from '../theme/theme'

/** How many recent units a session shows when it is opened. */
export const REPLAY_UNITS = 20
/** Longest wait for a session's history before replaying what is loaded. */
const HISTORY_WAIT_MS = 3000
/** Erase the screen and the scrollback, cursor to the top left. */
export const CLEAR_ALL = '\u001B[2J\u001B[3J\u001B[H'

interface Cursor {
  written: Set<string>
  /**
   * Timestamp of the newest unit when the session was opened. Anything older
   * that shows up later is an older history page, never new conversation.
   */
  floorTs: number
  /** Questions that were open at opening: printed once answered, whatever their age. */
  openAtStart: Set<string>
  /** Group of the last unit printed, for the spacing between blocks. */
  lastGroup: Group | null
}

const printable = (u: Unit) => (u.kind === 'message' ? !u.open : u.final)

const cursors = new Map<string, Cursor>()
let openedSession: string | null = null
let historyAskedAt = 0
/** Something was printed already, so opening a session clears it first. */
let printedBefore = false

export function sessionTitle(state: RootState, sessionId: string): string {
  if (sessionId === 'main') return i18n.t('tui:session.main')
  if (sessionId === 'new') return i18n.t('tui:session.newChat')
  return selectSessionById(state, sessionId)?.title || i18n.t('tui:session.untitled')
}

/** Print the active session again from the top (a redraw, a width change, a clear). */
export function reopenActiveSession(): void {
  openedSession = null
}

/**
 * The backend created the real session for the open new chat: it is the
 * same conversation, so it keeps what was printed and prints no divider.
 */
export function adoptSession(from: string, to: string): void {
  const cursor = cursors.get(from)
  if (!cursor) return
  cursors.delete(from)
  cursors.set(to, cursor)
  if (openedSession === from) openedSession = to
}

// A cleared conversation (the /clear command, or clear in the sessions list)
// prints again from the top, so its old messages leave the screen.
onInboundMessage(msg => {
  if (msg.type !== 'session_cleared' && msg.type !== 'chat_clear') return
  const sessionId = (msg.data as { sessionId?: string | null } | undefined)?.sessionId ?? null
  if (sessionId === null || sessionId === store.getState().tui.activeSessionId) reopenActiveSession()
})

export function unitsOf(state: RootState, sessionId: string): Unit[] {
  return buildUnits(
    selectSessionMessages(state, sessionId),
    selectSessionActivity(state, sessionId),
    selectSessionBusy(state, sessionId),
  )
}

/**
 * What to append to scrollback for the active session now: '' when there is
 * nothing new, or while the session's history is still loading.
 */
export function pendingScrollback(state: RootState, columns: number, connected: boolean): string {
  const sessionId = state.tui.activeSessionId

  if (openedSession !== sessionId) {
    const status = selectSessionHistoryStatus(state, sessionId)
    if (sessionId !== 'new' && status !== 'fetched') {
      if (!connected) return ''
      if (status === 'unfetched') {
        requestHistory(sessionId)
        historyAskedAt = Date.now()
        return ''
      }
      if (Date.now() - historyAskedAt < HISTORY_WAIT_MS) return ''
    }
    openedSession = sessionId
    const all = unitsOf(state, sessionId)
    const units = all.filter(printable)
    const recent = units.slice(-REPLAY_UNITS)
    cursors.set(sessionId, {
      written: new Set(units.map(u => u.key)),
      floorTs: units.length ? units[units.length - 1].ts : 0,
      openAtStart: new Set(all.filter(u => u.kind === 'message' && u.open).map(u => u.key)),
      lastGroup: null,
    })
    const cursor = cursors.get(sessionId)!
    // The terminal shows one conversation: anything printed before goes,
    // scrollback included (the shell's own lines before the first one stay).
    let out = printedBefore ? CLEAR_ALL : ''
    printedBefore = true
    out += renderWelcome(
      {
        version: state.tui.hello?.version ?? '',
        agentName: state.agent.name,
        model: state.modelSettings.currentLlmModel,
      },
      columns,
    )
    out += renderSessionDivider(sessionTitle(state, sessionId), columns)
    if (units.length > recent.length) {
      out += '\n' + tone.muted(i18n.t('tui:transcript.earlier', { count: units.length - recent.length })) + '\n'
    }
    for (const unit of recent) {
      out += renderUnit(unit, columns, cursor.lastGroup)
      cursor.lastGroup = groupOf(unit)
    }
    return out
  }

  const cursor = cursors.get(sessionId)
  if (!cursor) return ''
  let out = ''
  for (const unit of unitsOf(state, sessionId)) {
    if (cursor.written.has(unit.key) || !printable(unit)) continue
    cursor.written.add(unit.key)
    if (unit.ts < cursor.floorTs && !cursor.openAtStart.has(unit.key)) continue
    out += renderUnit(unit, columns, cursor.lastGroup)
    cursor.lastGroup = groupOf(unit)
  }
  return out
}
