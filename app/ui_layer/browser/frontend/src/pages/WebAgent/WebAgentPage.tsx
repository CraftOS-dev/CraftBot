import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { Globe, ArrowRight, Square, RotateCw, MousePointerClick, KeyRound, ChevronLeft, ChevronRight, Plus, X, ShieldCheck, ShieldOff } from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useAppSelector } from '../../store/hooks'
import { getSocketClient } from '../../store/socket/socketInstance'
import {
  selectBrowserFrame,
  selectBrowserUrl,
  selectBrowserTitle,
} from '../../store/selectors/agent'
import { Chat } from '../../components/Chat'
import { PasswordsPanel } from './PasswordsPanel'
import type { ActionItem } from '../../types'
import styles from './WebAgentPage.module.css'

// Chat panel (left) width limits — the browser view takes the rest.
const DEFAULT_CHAT_WIDTH = 420
const MIN_CHAT_WIDTH = 280
const MAX_CHAT_WIDTH = 720

// Named keys we forward and whose default (page scroll, tab move) we suppress.
const HANDLED_KEYS = new Set([
  'Enter', 'Backspace', 'Tab', 'Delete', 'Escape', ' ',
  'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End',
  'PageUp', 'PageDown',
])

export function WebAgentPage() {
  const { actions, cancelTask, cancellingTaskId } = useWebSocket()
  const browserFrame = useAppSelector(selectBrowserFrame)
  const browserUrl = useAppSelector(selectBrowserUrl)
  const browserTitle = useAppSelector(selectBrowserTitle)

  const [urlInput, setUrlInput] = useState('')
  const [showPasswords, setShowPasswords] = useState(false)
  const [tabs, setTabs] = useState<Array<{ index: number; url: string; title: string; active: boolean }>>([])
  const [adblock, setAdblock] = useState(true)
  const [chatWidth, setChatWidth] = useState(DEFAULT_CHAT_WIDTH)
  const [isResizing, setIsResizing] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const viewportRef = useRef<HTMLDivElement>(null)
  const imgRef = useRef<HTMLImageElement>(null)

  // When on, YOUR clicks/typing/scrolling are sent to the page. Turn off to
  // just watch (so you don't interfere while the agent is working).
  const [interactive, setInteractive] = useState(true)

  // The one task currently running/waiting — used by the Stop button.
  const runningTask = useMemo<ActionItem | undefined>(() => {
    return actions
      .filter(a => a.itemType === 'task' && (a.status === 'running' || a.status === 'waiting'))
      .sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0))[0]
  }, [actions])

  // ── send helpers ────────────────────────────────────────────────────────
  const sendInput = useCallback((event: Record<string, unknown>) => {
    getSocketClient().send('browser_user_input', { event })
  }, [])

  // Normalise a pointer event to 0..1 of the displayed image, so the backend
  // maps it onto the real page regardless of scaling.
  const normFromEvent = useCallback((clientX: number, clientY: number) => {
    const el = imgRef.current
    if (!el) return null
    const r = el.getBoundingClientRect()
    if (r.width === 0 || r.height === 0) return null
    const nx = Math.min(Math.max((clientX - r.left) / r.width, 0), 1)
    const ny = Math.min(Math.max((clientY - r.top) / r.height, 0), 1)
    return { nx, ny }
  }, [])

  // ── resize drag for the chat/browser split ──────────────────────────────
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsResizing(true)
  }, [])

  useEffect(() => {
    if (!isResizing) return
    const handleMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return
      const rect = containerRef.current.getBoundingClientRect()
      const newWidth = e.clientX - rect.left
      setChatWidth(Math.min(Math.max(newWidth, MIN_CHAT_WIDTH), MAX_CHAT_WIDTH))
    }
    const handleMouseUp = () => setIsResizing(false)
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isResizing])

  // ── keep the Chromium viewport matching the panel (fills the space) ──────
  useEffect(() => {
    const el = viewportRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    let timer: ReturnType<typeof setTimeout> | null = null
    let last = ''
    const push = () => {
      const w = Math.round(el.clientWidth)
      const h = Math.round(el.clientHeight)
      const key = `${w}x${h}`
      if (w < 50 || h < 50 || key === last) return
      last = key
      getSocketClient().send('browser_resize', { width: w, height: h })
    }
    const ro = new ResizeObserver(() => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(push, 200)
    })
    ro.observe(el)
    push()
    return () => {
      ro.disconnect()
      if (timer) clearTimeout(timer)
    }
  }, [])

  // ── wheel needs a non-passive native listener to preventDefault ──────────
  useEffect(() => {
    const el = viewportRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (!interactive) return
      const n = normFromEvent(e.clientX, e.clientY)
      if (!n) return
      e.preventDefault()
      sendInput({ kind: 'scroll', nx: n.nx, ny: n.ny, dy: e.deltaY })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [normFromEvent, sendInput, interactive])

  // ── pointer / keyboard handlers on the live view ─────────────────────────
  const onViewportClick = useCallback((e: React.MouseEvent) => {
    if (!interactive) return
    const n = normFromEvent(e.clientX, e.clientY)
    if (!n) return
    viewportRef.current?.focus()
    sendInput({ kind: 'click', nx: n.nx, ny: n.ny })
  }, [normFromEvent, sendInput, interactive])

  const onViewportKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (!interactive) return
    // Ignore browser/app shortcuts so we don't hijack copy/paste etc.
    if (e.ctrlKey || e.metaKey || e.altKey) return
    if (e.key.length === 1 || HANDLED_KEYS.has(e.key)) {
      e.preventDefault()
      sendInput({ kind: 'key', key: e.key })
    }
  }, [sendInput, interactive])

  // ── url bar / controls ───────────────────────────────────────────────────
  // URL bar and reload drive the page DIRECTLY (like a real browser) — instant,
  // and works even while the agent is busy. You can also click/type in the view.
  const submitUrl = useCallback((e: React.FormEvent) => {
    e.preventDefault()
    const target = urlInput.trim()
    if (!target) return
    getSocketClient().send('browser_nav', { target })
  }, [urlInput])

  const reload = useCallback(() => {
    getSocketClient().send('browser_nav', { target: 'reload' })
  }, [])

  const goBack = useCallback(() => getSocketClient().send('browser_nav', { target: 'back' }), [])
  const goForward = useCallback(() => getSocketClient().send('browser_nav', { target: 'forward' }), [])

  // ── tabs ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    const client = getSocketClient()
    const unsub = client.onMessage('browser_tabs', (data: unknown) => {
      const d = data as { tabs?: Array<{ index: number; url: string; title: string; active: boolean }> }
      setTabs(d.tabs ?? [])
    })
    client.send('browser_tab', { action: 'list' })
    return () => unsub()
  }, [])

  const newTab = useCallback(() => getSocketClient().send('browser_tab', { action: 'new' }), [])
  const switchTab = useCallback((index: number) => getSocketClient().send('browser_tab', { action: 'switch', index }), [])
  const closeTab = useCallback((index: number) => getSocketClient().send('browser_tab', { action: 'close', index }), [])

  // ── ad blocker ────────────────────────────────────────────────────────────
  useEffect(() => {
    const client = getSocketClient()
    const unsub = client.onMessage('browser_adblock', (data: unknown) => {
      const d = data as { enabled?: boolean }
      if (typeof d.enabled === 'boolean') setAdblock(d.enabled)
    })
    client.send('browser_adblock', {}) // query current state
    return () => unsub()
  }, [])

  const toggleAdblock = useCallback(() => {
    getSocketClient().send('browser_adblock', { enabled: !adblock })
  }, [adblock])

  // Stop the agent's running task (if any) so it stops driving the browser.
  const stop = useCallback(() => {
    if (runningTask) cancelTask(runningTask.id)
  }, [runningTask, cancelTask])

  // Keep the URL bar in sync with where the browser actually is, unless editing.
  const urlInputRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (document.activeElement !== urlInputRef.current && browserUrl) {
      setUrlInput(browserUrl)
    }
  }, [browserUrl])

  return (
    <div
      className={`${styles.webAgentPage} ${isResizing ? styles.resizing : ''}`}
      ref={containerRef}
    >
      {/* Left: the agent chat — ask it to browse / buy / research */}
      <div className={styles.chatPanel} style={{ width: chatWidth, flexShrink: 0 }}>
        <Chat
          placeholder="Ask the agent to browse, search, or buy something…"
          emptyMessage="Tell the agent what to do on the web — or drive the browser yourself on the right."
        />
      </div>

      {/* Resize handle */}
      <div className={styles.resizeHandle} onMouseDown={handleMouseDown} />

      {/* Right: the live browser — the agent AND you can control it */}
      <div className={styles.browserPanel}>
        <div className={styles.browserHeader}>
          <button type="button" className={styles.headerBtn} onClick={goBack} title="Back" aria-label="Back">
            <ChevronLeft size={16} />
          </button>
          <button type="button" className={styles.headerBtn} onClick={goForward} title="Forward" aria-label="Forward">
            <ChevronRight size={16} />
          </button>
          <form className={styles.urlForm} onSubmit={submitUrl}>
            <Globe size={15} className={styles.urlIcon} />
            <input
              ref={urlInputRef}
              type="text"
              className={styles.urlBar}
              placeholder="Enter a URL and press Enter…"
              value={urlInput}
              onChange={e => setUrlInput(e.target.value)}
              spellCheck={false}
            />
            <button type="submit" className={styles.urlGo} title="Go" aria-label="Go">
              <ArrowRight size={15} />
            </button>
          </form>
          <button
            type="button"
            className={`${styles.interactiveToggle} ${interactive ? styles.interactiveOn : ''}`}
            onClick={() => setInteractive(v => !v)}
            title={
              interactive
                ? 'Interactive: your clicks/typing/scrolling control the browser. Click to switch to watch-only.'
                : 'Watch-only: your input is ignored. Click to take control.'
            }
            aria-pressed={interactive}
          >
            <MousePointerClick size={13} />
            {interactive ? 'Interactive' : 'Watch only'}
          </button>
          <button type="button" className={styles.headerBtn} onClick={reload} title="Reload page" aria-label="Reload page">
            <RotateCw size={15} />
          </button>
          <button
            type="button"
            className={`${styles.headerBtn} ${adblock ? styles.headerBtnOn : ''}`}
            onClick={toggleAdblock}
            title={adblock ? 'Ad blocker: ON (click to disable)' : 'Ad blocker: OFF (click to enable)'}
            aria-label="Toggle ad blocker"
            aria-pressed={adblock}
          >
            {adblock ? <ShieldCheck size={15} /> : <ShieldOff size={15} />}
          </button>
          <button
            type="button"
            className={styles.headerBtn}
            onClick={() => setShowPasswords(true)}
            title="Saved passwords"
            aria-label="Saved passwords"
          >
            <KeyRound size={15} />
          </button>
          <button
            type="button"
            className={styles.stopBtn}
            onClick={stop}
            disabled={!runningTask || cancellingTaskId === runningTask?.id}
            title="Stop the agent"
            aria-label="Stop the agent"
          >
            <Square size={14} /> Stop
          </button>
        </div>

        {tabs.length > 0 && (
          <div className={styles.tabBar}>
            {tabs.map(t => (
              <div
                key={t.index}
                className={`${styles.tab} ${t.active ? styles.tabActive : ''}`}
                onClick={() => switchTab(t.index)}
                title={t.url}
              >
                <span className={styles.tabTitle}>{t.title || 'New tab'}</span>
                <button
                  className={styles.tabClose}
                  onClick={e => { e.stopPropagation(); closeTab(t.index) }}
                  title="Close tab"
                  aria-label="Close tab"
                >
                  <X size={12} />
                </button>
              </div>
            ))}
            <button className={styles.tabNew} onClick={newTab} title="New tab" aria-label="New tab">
              <Plus size={14} />
            </button>
          </div>
        )}

        <div
          className={`${styles.browserViewport} ${interactive ? styles.viewportInteractive : ''}`}
          ref={viewportRef}
          tabIndex={0}
          onClick={onViewportClick}
          onKeyDown={onViewportKeyDown}
        >
          {browserFrame ? (
            <img
              ref={imgRef}
              src={browserFrame}
              alt={browserTitle || 'Live browser view'}
              className={styles.frame}
              draggable={false}
            />
          ) : (
            <div className={styles.emptyState}>
              <div className={styles.emptyIcon}>
                <Globe size={40} />
              </div>
              <h3>The agent's browser will appear here</h3>
              <p>
                Type a URL above, or ask the agent in the chat — for example
                &ldquo;find wireless headphones under $50 on Amazon&rdquo;. You'll
                watch every click live, and you can click, type, and scroll here yourself.
              </p>
            </div>
          )}
        </div>

        {browserTitle && (
          <div className={styles.statusBar}>
            <span className={styles.statusTitle}>{browserTitle}</span>
            <span className={styles.statusUrl}>{browserUrl}</span>
          </div>
        )}
      </div>

      <PasswordsPanel open={showPasswords} onClose={() => setShowPasswords(false)} />
    </div>
  )
}
