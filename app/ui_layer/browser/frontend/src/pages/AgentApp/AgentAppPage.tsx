import React, { useEffect, useState, useRef } from 'react'
import { flushSync } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { useParams, useNavigate } from 'react-router-dom'
import {
  AlertCircle,
} from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useAgentAppTheme } from '../../features/agentApps/useAgentAppTheme'
import { AgentAppSurface } from '../../features/agentApps/AgentAppSurface'
import { Button } from '../../components/ui/Button'
import { ConfirmModal } from '../../components/ui/ConfirmModal'
import { Chat } from '../../components/Chat'
import { removeIframe } from '../../features/agentApps/frameHost'
import { AgentAppThemeModal } from './AgentAppThemeModal'
import { usePersistedState } from '../../hooks'
import { openTriggerReview } from '../../store/slices/agentAppSlice'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  selectAgentAppProjects,
} from '../../store/selectors/agentApp'
import { UI_STATE } from '../../store/uiState'
import styles from './AgentAppPage.module.css'

// Chat panel resize bounds (desktop = px width, mobile = height ratio). Dragging
// the panel narrower than the COLLAPSE threshold snaps it shut instead of
// clamping — a natural "drag it away to hide it" gesture.
const PANEL_MIN_WIDTH = 220
const PANEL_MAX_WIDTH = 600
const PANEL_COLLAPSE_WIDTH = 180
const MOBILE_MIN_RATIO = 0.15
const MOBILE_MAX_RATIO = 0.85
const MOBILE_COLLAPSE_RATIO = 0.07

export function AgentAppPage() {
  const { t } = useTranslation(['agentapp', 'common'])
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const dispatch = useAppDispatch()
  const {
    deleteAgentApp,
    setActiveAgentApp,
  } = useWebSocket()
  const agentAppProjects = useAppSelector(selectAgentAppProjects)

  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showThemeModal, setShowThemeModal] = useState(false)
  // Chat panel layout: persisted preferences shared by every Agent App, so
  // they survive navigation, switching apps and reloads.
  const [showChat, setShowChat] = usePersistedState(UI_STATE.agentApp.chatPanelOpen)
  const [panelWidth, setPanelWidth] = usePersistedState(UI_STATE.agentApp.chatPanelWidth)
  const [mobileChatRatio, setMobileChatRatio] = usePersistedState(UI_STATE.agentApp.chatPanelMobileRatio)
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.innerWidth <= 768
  )
  const [isResizing, setIsResizing] = useState(false)
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
  const { agentAppTheme, agentAppCustomColors, handleThemeSelect } = useAgentAppTheme(project)

  // Set active Agent App when viewing
  useEffect(() => {
    if (projectId) {
      setActiveAgentApp(projectId)
    }
    return () => {
      setActiveAgentApp(null)
    }
  }, [projectId, setActiveAgentApp])

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

    // The drag ends and the panel collapses in one render: a pointermove is a
    // continuous event, so React would render the store's update (the panel
    // closing) before this component's (the drag ending), while the drag
    // still turns the panel's transition off, and the panel would jump shut.
    const collapseFromDrag = () => {
      dragRef.current = null
      flushSync(() => {
        setIsResizing(false)
        setShowChat(false)
      })
    }

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
        // Dragged too small ⇒ collapse (animated) and end the drag.
        if (ratio < MOBILE_COLLAPSE_RATIO) {
          collapseFromDrag()
          return
        }
        setMobileChatRatio(Math.max(MOBILE_MIN_RATIO, Math.min(MOBILE_MAX_RATIO, ratio)))
      } else {
        const newWidth = rect.right - e.clientX
        if (newWidth < PANEL_COLLAPSE_WIDTH) {
          collapseFromDrag()
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
      {project.triggerConsent && (project.triggerConsent.required || project.triggerConsent.triggers.length > 0) && (
        <div className={styles.triggerConsentBanner} role="status">
          <span>{project.triggerConsent.error || t(project.triggerConsent.required
            ? project.triggerConsent.triggers.some(request => request.change === 'approved')
              ? 'agentapp:triggerConsent.pendingChanges' : 'agentapp:triggerConsent.off'
            : 'agentapp:triggerConsent.on')}</span>
          <Button variant="secondary" size="sm" onClick={() => dispatch(openTriggerReview(project.id))}>
            {t('agentapp:triggerConsent.review')}
          </Button>
        </div>
      )}
      {/* Main Content Area. The old top bar is gone: lifecycle + view controls
          now live on the sidebar row, and the chat panel collapses to an edge
          rail (below) so it can be hidden without losing its re-open affordance. */}
      <div ref={contentRef} className={styles.content}>
        {/* Agent App Iframe */}
        <div className={styles.iframeContainer}>
          {project && <AgentAppSurface project={project} moving={isResizing}
            blocked={showThemeModal || showDeleteModal} onDelete={() => setShowDeleteModal(true)}
            themeManaged />}
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
                panelLayout="stacked"
                panelVisible={showChat}
                showAgentApps={false}
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
