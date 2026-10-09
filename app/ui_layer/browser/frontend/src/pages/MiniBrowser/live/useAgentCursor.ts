import { useEffect, useRef, type RefObject } from 'react'
import type { MiniBrowserPointer } from '../../../types'
import { useLatest } from '../useLatest'
import { onLiveMessage } from '../useMiniBrowserSocket'
import { drawnImageRect } from './geometry'

// The cursor fades out when the agent's mouse has been still this long.
const CURSOR_IDLE_MS = 2500
const RIPPLE_MS = 480

/** A `mini_browser_pointer` payload (coordinates clamped to 0..1), or null. */
export function parsePointer(data: unknown): MiniBrowserPointer | null {
  if (typeof data !== 'object' || data === null) return null
  const d = data as Record<string, unknown>
  if (typeof d.tabId !== 'string' || typeof d.x !== 'number' || typeof d.y !== 'number') return null
  if (!Number.isFinite(d.x) || !Number.isFinite(d.y)) return null
  const kind = d.kind === 'down' || d.kind === 'up' || d.kind === 'click' ? d.kind : 'move'
  return { tabId: d.tabId, x: Math.min(1, Math.max(0, d.x)), y: Math.min(1, Math.max(0, d.y)), kind }
}

interface AgentCursorElements {
  stage: RefObject<HTMLElement>
  img: RefObject<HTMLImageElement>
  cursor: RefObject<HTMLElement>
  ripple: RefObject<HTMLElement>
}

/**
 * Draws the agent's mouse over the live view from `mini_browser_pointer`
 * events: the arrow glides between points (a CSS transition) and a ripple
 * marks each click. Pure DOM updates — no React render per event.
 */
export function useAgentCursor(
  elements: AgentCursorElements,
  tabId: string | null,
  enabled: boolean,
  visibleClass: string,
): void {
  const { stage, img, cursor, ripple } = elements
  const tabIdRef = useLatest(tabId)
  const enabledRef = useLatest(enabled)
  const idleTimerRef = useRef<number | undefined>(undefined)

  useEffect(() => {
    const off = onLiveMessage('mini_browser_pointer', (data) => {
      const pointer = parsePointer(data)
      if (!pointer || !enabledRef.current || pointer.tabId !== tabIdRef.current) return
      const stageEl = stage.current
      const cursorEl = cursor.current
      const drawn = drawnImageRect(img.current)
      if (!stageEl || !cursorEl || !drawn) return
      const box = stageEl.getBoundingClientRect()
      const x = drawn.left - box.left + pointer.x * drawn.width
      const y = drawn.top - box.top + pointer.y * drawn.height
      cursorEl.style.transform = `translate3d(${x}px, ${y}px, 0)`
      cursorEl.classList.add(visibleClass)
      window.clearTimeout(idleTimerRef.current)
      idleTimerRef.current = window.setTimeout(() => cursorEl.classList.remove(visibleClass), CURSOR_IDLE_MS)

      const rippleEl = ripple.current
      if ((pointer.kind === 'click' || pointer.kind === 'down') && rippleEl && typeof rippleEl.animate === 'function') {
        rippleEl.style.left = `${x}px`
        rippleEl.style.top = `${y}px`
        rippleEl.animate(
          [
            { transform: 'translate(-50%, -50%) scale(0.2)', opacity: 0.7 },
            { transform: 'translate(-50%, -50%) scale(1)', opacity: 0 },
          ],
          { duration: RIPPLE_MS, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' },
        )
      }
    })
    return () => {
      off()
      window.clearTimeout(idleTimerRef.current)
    }
  }, [cursor, enabledRef, img, ripple, stage, tabIdRef, visibleClass])

  // A different tab, or cursors turned off: hide it at once.
  useEffect(() => {
    cursor.current?.classList.remove(visibleClass)
  }, [cursor, tabId, enabled, visibleClass])
}
