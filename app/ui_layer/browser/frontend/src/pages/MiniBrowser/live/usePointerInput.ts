import { useEffect, type MutableRefObject, type RefObject } from 'react'
import type { MiniBrowserFrame, MiniBrowserMouseButton, MiniBrowserTab } from '../../../types'
import { drawnImageRect, toFramePoint, type FramePoint } from './geometry'
import type { LiveInput } from './useLiveInput'

const WHEEL_LINE_PX = 16
// Touch: tap = click, drag = scroll, long press = right click.
const TAP_SLOP_PX = 10
const LONG_PRESS_MS = 550
const DOUBLE_TAP_MS = 350

const MOUSE_BUTTONS: Record<number, MiniBrowserMouseButton | undefined> = {
  0: 'left',
  1: 'middle',
  2: 'right',
}
const BROWSER_BACK_BUTTON = 3
const BROWSER_FORWARD_BUTTON = 4

const clampClicks = (detail: number): number => Math.min(3, Math.max(1, detail || 1))

export interface PointerTarget {
  tab: MiniBrowserTab | null
  onHistory(action: 'back' | 'forward'): void
}

interface PointerOptions {
  stage: RefObject<HTMLElement>
  img: RefObject<HTMLImageElement>
  input: LiveInput
  /** The frame on screen: its CSS-px size converts wheel/touch deltas. */
  shownFrame: MutableRefObject<MiniBrowserFrame | null>
  target: MutableRefObject<PointerTarget>
  /** Give the page the keyboard (and park the IME sink at the click). */
  focusAt(clientX: number, clientY: number): void
}

interface TouchGesture {
  pointerId: number
  startX: number
  startY: number
  lastX: number
  lastY: number
  point: FramePoint
  moved: boolean
  /** The long-press right click already fired. */
  handled: boolean
  timer: number
}

/**
 * Mouse, wheel and touch on the live view, bound natively once.
 *
 * Mouse: down/up carry the button and click count (`detail`, so double and
 * triple clicks select words and lines), moves are throttled, a drag keeps
 * going outside the stage, right-click goes to the page (no native menu) and
 * the back/forward mouse buttons drive the page's history. Clicks on the
 * letterbox bars are ignored. Wheel: deltaMode-normalized, Shift turns it
 * sideways, Ctrl+wheel (zoom) stays with the app. Touch: tap = click, drag =
 * scroll, long press = right click.
 */
