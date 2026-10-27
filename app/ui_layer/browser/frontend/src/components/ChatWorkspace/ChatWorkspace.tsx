import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { flushSync } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { Globe, Layers3, Plus } from 'lucide-react'
import type { ChatMessage, GenerativeUIArtifact } from '../../types'
import { usePersistedState } from '../../hooks'
import { useAppDispatch } from '../../store/hooks'
import { resetUiState } from '../../store/slices/uiSlice'
import { UI_STATE } from '../../store/uiState'
import { IconButton } from '../ui/IconButton'
import { ChromeTabs, type ChromeTab } from '../ui/ChromeTabs'
import { GenerativeUI, type OutputVersion } from '../GenerativeUI/GenerativeUI'
import styles from './ChatWorkspace.module.css'
import { OutputContext } from './OutputReference'
import { PanelChooser } from './PanelChooser'
import { PanelSwitcher } from './PanelSwitcher'
import { PanelAppContext } from '../../features/agentApps/PanelAppContext'

/** The chat's own browser as the panel's second mode. */
export interface BrowserPanelMode {
  /** The chat's browser runs. */
  running: boolean
  /** An agent is browsing in it right now. */
  browsing: boolean
  /** The browser pane. */
  render(): ReactNode
}

/** The chat's installed apps as a panel mode (features/agentApps/usePanelApps). */
export interface AppsPanelMode {
  render(moving: boolean, active: boolean): ReactNode
  openProject(projectId: string): void
  canOpenProject(projectId: string): boolean
  removeProject(projectId: string): void
  /** The apps attached to this chat, in tab order. */
  attached: { projectId: string; title: string; icon: ReactNode; closeLabel: string }[]
  selectedProjectId: string | null
  loaded: boolean
  choices: { id: string; title: string; icon: ReactNode }[]
  actions: ReactNode
}

/** A tab of the panel's strip with what selecting and closing it does. Its id
 *  is only a unique key for the strip; nothing reads meaning back out of it. */
interface PanelTab extends ChromeTab {
  shown: boolean
  select(): void
  close(): void
}

/** Where the panel sits: on the chat's left, or above it (an Agent App's
 *  narrow chat panel). A workspace too narrow for both side by side stacks
 *  either way. */
export type PanelLayout = 'side' | 'stacked'

type Exiting =
  | { sessionId: string; kind: 'output'; artifact: GenerativeUIArtifact }
  | { sessionId: string; kind: 'browser' | 'apps' | 'chooser' }

interface Tracks { columns: string; rows: string }

// Side by side, the chat keeps its width (like an Agent App's chat panel)
// and the panel takes the rest. Dragging the seam to within
// PANEL_COLLAPSE_WIDTH of the panel's far edge snaps the panel shut.
const CHAT_MIN_WIDTH = 320
const PANEL_MIN_WIDTH = 440
const PANEL_COLLAPSE_WIDTH = 400
const SEAM_WIDTH = 1
// Narrower than this, the panel stacks above the chat.
const SIDE_BY_SIDE_MIN_WIDTH = 860
// Stacked, the panel's share of the height; dragging it below
// STACKED_COLLAPSE_SHARE snaps it shut.
const STACKED_MIN_SHARE = 0.2
const STACKED_MAX_SHARE = 0.75
const STACKED_COLLAPSE_SHARE = 0.12
// Movement that turns a press on the seam into a drag (else it is a click).
const DRAG_THRESHOLD = 4
const KEY_STEP_WIDTH = 32
const KEY_STEP_SHARE = 0.04

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))
const readTracks = (element: HTMLElement): Tracks => {
  const style = getComputedStyle(element)
  return { columns: style.gridTemplateColumns, rows: style.gridTemplateRows }
}

/**
 * The chat with its panel. The panel shows one thing at a time: the chat's
 * Generative UI outputs, installed apps, or the chat's own browser. The
 * single button at the chat's top left toggles the panel; its shared
 * tab strip selects the content. A new output opens the panel on it; the
 * chat's browser takes it over when the agent starts browsing (set by the
 * browser's owner through the same per-session panel mode). Opening and
 * closing animate the shared grid tracks. The seam between panel and chat
 * works like an Agent App's: drag it to resize, drag it to the panel's edge
 * or click it to close the panel.
 */
