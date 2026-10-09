import React, { memo, useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type RefObject } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import { Chat } from '../../components/Chat'
import { usePersistedState } from '../../hooks'
import { UI_STATE } from '../../store/uiState'
import styles from './ChatPanel.module.css'

// Panel bounds (desktop: px width; mobile: share of the height). Dragging the
// panel below the COLLAPSE size snaps it shut — "drag it away to hide it".
const PANEL_MIN_WIDTH = 280
const PANEL_MAX_WIDTH = 640
const PANEL_COLLAPSE_WIDTH = 200
// The browser keeps at least this much room next to the chat.
const BROWSER_MIN_WIDTH = 360
// Narrower than this, the two can't sit side by side at their minimums
// (e.g. a ~800 px window with the sidebar open): the chat moves under the
// browser, collapsed until the user opens it.
export const SIDE_BY_SIDE_MIN_WIDTH = PANEL_MIN_WIDTH + BROWSER_MIN_WIDTH
const MOBILE_MIN_RATIO = 0.2
const MOBILE_MAX_RATIO = 0.8
const MOBILE_COLLAPSE_RATIO = 0.08
const SEAM_KEY_STEP_PX = 24
const SEAM_KEY_STEP_RATIO = 0.05
const DRAG_THRESHOLD_PX = 4
// Matches the layout's mobile breakpoint, where the panels stack.
const MOBILE_QUERY = '(max-width: 768px)'

const clamp = (value: number, min: number, max: number): number => Math.min(max, Math.max(min, value))

/** Widest the panel may be in a row `total` px wide. */
const maxPanelWidth = (total: number): number =>
  total > 0 ? clamp(total - BROWSER_MIN_WIDTH, PANEL_MIN_WIDTH, PANEL_MAX_WIDTH) : PANEL_MAX_WIDTH

/** The chat itself. Memoized: browser state re-renders the page often, and
 *  the chat is the heaviest thing on it. */
const ChatPane = memo(function ChatPane({ sessionId, placeholder, loadingText }: {
  sessionId: string | null
  placeholder: string
  loadingText: string
}) {
  if (!sessionId) {
    return (
      <div className={styles.chatLoading} role="status">
        <Loader2 size={18} className={styles.spin} />
        <span>{loadingText}</span>
      </div>
    )
  }
  return <Chat sessionId={sessionId} placeholder={placeholder} />
})

interface ChatPanelProps {
  /** The row holding the browser and this panel; sizes are measured on it. */
  containerRef: RefObject<HTMLElement>
  /** The Mini Browser's chat session (null until the backend reports it). */
  sessionId: string | null
  /** The chat sits under the browser (narrow or mobile layout) rather than
   *  beside it; the page stacks its row accordingly. */
  onStackedChange?(stacked: boolean): void
  /** Bumped to open the chat (e.g. an example prompt was put in it). */
  openSignal?: number
}

/**
 * The Mini Browser chat beside the browser, behind a seam: drag to resize,
 * click (or Enter) to collapse/expand; arrows resize from the keyboard. Open
 * state and sizes persist. Below 768px the panels stack and the seam runs
 * horizontally — the same pattern as the Agent App page. Where the row is too
 * narrow for both side by side, the chat also stacks under the browser, and
 * starts collapsed (without changing the saved preference) so the browser
 * keeps its room. Memoized, so browser updates on the page don't re-render it.
 */
