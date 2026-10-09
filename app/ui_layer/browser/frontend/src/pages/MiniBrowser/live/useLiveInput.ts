import { useEffect, useMemo, type MutableRefObject } from 'react'
import type {
  MiniBrowserInputEvent,
  MiniBrowserKeyModifiers,
  MiniBrowserMouseButton,
  MiniBrowserTab,
} from '../../../types'
import { sendInput } from '../useMiniBrowserSocket'
import type { FramePoint } from './geometry'

// Typed or pasted text is batched briefly, so a fast typist or a paste
// becomes a few `insert_text` calls instead of one message per character.
const TEXT_BATCH_MS = 30
// Backend limit per text event, in code points.
export const TEXT_CHUNK_CHARS = 2000
// Pointer moves: ~30/s while a button is held (drags, selections), ~15/s
// while hovering (menus, tooltips).
const MOVE_INTERVAL_PRESSED_MS = 33
const MOVE_INTERVAL_HOVER_MS = 66
const WHEEL_MAX_DELTA = 5000
// "The user is interacting" is reported at most this often.
const USER_INPUT_NOTICE_MS = 2000

/** What input is aimed at, read fresh on every event. */
export interface LiveTarget {
  /** The page is on screen (the browser is ready). */
  active: boolean
  connected: boolean
  tab: MiniBrowserTab | null
  /** The user just interacted with the page. */
  onUserInput(): void
}

/** Whether a tab is open (and not crashed) right now. Read from the store,
 *  which is already up to date while React commits a tab switch. */
export type TabOpenCheck = (tabId: string) => boolean

/** Sends one input event to one tab (the socket, or a fake in tests). */
export type InputSender = (tabId: string, event: MiniBrowserInputEvent) => boolean

/**
 * Sends the user's input to the tab it was made for, in order:
 *   - text is batched (~30 ms) for the tab it was typed in, and always
 *     flushed before any other event;
 *   - pointer moves are throttled, newest position wins;
 *   - wheel deltas are summed and sent once per animation frame.
 *
 * Input never follows the view to another tab: a batch, a drag or a pending
 * scroll belongs to the tab it started on and is delivered there, or dropped
 * once that tab is gone. When the view leaves a tab (`leaveTab`), pending
 * text goes to that tab, pending moves and scrolling are dropped, and held
 * buttons are released there (see `onLeave`). Nothing is sent (or queued)
 * while disconnected.
 */
export interface LiveInput {
  canInput(): boolean
  /** The tab that input goes to right now (null: none). */
  currentTabId(): string | null
  /** Send to the tab on screen. */
  send(event: MiniBrowserInputEvent): boolean
  /** Send to `tabId`, if it is still open (whether or not it is on screen). */
  sendTo(tabId: string, event: MiniBrowserInputEvent): boolean
  /** Queue text for `tabId` (default: the tab on screen). */
  queueText(text: string, tabId?: string | null): void
  flushText(): void
  pressKey(key: string, modifiers?: MiniBrowserKeyModifiers): void
  /** A pointer move; `heldTabId` is the tab of a held button (a drag), which
   *  the move belongs to, or null for hovering the tab on screen. */
  scheduleMove(point: FramePoint, heldTabId: string | null): void
  cancelMove(): void
  queueWheel(point: FramePoint, dx: number, dy: number): void
  /** A complete click (down + up), e.g. for a touch tap. */
  click(point: FramePoint, button: MiniBrowserMouseButton, clickCount: number): void
  noteUserInput(): void
  /** The view is leaving the tab on screen: deliver what was typed for it,
   *  drop pending moves and scrolling, and run the `onLeave` handlers. */
  leaveTab(): void
  /** Run `handler` on every leaveTab (e.g. to release a held mouse button).
   *  Returns the unsubscribe. */
  onLeave(handler: () => void): () => void
  dispose(): void
}

/** Split by code points (never inside a surrogate pair). */
export function chunkText(text: string, size: number): string[] {
  const points = Array.from(text)
  const chunks: string[] = []
  for (let i = 0; i < points.length; i += size) chunks.push(points.slice(i, i + size).join(''))
  return chunks
}

const clampDelta = (value: number): number => Math.max(-WHEEL_MAX_DELTA, Math.min(WHEEL_MAX_DELTA, value))

