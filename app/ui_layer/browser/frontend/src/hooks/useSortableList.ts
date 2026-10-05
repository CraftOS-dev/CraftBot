import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent as ReactDragEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from 'react'

/** Pointer travel (px) before a press on a row turns into a drag. */
const DRAG_THRESHOLD = 5
/** Distance (px) from the scroll container's edge where auto-scroll kicks in. */
const AUTO_SCROLL_EDGE = 36
/** Max auto-scroll speed in px per frame, reached at the very edge. */
const AUTO_SCROLL_SPEED = 12

interface DragState {
  id: string
  /** How far the dragged row has travelled, in content px (includes auto-scroll). */
  offset: number
  /** Index of the dragged row in the drag-start snapshot. */
  from: number
  /** Index it would drop at. */
  to: number
  /** Distance between adjacent rows: the dragged row's height plus the list gap. */
  pitch: number
  /** Ids at drag start; rows mounted mid-drag (pagination) are left in place. */
  ids: string[]
}

interface SortableListOptions {
  /** Ids of the rendered rows, in display order. */
  ids: string[]
  /** Called on drop with the rendered ids in their new order. */
  onReorder: (ids: string[]) => void
  /** The scrolling ancestor, auto-scrolled while dragging near its edges. */
  scrollRef: RefObject<HTMLElement>
}

/**
 * Drag-to-reorder for a vertical list, built on pointer events. (Native HTML5
 * drag and drop won't start from a <button> in Firefox, and every sidebar row
 * is mostly button.)
 *
 * Press the handle and move a few px: the row lifts and follows the pointer,
 * and its neighbours slide aside to show where it will land. Release to drop,
 * or press Escape to cancel. Rows stay where they are in the DOM until the
 * drop, when `onReorder` receives the new order. The click that would follow
 * the drop is swallowed, so dropping a row doesn't also open it.
 *
 * Mouse and pen only: on touch, a swipe across the list still scrolls it.
 */
