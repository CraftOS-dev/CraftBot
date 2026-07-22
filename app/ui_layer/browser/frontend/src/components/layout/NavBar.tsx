import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  MessageSquare,
  MessageCircle,
  LayoutDashboard,
  FolderOpen,
  Settings,
  Box,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  ChevronRight,
  Plus,
  MoreHorizontal,
  Pencil,
  Eraser,
  Trash2,
  Sparkles,
} from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useTheme } from '../../contexts/ThemeContext'
import { useSkillCreator } from '../../hooks'
import { CreateLivingUIModal } from '../ui/CreateLivingUIModal'
import { SkillCreatorModal } from '../ui/SkillCreatorModal'
import type { LivingUICreateRequest, SessionInfo } from '../../types'
import { useAppSelector } from '../../store/hooks'
import { selectMainSession, selectChatSessions } from '../../store/selectors/sessions'
import { selectLastMessageIdBySession } from '../../store/selectors/messages'
import { TopBar } from './TopBar'
import styles from './NavBar.module.css'

interface NavItem {
  id: string
  label: string
  icon: React.ReactNode
  path: string
}

const utilityNavItems: NavItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard size={16} />, path: '/dashboard' },
  { id: 'workspace', label: 'Workspace', icon: <FolderOpen size={16} />, path: '/workspace' },
]

const settingsItem: NavItem = { id: 'settings', label: 'Settings', icon: <Settings size={16} />, path: '/settings' }

interface NavBarProps {
  collapsed?: boolean
  onToggleCollapsed?: () => void
}

// Per-row "…" context menu state: which session's menu is open.
interface SessionMenuState {
  sessionId: string
}

