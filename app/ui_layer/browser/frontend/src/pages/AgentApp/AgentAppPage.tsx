import React, { useEffect, useState, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Play,
  AlertCircle,
  Loader2,
} from 'lucide-react'
import { CraftBotMascot } from '@mascot'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useTheme } from '../../contexts/ThemeContext'
import { Button } from '../../components/ui/Button'
import { ConfirmModal } from '../../components/ui/ConfirmModal'
import { Chat } from '../../components/Chat'
import { getOrCreateIframe, showIframe, hideIframe, removeIframe, postMessageToIframe, ownsProjectWindow } from './iframePool'
import { ConstructionDock } from './ConstructionDock'
import { AgentAppThemeModal, DEFAULT_CUSTOM_COLORS } from './AgentAppThemeModal'
import type { AgentAppThemeId, AgentAppCustomColors } from './AgentAppThemeModal'
import { useAppSelector } from '../../store/hooks'
import { selectAgentAppBuildEvents, selectAgentAppSnapshots } from '../../store/selectors/agentApp'
import type { AgentAppBuildEvent } from '../../types'
import styles from './AgentAppPage.module.css'

// Stable empty array so the dock's memoized selectors don't churn per render.
const EMPTY_EVENTS: AgentAppBuildEvent[] = []

// Chat panel resize bounds (desktop = px width, mobile = height ratio). Dragging
// the panel narrower than the COLLAPSE threshold snaps it shut instead of
// clamping — a natural "drag it away to hide it" gesture.
const PANEL_MIN_WIDTH = 220
const PANEL_MAX_WIDTH = 600
const PANEL_COLLAPSE_WIDTH = 180
const MOBILE_MIN_RATIO = 0.15
const MOBILE_MAX_RATIO = 0.85
const MOBILE_COLLAPSE_RATIO = 0.07

function loadAgentAppTheme(projectId: string): AgentAppThemeId {
  try {
    const stored = localStorage.getItem(`agentapp-theme-${projectId}`)
    if (stored) return stored as AgentAppThemeId
  } catch {}
  return 'craftbot'
}

function saveAgentAppTheme(projectId: string, themeId: AgentAppThemeId) {
  try { localStorage.setItem(`agentapp-theme-${projectId}`, themeId) } catch {}
}

function loadAgentAppCustomColors(projectId: string): AgentAppCustomColors {
  try {
    const raw = localStorage.getItem(`agentapp-custom-colors-${projectId}`)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (parsed.bg && parsed.surface && parsed.text && parsed.accent) return parsed
    }
  } catch {}
  return { ...DEFAULT_CUSTOM_COLORS }
}

function saveAgentAppCustomColors(projectId: string, colors: AgentAppCustomColors) {
  try { localStorage.setItem(`agentapp-custom-colors-${projectId}`, JSON.stringify(colors)) } catch {}
}

