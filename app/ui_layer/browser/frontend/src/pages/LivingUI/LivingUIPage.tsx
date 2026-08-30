import React, { useEffect, useState, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Box,
  RefreshCw,
  Trash2,
  Play,
  Square,
  AlertCircle,
  MessageSquare,
  Maximize2,
  Minimize2,
  Loader2,
  Palette,
} from 'lucide-react'
import { CraftBotMascot } from '@mascot'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useFullscreen } from '../../contexts/FullscreenContext'
import { useTheme } from '../../contexts/ThemeContext'
import { Button } from '../../components/ui/Button'
import { IconButton } from '../../components/ui/IconButton'
import { ConfirmModal } from '../../components/ui/ConfirmModal'
import { Chat } from '../../components/Chat'
import { getOrCreateIframe, showIframe, hideIframe, refreshIframe, removeIframe, postMessageToIframe, ownsProjectWindow } from './iframePool'
import { ConstructionDock } from './ConstructionDock'
import { LivingUIThemeModal, DEFAULT_CUSTOM_COLORS } from './LivingUIThemeModal'
import type { LivingUIThemeId, LivingUICustomColors } from './LivingUIThemeModal'
import { useAppSelector } from '../../store/hooks'
import { selectLivingUiBuildEvents, selectLivingUiSnapshots } from '../../store/selectors/livingUi'
import type { LivingUIBuildEvent } from '../../types'
import styles from './LivingUIPage.module.css'

// Stable empty array so the dock's memoized selectors don't churn per render.
const EMPTY_EVENTS: LivingUIBuildEvent[] = []

// Maps each backend status enum to its (type-checked) i18n key for the status pill.
const STATUS_LABEL_KEY = {
  creating: 'livingui:page.status.creating',
  launching: 'livingui:page.status.launching',
  ready: 'livingui:page.status.ready',
  running: 'livingui:page.status.running',
  stopping: 'livingui:page.status.stopping',
  stopped: 'livingui:page.status.stopped',
  error: 'livingui:page.status.error',
} as const

function loadLivingUITheme(projectId: string): LivingUIThemeId {
  try {
    const stored = localStorage.getItem(`livingui-theme-${projectId}`)
    if (stored) return stored as LivingUIThemeId
  } catch {}
  return 'craftbot'
}

function saveLivingUITheme(projectId: string, themeId: LivingUIThemeId) {
  try { localStorage.setItem(`livingui-theme-${projectId}`, themeId) } catch {}
}

function loadLivingUICustomColors(projectId: string): LivingUICustomColors {
  try {
    const raw = localStorage.getItem(`livingui-custom-colors-${projectId}`)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (parsed.bg && parsed.surface && parsed.text && parsed.accent) return parsed
    }
  } catch {}
  return { ...DEFAULT_CUSTOM_COLORS }
}

function saveLivingUICustomColors(projectId: string, colors: LivingUICustomColors) {
  try { localStorage.setItem(`livingui-custom-colors-${projectId}`, JSON.stringify(colors)) } catch {}
}