export function NavBar({ collapsed = false, onToggleCollapsed }: NavBarProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const {
    livingUIProjects,
    createLivingUI,
    createSession,
    deleteSession,
    renameSession,
    clearSession,
    lastSeenBySession,
    skillMeta,
  } = useWebSocket()
  const { theme } = useTheme()
  const [showCreateModal, setShowCreateModal] = useState(false)

  const mainSession = useAppSelector(selectMainSession)
  const chatSessions = useAppSelector(selectChatSessions)
  const lastMessageIdBySession = useAppSelector(selectLastMessageIdBySession)

  const [chatsExpanded, setChatsExpanded] = useState(true)
  const [livingUIExpanded, setLivingUIExpanded] = useState(true)
  const [menu, setMenu] = useState<SessionMenuState | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const renameInputRef = useRef<HTMLInputElement>(null)

  const skillCreator = useSkillCreator()
  const reservedSkillNames = useMemo(
    () => new Set(skillMeta.reservedSkillNames),
    [skillMeta.reservedSkillNames],
  )

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

  const sessionPath = (sessionId: string) =>
    sessionId === 'main' ? '/' : `/session/${sessionId}`

  const isSessionOpen = (sessionId: string) => isActive(sessionPath(sessionId))

  // A session shows the unread dot when it has messages newer than its
  // lastSeen marker and isn't the currently open session.
  const hasUnread = (sessionId: string): boolean => {
    if (isSessionOpen(sessionId)) return false
    const lastId = lastMessageIdBySession[sessionId]
    if (!lastId) return false
    return lastSeenBySession[sessionId] !== lastId
  }

  const handleCreateSubmit = (data: LivingUICreateRequest) => {
    createLivingUI(data)
    setShowCreateModal(false)
  }

  // Close any open context menu when clicking anywhere else.
  useEffect(() => {
    if (!menu) return
    const close = () => setMenu(null)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menu])

  useEffect(() => {
    if (renamingId) {
      renameInputRef.current?.focus()
      renameInputRef.current?.select()
    }
  }, [renamingId])

  const startRename = (session: SessionInfo) => {
    setMenu(null)
    setRenamingId(session.id)
    setRenameDraft(session.title)
  }

  const commitRename = () => {
    if (renamingId && renameDraft.trim()) {
      renameSession(renamingId, renameDraft.trim())
    }
    setRenamingId(null)
    setRenameDraft('')
  }

  const cancelRename = () => {
    setRenamingId(null)
    setRenameDraft('')
  }

  const handleClearSession = (sessionId: string) => {
    setMenu(null)
    clearSession(sessionId)
  }

  const handleDeleteSession = (sessionId: string) => {
    setMenu(null)
    deleteSession(sessionId)
    // Deleting the open session navigates back to Main.
    if (isSessionOpen(sessionId)) navigate('/')
  }

  const handleCreateSkill = (sessionId: string) => {
    setMenu(null)
    skillCreator.open(sessionId)
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
  }, [livingUIProjects.length, chatSessions.length, chatsExpanded, livingUIExpanded])

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

  // "…" context menu attached to a session row. `isMain` limits the menu
  // to Clear conversation + Create skill for the pinned Main session.
  const renderSessionMenu = (session: SessionInfo, isMain: boolean) => {
    if (menu?.sessionId !== session.id) return null
    return (
      <div className={styles.sessionMenu} onMouseDown={e => e.stopPropagation()}>
        {!isMain && (
          <button className={styles.sessionMenuItem} onClick={() => startRename(session)}>
            <Pencil size={13} /> Rename
          </button>
        )}
        <button className={styles.sessionMenuItem} onClick={() => handleClearSession(session.id)}>
          <Eraser size={13} /> Clear conversation
        </button>
        {!isMain && (
          <button
            className={`${styles.sessionMenuItem} ${styles.sessionMenuItemDanger}`}
            onClick={() => handleDeleteSession(session.id)}
          >
            <Trash2 size={13} /> Delete
          </button>
        )}
        <button className={styles.sessionMenuItem} onClick={() => handleCreateSkill(session.id)}>
          <Sparkles size={13} /> Create skill from this session
        </button>
      </div>
    )
  }

  const renderSessionRow = (session: SessionInfo, opts: { isMain: boolean; indent: boolean }) => {
    const path = sessionPath(session.id)
    const active = isActive(path)
    const renaming = renamingId === session.id

    return (
      <div
        key={session.id}
        className={`${styles.sessionRow} ${opts.indent ? styles.sessionRowIndent : ''} ${active ? styles.sessionRowActive : ''}`}
      >
        {renaming ? (
          <input
            ref={renameInputRef}
            className={styles.renameInput}
            value={renameDraft}
            onChange={e => setRenameDraft(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') commitRename()
              else if (e.key === 'Escape') cancelRename()
            }}
            onBlur={commitRename}
          />
        ) : (
          <>
            <button
              className={styles.sessionRowButton}
              onClick={() => navigate(path)}
              title={session.title}
            >
              <span className={styles.icon}>
                {opts.isMain ? <MessageSquare size={16} /> : <MessageCircle size={14} />}
              </span>
              <span className={styles.label}>{opts.isMain ? 'Main' : session.title}</span>
              {hasUnread(session.id) && <span className={styles.unreadDot} aria-label="Unread messages" />}
            </button>
            <button
              className={styles.sessionMenuButton}
              onClick={(e) => {
                e.stopPropagation()
                setMenu(prev =>
                  prev?.sessionId === session.id
                    ? null
                    : { sessionId: session.id })
              }}
              aria-label="Session options"
              title="Options"
            >
              <MoreHorizontal size={14} />
            </button>
            {renderSessionMenu(session, opts.isMain)}
          </>
        )}
      </div>
    )
  }

  // The Main session is always present in the UI (pinned first) even if the
  // backend hasn't confirmed it yet — its id is the well-known "main".
  const mainSessionInfo: SessionInfo = mainSession ?? {
    id: 'main',
    type: 'main',
    title: 'Main',
    createdAt: '',
    lastActiveAt: '',
  }

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

        {/* Scrollable region with fades */}
        <div className={styles.scrollArea}>
          <div
            ref={scrollRef}
            className={styles.scrollContent}
            onScroll={updateOverflow}
          >
            {/* Main — pinned first, always present */}
            {renderSessionRow(mainSessionInfo, { isMain: true, indent: false })}

            {/* Chats group */}
            <div className={styles.groupRow}>
              <button
                className={styles.groupToggle}
                onClick={() => setChatsExpanded(v => !v)}
                aria-expanded={chatsExpanded}
              >
                <ChevronRight
                  size={14}
                  className={`${styles.groupChevron} ${chatsExpanded ? styles.groupChevronOpen : ''}`}
                />
                <span className={styles.icon}><MessageCircle size={16} /></span>
                <span className={styles.label}>Chats</span>
              </button>
              <button
                className={styles.groupAddButton}
                onClick={() => {
                  setChatsExpanded(true)
                  createSession()
                }}
                aria-label="New chat"
                title="New chat"
              >
                <Plus size={14} />
              </button>
            </div>
            {chatsExpanded && chatSessions.map(session =>
              renderSessionRow(session, { isMain: false, indent: true })
            )}
            {chatsExpanded && chatSessions.length === 0 && (
              <div className={styles.groupEmpty}>No chats yet</div>
            )}

            {/* Living UI group */}
            <div className={styles.groupRow}>
              <button
                className={styles.groupToggle}
                onClick={() => setLivingUIExpanded(v => !v)}
                aria-expanded={livingUIExpanded}
              >
                <ChevronRight
                  size={14}
                  className={`${styles.groupChevron} ${livingUIExpanded ? styles.groupChevronOpen : ''}`}
                />
                <span className={styles.icon}><Box size={16} /></span>
                <span className={styles.label}>Living UI</span>
              </button>
              <button
                className={styles.groupAddButton}
                onClick={() => setShowCreateModal(true)}
                aria-label="Add Living UI"
                title="Add Living UI"
              >
                <Plus size={14} />
              </button>
            </div>
            {livingUIExpanded && livingUIProjects.map(project => {
              const path = `/living-ui/${project.id}`
              const active = isActive(path)
              return (
                <button
                  key={project.id}
                  className={`${styles.livingUITab} ${styles.sessionRowIndent} ${active ? styles.livingUITabActive : ''}`}
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
            {livingUIExpanded && livingUIProjects.length === 0 && (
              <div className={styles.groupEmpty}>No Living UI apps</div>
            )}

            <div className={styles.innerDivider} aria-hidden="true" />

            {/* Utility items */}
            {utilityNavItems.map(item => (
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
        onSubmit={handleCreateSubmit}
      />

      <SkillCreatorModal
        isOpen={skillCreator.isOpen}
        sourceSkills={[]}
        reservedNames={reservedSkillNames}
        status={skillCreator.status}
        serverError={skillCreator.serverError}
        successInfo={skillCreator.successInfo}
        onClose={skillCreator.close}
        onSubmit={skillCreator.submit}
      />
    </>
  )
}
