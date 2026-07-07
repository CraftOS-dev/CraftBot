import React, { useEffect, useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
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
import { LivingUIIcon } from '../../components/ui/LivingUIIcon'
import { Chat } from '../../components/Chat'
import { getOrCreateIframe, showIframe, hideIframe, refreshIframe, removeIframe, postMessageToIframe, getIframeWindow } from './iframePool'
import { ConstructionView, devIframeKey } from './ConstructionView'
import { CreationQuestionForm } from './CreationQuestionForm'
import { LivingUIThemeModal, DEFAULT_CUSTOM_COLORS, buildThemeMessage } from './LivingUIThemeModal'
import type { LivingUIThemeId, LivingUICustomColors } from './LivingUIThemeModal'
import type { LivingUIBuildEvent } from '../../types'
import { useAppSelector, useAppDispatch } from '../../store/hooks'
import { selectLivingUiPendingQuestions, selectLivingUiBuildEvents } from '../../store/selectors/livingUi'
import { clearPendingQuestion } from '../../store/slices/livingUiSlice'
import styles from './LivingUIPage.module.css'

const EMPTY_EVENTS: LivingUIBuildEvent[] = []

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

function hasLocalTheme(projectId: string): boolean {
  try { return localStorage.getItem(`livingui-theme-${projectId}`) !== null } catch { return false }
}

// Origin of the embedded app, for postMessage target/source verification.
function projectOrigin(url?: string): string | null {
  if (!url) return null
  try { return new URL(url).origin } catch { return null }
}

export function LivingUIPage() {
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
    sendMessage,
  } = useWebSocket()
  const { isFullscreen, setFullscreen, toggleFullscreen } = useFullscreen()
  const { theme: appTheme } = useTheme()
  const dispatch = useAppDispatch()
  const pendingQuestions = useAppSelector(selectLivingUiPendingQuestions)
  const buildEventsMap = useAppSelector(selectLivingUiBuildEvents)

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

  // A question the agent mirrored onto this screen (waiting on the user's reply).
  const pendingQuestion = projectId ? pendingQuestions[projectId] : undefined

  // Live Construction View: shown for the whole build, and kept up through
  // the launch phase while the dev preview is still alive so there's no
  // blank gap between "creating" and "running".
  const buildEvents = projectId ? (buildEventsMap[projectId] ?? EMPTY_EVENTS) : EMPTY_EVENTS
  const showConstruction =
    !!project &&
    (project.status === 'creating' ||
      (!!project.devUrl && (project.status === 'ready' || project.status === 'launching')))

  // Once the production preview takes over, drop the dev iframe for good.
  useEffect(() => {
    if (projectId && project?.status === 'running') {
      removeIframe(devIframeKey(projectId))
    }
  }, [projectId, project?.status])

  // Answer from the screen → send back as a reply targeting the creation task's
  // session (Rule 2 in chat routing resumes the waiting task). Mirrors a chat reply.
  const handleAnswer = (text: string) => {
    if (!projectId || !pendingQuestion) return
    sendMessage(
      text,
      undefined,
      { sessionId: pendingQuestion.sessionId, originalMessage: pendingQuestion.message },
      projectId,
    )
    dispatch(clearPendingQuestion({ projectId }))
  }

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

  // Adopt the server-persisted theme when this browser has no local choice
  // yet (e.g. a different device/browser than the one that picked it).
  const adoptedServerTheme = useRef(false)
  useEffect(() => {
    if (!projectId || !project?.uiTheme || adoptedServerTheme.current) return
    adoptedServerTheme.current = true
    if (!hasLocalTheme(projectId)) {
      setLivingUITheme(project.uiTheme.themeId as LivingUIThemeId)
      if (project.uiTheme.customColors) {
        setLivingUICustomColors(project.uiTheme.customColors)
      }
    }
  }, [projectId, project?.uiTheme])

  // Send the selected Living UI theme to the iframe using the same
  // 'craftbot-theme' protocol the template's theme-sync script listens for.
  useEffect(() => {
    if (!projectId || project?.status !== 'running') return
    postMessageToIframe(
      projectId,
      buildThemeMessage(livingUITheme, appTheme, livingUICustomColors),
    )
  }, [livingUITheme, livingUICustomColors, appTheme, projectId, project?.status])

  // When the iframe finishes loading it sends 'craftbot-theme-request'. Reply
  // with the saved per-project theme so the palette persists across refreshes.
  useEffect(() => {
    if (!projectId) return
    const onIframeReady = (e: MessageEvent) => {
      if (e.data?.type !== 'craftbot-theme-request' || !e.source) return
      if (e.source !== getIframeWindow(projectId)) return
      const expectedOrigin = projectOrigin(project?.url)
      if (expectedOrigin && e.origin !== expectedOrigin) return
      ;(e.source as Window).postMessage(
        buildThemeMessage(livingUITheme, appTheme, livingUICustomColors),
        expectedOrigin ?? e.origin,
      )
    }
    window.addEventListener('message', onIframeReady)
    return () => window.removeEventListener('message', onIframeReady)
  }, [projectId, livingUITheme, livingUICustomColors, appTheme, project?.url])

  const handleThemeSelect = (themeId: LivingUIThemeId, colors?: LivingUICustomColors) => {
    if (!projectId) return
    setLivingUITheme(themeId)
    saveLivingUITheme(projectId, themeId)
    if (colors) {
      setLivingUICustomColors(colors)
      saveLivingUICustomColors(projectId, colors)
    }
    // Persist with the project so the choice survives this browser's storage.
    updateLivingUITheme(projectId, themeId, colors ?? livingUICustomColors)
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
      removeIframe(devIframeKey(projectId))
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
        <h2>Living UI Not Found</h2>
        <p>The Living UI project you're looking for doesn't exist or has been deleted.</p>
        <Button variant="primary" onClick={() => navigate('/')}>
          Go to Chat
        </Button>
      </div>
    )
  }

  return (
    <div className={`${styles.container} ${isResizing ? styles.resizing : ''}`}>
      {/* Menu Bar */}
      <div className={styles.menuBar}>
        <div className={styles.menuLeft}>
          <LivingUIIcon icon={project.icon} projectId={project.id} size={14} className={styles.projectIcon} />
          <h1 className={styles.projectName}>{project.name}</h1>
          <span className={`${styles.status} ${styles[project.status]}`}>
            {project.status}
          </span>
          {isFullscreen && (
            <span className={styles.fullscreenBadge}>Fullscreen</span>
          )}
        </div>

        <div className={styles.menuActions}>
          {project.status === 'running' ? (
            <>
              <IconButton
                size="sm"
                icon={<RefreshCw size={14} />}
                tooltip="Refresh"
                onClick={handleRefresh}
              />
              <IconButton
                size="sm"
                icon={<Square size={14} />}
                tooltip="Stop"
                onClick={handleStop}
              />
            </>
          ) : project.status === 'launching' || project.status === 'stopping' ? (
            <IconButton
              size="sm"
              disabled
              icon={<Loader2 size={14} className={styles.spinner} />}
              tooltip={project.status === 'launching' ? 'Launching…' : 'Stopping…'}
            />
          ) : project.status === 'ready' || project.status === 'stopped' ? (
            <IconButton
              size="sm"
              icon={<Play size={14} />}
              tooltip="Launch"
              onClick={handleLaunch}
            />
          ) : null}
          <IconButton
            size="sm"
            icon={<Palette size={14} />}
            tooltip="Theme"
            onClick={() => setShowThemeModal(true)}
          />
          <IconButton
            size="sm"
            icon={<MessageSquare size={14} />}
            tooltip={showChat ? 'Hide Chat' : 'Show Chat'}
            onClick={() => setShowChat(prev => !prev)}
          />
          <IconButton
            size="sm"
            active={isFullscreen}
            icon={isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            tooltip={isFullscreen ? 'Exit Fullscreen (Esc)' : 'Fullscreen'}
            onClick={toggleFullscreen}
          />
          {project.status !== 'running' && (
            <IconButton
              size="sm"
              icon={<Trash2 size={14} />}
              tooltip="Delete"
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
          ) : showConstruction ? (
            <>
              <ConstructionView
                project={project}
                todos={livingUITodos[project.id]}
                events={buildEvents}
              />
              {pendingQuestion && (
                <div className={styles.questionOverlay}>
                  <CreationQuestionForm
                    key={pendingQuestion.message}
                    projectName={project.name}
                    message={pendingQuestion.message}
                    onAnswer={handleAnswer}
                  />
                </div>
              )}
            </>
          ) : project.status === 'launching' ? (
            <div className={styles.loading}>
              <CraftBotMascot state="launching" size={96} />
              <p>Launching Living UI...</p>
              <p className={styles.hint}>Installing dependencies, running tests, starting servers</p>
            </div>
          ) : project.status === 'stopping' ? (
            <div className={styles.loading}>
              <Loader2 size={48} className={styles.spinner} />
              <p>Stopping Living UI...</p>
            </div>
          ) : project.status === 'error' ? (
            <div className={styles.error}>
              <AlertCircle size={32} />
              <p>Error creating Living UI</p>
              <p className={styles.errorMessage}>{project.error || 'Unknown error'}</p>
              <Button variant="secondary" onClick={() => setShowDeleteModal(true)}>
                Delete Project
              </Button>
            </div>
          ) : (
            <div className={styles.stopped}>
              <CraftBotMascot state="stopped" size={96} />
              <p>Living UI is not running</p>
              <Button variant="primary" onClick={handleLaunch}>
                <Play size={16} /> Launch
              </Button>
            </div>
          )}
        </div>

        {/* Resize Handle */}
        {showChat && (
          <div
            className={`${styles.resizeHandle} ${isResizing ? styles.resizing : ''}`}
            onPointerDown={handlePointerDown}
          />
        )}

        {/* Chat Panel */}
        {showChat && (
          <div
            className={styles.chatPanel}
            style={
              isMobile
                ? { flex: `0 0 ${mobileChatRatio * 100}%` }
                : { width: panelWidth }
            }
          >
            <Chat
              livingUIId={projectId}
              placeholder="Ask about this Living UI..."
              emptyMessage="Chat with the agent"
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
        title="Delete Living UI"
        message={`Are you sure you want to delete "${project.name}"? This action cannot be undone.`}
        confirmText="Delete"
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setShowDeleteModal(false)}
      />
    </div>
  )
}
