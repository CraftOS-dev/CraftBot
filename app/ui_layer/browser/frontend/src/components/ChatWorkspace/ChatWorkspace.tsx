import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { flushSync } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { Globe, Layers3 } from 'lucide-react'
import type { ChatMessage, GenerativeUIArtifact } from '../../types'
import { usePersistedState } from '../../hooks'
import { useAppDispatch } from '../../store/hooks'
import { resetUiState } from '../../store/slices/uiSlice'
import { UI_STATE } from '../../store/uiState'
import { ChromeTabs } from '../ui/ChromeTabs'
import { GenerativeUI, type OutputVersion } from '../GenerativeUI/GenerativeUI'
import { PanelAppContext } from '../../features/agentApps/PanelAppContext'
import { AppPickerButton } from './AppPickerButton'
import { OutputContext } from './OutputReference'
import styles from './ChatWorkspace.module.css'

/** The chat's own browser as the panel's second mode. */
export interface BrowserPanelMode {
  /** The chat's browser runs. */
  running: boolean
  /** An agent is browsing in it right now. */
  browsing: boolean
  /** The browser pane. */
  render(): ReactNode
}

/** An installed Agent App as the panel's third mode (usePanelApps). */
export interface AppsPanelMode {
  /** Installed apps this chat can show: the apps menu. */
  choices: { id: string; title: string; icon: ReactNode }[]
  /** False until the app catalog first arrives. */
  loaded: boolean
  /** The app this chat shows, once picked (and while it still exists); its
   *  icon is the apps button's. */
  selected: { id: string; title: string; icon: ReactNode } | null
  /** Make an app this chat's app. */
  select(projectId: string): void
  /** The chat no longer has an app. */
  clear(): void
  canOpenProject(projectId: string): boolean
  /** An app's view. By id, so a closed app still slides out of the pane;
   *  `interactive` is false while it does. */
  render(projectId: string, moving: boolean, interactive: boolean): ReactNode
}

/** Where the panel sits: on the chat's left, or above it (an Agent App's
 *  narrow chat panel). A workspace too narrow for both side by side stacks
 *  either way. */
export type PanelLayout = 'side' | 'stacked'

type Exiting =
  | { sessionId: string; kind: 'output'; artifact: GenerativeUIArtifact }
  | { sessionId: string; kind: 'apps'; projectId: string }
  | { sessionId: string; kind: 'browser' }

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
// Opening and closing use the Agent App page's chat panel transition
// (AgentAppPage.module.css .chatPanel), here ChatWorkspace.module.css
// .paneMoving. A size change that animates nothing ends its motion after
// this long without a transitionrun.
const NO_TRANSITION_MS = 100

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))