export function ChatWorkspace({ sessionId, messages, browser, apps, layout = 'side', onCloseOutput, children }: {
  sessionId: string
  messages: ChatMessage[]
  /** The chat's browser; omitted where there is none (a draft chat). */
  browser?: BrowserPanelMode
  /** Installed apps; omitted where there are none (a draft chat). */
  apps?: AppsPanelMode
  layout?: PanelLayout
  /** The user closed an output (its tab's ×): it goes for good (its code
   *  and saved progress). */
  onCloseOutput(artifactId: string): void
  children: ReactNode
}) {
  const { t } = useTranslation('chat')
  const dispatch = useAppDispatch()
  const [mode, setMode] = usePersistedState(UI_STATE.chat.panelMode(sessionId))
  const [browserTabOpen, setBrowserTabOpen] = usePersistedState(UI_STATE.chat.panelBrowserOpen(sessionId))
  const [lastMode, setLastMode] = usePersistedState(UI_STATE.chat.panelLastMode(sessionId))
  const [selection, setSelection] = usePersistedState(UI_STATE.chat.outputSelection(sessionId))
  const [chatWidth, setChatWidth] = usePersistedState(UI_STATE.chat.conversationWidth)
  const [stackedShare, setStackedShare] = usePersistedState(UI_STATE.chat.stackedPanelShare)
  // While the seam is held: the size it shows, uncommitted (the chat's width
  // side by side, the panel's share stacked).
  const [resizing, setResizing] = useState(false)
  const [dragSize, setDragSize] = useState<number | null>(null)
  const [workspaceWidth, setWorkspaceWidth] = useState(0)
  const [closing, setClosing] = useState<Exiting | null>(null)
  const workspace = useRef<HTMLDivElement>(null)
  const pane = useRef<HTMLElement>(null)
  const seam = useRef<HTMLDivElement>(null)
  const panelButton = useRef<HTMLButtonElement>(null)
  const [animating, setAnimating] = useState(false)
  const layoutAnimation = useRef<Animation | null>(null)
  const previousTracks = useRef<Tracks | null>(null)
  // The grid as the last commit left it: the starting point when the panel
  // opens without a user action here (the chat's browser taking the panel
  // over when its agent starts browsing).
  const committed = useRef<{ tracks: Tracks | null; isOpen: boolean; stacked: boolean }>({ tracks: null, isOpen: false, stacked: false })
  const press = useRef<{ x: number; y: number; moved: boolean } | null>(null)
  // Focus was in the panel or on the seam when it closed: give it to the
  // panel's button once the panel is gone.
  const restoreFocus = useRef(false)
  // The output revisions already known: an incoming one is new to this set
  // (closing the newest output must not count as a new one arriving).
  // Null distinguishes the initial snapshot from a chat with no outputs yet.
  const knownOutputs = useRef<{ sessionId: string; keys: Set<string> } | null>(null)
  const [controlsTarget, setControlsTarget] = useState<HTMLDivElement | null>(null)
  // Every revision still open (a closed output keeps only a marker).
  const outputs = useMemo(() => {
    const revisions = new Map<string, GenerativeUIArtifact>()
    for (const message of messages) {
      const artifact = message.uiArtifact
      if (message.style === 'agent' && artifact && !artifact.closed) {
        revisions.set(`${artifact.id}:${artifact.revision}`, artifact)
      }
    }
    return Array.from(revisions.values())
  }, [messages])
  // One tab per output, in order of appearance, on its newest revision.
  const tabs = useMemo(() => {
    const latest = new Map<string, GenerativeUIArtifact>()
    for (const artifact of outputs) {
      const current = latest.get(artifact.id)
      if (!current || artifact.revision > current.revision) latest.set(artifact.id, artifact)
    }
    return Array.from(latest.values())
  }, [outputs])
  const newest = outputs[outputs.length - 1]
  const newestKey = newest ? `${newest.id}:${newest.revision}` : undefined
  const exiting = closing?.sessionId === sessionId ? closing : null
  const selected = (exiting?.kind === 'output' ? exiting.artifact : null)
    ?? outputs.find(artifact => `${artifact.id}:${artifact.revision}` === selection) ?? newest
  const showBrowser = !!browser && (exiting ? exiting.kind === 'browser' : mode === 'browser')
  const showOutput = !showBrowser && !!selected
    && (exiting ? exiting.kind === 'output' : mode === 'output' || mode === 'auto')
  const showApps = !!apps && (exiting ? exiting.kind === 'apps' : mode === 'apps')
  const showChooser = (exiting ? exiting.kind === 'chooser' : mode === 'chooser') || showApps && !apps?.selectedProjectId
  const isOpen = showBrowser || showOutput || showApps || showChooser
  const stacked = layout === 'stacked' || (workspaceWidth > 0 && workspaceWidth < SIDE_BY_SIDE_MIN_WIDTH)
  const captureLayout = useCallback(() => {
    if (workspace.current) previousTracks.current = readTracks(workspace.current)
    layoutAnimation.current?.cancel()
    layoutAnimation.current = null
    setAnimating(false)
  }, [])

  // Incoming outputs open automatically (over the browser too). Prepending
  // older history or a language synchronization must not reopen a pane that
  // the user deliberately closed.
  useEffect(() => {
    const known = knownOutputs.current
    if (known?.sessionId === sessionId && newestKey && !known.keys.has(newestKey)) {
      captureLayout()
      setClosing(null)
      setSelection(newestKey)
      setMode('output')
    }
    const keys = known?.sessionId === sessionId ? known.keys : new Set<string>()
    for (const artifact of outputs) keys.add(`${artifact.id}:${artifact.revision}`)
    knownOutputs.current = { sessionId, keys }
  }, [sessionId, outputs, newestKey, setSelection, setMode, captureLayout])
  useEffect(() => { setClosing(null) }, [sessionId])
  useEffect(() => { if (mode === 'browser') setBrowserTabOpen(true) }, [mode, setBrowserTabOpen])
  useEffect(() => { if (mode !== 'closed') setLastMode(mode) }, [mode, setLastMode])
  // A drag never carries over to another chat or layout.
  useEffect(() => {
    press.current = null
    setResizing(false)
    setDragSize(null)
  }, [sessionId, stacked])
  // The width decides side by side or stacked before the first paint.
  useLayoutEffect(() => {
    const element = workspace.current
    if (!element) return
    setWorkspaceWidth(element.getBoundingClientRect().width)
    const observer = new ResizeObserver(([entry]) => setWorkspaceWidth(entry.contentRect.width))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  useLayoutEffect(() => () => {
    layoutAnimation.current?.cancel()
    layoutAnimation.current = null
    previousTracks.current = null
    committed.current = { tracks: null, isOpen: false, stacked: false }
  }, [sessionId])
  useLayoutEffect(() => {
    const element = workspace.current
    const last = committed.current
    const captured = previousTracks.current
    previousTracks.current = null
    if (!element) return
    // Captured by the action that changed the layout here, else where the
    // last commit left the grid (an opening from outside: the browser).
    const previous = captured ?? (last.isOpen !== isOpen && last.stacked === stacked ? last.tracks : null)
    if (captured === null && previous !== null) {
      // Read the new layout itself, not a frame of a motion still running.
      layoutAnimation.current?.cancel()
      layoutAnimation.current = null
      setAnimating(false)
    }
    const next = readTracks(element)
    committed.current = { tracks: next, isOpen, stacked }
    if (!previous) return
    const from: Keyframe = {}
    const to: Keyframe = {}
    if (previous.columns !== next.columns) { from.gridTemplateColumns = previous.columns; to.gridTemplateColumns = next.columns }
    if (previous.rows !== next.rows) { from.gridTemplateRows = previous.rows; to.gridTemplateRows = next.rows }
    if (Object.keys(to).length === 0 || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      if (exiting) finishClose()
      return
    }
    // Animate the shared tracks, so chat, seam and pane travel together. No
    // screenshot overlays, document recreation or text scaling.
    const animation = element.animate([from, to], { duration: 300, easing: 'cubic-bezier(.22, 1, .36, 1)' })
    setAnimating(true)
    layoutAnimation.current = animation
    void animation.finished.then(() => {
      if (layoutAnimation.current !== animation) return
      layoutAnimation.current = null
      setAnimating(false)
      if (exiting) finishClose()
    }).catch(() => { /* Reversing direction or switching sessions cancels motion. */ })
  }, [isOpen, exiting, stacked])

  // Side by side: the chat's width, leaving the panel its minimum.
  const chatMaxWidth = Math.max(CHAT_MIN_WIDTH, workspaceWidth - PANEL_MIN_WIDTH - SEAM_WIDTH)
  const conversationWidth = clamp(stacked ? chatWidth : dragSize ?? chatWidth, CHAT_MIN_WIDTH, chatMaxWidth)
  const panelShare = clamp(stacked ? dragSize ?? stackedShare : stackedShare, STACKED_MIN_SHARE, STACKED_MAX_SHARE)
  // The seam's value is the panel's share of the workspace, in percent.
  const percent = (width: number) => Math.round(width / (workspaceWidth || 1) * 100)
  const seamValue = stacked
    ? { now: Math.round(panelShare * 100), min: Math.round(STACKED_MIN_SHARE * 100), max: Math.round(STACKED_MAX_SHARE * 100) }
    : { now: percent(workspaceWidth - conversationWidth - SEAM_WIDTH), min: percent(workspaceWidth - chatMaxWidth - SEAM_WIDTH), max: percent(workspaceWidth - CHAT_MIN_WIDTH - SEAM_WIDTH) }
  // The size the pointer asks for, or 'close' within the panel's collapse zone.
  const sizeAt = (clientX: number, clientY: number): number | 'close' | null => {
    const bounds = workspace.current?.getBoundingClientRect()
    if (!bounds?.width || !bounds.height) return null
    if (stacked) {
      const share = (clientY - bounds.top) / bounds.height
      return share < STACKED_COLLAPSE_SHARE ? 'close' : clamp(share, STACKED_MIN_SHARE, STACKED_MAX_SHARE)
    }
    if (clientX - bounds.left < PANEL_COLLAPSE_WIDTH) return 'close'
    return clamp(bounds.right - clientX, CHAT_MIN_WIDTH, Math.max(CHAT_MIN_WIDTH, bounds.width - PANEL_MIN_WIDTH - SEAM_WIDTH))
  }
  const commitSize = (size: number) => (stacked ? setStackedShare(size) : setChatWidth(size))

  const open = (artifact: GenerativeUIArtifact) => {
    if (!isOpen) captureLayout()
    setClosing(null)
    setSelection(`${artifact.id}:${artifact.revision}`)
    setMode('output')
  }
  const openApp = (id?: string) => {
    if (id && !apps?.canOpenProject(id)) return
    if (!isOpen) captureLayout()
    setClosing(null)
    if (id) apps?.openProject(id)
    setMode('apps')
  }
  const openChooser = () => {
    if (!isOpen) captureLayout()
    setClosing(null)
    setMode('chooser')
  }
  const openBrowser = () => {
    setBrowserTabOpen(true)
    if (!isOpen) captureLayout()
    setClosing(null)
    setMode('browser')
  }
  const selectOutput = (id: string) => {
    const tab = tabs.find(item => item.id === id)
    if (tab) { setSelection(`${tab.id}:${tab.revision}`); setClosing(null); setMode('output') }
  }
  // Closing an output disposes of it: its saved progress here, then its code
  // everywhere (onCloseOutput). The tab next to it takes its place; the last
  // one closes the panel.
  const closeOutput = (id: string) => {
    dispatch(resetUiState(UI_STATE.chat.artifactState(JSON.stringify([sessionId, id]))))
    if (selected?.id === id && showOutput) {
      const remaining = tabs.filter(tab => tab.id !== id)
      if (remaining.length === 0) {
        close()
      } else {
        const next = remaining[Math.min(tabs.findIndex(tab => tab.id === id), remaining.length - 1)]
        setSelection(`${next.id}:${next.revision}`)
      }
    }
    onCloseOutput(id)
  }
  const closeBrowserTab = () => {
    setBrowserTabOpen(false)
    if (showBrowser) openChooser()
  }
  // Detaching only: the app keeps running. Focus the tab that takes its place.
  const removeApp = (projectId: string) => {
    apps?.removeProject(projectId)
    requestAnimationFrame(() => {
      const next = pane.current?.querySelector<HTMLButtonElement>('[role="tab"][aria-selected="true"]')
        ?? pane.current?.querySelector<HTMLButtonElement>('button[aria-label]')
      next?.focus()
    })
  }
  const finishClose = () => {
    const opener = panelButton
    setClosing(null)
    if (!restoreFocus.current) return
    restoreFocus.current = false
    requestAnimationFrame(() => opener.current?.focus({ preventScroll: true }))
  }
  const close = () => {
    if (exiting || !isOpen) return
    const active = document.activeElement
    restoreFocus.current = !!active && (active === seam.current || !!pane.current?.contains(active) || showApps && active instanceof HTMLIFrameElement)
    captureLayout()
    // Persist intent immediately; only the visible pane waits for the exit.
    // Switching chats during that exit must not discard the close choice.
    if (showChooser) setClosing({ sessionId, kind: 'chooser' })
    else if (showApps) setClosing({ sessionId, kind: 'apps' })
    else if (showBrowser) setClosing({ sessionId, kind: 'browser' })
    else if (selected) setClosing({ sessionId, kind: 'output', artifact: selected })
    setMode('closed')
  }
  const endPress = () => {
    press.current = null
    setResizing(false)
    setDragSize(null)
  }
  const onSeamPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return
    event.preventDefault()
    layoutAnimation.current?.cancel()
    layoutAnimation.current = null
    setAnimating(false)
    event.currentTarget.focus({ preventScroll: true })
    event.currentTarget.setPointerCapture(event.pointerId)
    press.current = { x: event.clientX, y: event.clientY, moved: false }
    setResizing(true)
  }
  const onSeamPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const current = press.current
    if (!current) return
    if (!current.moved && Math.abs(event.clientX - current.x) <= DRAG_THRESHOLD && Math.abs(event.clientY - current.y) <= DRAG_THRESHOLD) return
    current.moved = true
    const size = sizeAt(event.clientX, event.clientY)
    if (size === 'close') {
      // A pointermove is a continuous event: React would render the store's
      // update (the panel mode) before this component's (the exiting pane),
      // unmounting the pane before it could animate shut. One render.
      flushSync(() => {
        endPress()
        close()
      })
    } else if (size !== null) {
      setDragSize(size)
    }
  }
  const onSeamPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    const current = press.current
    if (!current) return
    endPress()
    // A press without a drag is a click: it closes the panel.
    if (!current.moved) { close(); return }
    const size = sizeAt(event.clientX, event.clientY)
    if (size === 'close') close()
    else if (size !== null) commitSize(size)
  }
  // Arrow keys move the seam, Home and End take the panel to its smallest
  // and largest, Enter or Space closes it.
  const onSeamKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      close()
      return
    }
    if (stacked) {
      let share = panelShare
      if (event.key === 'ArrowUp') share -= KEY_STEP_SHARE
      else if (event.key === 'ArrowDown') share += KEY_STEP_SHARE
      else if (event.key === 'Home') share = STACKED_MIN_SHARE
      else if (event.key === 'End') share = STACKED_MAX_SHARE
      else return
      event.preventDefault()
      setStackedShare(clamp(share, STACKED_MIN_SHARE, STACKED_MAX_SHARE))
      return
    }
    let width = conversationWidth
    if (event.key === 'ArrowLeft') width += KEY_STEP_WIDTH
    else if (event.key === 'ArrowRight') width -= KEY_STEP_WIDTH
    else if (event.key === 'Home') width = chatMaxWidth
    else if (event.key === 'End') width = CHAT_MIN_WIDTH
    else return
    event.preventDefault()
    setChatWidth(clamp(width, CHAT_MIN_WIDTH, chatMaxWidth))
  }

  const sizes = {
    '--conversation-width': `${conversationWidth}px`,
    '--panel-share': `${panelShare}fr`,
    '--chat-share': `${1 - panelShare}fr`,
  } as CSSProperties
  const exitingProps = exiting ? { 'aria-hidden': true, inert: '' } : {}
  // While a closed output's pane slides away, its tab stays with it.
  const shownTabs = exiting?.kind === 'output' && !tabs.some(tab => tab.id === exiting.artifact.id)
    ? [...tabs, exiting.artifact]
    : tabs
  const panelTabs: PanelTab[] = [
    ...(browser && (browserTabOpen || showBrowser) ? [{
      id: 'browser', title: t('panel.browser'), icon: <Globe size={13} />, closeLabel: t('panel.close'),
      shown: !showChooser && showBrowser, select: openBrowser, close: closeBrowserTab,
    }] : []),
    ...(apps?.attached ?? []).map(app => ({
      id: `app:${app.projectId}`, title: app.title, icon: app.icon, closeLabel: app.closeLabel,
      shown: !showChooser && showApps && apps?.selectedProjectId === app.projectId,
      select: () => openApp(app.projectId), close: () => removeApp(app.projectId),
    })),
    ...shownTabs.map(artifact => ({
      id: `output:${artifact.id}`, title: artifact.title, icon: <Layers3 size={13} />,
      closeLabel: t('generativeUI.closeNamed', { title: artifact.title }),
      shown: !showChooser && !showBrowser && !showApps && selected?.id === artifact.id,
      select: () => selectOutput(artifact.id), close: () => closeOutput(artifact.id),
    })),
  ]
  const panelTabById = new Map(panelTabs.map(tab => [tab.id, tab]))
  const versions: OutputVersion[] = selected
    ? outputs
      .filter(artifact => artifact.id === selected.id)
      .sort((a, b) => a.revision - b.revision)
      .map(artifact => ({
        key: `${artifact.id}:${artifact.revision}`,
        label: t('generativeUI.version', { revision: artifact.revision }),
        current: artifact.revision === selected.revision,
      }))
    : []
  return <OutputContext.Provider value={open}><PanelAppContext.Provider value={apps ? { open: openApp, canOpen: apps.canOpenProject } : null}>
    <div ref={workspace} style={sizes} className={`${styles.workspace} ${stacked ? styles.stacked : ''} ${isOpen && !exiting ? styles.open : ''} ${exiting ? styles.closing : ''} ${resizing ? styles.resizing : ''}`}>
      {isOpen && <>
        <section ref={pane} className={styles.pane} aria-label={t(showChooser ? 'panel.open' : showApps ? 'apps.region' : showBrowser ? 'browserPanel.region' : 'generativeUI.outputPanel')} {...exitingProps}>
          <ChromeTabs label={t('panel.tabs')} tabs={panelTabs}
            selectedId={panelTabs.find(tab => tab.shown)?.id ?? null}
            onSelect={id => panelTabById.get(id)?.select()}
            onClose={id => panelTabById.get(id)?.close()} closeTitle={t('panel.close')}
            after={(apps || browser) && <IconButton type="button" size="sm" icon={<Plus size={16} />} onClick={openChooser} aria-label={t('panel.open')} tooltip={t('panel.open')} />}
            actions={showApps ? apps?.actions : undefined} actionsRef={setControlsTarget} />
          {showChooser ? <PanelChooser browser={!!browser} apps={apps?.choices ?? []} loaded={apps?.loaded ?? true}
            outputs={tabs.map(item => ({ id: item.id, title: item.title, icon: <Layers3 size={19} /> }))}
            onBrowser={openBrowser} onApp={openApp} onOutput={selectOutput} />
            : showApps && apps ? apps.render(resizing || animating, !exiting)
            : showBrowser && browser ? browser.render()
            : selected && <GenerativeUI key={`${sessionId}:${selected.id}`} artifact={selected} sessionId={sessionId}
              controlsTarget={controlsTarget} versions={versions} onSelectVersion={setSelection} />}
        </section>
        <div ref={seam} className={styles.seam} role="separator" tabIndex={0} aria-label={t('generativeUI.resizePanel')} title={t('panel.close')}
          aria-orientation={stacked ? 'horizontal' : 'vertical'} aria-valuenow={seamValue.now} aria-valuemin={seamValue.min} aria-valuemax={seamValue.max}
          onPointerDown={onSeamPointerDown} onPointerMove={onSeamPointerMove} onPointerUp={onSeamPointerUp} onLostPointerCapture={endPress} onKeyDown={onSeamKeyDown}>
          <span className={styles.grip} aria-hidden="true" />
        </div>
      </>}
      <div className={styles.conversation}>
        {(outputs.length > 0 || browser || apps) && <PanelSwitcher key={sessionId} buttonRef={panelButton} panelOpen={isOpen && !exiting}
          label={apps || browser && outputs.length ? t('panel.toggle') : browser ? t('browserPanel.show') : t('generativeUI.showOutputs')}
          browserRunning={browser?.running} browsing={browser?.browsing} onToggle={() => {
            if (isOpen && !exiting) { close(); return }
            if (apps) { openChooser(); return }
            if (lastMode === 'chooser') { openChooser(); return }
            if (lastMode === 'browser' && browser) openBrowser()
            else if (lastMode === 'apps' && apps) openApp()
            else if (selected) open(selected)
            else if (apps) openApp()
            else openBrowser()
          }} />}
        <div className={styles.chat}>{children}</div>
      </div>
    </div>
  </PanelAppContext.Provider></OutputContext.Provider>
}