export function AgentAppPage() {
  const { t } = useTranslation(['agentapp', 'common'])
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const {
    agentAppProjects,
    agentAppTodos,
    launchAgentApp,
    deleteAgentApp,
    setActiveAgentApp,
    updateAgentAppTheme,
  } = useWebSocket()
  const { theme: appTheme } = useTheme()
  const buildEventsMap = useAppSelector(selectAgentAppBuildEvents)
  const snapshotMap = useAppSelector(selectAgentAppSnapshots)

  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showThemeModal, setShowThemeModal] = useState(false)
  const [agentAppTheme, setAgentAppTheme] = useState<AgentAppThemeId>(
    () => (projectId ? loadAgentAppTheme(projectId) : 'craftbot')
  )
  const [agentAppCustomColors, setAgentAppCustomColors] = useState<AgentAppCustomColors>(
    () => (projectId ? loadAgentAppCustomColors(projectId) : { ...DEFAULT_CUSTOM_COLORS })
  )
  const [showChat, setShowChat] = useState(true)
  const [panelWidth, setPanelWidth] = useState(350)
  const [mobileChatRatio, setMobileChatRatio] = useState(0.4)
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.innerWidth <= 768
  )
  const [isResizing, setIsResizing] = useState(false)
  const iframePlaceholderRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  // Tracks a pointer interaction on the seam handle so we can tell a click
  // (toggle the panel) from a drag (resize it).
  const dragRef = useRef<{ startX: number; startY: number; moved: boolean } | null>(null)

  // Track viewport width for mobile/desktop layout switch
  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth <= 768)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // The theme picker now lives behind the sidebar row's "…" menu. That kebab
  // only appears for the active project, so its page (this one) is mounted and
  // catches the event to open the modal here, where the iframe bridge lives.
  useEffect(() => {
    if (!projectId) return
    const onOpenTheme = (e: Event) => {
      const detail = (e as CustomEvent<{ projectId?: string }>).detail
      if (detail?.projectId === projectId) setShowThemeModal(true)
    }
    window.addEventListener('agentapp:open-theme', onOpenTheme)
    return () => window.removeEventListener('agentapp:open-theme', onOpenTheme)
  }, [projectId])

  // Find the current project
  const project = agentAppProjects.find(p => p.id === projectId)

  // Server-persisted theme (wizard pick or another browser's selection):
  // adopt it when the user has no local override — survives frontend
  // rebuilds and cleared localStorage. Legacy projects fall back to the
  // scaffold-time stylePack.
  useEffect(() => {
    if (!projectId) return
    try {
      if (localStorage.getItem(`agentapp-theme-${projectId}`)) return
      const serverTheme = project?.uiTheme?.themeId || project?.stylePack
      if (serverTheme && serverTheme !== 'craftbot') {
        setAgentAppTheme(serverTheme as AgentAppThemeId)
        const colors = project?.uiTheme?.customColors
        if (serverTheme === 'custom' && colors?.bg && colors?.surface && colors?.text && colors?.accent) {
          setAgentAppCustomColors({
            bg: colors.bg, surface: colors.surface, text: colors.text, accent: colors.accent,
          })
        }
      }
    } catch { /* cosmetic only */ }
  }, [projectId, project?.uiTheme, project?.stylePack])

  // Build-event feed + live-activity row for the construction dock (read-only).
  const buildEvents = projectId
    ? (buildEventsMap[projectId] ?? EMPTY_EVENTS)
    : EMPTY_EVENTS
  const snapshot = projectId ? (snapshotMap[projectId] ?? null) : null

  // Set active Agent App when viewing
  useEffect(() => {
    if (projectId) {
      setActiveAgentApp(projectId)
    }
    return () => {
      setActiveAgentApp(null)
    }
  }, [projectId, setActiveAgentApp])

  // Persistent iframe — lives in a pool on document.body, positioned over the placeholder
  useEffect(() => {
    if (!projectId || project?.status !== 'running' || !project?.url) {
      if (projectId) hideIframe(projectId)
      return
    }

    getOrCreateIframe(projectId, project.url)

    const updatePosition = () => {
      if (iframePlaceholderRef.current && projectId) {
        showIframe(projectId, iframePlaceholderRef.current.getBoundingClientRect())
      }
    }

    // Track container size/position changes
    const observer = new ResizeObserver(updatePosition)
    if (iframePlaceholderRef.current) {
      observer.observe(iframePlaceholderRef.current)
    }
    window.addEventListener('resize', updatePosition)

    // Initial position
    updatePosition()

    return () => {
      observer.disconnect()
      window.removeEventListener('resize', updatePosition)
      if (projectId) hideIframe(projectId)
    }
  }, [projectId, project?.status, project?.url])

  // Send the selected Agent App theme + current app mode to the iframe.
  // NOTE: the postMessage `type` stays 'livingui-theme' — it is the wire
  // contract with apps already built by their bridge. Renaming it (like the
  // rest of the Living UI → Agent App rename) would silently break theme
  // following for every app scaffolded before the rename, so it's kept stable
  // exactly like the other retained runtime values (trigger/session values).
  useEffect(() => {
    if (!projectId || project?.status !== 'running') return
    postMessageToIframe(projectId, {
      type: 'livingui-theme',
      themeId: agentAppTheme,
      mode: appTheme,
      // Only for the 'custom' theme — the bridge applies these as inline
      // overrides that outrank every style-pack rule.
      customColors: agentAppTheme === 'custom' ? agentAppCustomColors : undefined,
    })
  }, [agentAppTheme, agentAppCustomColors, appTheme, projectId, project?.status])

  // When the iframe finishes loading it sends 'craftbot-theme-request'. Reply
  // with the saved per-project theme so the palette persists across refreshes.
  useEffect(() => {
    if (!projectId) return
    const onIframeReady = (e: MessageEvent) => {
      if (e.data?.type !== 'craftbot-theme-request' || !e.source) return
      if (!ownsProjectWindow(projectId, e.source)) return
      ;(e.source as Window).postMessage({
        // Stable wire type — see the send effect above.
        type: 'livingui-theme',
        themeId: agentAppTheme,
        mode: appTheme,
        customColors: agentAppTheme === 'custom' ? agentAppCustomColors : undefined,
      }, '*')
    }
    window.addEventListener('message', onIframeReady)
    return () => window.removeEventListener('message', onIframeReady)
  }, [projectId, agentAppTheme, agentAppCustomColors, appTheme])

  const handleThemeSelect = (themeId: AgentAppThemeId, colors?: AgentAppCustomColors) => {
    if (!projectId) return
    setAgentAppTheme(themeId)
    saveAgentAppTheme(projectId, themeId)
    if (colors) {
      setAgentAppCustomColors(colors)
      saveAgentAppCustomColors(projectId, colors)
    }
    // Server-side persistence so the pick follows the user across browsers.
    updateAgentAppTheme(projectId, {
      themeId,
      ...(themeId === 'custom' ? { customColors: colors ?? agentAppCustomColors } : {}),
    })
  }

  const handleLaunch = () => {
    if (projectId) {
      launchAgentApp(projectId)
    }
  }

  const handleDelete = () => {
    if (projectId) {
      removeIframe(projectId)
      deleteAgentApp(projectId)
      navigate('/')
    }
  }

  // The seam handle does double duty: drag it to resize the panel, or click it
  // (no drag) to collapse/expand. Pointer events cover both mouse and touch.
  const handlePointerDown = (e: React.PointerEvent) => {
    e.preventDefault()
    dragRef.current = { startX: e.clientX, startY: e.clientY, moved: false }
    setIsResizing(true)
  }

  const toggleChat = () => setShowChat(prev => !prev)

  useEffect(() => {
    if (!isResizing) return

    const handlePointerMove = (e: PointerEvent) => {
      if (!dragRef.current) return
      if (
        Math.abs(e.clientX - dragRef.current.startX) > 4 ||
        Math.abs(e.clientY - dragRef.current.startY) > 4
      ) {
        dragRef.current.moved = true
      }
      // A collapsed panel has nothing to resize — the handle is click-only.
      if (!showChat) return
      const rect = contentRef.current?.getBoundingClientRect()
      if (!rect) return
      if (isMobile) {
        const ratio = (rect.bottom - e.clientY) / rect.height
        // Dragged too small ⇒ collapse and end the drag.
        if (ratio < MOBILE_COLLAPSE_RATIO) {
          dragRef.current = null
          setIsResizing(false)
          setShowChat(false)
          return
        }
        setMobileChatRatio(Math.max(MOBILE_MIN_RATIO, Math.min(MOBILE_MAX_RATIO, ratio)))
      } else {
        const newWidth = rect.right - e.clientX
        if (newWidth < PANEL_COLLAPSE_WIDTH) {
          dragRef.current = null
          setIsResizing(false)
          setShowChat(false)
          return
        }
        setPanelWidth(Math.max(PANEL_MIN_WIDTH, Math.min(PANEL_MAX_WIDTH, newWidth)))
      }
    }

    const handlePointerUp = () => {
      // No meaningful movement ⇒ it was a click ⇒ toggle the panel.
      const wasClick = !!dragRef.current && !dragRef.current.moved
      dragRef.current = null
      setIsResizing(false)
      if (wasClick) toggleChat()
    }

    document.addEventListener('pointermove', handlePointerMove)
    document.addEventListener('pointerup', handlePointerUp)
    document.addEventListener('pointercancel', handlePointerUp)

    return () => {
      document.removeEventListener('pointermove', handlePointerMove)
      document.removeEventListener('pointerup', handlePointerUp)
      document.removeEventListener('pointercancel', handlePointerUp)
    }
  }, [isResizing, isMobile, showChat])

  // Project not found
  if (!project) {
    return (
      <div className={styles.notFound}>
        <AlertCircle size={48} />
        <h2>{t('agentapp:page.notFoundTitle')}</h2>
        <p>{t('agentapp:page.notFoundBody')}</p>
        <Button variant="primary" onClick={() => navigate('/')}>
          {t('agentapp:page.goToChat')}
        </Button>
      </div>
    )
  }

  return (
    <div className={`${styles.container} ${isResizing ? styles.resizing : ''}`}>
      {/* Main Content Area. The old top bar is gone: lifecycle + view controls
          now live on the sidebar row, and the chat panel collapses to an edge
          rail (below) so it can be hidden without losing its re-open affordance. */}
      <div ref={contentRef} className={styles.content}>
        {/* Agent App Iframe */}
        <div className={styles.iframeContainer}>
          {project.status === 'running' && project.url ? (
            <div ref={iframePlaceholderRef} className={styles.iframe} />
          ) : project.status === 'creating' ? (
            <ConstructionDock
              project={project}
              todos={agentAppTodos[project.id]}
              events={buildEvents}
              snapshot={snapshot}
            />
          ) : project.status === 'launching' ? (
            <div className={styles.loading}>
              <CraftBotMascot state="launching" size={96} />
              <p>{t('agentapp:page.launchingTitle')}</p>
              <p className={styles.hint}>{t('agentapp:page.launchingHint')}</p>
            </div>
          ) : project.status === 'stopping' ? (
            <div className={styles.loading}>
              <Loader2 size={48} className={styles.spinner} />
              <p>{t('agentapp:page.stoppingTitle')}</p>
            </div>
          ) : project.status === 'error' ? (
            <div className={styles.error}>
              <AlertCircle size={32} />
              <p>{t('agentapp:page.errorTitle')}</p>
              <p className={styles.errorMessage}>{project.error || t('common:status.unknownError')}</p>
              <Button variant="secondary" onClick={() => setShowDeleteModal(true)}>
                {t('agentapp:page.deleteProject')}
              </Button>
            </div>
          ) : (
            <div className={styles.stopped}>
              <CraftBotMascot state="stopped" size={96} />
              <p>{t('agentapp:page.stoppedTitle')}</p>
              <Button variant="primary" onClick={handleLaunch}>
                <Play size={16} /> {t('agentapp:page.launch')}
              </Button>
            </div>
          )}
        </div>

        {/* Seam handle: drag to resize, click to collapse/expand. When
            collapsed the panel is gone and this parks at the edge as a
            half-visible tab — the only re-open affordance. Exists only when
            the backend gave this project a backing session; older projects
            without one just show the Agent App full-width. */}
        {project.sessionId && (
          <div
            className={`${styles.resizeHandle} ${!showChat ? styles.resizeHandleCollapsed : ''} ${isResizing ? styles.resizing : ''}`}
            onPointerDown={handlePointerDown}
            onKeyDown={e => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                toggleChat()
              }
            }}
            role="button"
            tabIndex={0}
            aria-expanded={showChat}
            aria-label={showChat ? t('agentapp:page.hideChat') : t('agentapp:page.showChat')}
            title={showChat ? t('agentapp:page.hideChat') : t('agentapp:page.showChat')}
          >
            <span className={styles.resizeGrip} aria-hidden="true" />
          </div>
        )}

        {/* Chat Panel. Kept mounted (when a session exists) so collapse/expand
            can animate its width/height to zero and back. The inner wrapper
            holds the panel's open size fixed, so the chat content slides out of
            view instead of reflowing as the outer size animates. Transitions are
            suppressed mid-drag (chatPanelDragging) so resizing tracks 1:1. */}
        {project.sessionId && (
          <div
            className={`${styles.chatPanel} ${!showChat ? styles.chatPanelCollapsed : ''} ${isResizing ? styles.chatPanelDragging : ''}`}
            style={
              isMobile
                ? { flexBasis: showChat ? `${mobileChatRatio * 100}%` : '0%' }
                : { width: showChat ? panelWidth : 0 }
            }
            aria-hidden={!showChat}
          >
            <div
              className={styles.chatPanelInner}
              style={isMobile ? undefined : { width: panelWidth }}
            >
              <Chat
                sessionId={project.sessionId}
                placeholder={t('agentapp:page.chatPlaceholder')}
              />
            </div>
          </div>
        )}
      </div>

      {/* Resize overlay — covers the Agent App iframe while dragging so the
          iframe doesn't swallow pointer events and abort the drag. */}
      {isResizing && <div className={styles.resizeOverlay} aria-hidden="true" />}

      {/* Theme Picker Modal */}
      <AgentAppThemeModal
        isOpen={showThemeModal}
        activeTheme={agentAppTheme}
        customColors={agentAppCustomColors}
        onSelect={handleThemeSelect}
        onClose={() => setShowThemeModal(false)}
      />

      {/* Delete Confirmation Modal */}
      <ConfirmModal
        isOpen={showDeleteModal}
        title={t('agentapp:page.deleteModalTitle')}
        message={t('agentapp:page.deleteModalMessage', { name: project.name })}
        confirmText={t('common:actions.delete')}
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setShowDeleteModal(false)}
      />
    </div>
  )
}