/**
 * The chat with its panel. The panel shows one thing at a time: the chat's
 * Generative UI outputs, (with `browser`) the chat's own browser, or (with
 * `apps`) an installed Agent App. The round buttons at the chat's top left
 * switch between them; pressing the one on show closes the panel, except the
 * apps button, which always lists the apps to show (and Close, which stops
 * the chat having one). A new output opens the
 * panel on it; the chat's browser takes it over when the agent starts
 * browsing (set by the browser's owner through the same per-session panel
 * mode). The pane stays mounted and opening and closing animate its width
 * (stacked: height) with a CSS transition, as the Agent App page's chat panel
 * does. The seam between panel and chat works like an Agent App's: drag it
 * to resize, drag it to the panel's edge or click it to close the panel.
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
  const [selection, setSelection] = usePersistedState(UI_STATE.chat.outputSelection(sessionId))
  const [chatWidth, setChatWidth] = usePersistedState(UI_STATE.chat.conversationWidth)
  const [stackedShare, setStackedShare] = usePersistedState(UI_STATE.chat.stackedPanelShare)
  // While the seam is held: the size it shows, uncommitted (the chat's width
  // side by side, the panel's share stacked).
  const [resizing, setResizing] = useState(false)
  const [dragSize, setDragSize] = useState<number | null>(null)
  const [workspaceWidth, setWorkspaceWidth] = useState(0)
  const [workspaceHeight, setWorkspaceHeight] = useState(0)
  const [closing, setClosing] = useState<Exiting | null>(null)
  const workspace = useRef<HTMLDivElement>(null)
  const pane = useRef<HTMLElement>(null)
  const seam = useRef<HTMLDivElement>(null)
  const outputsButton = useRef<HTMLButtonElement>(null)
  const browserButton = useRef<HTMLButtonElement>(null)
  const appsButton = useRef<HTMLButtonElement>(null)
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
  // While closing, the app that is sliding out (Close may already have
  // cleared the chat's app); otherwise the chat's app.
  const shownAppId = exiting?.kind === 'apps' ? exiting.projectId : apps?.selected?.id
  const showBrowser = !!browser && (exiting ? exiting.kind === 'browser' : mode === 'browser')
  const showApps = !showBrowser && !!shownAppId && (exiting ? exiting.kind === 'apps' : mode === 'apps')
  const showOutput = !showBrowser && !showApps && !!selected
    && (exiting ? exiting.kind === 'output' : mode === 'output' || mode === 'auto')
  const isOpen = showBrowser || showApps || showOutput
  const stacked = layout === 'stacked' || (workspaceWidth > 0 && workspaceWidth < SIDE_BY_SIDE_MIN_WIDTH)
  const expanded = isOpen && !exiting
  // The pane's transition is on only while it opens or closes (whatever
  // opened it: a button, a new output, the agent starting to browse), so
  // dragging or keying the seam resizes at once. Set in the render that
  // flips `expanded`, so the transition applies to that very change; a chat
  // switch or a layout change only takes the new state.
  const [motion, setMotion] = useState({ sessionId, stacked, expanded, moving: false, seq: 0 })
  if (motion.sessionId !== sessionId || motion.stacked !== stacked) {
    setMotion({ sessionId, stacked, expanded, moving: false, seq: motion.seq })
  } else if (motion.expanded !== expanded) {
    setMotion({ sessionId, stacked, expanded, moving: true, seq: motion.seq + 1 })
  }

  // Incoming outputs open automatically (over the browser too). Prepending
  // older history or a language synchronization must not reopen a pane that
  // the user deliberately closed.
  useEffect(() => {
    const known = knownOutputs.current
    if (known?.sessionId === sessionId && newestKey && !known.keys.has(newestKey)) {
      setClosing(null)
      setSelection(newestKey)
      setMode('output')
    }
    const keys = known?.sessionId === sessionId ? known.keys : new Set<string>()
    for (const artifact of outputs) keys.add(`${artifact.id}:${artifact.revision}`)
    knownOutputs.current = { sessionId, keys }
  }, [sessionId, outputs, newestKey, setSelection, setMode])
  useEffect(() => { setClosing(null) }, [sessionId])
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
    const bounds = element.getBoundingClientRect()
    setWorkspaceWidth(bounds.width)
    setWorkspaceHeight(bounds.height)
    const observer = new ResizeObserver(([entry]) => {
      setWorkspaceWidth(entry.contentRect.width)
      setWorkspaceHeight(entry.contentRect.height)
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  // The open/close transition ended, or nothing ran (the size did not change).
  useEffect(() => {
    if (!motion.moving) return
    const element = pane.current
    let ended = false
    let idle = 0
    const end = () => {
      if (ended) return
      ended = true
      setMotion(current => (current.seq === motion.seq ? { ...current, moving: false } : current))
    }
    // A transition announces itself (transitionrun) in the frame it starts.
    const awaitRun = () => { window.clearTimeout(idle); idle = window.setTimeout(end, NO_TRANSITION_MS) }
    const onRun = (event: TransitionEvent) => { if (event.target === element) window.clearTimeout(idle) }
    const onEnd = (event: TransitionEvent) => { if (event.target === element) end() }
    // Cancelled: a reversal starts its own transition, else the motion is over.
    const onCancel = (event: TransitionEvent) => { if (event.target === element) awaitRun() }
    element?.addEventListener('transitionrun', onRun)
    element?.addEventListener('transitionend', onEnd)
    element?.addEventListener('transitioncancel', onCancel)
    awaitRun()
    return () => {
      element?.removeEventListener('transitionrun', onRun)
      element?.removeEventListener('transitionend', onEnd)
      element?.removeEventListener('transitioncancel', onCancel)
      window.clearTimeout(idle)
    }
  }, [motion.moving, motion.seq])
  // A closing pane lets its content go once it has slid shut.
  useEffect(() => {
    if (exiting && !motion.moving) finishClose(exiting.kind)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exiting, motion.moving])

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
    setClosing(null)
    setSelection(`${artifact.id}:${artifact.revision}`)
    setMode('output')
  }
  const openBrowser = () => {
    setClosing(null)
    setMode('browser')
  }
  // Show an installed app as this chat's app. Never launches or stops it.
  const openApp = (projectId: string) => {
    if (!apps?.canOpenProject(projectId)) return
    setClosing(null)
    apps.select(projectId)
    setMode('apps')
  }
  // The apps list's Close: the chat stops having an app (and its pane goes).
  const closeApp = () => {
    if (showApps) close()
    apps?.clear()
  }
  const selectOutput = (id: string) => {
    const tab = tabs.find(item => item.id === id)
    if (tab) setSelection(`${tab.id}:${tab.revision}`)
  }
  // Closing an output disposes of it: its saved progress here, then its code
  // everywhere (onCloseOutput). The tab next to it takes its place; the last
  // one closes the panel.
  const closeOutput = (id: string) => {
    dispatch(resetUiState(UI_STATE.chat.artifactState(JSON.stringify([sessionId, id]))))
    if (selected?.id === id) {
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
  const finishClose = (kind: Exiting['kind']) => {
    const opener = kind === 'browser' ? browserButton : kind === 'apps' ? appsButton : outputsButton
    setClosing(null)
    if (!restoreFocus.current) return
    restoreFocus.current = false
    requestAnimationFrame(() => opener.current?.focus({ preventScroll: true }))
  }
  const close = () => {
    if (exiting || !isOpen) return
    const active = document.activeElement
    // An app's frame lives outside the pane's DOM.
    restoreFocus.current = !!active && (active === seam.current || !!pane.current?.contains(active)
      || (showApps && active instanceof HTMLIFrameElement))
    // Persist intent immediately; only the visible pane waits for the exit.
    // Switching chats during that exit must not discard the close choice.
    if (showBrowser) setClosing({ sessionId, kind: 'browser' })
    else if (showApps && shownAppId) setClosing({ sessionId, kind: 'apps', projectId: shownAppId })
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
      // update (the panel mode) before this component's (the exiting pane and
      // the drag's end, which turns the transition back on). One render, so
      // the pane slides shut from where the drag left it.
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

  const sizes = { '--conversation-width': `${conversationWidth}px` } as CSSProperties
  // The always-mounted pane: its open size, or 0 (the CSS transition animates
  // between them while it opens or closes).
  const paneSize: CSSProperties = stacked
    ? { height: expanded ? `calc((100% - ${SEAM_WIDTH}px) * ${panelShare})` : '0px' }
    : { width: expanded ? `calc(100% - var(--conversation-width) - ${SEAM_WIDTH}px)` : '0px' }
  const paneLabel = !isOpen ? undefined
    : showBrowser ? t('browserPanel.region') : showApps ? t('apps.region') : t('generativeUI.outputPanel')
  // Closed, or sliding shut: out of reach. Not a sliding app, though: its
  // frame lives outside this subtree and an aria-hidden/inert pane would hide
  // it at once; it takes no input while it slides instead.
  const paneHidden = !isOpen || (exiting && exiting.kind !== 'apps') ? { 'aria-hidden': true, inert: '' } : {}
  // The pane's content keeps the open panel's size: opening and closing then
  // slide it in and out of the clipping pane (anchored on the chat's side)
  // instead of reflowing it, as the Agent App page's chat panel does.
  const paneContentSize: CSSProperties | undefined = workspaceWidth > 0
    ? stacked
      ? { height: Math.max(0, (workspaceHeight - SEAM_WIDTH) * panelShare) }
      : { width: Math.max(0, workspaceWidth - conversationWidth - SEAM_WIDTH) }
    : undefined
  // While a closed output's pane slides away, its tab stays with it.
  const shownTabs = exiting?.kind === 'output' && !tabs.some(tab => tab.id === exiting.artifact.id)
    ? [...tabs, exiting.artifact]
    : tabs
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
    <div ref={workspace} style={sizes} className={`${styles.workspace} ${stacked ? styles.stacked : ''} ${resizing ? styles.resizing : ''}`}>
      <section ref={pane} className={`${styles.pane} ${motion.moving ? styles.paneMoving : ''}`} style={paneSize}
        aria-label={paneLabel} {...paneHidden}>
        {isOpen && <div className={styles.paneContent} style={paneContentSize}>
          {showBrowser && browser ? browser.render()
            /* No bar: the app fills the pane, as on its own page. The apps
               button changes or closes it. */
            : showApps && apps && shownAppId ? apps.render(shownAppId, resizing || motion.moving, !exiting)
            : selected && <>
              <ChromeTabs
                label={t('generativeUI.tabsLabel')}
                tabs={shownTabs.map(artifact => ({
                  id: artifact.id,
                  title: artifact.title,
                  icon: <Layers3 size={13} />,
                  closeLabel: t('generativeUI.closeNamed', { title: artifact.title }),
                }))}
                selectedId={selected.id}
                onSelect={selectOutput}
                onClose={closeOutput}
                closeTitle={t('generativeUI.close')}
                actionsRef={setControlsTarget}
              />
              <GenerativeUI key={`${sessionId}:${selected.id}`} artifact={selected} sessionId={sessionId}
                controlsTarget={controlsTarget} versions={versions} onSelectVersion={setSelection} />
            </>}
        </div>}
      </section>
      {/* Kept, unseen, while the pane slides shut. */}
      {isOpen && <div ref={seam} className={`${styles.seam}${exiting ? ` ${styles.seamHidden}` : ''}`} role="separator" tabIndex={0} aria-label={t('generativeUI.resizePanel')} title={t('panel.close')}
        aria-orientation={stacked ? 'horizontal' : 'vertical'} aria-valuenow={seamValue.now} aria-valuemin={seamValue.min} aria-valuemax={seamValue.max}
        onPointerDown={onSeamPointerDown} onPointerMove={onSeamPointerMove} onPointerUp={onSeamPointerUp} onLostPointerCapture={endPress} onKeyDown={onSeamKeyDown}>
        <span className={styles.grip} aria-hidden="true" />
      </div>}
      <div className={styles.conversation}>
        {(outputs.length > 0 || browser || apps) && <div className={styles.switcher}>
          {outputs.length > 0 && <button type="button" ref={outputsButton} onClick={() => (showOutput && !exiting ? close() : selected && open(selected))} aria-label={t('generativeUI.showOutputs')} title={t('generativeUI.showOutputs')} aria-expanded={showOutput && !exiting}>
            <Layers3 size={16} />
          </button>}
          {browser && <button type="button" ref={browserButton} onClick={() => (showBrowser && !exiting ? close() : openBrowser())} aria-label={t('browserPanel.show')} title={t(browser.browsing ? 'browserPanel.browsing' : browser.running ? 'browserPanel.running' : 'browserPanel.show')} aria-expanded={showBrowser && !exiting}>
            <Globe size={16} />
            {browser.running && <span className={`${styles.browserDot} ${browser.browsing ? styles.browserDotBusy : ''}`} aria-hidden="true" />}
          </button>}
          {apps && <AppPickerButton apps={apps} shown={showApps && !exiting} buttonRef={appsButton} onPick={openApp} onClose={closeApp} />}
        </div>}
        <div className={styles.chat}>{children}</div>
      </div>
    </div>
  </PanelAppContext.Provider></OutputContext.Provider>
}
