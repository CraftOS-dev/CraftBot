import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  MessageSquare,
  ListTodo,
  LayoutDashboard,
  FolderOpen,
  Settings,
  Sparkles,
  Box,
  Loader2,
  Heart
} from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { CreateLivingUIModal } from '../ui/CreateLivingUIModal'
import type { LivingUICreateRequest } from '../../types'
import styles from './NavBar.module.css'

interface NavItem {
  id: string
  label: string
  icon: React.ReactNode
  path: string
}

const leftNavItems: NavItem[] = [
  { id: 'chat', label: 'Chat', icon: <MessageSquare size={16} />, path: '/' },
  { id: 'tasks', label: 'Tasks', icon: <ListTodo size={16} />, path: '/tasks' },
  { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard size={16} />, path: '/dashboard' },
  { id: 'workspace', label: 'Workspace', icon: <FolderOpen size={16} />, path: '/workspace' },
  { id: 'pet', label: 'Pet', icon: <Heart size={16} />, path: '/pet' },
]

const settingsItem: NavItem = { id: 'settings', label: 'Settings', icon: <Settings size={16} />, path: '/settings' }

const DRAG_THRESHOLD = 5

export function NavBar() {
  const location = useLocation()
  const navigate = useNavigate()
  const { livingUIProjects, createLivingUI } = useWebSocket()
  const [showCreateModal, setShowCreateModal] = useState(false)

  const scrollRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef({
    pointerId: -1,
    startX: 0,
    startScrollLeft: 0,
    moved: false,
  })

  const [canScrollLeft, setCanScrollLeft] = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(false)

  const isActive = (path: string) => {
    if (path === '/') {
      return location.pathname === '/'
    }
    return location.pathname.startsWith(path)
  }

  const handleCreateSubmit = (data: LivingUICreateRequest) => {
    createLivingUI(data)
    setShowCreateModal(false)
  }

  const updateOverflow = () => {
    const el = scrollRef.current
    if (!el) return
    const maxScroll = el.scrollWidth - el.clientWidth
    setCanScrollLeft(el.scrollLeft > 1)
    setCanScrollRight(el.scrollLeft < maxScroll - 1)
  }

  useLayoutEffect(() => {
    updateOverflow()
  }, [livingUIProjects.length])

  useEffect(() => {
    const el = scrollRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(updateOverflow)
    ro.observe(el)
    window.addEventListener('resize', updateOverflow)
    return () => {
      ro.disconnect()
      window.removeEventListener('resize', updateOverflow)
    }
  }, [])

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!scrollRef.current) return
    dragRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startScrollLeft: scrollRef.current.scrollLeft,
      moved: false,
    }
  }

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (drag.pointerId !== e.pointerId || !scrollRef.current) return
    const dx = e.clientX - drag.startX
    if (!drag.moved && Math.abs(dx) < DRAG_THRESHOLD) return
    if (!drag.moved) {
      drag.moved = true
      scrollRef.current.setPointerCapture?.(e.pointerId)
    }
    scrollRef.current.scrollLeft = drag.startScrollLeft - dx
  }

  const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (drag.pointerId !== e.pointerId) return
    if (drag.moved && scrollRef.current?.hasPointerCapture?.(e.pointerId)) {
      scrollRef.current.releasePointerCapture(e.pointerId)
    }
    drag.pointerId = -1
    queueMicrotask(() => {
      drag.moved = false
    })
  }

  const onClickCapture = (e: React.MouseEvent<HTMLDivElement>) => {
    if (dragRef.current.moved) {
      e.stopPropagation()
      e.preventDefault()
    }
  }

  return (
    <>
      <nav className={styles.navBar}>
        {/* Left + middle: draggable / scrollable region with fades */}
        <div className={styles.scrollArea}>
          <div
            ref={scrollRef}
            className={styles.scrollContent}
            onScroll={updateOverflow}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            onClickCapture={onClickCapture}
          >
            {leftNavItems.map(item => (
              <button
                key={item.id}
                className={`${styles.navItem} ${isActive(item.path) ? styles.active : ''}`}
                onClick={() => navigate(item.path)}
                title={item.label}
              >
                <span className={styles.icon}>{item.icon}</span>
                <span className={styles.label}>{item.label}</span>
              </button>
            ))}

            <div className={styles.innerDivider} aria-hidden="true" />

            {livingUIProjects.map(project => {
              const path = `/living-ui/${project.id}`
              const active = isActive(path)
              return (
                <button
                  key={project.id}
                  className={`${styles.livingUITab} ${active ? styles.livingUITabActive : ''}`}
                  onClick={() => navigate(path)}
                  title={project.name}
                >
                  <span className={styles.livingUITabIcon}>
                    {project.status === 'creating' || project.status === 'launching' || project.status === 'stopping'
                      ? <Loader2 size={13} className={styles.spinner} />
                      : <Box size={13} />}
                  </span>
                  <span className={styles.livingUITabLabel}>{project.name}</span>
                </button>
              )
            })}

            <button
              className={styles.addLivingUIButton}
              onClick={() => setShowCreateModal(true)}
              title="Add Living UI"
            >
              <Sparkles size={14} className={styles.addLivingUIIcon} />
              <span className={styles.addLivingUILabel}>Add Living UI</span>
            </button>
          </div>

          <div
            className={`${styles.fade} ${styles.fadeLeft} ${canScrollLeft ? styles.fadeVisible : ''}`}
            aria-hidden="true"
          />
          <div
            className={`${styles.fade} ${styles.fadeRight} ${canScrollRight ? styles.fadeVisible : ''}`}
            aria-hidden="true"
          />
        </div>

        <div className={styles.divider} aria-hidden="true" />

        {/* Right: Settings, always pinned */}
        <div className={styles.navRight}>
          <button
            className={`${styles.navItem} ${isActive(settingsItem.path) ? styles.active : ''}`}
            onClick={() => navigate(settingsItem.path)}
            title={settingsItem.label}
          >
            <span className={styles.icon}>{settingsItem.icon}</span>
            <span className={styles.label}>{settingsItem.label}</span>
          </button>
        </div>
      </nav>

      <CreateLivingUIModal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        onSubmit={handleCreateSubmit}
      />
      {/* No onInstalled/navigate: marketplace installs just spawn a tab in the
          navbar (like form-create) — the user opens it themselves. */}
    </>
  )
}