export function useSortableList({ ids, onReorder, scrollRef }: SortableListOptions) {
  const [drag, setDrag] = useState<DragState | null>(null)
  const rowEls = useRef(new Map<string, HTMLElement>())
  const refCallbacks = useRef(new Map<string, (el: HTMLElement | null) => void>())
  const idsRef = useRef(ids)
  idsRef.current = ids
  const onReorderRef = useRef(onReorder)
  onReorderRef.current = onReorder
  // Tears down the in-flight press/drag; also run on unmount.
  const cleanupRef = useRef<(() => void) | null>(null)

  useEffect(() => () => cleanupRef.current?.(), [])

  const rowRef = useCallback((id: string) => {
    let cb = refCallbacks.current.get(id)
    if (!cb) {
      cb = (el: HTMLElement | null) => {
        if (el) rowEls.current.set(id, el)
        else rowEls.current.delete(id)
      }
      refCallbacks.current.set(id, cb)
    }
    return cb
  }, [])

  const onPointerDown = (e: ReactPointerEvent, id: string) => {
    if (e.button !== 0 || e.pointerType === 'touch') return
    if (idsRef.current.length < 2) return
    cleanupRef.current?.()

    const pointerId = e.pointerId
    const startClientY = e.clientY
    let clientY = e.clientY
    let rafId = 0

    // Filled in when the press crosses the threshold and becomes a drag.
    let snapshot: string[] = []
    let rects: { top: number; bottom: number }[] = []
    let from = -1
    let pitch = 0
    let startScrollTop = 0
    let to = -1
    // Escape drops the row back in place; the release that follows is then
    // only swallowed, never treated as a drop or a click.
    let cancelled = false

    const begin = (): boolean => {
      snapshot = idsRef.current.slice()
      from = snapshot.indexOf(id)
      if (from < 0) return false
      rects = []
      for (const rowId of snapshot) {
        const el = rowEls.current.get(rowId)
        if (!el) return false
        const r = el.getBoundingClientRect()
        rects.push({ top: r.top, bottom: r.bottom })
      }
      const neighbour = from + 1 < rects.length ? from + 1 : from - 1
      const gap = neighbour > from
        ? rects[neighbour].top - rects[from].bottom
        : rects[from].top - rects[neighbour].bottom
      pitch = rects[from].bottom - rects[from].top + gap
      startScrollTop = scrollRef.current?.scrollTop ?? 0
      to = from
      return true
    }

    const update = () => {
      const scrollDelta = (scrollRef.current?.scrollTop ?? 0) - startScrollTop
      // Keep the lifted row within the list's own bounds.
      const minOffset = rects[0].top - rects[from].top
      const maxOffset = rects[rects.length - 1].bottom - rects[from].bottom
      const offset = Math.max(minOffset, Math.min(maxOffset, clientY - startClientY + scrollDelta))
      const center = (rects[from].top + rects[from].bottom) / 2 + offset
      // A row counts as passed once the dragged row's center reaches its
      // midpoint. Ties go to the direction of travel, so the clamped row can
      // still claim the first and last slots.
      to = 0
      rects.forEach((r, i) => {
        const mid = (r.top + r.bottom) / 2
        if (i < from ? mid < center : i > from && mid <= center) to += 1
      })
      setDrag({ id, offset, from, to, pitch, ids: snapshot })
    }

    const autoScroll = () => {
      const scrollEl = scrollRef.current
      if (scrollEl) {
        const box = scrollEl.getBoundingClientRect()
        let step = 0
        if (clientY < box.top + AUTO_SCROLL_EDGE) {
          step = -Math.ceil(((box.top + AUTO_SCROLL_EDGE - clientY) / AUTO_SCROLL_EDGE) * AUTO_SCROLL_SPEED)
        } else if (clientY > box.bottom - AUTO_SCROLL_EDGE) {
          step = Math.ceil(((clientY - (box.bottom - AUTO_SCROLL_EDGE)) / AUTO_SCROLL_EDGE) * AUTO_SCROLL_SPEED)
        }
        if (step !== 0) {
          const before = scrollEl.scrollTop
          scrollEl.scrollTop = before + Math.max(-AUTO_SCROLL_SPEED, Math.min(AUTO_SCROLL_SPEED, step))
          if (scrollEl.scrollTop !== before) update()
        }
      }
      rafId = requestAnimationFrame(autoScroll)
    }

    const active = () => from >= 0

    const onMove = (ev: PointerEvent) => {
      if (ev.pointerId !== pointerId || cancelled) return
      clientY = ev.clientY
      if (!active()) {
        if (Math.abs(clientY - startClientY) < DRAG_THRESHOLD) return
        if (!begin()) {
          cleanup()
          return
        }
        rafId = requestAnimationFrame(autoScroll)
      }
      update()
    }

    const onUp = (ev: PointerEvent) => {
      if (ev.pointerId !== pointerId) return
      const wasActive = active()
      cleanup()
      if (!wasActive) return
      swallowNextClick()
      if (!cancelled && to !== from) {
        const next = snapshot.slice()
        next.splice(to, 0, ...next.splice(from, 1))
        onReorderRef.current(next)
      }
    }

    const onCancel = (ev: PointerEvent) => {
      if (ev.pointerId === pointerId) cleanup()
    }

    const onKeyDown = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape' && active() && !cancelled) {
        ev.preventDefault()
        ev.stopPropagation()
        cancelled = true
        cancelAnimationFrame(rafId)
        setDrag(null)
      }
    }

    function cleanup() {
      cancelAnimationFrame(rafId)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onCancel)
      window.removeEventListener('keydown', onKeyDown, true)
      cleanupRef.current = null
      setDrag(null)
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onCancel)
    window.addEventListener('keydown', onKeyDown, true)
    cleanupRef.current = cleanup
  }

  /** Inline style for a row: lifted, shifted aside, or untouched. */
  const rowStyle = (id: string): CSSProperties | undefined => {
    if (!drag) return undefined
    if (id === drag.id) {
      // No inline transition: the row must track the pointer, and leaving it
      // unset lets a stylesheet ease other properties (e.g. a `rotate` tilt).
      return { transform: `translateY(${drag.offset}px)`, zIndex: 5 }
    }
    const i = drag.ids.indexOf(id)
    if (i < 0) return undefined
    let shift = 0
    if (drag.from < drag.to && i > drag.from && i <= drag.to) shift = -drag.pitch
    else if (drag.to < drag.from && i >= drag.to && i < drag.from) shift = drag.pitch
    // The transition lives only in this inline style so it vanishes together
    // with the transform on drop; the reordered rows then land without
    // re-animating from their shifted positions.
    return { transform: shift ? `translateY(${shift}px)` : undefined, transition: 'transform 150ms ease' }
  }

  return {
    /** Id of the row being dragged, or null. */
    draggingId: drag?.id ?? null,
    rowRef,
    rowStyle,
    /** Spread onto the element that starts a drag (the row's main button). */
    handleProps: (id: string) => ({
      onPointerDown: (e: ReactPointerEvent) => onPointerDown(e, id),
      // Stop the browser's own image/text drag (e.g. from an app icon <img>),
      // which would cancel the pointer stream mid-drag.
      onDragStart: (e: ReactDragEvent) => e.preventDefault(),
    }),
  }
}

/** Swallows the click the browser fires right after a drop or cancel. */
function swallowNextClick() {
  const swallow = (ev: MouseEvent) => {
    ev.stopPropagation()
    ev.preventDefault()
  }
  window.addEventListener('click', swallow, { capture: true, once: true })
  // pointerup → click run in the same task; if no click comes, stop waiting.
  setTimeout(() => window.removeEventListener('click', swallow, { capture: true }), 0)
}

/**
 * Sorts `items` by a saved id order. Items the order doesn't mention yet
 * (created since the last reorder) keep their natural order and go first or
 * last, matching where new items show up in that list.
 */
export function applySavedOrder<T>(
  items: T[],
  order: string[],
  getId: (item: T) => string,
  unsorted: 'first' | 'last',
): T[] {
  if (order.length === 0) return items
  const rank = new Map(order.map((id, i) => [id, i]))
  const known: T[] = []
  const fresh: T[] = []
  for (const item of items) (rank.has(getId(item)) ? known : fresh).push(item)
  if (known.length === 0) return items
  known.sort((a, b) => rank.get(getId(a))! - rank.get(getId(b))!)
  return unsorted === 'first' ? [...fresh, ...known] : [...known, ...fresh]
}
