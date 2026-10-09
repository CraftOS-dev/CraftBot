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

/**
 * Sends the user's input to the viewed tab, in order:
 *   - text is batched (~30 ms) and always flushed before any other event;
 *   - pointer moves are throttled, newest position wins;
 *   - wheel deltas are summed and sent once per animation frame.
 * Nothing is sent (or queued) while disconnected.
 */
export interface LiveInput {
  canInput(): boolean
  send(event: MiniBrowserInputEvent): boolean
  queueText(text: string): void
  flushText(): void
  pressKey(key: string, modifiers?: MiniBrowserKeyModifiers): void
  scheduleMove(point: FramePoint, pressed: boolean): void
  cancelMove(): void
  queueWheel(point: FramePoint, dx: number, dy: number): void
  /** A complete click (down + up), e.g. for a touch tap. */
  click(point: FramePoint, button: MiniBrowserMouseButton, clickCount: number): void
  noteUserInput(): void
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

export function createLiveInput(getTarget: () => LiveTarget): LiveInput {
  let text = ''
  let textTimer: number | undefined
  let pendingMove: FramePoint | null = null
  let moveTimer: number | undefined
  let lastMoveAt = 0
  const wheel = { dx: 0, dy: 0, x: 0.5, y: 0.5, frame: 0 }
  let lastNoticeAt = -Infinity

  const canInput = (): boolean => {
    const { active, connected, tab } = getTarget()
    return active && connected && !!tab && !tab.crashed
  }

  const send = (event: MiniBrowserInputEvent): boolean => {
    const { tab } = getTarget()
    if (!tab || !canInput()) return false
    return sendInput(tab.id, event)
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
    text = ''
    if (!batch) return
    for (const chunk of chunkText(batch, TEXT_CHUNK_CHARS)) send({ kind: 'text', text: chunk })
  }

  const queueText = (value: string): void => {
    if (!value) return
    text += value
    noteUserInput()
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
    const point = pendingMove
    pendingMove = null
    if (!point) return
    lastMoveAt = performance.now()
    send({ kind: 'mouse', action: 'move', x: point.x, y: point.y })
  }

  const cancelMove = (): void => {
    window.clearTimeout(moveTimer)
    moveTimer = undefined
    pendingMove = null
  }

  const scheduleMove = (point: FramePoint, pressed: boolean): void => {
    pendingMove = point
    const wait = lastMoveAt + (pressed ? MOVE_INTERVAL_PRESSED_MS : MOVE_INTERVAL_HOVER_MS) - performance.now()
    if (wait <= 0) flushMove()
    else if (moveTimer === undefined) moveTimer = window.setTimeout(flushMove, wait)
  }

  const flushWheel = (): void => {
    wheel.frame = 0
    // Whole pixels go now; the fraction carries into the next frame.
    const dx = Math.trunc(wheel.dx)
    const dy = Math.trunc(wheel.dy)
    wheel.dx -= dx
    wheel.dy -= dy
    if (!dx && !dy) return
    flushText()
    send({ kind: 'wheel', x: wheel.x, y: wheel.y, dx: clampDelta(dx), dy: clampDelta(dy) })
  }

  const queueWheel = (point: FramePoint, dx: number, dy: number): void => {
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

  const dispose = (): void => {
    // Keystrokes still in the batch are delivered, not dropped.
    flushText()
    cancelMove()
    cancelAnimationFrame(wheel.frame)
    wheel.frame = 0
  }

  return {
    canInput,
    send,
    queueText,
    flushText,
    pressKey,
    scheduleMove,
    cancelMove,
    queueWheel,
    click,
    noteUserInput,
    dispose,
  }
}

/** The live view's input sender, stable for the component's lifetime. */
export function useLiveInput(target: MutableRefObject<LiveTarget>): LiveInput {
  const input = useMemo(() => createLiveInput(() => target.current), [target])
  useEffect(() => () => input.dispose(), [input])
  return input
}
