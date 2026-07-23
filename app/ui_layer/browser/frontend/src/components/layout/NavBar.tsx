import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
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
  SquarePen,
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

// Sidebar title with a typewriter reveal: when the auto-title replaces the
// "New chat" placeholder, the new name types in character by character with
// a blinking caret. Manual renames and any other title change swap
// instantly — the animation marks only the LLM-generated christening.
function AnimatedSessionTitle({ title }: { title: string }) {
  const [display, setDisplay] = useState(title)
  const [typing, setTyping] = useState(false)
  const prevRef = useRef(title)

  useEffect(() => {
    const prev = prevRef.current
    prevRef.current = title
    if (title === prev) return
    if (prev.trim().toLowerCase() !== 'new chat') {
      setDisplay(title)
      return
    }
    setTyping(true)
    setDisplay('')
    let i = 0
    const id = window.setInterval(() => {
      i += 1
      setDisplay(title.slice(0, i))
      if (i >= title.length) {
        window.clearInterval(id)
        setTyping(false)
      }
    }, 40)
    return () => {
      window.clearInterval(id)
      setTyping(false)
    }
  }, [title])

  return (
    <>
      {display}
      {typing && <span className={styles.titleCaret} aria-hidden="true" />}
    </>
  )
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

// Collapsed/expanded state of the sidebar groups, persisted so collapsing
// a group survives reloads. Only the COLLAPSED state is stored ("1");
// absence of the key means expanded (the default).
const GROUP_COLLAPSED_KEY_PREFIX = 'sidebarGroupCollapsed.'

// How many Living UI items show before the "Show more" row takes over.
const GROUP_PREVIEW_COUNT = 5

// Chats never truncate behind a "Show more" — the full list is always
// reachable. Rows mount in pages of this size as the sidebar scrolls.
const CHAT_PAGE_SIZE = 30

type SidebarGroup = 'livingui' | 'chats'

const loadGroupExpanded = (group: SidebarGroup): boolean => {
  try {
    return localStorage.getItem(GROUP_COLLAPSED_KEY_PREFIX + group) !== '1'
  } catch {
    return true
  }
}

const persistGroupExpanded = (group: SidebarGroup, expanded: boolean) => {
  try {
    if (expanded) {
      localStorage.removeItem(GROUP_COLLAPSED_KEY_PREFIX + group)
    } else {
      localStorage.setItem(GROUP_COLLAPSED_KEY_PREFIX + group, '1')
    }
  } catch {
    // localStorage may be unavailable
  }
}

export function NavBar({ collapsed = false, onToggleCollapsed }: NavBarProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const {
    livingUIProjects,
    createLivingUI,
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

  const [chatsExpanded, setChatsExpanded] = useState(() => loadGroupExpanded('chats'))
  const [livingUIExpanded, setLivingUIExpanded] = useState(() => loadGroupExpanded('livingui'))
  // Living UI "Show more" state: only the first GROUP_PREVIEW_COUNT items
  // render until expanded. Not persisted — collapses back to 5 on reload.
  const [showAllLivingUI, setShowAllLivingUI] = useState(false)
  // Chats scroll pagination: how many chat rows are currently mounted.
  // Grows by CHAT_PAGE_SIZE whenever the sidebar scrolls near its bottom.
  const [chatVisibleCount, setChatVisibleCount] = useState(CHAT_PAGE_SIZE)
  // Ref mirror so the scroll handler (bound once via ResizeObserver) sees
  // the current total without re-subscribing.
  const chatTotalRef = useRef(0)
  chatTotalRef.current = chatSessions.length

  // Collapsed-sidebar flyout (ChatGPT-style): each group collapses to one
  // icon button whose click opens a popover listing the group's items.
  const [flyout, setFlyout] = useState<
    { kind: 'livingui' | 'chats'; top: number; left: number } | null
  >(null)

  const FLYOUT_MAX_HEIGHT = 420

  const openFlyout = (
    kind: 'livingui' | 'chats',
    e: React.MouseEvent<HTMLButtonElement>,
  ) => {
    if (flyout?.kind === kind) {
      setFlyout(null)
      return
    }
    const rect = e.currentTarget.getBoundingClientRect()
    setFlyout({
      kind,
      top: Math.max(8, Math.min(rect.top, window.innerHeight - 8 - FLYOUT_MAX_HEIGHT)),
      left: rect.right + 8,
    })
  }

  // Close the flyout on outside click, Escape, or when the sidebar expands.
  useEffect(() => {
    if (!flyout) return
    const close = () => setFlyout(null)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setFlyout(null)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', onKey)
    }
  }, [flyout])

  useEffect(() => {
    if (!collapsed) setFlyout(null)
  }, [collapsed])

  useEffect(() => {
    persistGroupExpanded('chats', chatsExpanded)
  }, [chatsExpanded])

  useEffect(() => {
    persistGroupExpanded('livingui', livingUIExpanded)
  }, [livingUIExpanded])
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

  // Lazy session creation: "New Chat" only opens the draft view at
  // /session/new. The real session is created by the backend on the first
  // message sent from that view (session_created then navigates us there).
  const startNewChat = () => {
    setChatsExpanded(true)
    navigate('/session/new')
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
    // Chats scroll pagination: nearing the bottom mounts the next page.
    // Functional update no-ops once every chat row is mounted.
    if (maxScroll - el.scrollTop < 80) {
      setChatVisibleCount(c => (c < chatTotalRef.current ? c + CHAT_PAGE_SIZE : c))
    }
  }

  useLayoutEffect(() => {
    updateOverflow()
  }, [livingUIProjects.length, chatSessions.length, chatsExpanded, livingUIExpanded, chatVisibleCount])

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

  const renderSessionRow = (session: SessionInfo, opts: { isMain: boolean }) => {
    const path = sessionPath(session.id)
    const active = isActive(path)
    const renaming = renamingId === session.id

    return (
      <div
        key={session.id}
        className={`${styles.sessionRow} ${active ? styles.sessionRowActive : ''} ${opts.isMain ? styles.sessionRowMain : ''}`}
        title={opts.isMain ? 'Main' : session.title}
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
              title={opts.isMain ? 'Main' : session.title}
            >
              <span className={styles.icon}>
                {opts.isMain ? <MessageSquare size={16} /> : <MessageCircle size={14} />}
              </span>
              <span className={styles.label}>
                {opts.isMain ? 'Main' : <AnimatedSessionTitle title={session.title} />}
              </span>
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
            {/* New Chat — action item pinned at the very top */}
            <button
              className={`${styles.navItem} ${location.pathname === '/session/new' ? styles.active : ''}`}
              onClick={startNewChat}
              title="New Chat"
            >
              <span className={styles.icon}><SquarePen size={16} /></span>
              <span className={styles.label}>New Chat</span>
            </button>

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

            <div className={styles.innerDivider} aria-hidden="true" />

            {collapsed ? (
              <>
                {/* Collapsed: each group is one icon button opening a flyout */}
                <button
                  className={`${styles.navItem} ${flyout?.kind === 'livingui' ? styles.active : ''}`}
                  onClick={e => openFlyout('livingui', e)}
                  onMouseDown={e => e.stopPropagation()}
                  title="Living UI"
                  aria-haspopup="menu"
                  aria-expanded={flyout?.kind === 'livingui'}
                >
                  <span className={styles.icon}><Box size={16} /></span>
                </button>
                <button
                  className={`${styles.navItem} ${flyout?.kind === 'chats' ? styles.active : ''}`}
                  onClick={e => openFlyout('chats', e)}
                  onMouseDown={e => e.stopPropagation()}
                  title="Chats"
                  aria-haspopup="menu"
                  aria-expanded={flyout?.kind === 'chats'}
                >
                  <span className={styles.icon}><MessageCircle size={16} /></span>
                  {(hasUnread('main') || chatSessions.some(s => hasUnread(s.id))) && (
                    <span className={styles.collapsedUnreadDot} aria-label="Unread messages" />
                  )}
                </button>
              </>
            ) : (
              <>
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
            {livingUIExpanded && (
              <div className={styles.groupChildren}>
                {(showAllLivingUI
                  ? livingUIProjects
                  : livingUIProjects.slice(0, GROUP_PREVIEW_COUNT)
                ).map(project => {
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
                {livingUIProjects.length > GROUP_PREVIEW_COUNT && (
                  <button
                    className={styles.showMoreRow}
                    onClick={() => setShowAllLivingUI(v => !v)}
                  >
                    {showAllLivingUI
                      ? 'Show less'
                      : `Show more (${livingUIProjects.length - GROUP_PREVIEW_COUNT})`}
                  </button>
                )}
                {livingUIProjects.length === 0 && (
                  <div className={styles.groupEmpty}>No Living UI apps</div>
                )}
              </div>
            )}

            <div className={styles.innerDivider} aria-hidden="true" />

            {/* Chats group — Main always pinned first inside it */}
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
                onClick={startNewChat}
                aria-label="New chat"
                title="New chat"
              >
                <Plus size={14} />
              </button>
            </div>
            {chatsExpanded && (
              <div className={styles.groupChildren}>
                {renderSessionRow(mainSessionInfo, { isMain: true })}
                {chatSessions.slice(0, chatVisibleCount).map(session =>
                  renderSessionRow(session, { isMain: false })
                )}
              </div>
            )}
              </>
            )}
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

      {/* Collapsed-sidebar flyout menu (rendered in a portal so it can sit
          beside the narrow nav). */}
      {flyout && createPortal(
        <div
          className={styles.flyout}
          style={{ top: flyout.top, left: flyout.left }}
          onMouseDown={e => e.stopPropagation()}
          role="menu"
        >
          <div className={styles.flyoutHeader}>
            {flyout.kind === 'livingui' ? 'Living UI' : 'Chats'}
          </div>
          <div className={styles.flyoutList}>
            {flyout.kind === 'livingui' ? (
              <>
                {livingUIProjects.map(project => {
                  const path = `/living-ui/${project.id}`
                  return (
                    <button
                      key={project.id}
                      className={`${styles.flyoutItem} ${isActive(path) ? styles.flyoutItemActive : ''}`}
                      onClick={() => {
                        setFlyout(null)
                        navigate(path)
                      }}
                      title={project.name}
                    >
                      <span className={styles.flyoutItemIcon}>
                        {project.status === 'creating' || project.status === 'launching' || project.status === 'stopping'
                          ? <Loader2 size={13} className={styles.spinner} />
                          : <Box size={13} />}
                      </span>
                      <span className={styles.flyoutItemLabel}>{project.name}</span>
                    </button>
                  )
                })}
                {livingUIProjects.length === 0 && (
                  <div className={styles.flyoutEmpty}>No Living UI apps</div>
                )}
              </>
            ) : (
              [mainSessionInfo, ...chatSessions].map(session => {
                const isMain = session.id === 'main'
                const path = sessionPath(session.id)
                return (
                  <button
                    key={session.id}
                    className={`${styles.flyoutItem} ${isActive(path) ? styles.flyoutItemActive : ''} ${isMain ? styles.flyoutItemMain : ''}`}
                    onClick={() => {
                      setFlyout(null)
                      navigate(path)
                    }}
                    title={isMain ? 'Main' : session.title}
                  >
                    <span className={styles.flyoutItemIcon}>
                      {isMain ? <MessageSquare size={13} /> : <MessageCircle size={13} />}
                    </span>
                    <span className={styles.flyoutItemLabel}>
                      {isMain ? 'Main' : <AnimatedSessionTitle title={session.title} />}
                    </span>
                    {hasUnread(session.id) && (
                      <span className={styles.unreadDot} aria-label="Unread messages" />
                    )}
                  </button>
                )
              })
            )}
          </div>
        </div>,
        document.body,
      )}

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