export const ChatPanel = memo(function ChatPanel({
  containerRef,
  sessionId,
  onStackedChange,
  openSignal = 0,
}: ChatPanelProps) {
  const { t } = useTranslation(['minibrowser', 'common'])
  const panelId = useId()
  const [savedOpen, setSavedOpen] = usePersistedState(UI_STATE.miniBrowser.chatPanelOpen)
  const [width, setWidth] = usePersistedState(UI_STATE.miniBrowser.chatPanelWidth)
  const [mobileRatio, setMobileRatio] = usePersistedState(UI_STATE.miniBrowser.chatPanelMobileRatio)
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && !!window.matchMedia?.(MOBILE_QUERY).matches,
  )
  const [containerWidth, setContainerWidth] = useState(0)
  const [isResizing, setIsResizing] = useState(false)
  // Narrow layout only: whether the user opened the chat (not saved).
  const [narrowOpen, setNarrowOpen] = useState(false)
  // A pointer interaction on the seam: a click toggles, a drag resizes.
  const dragRef = useRef<{ startX: number; startY: number; moved: boolean } | null>(null)

  useEffect(() => {
    const query = window.matchMedia?.(MOBILE_QUERY)
    if (!query) return
    const onChange = () => setIsMobile(query.matches)
    onChange()
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  // Measured before the first paint, so a narrow window never flashes the
  // side-by-side layout. On mount the row's own ref is attached only after
  // this effect runs (React attaches a parent's refs after its children's
  // layout effects), so the row is found as the seam's parent: this panel
  // renders straight into it.
  const seamRef = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const el = containerRef.current ?? seamRef.current?.parentElement ?? null
    if (!el) return
    setContainerWidth(el.clientWidth)
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => setContainerWidth(el.clientWidth))
    observer.observe(el)
    return () => observer.disconnect()
  }, [containerRef])

  const narrow = !isMobile && containerWidth > 0 && containerWidth < SIDE_BY_SIDE_MIN_WIDTH
  const stacked = isMobile || narrow
  const open = narrow ? narrowOpen : savedOpen
  const setOpen = narrow ? setNarrowOpen : setSavedOpen

  // A wide row again: the next narrow spell starts collapsed again.
  useEffect(() => {
    if (!narrow) setNarrowOpen(false)
  }, [narrow])

  useLayoutEffect(() => {
    onStackedChange?.(stacked)
  }, [onStackedChange, stacked])

  // Asked to show the chat, in whichever layout is current.
  const seenOpenSignalRef = useRef(openSignal)
  useEffect(() => {
    if (openSignal === seenOpenSignalRef.current) return
    seenOpenSignalRef.current = openSignal
    setOpen(true)
  }, [openSignal, setOpen])

  const maxWidth = maxPanelWidth(containerWidth)
  // The saved width, shrunk if the window no longer has room for it.
  const shownWidth = clamp(width, PANEL_MIN_WIDTH, maxWidth)

  const toggle = useCallback(() => setOpen(value => !value), [setOpen])

  const onSeamPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return
    e.preventDefault()
    dragRef.current = { startX: e.clientX, startY: e.clientY, moved: false }
    setIsResizing(true)
  }

  useEffect(() => {
    if (!isResizing) return
    const finish = () => {
      dragRef.current = null
      setIsResizing(false)
    }
    const onMove = (e: PointerEvent) => {
      const drag = dragRef.current
      if (!drag) return
      if (Math.abs(e.clientX - drag.startX) > DRAG_THRESHOLD_PX || Math.abs(e.clientY - drag.startY) > DRAG_THRESHOLD_PX) {
        drag.moved = true
      }
      // A collapsed panel has nothing to resize: the seam is click-only.
      if (!drag.moved || !open) return
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect) return
      if (stacked) {
        const ratio = (rect.bottom - e.clientY) / rect.height
        if (ratio < MOBILE_COLLAPSE_RATIO) {
          finish()
          setOpen(false)
          return
        }
        setMobileRatio(clamp(ratio, MOBILE_MIN_RATIO, MOBILE_MAX_RATIO))
      } else {
        const next = rect.right - e.clientX
        if (next < PANEL_COLLAPSE_WIDTH) {
          finish()
          setOpen(false)
          return
        }
        setWidth(clamp(next, PANEL_MIN_WIDTH, maxPanelWidth(rect.width)))
      }
    }
    const onUp = () => {
      // No real movement: a click, which toggles the panel.
      const wasClick = !!dragRef.current && !dragRef.current.moved
      finish()
      if (wasClick) toggle()
    }
    document.addEventListener('pointermove', onMove)
    document.addEventListener('pointerup', onUp)
    document.addEventListener('pointercancel', finish)
    return () => {
      document.removeEventListener('pointermove', onMove)
      document.removeEventListener('pointerup', onUp)
      document.removeEventListener('pointercancel', finish)
    }
  }, [isResizing, stacked, open, containerRef, setOpen, setWidth, setMobileRatio, toggle])

  // Window-splitter keyboard: arrows resize, Enter/Space collapses/restores.
  const onSeamKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      toggle()
      return
    }
    if (!open) return
    if (stacked && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault()
      const delta = e.key === 'ArrowUp' ? SEAM_KEY_STEP_RATIO : -SEAM_KEY_STEP_RATIO
      setMobileRatio(clamp(mobileRatio + delta, MOBILE_MIN_RATIO, MOBILE_MAX_RATIO))
    } else if (!stacked && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
      e.preventDefault()
      const delta = e.key === 'ArrowLeft' ? SEAM_KEY_STEP_PX : -SEAM_KEY_STEP_PX
      setWidth(clamp(shownWidth + delta, PANEL_MIN_WIDTH, maxWidth))
    }
  }

  // The splitter's value: the chat's share of the page, in percent.
  const share = !open
    ? 0
    : stacked
      ? Math.round(mobileRatio * 100)
      : containerWidth > 0 ? Math.round((shownWidth / containerWidth) * 100) : 0
  const label = open ? t('minibrowser:chat.hide') : t('minibrowser:chat.show')

  return (
    <>
      <div
        ref={seamRef}
        className={[
          styles.seam,
          stacked ? styles.stacked : '',
          !open ? styles.seamCollapsed : '',
          isResizing ? styles.seamActive : '',
        ].filter(Boolean).join(' ')}
        role="separator"
        tabIndex={0}
        aria-orientation={stacked ? 'horizontal' : 'vertical'}
        aria-controls={panelId}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={share}
        aria-label={label}
        title={label}
        onPointerDown={onSeamPointerDown}
        onKeyDown={onSeamKeyDown}
      >
        <span className={styles.grip} aria-hidden="true" />
      </div>

      {/* Kept mounted so collapse/expand can animate; the inner box keeps its
          open size so the chat slides out instead of reflowing. */}
      <div
        id={panelId}
        className={[
          styles.panel,
          stacked ? styles.stacked : '',
          !open ? styles.panelCollapsed : '',
          isResizing ? styles.panelDragging : '',
        ].filter(Boolean).join(' ')}
        style={stacked ? { flexBasis: open ? `${mobileRatio * 100}%` : '0%' } : { width: open ? shownWidth : 0 }}
        aria-hidden={!open}
      >
        <div
          className={`${styles.panelInner} ${stacked ? styles.stacked : ''}`}
          style={stacked ? undefined : { width: shownWidth }}
        >
          <ChatPane
            sessionId={sessionId}
            placeholder={t('minibrowser:chat.placeholder')}
            loadingText={t('minibrowser:chat.loading')}
          />
        </div>
      </div>

      {/* Covers the page mid-drag so the live view never takes the pointer. */}
      {isResizing && (
        <div className={`${styles.overlay} ${stacked ? styles.overlayRows : ''}`} aria-hidden="true" />
      )}
    </>
  )
})
