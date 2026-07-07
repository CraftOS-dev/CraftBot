import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  MessageSquare,
  ListTodo,
  LayoutDashboard,
  FolderOpen,
  Settings,
  Sparkles,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen
} from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useTheme } from '../../contexts/ThemeContext'
import { CreateLivingUIModal } from '../ui/CreateLivingUIModal'
import { LivingUIIcon } from '../ui/LivingUIIcon'
import { TopBar } from './TopBar'
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
]

const settingsItem: NavItem = { id: 'settings', label: 'Settings', icon: <Settings size={16} />, path: '/settings' }

interface NavBarProps {
  collapsed?: boolean
  onToggleCollapsed?: () => void
}

export function NavBar({ collapsed = false, onToggleCollapsed }: NavBarProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const { livingUIProjects } = useWebSocket()
  const { theme } = useTheme()
  const [showCreateModal, setShowCreateModal] = useState(false)

  const logoSrc = theme === 'light'
    ? '/craftbot_logo_text_no_border_light.png'
    : '/craftbot_logo_text_no_border_dark.png'

  const scrollRef = useRef<HTMLDivElement>(null)

  const [canScrollUp, setCanScrollUp] = useState(false)
  const [canScrollDown, setCanScrollDown] = useState(false)

  const isActive = (path: string) => {
    if (path === '/') {
      return location.pathname === '/'
    }
    return location.pathname.startsWith(path)
  }


  const updateOverflow = () => {
    const el = scrollRef.current
    if (!el) return
    const maxScroll = el.scrollHeight - el.clientHeight
    setCanScrollUp(el.scrollTop > 1)
    setCanScrollDown(el.scrollTop < maxScroll - 1)
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

  return (
    <>
      <nav className={`${styles.navBar} ${collapsed ? styles.collapsed : ''}`}>
        {/* Top: logo (left) + collapse toggle (right). Hidden on mobile drawer. */}
        {onToggleCollapsed && (
          <div className={styles.collapseRow}>
            {!collapsed && (
              <img
                src={logoSrc}
                alt="CraftBot"
                className={styles.logo}
                draggable={false}
              />
            )}
            <button
              type="button"
              className={styles.collapseButton}
              onClick={onToggleCollapsed}
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              aria-pressed={collapsed}
              title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            </button>
          </div>
        )}

        {/* Scrollable region with fades for left nav + Living UI tabs */}
        <div className={styles.scrollArea}>
          <div
            ref={scrollRef}
            className={styles.scrollContent}
            onScroll={updateOverflow}
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
                      : <LivingUIIcon icon={project.icon} projectId={project.id} size={13} />}
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
            className={`${styles.fade} ${styles.fadeLeft} ${canScrollUp ? styles.fadeVisible : ''}`}
            aria-hidden="true"
          />
          <div
            className={`${styles.fade} ${styles.fadeRight} ${canScrollDown ? styles.fadeVisible : ''}`}
            aria-hidden="true"
          />
        </div>

        {/* Bottom toolbar: version + action icons */}
        <TopBar collapsed={collapsed} />

        {/* Settings, pinned at very bottom */}
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
        onCreated={projectId => {
          setShowCreateModal(false)
          navigate(`/living-ui/${projectId}`)
        }}
      />
      {/* No onInstalled/navigate for MARKETPLACE installs — they just spawn a
          tab in the navbar; the user opens it themselves. The custom wizard's
          onCreated DOES navigate: the user watches the build live. */}
    </>
  )
}