export function LivingUIPage() {
  const { t } = useTranslation(['livingui', 'common'])
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const {
    livingUIProjects,
    livingUITodos,
    launchLivingUI,
    stopLivingUI,
    deleteLivingUI,
    setActiveLivingUI,
    updateLivingUITheme,
  } = useWebSocket()
  const { isFullscreen, setFullscreen, toggleFullscreen } = useFullscreen()
  const { theme: appTheme } = useTheme()
  const buildEventsMap = useAppSelector(selectLivingUiBuildEvents)
  const snapshotMap = useAppSelector(selectLivingUiSnapshots)

  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showThemeModal, setShowThemeModal] = useState(false)
  const [livingUITheme, setLivingUITheme] = useState<LivingUIThemeId>(
    () => (projectId ? loadLivingUITheme(projectId) : 'craftbot')
  )
  const [livingUICustomColors, setLivingUICustomColors] = useState<LivingUICustomColors>(
    () => (projectId ? loadLivingUICustomColors(projectId) : { ...DEFAULT_CUSTOM_COLORS })
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

  // Track viewport width for mobile/desktop layout switch
  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth <= 768)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // Reset fullscreen when leaving the page so other pages aren't stuck without nav
  useEffect(() => {
    return () => setFullscreen(false)
  }, [setFullscreen])

  // ESC exits fullscreen
  useEffect(() => {
    if (!isFullscreen) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setFullscreen(false)
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [isFullscreen, setFullscreen])

  // Find the current project
  const project = livingUIProjects.find(p => p.id === projectId)

  // Server-persisted theme (wizard pick or another browser's selection):
  // adopt it when the user has no local override — survives frontend
  // rebuilds and cleared localStorage. Legacy projects fall back to the
  // scaffold-time stylePack.
  useEffect(() => {
    if (!projectId) return
    try {
      if (localStorage.getItem(`livingui-theme-${projectId}`)) return
      const serverTheme = project?.uiTheme?.themeId || project?.stylePack
      if (serverTheme && serverTheme !== 'craftbot') {
        setLivingUITheme(serverTheme as LivingUIThemeId)
        const colors = project?.uiTheme?.customColors
        if (serverTheme === 'custom' && colors?.bg && colors?.surface && colors?.text && colors?.accent) {
          setLivingUICustomColors({
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

  // Set active Living UI when viewing
  useEffect(() => {
    if (projectId) {
      setActiveLivingUI(projectId)
    }
    return () => {
      setActiveLivingUI(null)
    }
  }, [projectId, setActiveLivingUI])

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

  // Send the selected Living UI theme + current app mode to the iframe
  useEffect(() => {
    if (!projectId || project?.status !== 'running') return
    postMessageToIframe(projectId, {
      type: 'livingui-theme',
      themeId: livingUITheme,
      mode: appTheme,
      // Only for the 'custom' theme — the bridge applies these as inline
      // overrides that outrank every style-pack rule.
      customColors: livingUITheme === 'custom' ? livingUICustomColors : undefined,
    })
  }, [livingUITheme, livingUICustomColors, appTheme, projectId, project?.status])

  // When the iframe finishes loading it sends 'craftbot-theme-request'. Reply
  // with the saved per-project theme so the palette persists across refreshes.
  useEffect(() => {
    if (!projectId) return
    const onIframeReady = (e: MessageEvent) => {
      if (e.data?.type !== 'craftbot-theme-request' || !e.source) return
      if (!ownsProjectWindow(projectId, e.source)) return
      ;(e.source as Window).postMessage({
        type: 'livingui-theme',
        themeId: livingUITheme,
        mode: appTheme,
        customColors: livingUITheme === 'custom' ? livingUICustomColors : undefined,
      }, '*')
    }
    window.addEventListener('message', onIframeReady)
    return () => window.removeEventListener('message', onIframeReady)
  }, [projectId, livingUITheme, livingUICustomColors, appTheme])

  const handleThemeSelect = (themeId: LivingUIThemeId, colors?: LivingUICustomColors) => {
    if (!projectId) return
    setLivingUITheme(themeId)
    saveLivingUITheme(projectId, themeId)
    if (colors) {
      setLivingUICustomColors(colors)
      saveLivingUICustomColors(projectId, colors)
    }
    // Server-side persistence so the pick follows the user across browsers.
    updateLivingUITheme(projectId, {
      themeId,
      ...(themeId === 'custom' ? { customColors: colors ?? livingUICustomColors } : {}),
    })
  }

  const handleLaunch = () => {
    if (projectId) {
      launchLivingUI(projectId)
    }
  }

  const handleStop = () => {
    if (projectId) {
      stopLivingUI(projectId)
    }
  }

  const handleDelete = () => {
    if (projectId) {
      removeIframe(projectId)
      deleteLivingUI(projectId)
      navigate('/')
    }
  }

  const handleRefresh = () => {
    if (projectId) {
      refreshIframe(projectId)
    }
  }

  // Handle resize (horizontal on desktop, vertical on mobile). Uses pointer
  // events so both mouse and touch work on the mobile handle.
  const handlePointerDown = (e: React.PointerEvent) => {
    e.preventDefault()
    setIsResizing(true)
  }

  useEffect(() => {
    if (!isResizing) return

    const handlePointerMove = (e: PointerEvent) => {
      const rect = contentRef.current?.getBoundingClientRect()
      if (!rect) return
      if (isMobile) {
        const chatHeight = rect.bottom - e.clientY
        const ratio = chatHeight / rect.height
        setMobileChatRatio(Math.max(0.15, Math.min(0.85, ratio)))
      } else {
        const newWidth = rect.right - e.clientX
        setPanelWidth(Math.max(280, Math.min(600, newWidth)))
      }
    }

    const handlePointerUp = () => setIsResizing(false)

    document.addEventListener('pointermove', handlePointerMove)
    document.addEventListener('pointerup', handlePointerUp)
    document.addEventListener('pointercancel', handlePointerUp)

    return () => {
      document.removeEventListener('pointermove', handlePointerMove)
      document.removeEventListener('pointerup', handlePointerUp)
      document.removeEventListener('pointercancel', handlePointerUp)
    }
  }, [isResizing, isMobile])

  // Project not found
  if (!project) {
    return (
      <div className={styles.notFound}>
        <AlertCircle size={48} />
        <h2>{t('livingui:page.notFoundTitle')}</h2>
        <p>{t('livingui:page.notFoundBody')}</p>
        <Button variant="primary" onClick={() => navigate('/')}>
          {t('livingui:page.goToChat')}
        </Button>
      </div>
    )
  }

  return (
    <div className={`${styles.container} ${isResizing ? styles.resizing : ''}`}>
      {/* Menu Bar */}
      <div className={styles.menuBar}>
        <div className={styles.menuLeft}>
          <Box size={14} className={styles.projectIcon} />
          <h1 className={styles.projectName}>{project.name}</h1>
          <span className={`${styles.status} ${styles[project.status]}`}>
            {t(STATUS_LABEL_KEY[project.status])}
          </span>
          {isFullscreen && (
            <span className={styles.fullscreenBadge}>{t('livingui:page.fullscreen')}</span>
          )}
        </div>

        <div className={styles.menuActions}>
          {project.status === 'running' ? (
            <>
              <IconButton
                size="sm"
                icon={<RefreshCw size={14} />}
                tooltip={t('common:actions.refresh')}
                onClick={handleRefresh}
              />
              <IconButton
                size="sm"
                icon={<Square size={14} />}
                tooltip={t('livingui:page.stop')}
                onClick={handleStop}
              />
            </>
          ) : project.status === 'launching' || project.status === 'stopping' ? (
            <IconButton
              size="sm"
              disabled
              icon={<Loader2 size={14} className={styles.spinner} />}
              tooltip={project.status === 'launching' ? t('livingui:page.launching') : t('livingui:page.stopping')}
            />
          ) : project.status === 'ready' || project.status === 'stopped' ? (
            <IconButton
              size="sm"
              icon={<Play size={14} />}
              tooltip={t('livingui:page.launch')}
              onClick={handleLaunch}
            />
          ) : null}
          <IconButton
            size="sm"
            icon={<Palette size={14} />}
            tooltip={t('livingui:page.theme')}
            onClick={() => setShowThemeModal(true)}
          />
          {project.sessionId && (
            <IconButton
              size="sm"
              icon={<MessageSquare size={14} />}
              tooltip={showChat ? t('livingui:page.hideChat') : t('livingui:page.showChat')}
              onClick={() => setShowChat(prev => !prev)}
            />
          )}
          <IconButton
            size="sm"
            active={isFullscreen}
            icon={isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            tooltip={isFullscreen ? t('livingui:page.exitFullscreen') : t('livingui:page.fullscreen')}
            onClick={toggleFullscreen}
          />
          {project.status !== 'running' && (
            <IconButton
              size="sm"
              icon={<Trash2 size={14} />}
              tooltip={t('common:actions.delete')}
              variant="ghost"
              onClick={() => setShowDeleteModal(true)}
            />
          )}
        </div>
      </div>

      {/* Main Content Area */}
      <div ref={contentRef} className={styles.content}>
        {/* Living UI Iframe */}
        <div className={styles.iframeContainer}>
          {project.status === 'running' && project.url ? (
            <div ref={iframePlaceholderRef} className={styles.iframe} />
          ) : project.status === 'creating' ? (
            <ConstructionDock
              project={project}
              todos={livingUITodos[project.id]}
              events={buildEvents}
              snapshot={snapshot}
            />
          ) : project.status === 'launching' ? (
            <div className={styles.loading}>
              <CraftBotMascot state="launching" size={96} />
              <p>{t('livingui:page.launchingTitle')}</p>
              <p className={styles.hint}>{t('livingui:page.launchingHint')}</p>
            </div>
          ) : project.status === 'stopping' ? (
            <div className={styles.loading}>
              <Loader2 size={48} className={styles.spinner} />
              <p>{t('livingui:page.stoppingTitle')}</p>
            </div>
          ) : project.status === 'error' ? (
            <div className={styles.error}>
              <AlertCircle size={32} />
              <p>{t('livingui:page.errorTitle')}</p>
              <p className={styles.errorMessage}>{project.error || t('common:status.unknownError')}</p>
              <Button variant="secondary" onClick={() => setShowDeleteModal(true)}>
                {t('livingui:page.deleteProject')}
              </Button>
            </div>
          ) : (
            <div className={styles.stopped}>
              <CraftBotMascot state="stopped" size={96} />
              <p>{t('livingui:page.stoppedTitle')}</p>
              <Button variant="primary" onClick={handleLaunch}>
                <Play size={16} /> {t('livingui:page.launch')}
              </Button>
            </div>
          )}
        </div>

        {/* Resize Handle. The chat panel only exists when the backend gave
            this project a backing session — older projects without one just
            show the Living UI full-width. */}
        {showChat && project.sessionId && (
          <div
            className={`${styles.resizeHandle} ${isResizing ? styles.resizing : ''}`}
            onPointerDown={handlePointerDown}
          />
        )}

        {/* Chat Panel */}
        {showChat && project.sessionId && (
          <div
            className={styles.chatPanel}
            style={
              isMobile
                ? { flex: `0 0 ${mobileChatRatio * 100}%` }
                : { width: panelWidth }
            }
          >
            <Chat
              sessionId={project.sessionId}
              placeholder={t('livingui:page.chatPlaceholder')}
            />
          </div>
        )}
      </div>

      {/* Resize overlay — covers the Living UI iframe while dragging so the
          iframe doesn't swallow pointer events and abort the drag. */}
      {isResizing && <div className={styles.resizeOverlay} aria-hidden="true" />}

      {/* Theme Picker Modal */}
      <LivingUIThemeModal
        isOpen={showThemeModal}
        activeTheme={livingUITheme}
        customColors={livingUICustomColors}
        onSelect={handleThemeSelect}
        onClose={() => setShowThemeModal(false)}
      />

      {/* Delete Confirmation Modal */}
      <ConfirmModal
        isOpen={showDeleteModal}
        title={t('livingui:page.deleteModalTitle')}
        message={t('livingui:page.deleteModalMessage', { name: project.name })}
        confirmText={t('common:actions.delete')}
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setShowDeleteModal(false)}
      />
    </div>
  )
}