export function usePointerInput({ stage, img, input, shownFrame, target, focusAt }: PointerOptions): void {
  useEffect(() => {
    const stageEl = stage.current
    if (!stageEl) return

    const framePoint = (clientX: number, clientY: number, clamp: boolean): FramePoint | null => {
      const drawn = drawnImageRect(img.current)
      return drawn ? toFramePoint(drawn, clientX, clientY, clamp) : null
    }
    // Hovering must not take a working agent's tab away from it: only
    // deliberate input (a click, the wheel, keys) does that.
    const canHover = (): boolean => {
      const tab = target.current.tab
      if (!tab || !input.canInput()) return false
      return tab.userControl || !tab.busy || tab.ownerKind === 'user'
    }

    // ── Mouse ────────────────────────────────────────────────────────────
    let pressed: { button: MiniBrowserMouseButton; clicks: number; last: FramePoint } | null = null

    const release = (point: FramePoint, clicks: number) => {
      const held = pressed
      pressed = null
      window.removeEventListener('mousemove', onDragMove, true)
      window.removeEventListener('mouseup', onDragEnd, true)
      window.removeEventListener('blur', onWindowBlur)
      input.cancelMove()
      if (held) input.send({ kind: 'mouse', action: 'up', x: point.x, y: point.y, button: held.button, clickCount: clicks })
    }

    const onMouseDown = (e: MouseEvent) => {
      if (e.button === BROWSER_BACK_BUTTON || e.button === BROWSER_FORWARD_BUTTON) {
        e.preventDefault()
        return
      }
      const button = MOUSE_BUTTONS[e.button]
      if (!button) return
      // No host text selection, focus change or middle-click autoscroll.
      e.preventDefault()
      if (pressed || !input.canInput()) return
      const point = framePoint(e.clientX, e.clientY, false)
      if (!point) return // a letterbox bar
      focusAt(e.clientX, e.clientY)
      input.flushText()
      input.cancelMove()
      const clicks = clampClicks(e.detail)
      pressed = { button, clicks, last: point }
      input.send({ kind: 'mouse', action: 'down', x: point.x, y: point.y, button, clickCount: clicks })
      input.noteUserInput()
      window.addEventListener('mousemove', onDragMove, true)
      window.addEventListener('mouseup', onDragEnd, true)
      window.addEventListener('blur', onWindowBlur)
    }

    const onDragMove = (e: MouseEvent) => {
      if (!pressed) return
      const point = framePoint(e.clientX, e.clientY, true)
      if (!point) return
      pressed.last = point
      input.scheduleMove(point, true)
    }

    const onDragEnd = (e: MouseEvent) => {
      if (!pressed || MOUSE_BUTTONS[e.button] !== pressed.button) return
      release(framePoint(e.clientX, e.clientY, true) ?? pressed.last, clampClicks(e.detail || pressed.clicks))
    }

    // The window lost focus mid-drag: never leave the page's button held.
    const onWindowBlur = () => {
      if (pressed) release(pressed.last, pressed.clicks)
    }

    const onHover = (e: MouseEvent) => {
      if (pressed || !canHover()) return
      const point = framePoint(e.clientX, e.clientY, false)
      if (point) input.scheduleMove(point, false)
    }

    // Left to the host, the back/forward mouse buttons would navigate
    // CraftBot itself; they drive the page's history instead.
    const onMouseUp = (e: MouseEvent) => {
      if (e.button !== BROWSER_BACK_BUTTON && e.button !== BROWSER_FORWARD_BUTTON) return
      e.preventDefault()
      if (input.canInput()) target.current.onHistory(e.button === BROWSER_BACK_BUTTON ? 'back' : 'forward')
    }
    const preventDefault = (e: Event) => e.preventDefault()

    // ── Wheel ────────────────────────────────────────────────────────────
    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey) return // pinch / Ctrl+wheel zooms the app
      const point = framePoint(e.clientX, e.clientY, false)
      if (!point) return
      e.preventDefault()
      if (!input.canInput()) return
      const pageHeight = shownFrame.current?.height || stageEl.clientHeight
      const unit = e.deltaMode === 1 ? WHEEL_LINE_PX : e.deltaMode === 2 ? pageHeight : 1
      let dx = e.deltaX * unit
      let dy = e.deltaY * unit
      // Shift+wheel scrolls sideways (Windows/Linux mice report it as dy).
      if (e.shiftKey && dx === 0) {
        dx = dy
        dy = 0
      }
      input.queueWheel(point, dx, dy)
    }

    // ── Touch ────────────────────────────────────────────────────────────
    let touch: TouchGesture | null = null
    let lastTap: { at: number; x: number; y: number; clicks: number } | null = null

    const endTouch = () => {
      if (touch) window.clearTimeout(touch.timer)
      touch = null
    }

    const onPointerDown = (e: PointerEvent) => {
      if (e.pointerType !== 'touch') return
      e.preventDefault() // no emulated mouse events for this touch
      if (!e.isPrimary) {
        endTouch() // a second finger: neither a tap nor a scroll
        return
      }
      if (!input.canInput()) return
      const point = framePoint(e.clientX, e.clientY, false)
      if (!point) return
      try {
        stageEl.setPointerCapture(e.pointerId)
      } catch {
        // Not capturable (already released): the gesture still works.
      }
      const gesture: TouchGesture = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        lastX: e.clientX,
        lastY: e.clientY,
        point,
        moved: false,
        handled: false,
        timer: 0,
      }
      gesture.timer = window.setTimeout(() => {
        if (touch !== gesture || gesture.moved) return
        gesture.handled = true
        input.click(gesture.point, 'right', 1)
      }, LONG_PRESS_MS)
      touch = gesture
    }

    const onPointerMove = (e: PointerEvent) => {
      if (!touch || e.pointerId !== touch.pointerId) return
      if (!touch.moved && Math.hypot(e.clientX - touch.startX, e.clientY - touch.startY) > TAP_SLOP_PX) {
        touch.moved = true
        window.clearTimeout(touch.timer)
      }
      if (touch.moved && !touch.handled) {
        // The content follows the finger: screen px → page CSS px.
        const drawn = drawnImageRect(img.current)
        const cssWidth = shownFrame.current?.width
        const scale = drawn && cssWidth ? drawn.width / cssWidth : 1
        const point = framePoint(e.clientX, e.clientY, true) ?? touch.point
        input.queueWheel(point, (touch.lastX - e.clientX) / scale, (touch.lastY - e.clientY) / scale)
      }
      touch.lastX = e.clientX
      touch.lastY = e.clientY
    }

    const onPointerUp = (e: PointerEvent) => {
      if (!touch || e.pointerId !== touch.pointerId) return
      const gesture = touch
      endTouch()
      if (gesture.moved || gesture.handled) return
      const now = performance.now()
      const repeat =
        lastTap !== null &&
        now - lastTap.at < DOUBLE_TAP_MS &&
        Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) < TAP_SLOP_PX * 2
      const clicks = repeat && lastTap ? Math.min(3, lastTap.clicks + 1) : 1
      lastTap = { at: now, x: e.clientX, y: e.clientY, clicks }
      input.click(gesture.point, 'left', clicks)
    }

    const onPointerCancel = (e: PointerEvent) => {
      if (touch && e.pointerId === touch.pointerId) endTouch()
    }

    const listeners: Array<[string, EventListener, AddEventListenerOptions?]> = [
      ['mousedown', onMouseDown as EventListener],
      ['mousemove', onHover as EventListener],
      ['mouseup', onMouseUp as EventListener],
      ['auxclick', preventDefault],
      ['contextmenu', preventDefault],
      ['dragstart', preventDefault],
      // A file dropped on the view must not make the host open it (and
      // navigate CraftBot away).
      ['dragover', preventDefault],
      ['drop', preventDefault],
      ['wheel', onWheel as EventListener, { passive: false }],
      ['pointerdown', onPointerDown as EventListener],
      ['pointermove', onPointerMove as EventListener],
      ['pointerup', onPointerUp as EventListener],
      ['pointercancel', onPointerCancel as EventListener],
    ]
    for (const [type, listener, options] of listeners) stageEl.addEventListener(type, listener, options)
    return () => {
      if (pressed) release(pressed.last, pressed.clicks)
      endTouch()
      for (const [type, listener] of listeners) stageEl.removeEventListener(type, listener)
    }
  }, [stage, img, input, shownFrame, target, focusAt])
}
