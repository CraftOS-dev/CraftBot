import React, { useEffect, useState, useRef } from 'react'
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
} from 'lucide-react'
import { CraftBotMascot } from '@mascot'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useFullscreen } from '../../contexts/FullscreenContext'
import { Button } from '../../components/ui/Button'
import { IconButton } from '../../components/ui/IconButton'
import { ConfirmModal } from '../../components/ui/ConfirmModal'
import { Chat } from '../../components/Chat'
import { getOrCreateIframe, showIframe, hideIframe, refreshIframe, removeIframe } from './iframePool'
import { CreationProgress } from './CreationProgress'
import type { LivingUIProject } from '../../types'
import styles from './LivingUIPage.module.css'

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
  } = useWebSocket()
  const { isFullscreen, setFullscreen, toggleFullscreen } = useFullscreen()

  const [showDeleteModal, setShowDeleteModal] = useState(false)
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
          <Box size={14} className={styles.projectIcon} />
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
          ) : project.status === 'creating' ? (
            <CreationProgress
              projectName={project.name}
              todos={livingUITodos[project.id]}
            />
          ) : project.status === 'launching' ? (
            <div className={styles.loading}>
              <CraftBotMascot state="launching" size={96} />
              <p>Launching Living UI...</p>
              <p className={styles.hint}>Installing dependencies, running tests, starting servers</p>
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