export function createLiveInput(
  getTarget: () => LiveTarget,
  isTabOpen: TabOpenCheck,
  sender: InputSender = sendInput,
): LiveInput {
  let text = ''
  let textTabId: string | null = null
  let textTimer: number | undefined
  let pendingMove: { point: FramePoint; tabId: string } | null = null
  let moveTimer: number | undefined
  let lastMoveAt = 0
  const wheel = { dx: 0, dy: 0, x: 0.5, y: 0.5, frame: 0, tabId: null as string | null }
  let lastNoticeAt = -Infinity
  const leaveHandlers = new Set<() => void>()

  const canInput = (): boolean => {
    const { active, connected, tab } = getTarget()
    return active && connected && !!tab && !tab.crashed
  }

  const currentTabId = (): string | null => getTarget().tab?.id ?? null

  /** Input for `tabId` can still be delivered: connected, and the tab is
   *  still open (input for a tab that closed meanwhile is dropped). */
  const deliverable = (tabId: string): boolean => {
    const { active, connected } = getTarget()
    return active && connected && isTabOpen(tabId)
  }

  const sendTo = (tabId: string, event: MiniBrowserInputEvent): boolean =>
    deliverable(tabId) && sender(tabId, event)

  const send = (event: MiniBrowserInputEvent): boolean => {
    const tabId = currentTabId()
    return tabId !== null && canInput() && sender(tabId, event)
  }

  const noteUserInput = (): void => {
    const now = performance.now()
    if (now - lastNoticeAt < USER_INPUT_NOTICE_MS) return
    lastNoticeAt = now
    getTarget().onUserInput()
  }

  const flushText = (): void => {
    window.clearTimeout(textTimer)
    textTimer = undefined
    const batch = text
    const tabId = textTabId
    text = ''
    textTabId = null
    if (!batch || !tabId) return
    for (const chunk of chunkText(batch, TEXT_CHUNK_CHARS)) {
      if (!sendTo(tabId, { kind: 'text', text: chunk })) return
    }
  }

  const queueText = (value: string, tabId: string | null = currentTabId()): void => {
    if (!value || !tabId) return
    // A batch belongs to one tab: text for another tab starts a new batch.
    if (text && textTabId !== tabId) flushText()
    textTabId = tabId
    text += value
    if (tabId === currentTabId()) noteUserInput()
    if (text.length >= TEXT_CHUNK_CHARS) flushText()
    else if (textTimer === undefined) textTimer = window.setTimeout(flushText, TEXT_BATCH_MS)
  }

  const pressKey = (key: string, modifiers?: MiniBrowserKeyModifiers): void => {
    flushText()
    send(modifiers ? { kind: 'key', key, modifiers } : { kind: 'key', key })
    noteUserInput()
  }

  const flushMove = (): void => {
    window.clearTimeout(moveTimer)
    moveTimer = undefined
    const move = pendingMove
    pendingMove = null
    if (!move) return
    lastMoveAt = performance.now()
    sendTo(move.tabId, { kind: 'mouse', action: 'move', x: move.point.x, y: move.point.y })
  }

  const cancelMove = (): void => {
    window.clearTimeout(moveTimer)
    moveTimer = undefined
    pendingMove = null
  }

  const scheduleMove = (point: FramePoint, heldTabId: string | null): void => {
    const tabId = heldTabId ?? currentTabId()
    if (!tabId) return
    // A move for another tab never waits behind (or replaces) this one.
    if (pendingMove && pendingMove.tabId !== tabId) flushMove()
    pendingMove = { point, tabId }
    const interval = heldTabId ? MOVE_INTERVAL_PRESSED_MS : MOVE_INTERVAL_HOVER_MS
    const wait = lastMoveAt + interval - performance.now()
    if (wait <= 0) flushMove()
    else if (moveTimer === undefined) moveTimer = window.setTimeout(flushMove, wait)
  }

  const cancelWheel = (): void => {
    if (wheel.frame) cancelAnimationFrame(wheel.frame)
    wheel.frame = 0
    wheel.dx = 0
    wheel.dy = 0
    wheel.tabId = null
  }

  const flushWheel = (): void => {
    wheel.frame = 0
    // Whole pixels go now; the fraction carries into the next frame.
    const dx = Math.trunc(wheel.dx)
    const dy = Math.trunc(wheel.dy)
    wheel.dx -= dx
    wheel.dy -= dy
    const tabId = wheel.tabId
    if ((!dx && !dy) || !tabId) return
    flushText()
    sendTo(tabId, { kind: 'wheel', x: wheel.x, y: wheel.y, dx: clampDelta(dx), dy: clampDelta(dy) })
  }

  const queueWheel = (point: FramePoint, dx: number, dy: number): void => {
    const tabId = currentTabId()
    if (!tabId) return
    // Scrolling meant for another tab is not carried over to this one.
    if (wheel.tabId !== tabId) cancelWheel()
    wheel.tabId = tabId
    wheel.dx += dx
    wheel.dy += dy
    wheel.x = point.x
    wheel.y = point.y
    if (!wheel.frame) wheel.frame = requestAnimationFrame(flushWheel)
    noteUserInput()
  }

  const click = (point: FramePoint, button: MiniBrowserMouseButton, clickCount: number): void => {
    flushText()
    cancelMove()
    send({ kind: 'mouse', action: 'down', x: point.x, y: point.y, button, clickCount })
    send({ kind: 'mouse', action: 'up', x: point.x, y: point.y, button, clickCount })
    noteUserInput()
  }

  const leaveTab = (): void => {
    flushText()
    cancelMove()
    cancelWheel()
    for (const handler of Array.from(leaveHandlers)) handler()
  }

  const onLeave = (handler: () => void): (() => void) => {
    leaveHandlers.add(handler)
    return () => {
      leaveHandlers.delete(handler)
    }
  }

  const dispose = (): void => {
    // Keystrokes still in the batch are delivered, not dropped.
    flushText()
    cancelMove()
    cancelWheel()
    leaveHandlers.clear()
  }

  return {
    canInput,
    currentTabId,
    send,
    sendTo,
    queueText,
    flushText,
    pressKey,
    scheduleMove,
    cancelMove,
    queueWheel,
    click,
    noteUserInput,
    leaveTab,
    onLeave,
    dispose,
  }
}

/** The live view's input sender, stable for the component's lifetime. */
export function useLiveInput(target: MutableRefObject<LiveTarget>, isTabOpen: TabOpenCheck): LiveInput {
  const input = useMemo(() => createLiveInput(() => target.current, isTabOpen), [target, isTabOpen])
  useEffect(() => () => input.dispose(), [input])
  return input
}
