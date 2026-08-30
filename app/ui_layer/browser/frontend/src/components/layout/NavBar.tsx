import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  MessageSquare,
  MessageCircle,
  LayoutDashboard,
  FolderOpen,
  Settings,
  Waypoints,
  Box,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  ChevronRight,
  Plus,
  MoreHorizontal,
  Info,
  Pencil,
  SquarePen,
  Eraser,
  Trash2,
  Sparkles,
} from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useTheme } from '../../contexts/ThemeContext'
import { tourAnchorProps, useTourEnvAction, type TourAnchorId } from '../../tour'
import { useSkillCreator } from '../../hooks'
import { CreateAgentAppModal } from '../ui/CreateAgentAppModal'
import { SkillCreatorModal } from '../ui/SkillCreatorModal'
import { AgentAppIcon } from '../ui/AgentAppIcon'
import type { SessionInfo } from '../../types'
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
  tourAnchor?: TourAnchorId
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

// How many Agent App items show before the "Show more" row takes over.
const GROUP_PREVIEW_COUNT = 5

// Chats never truncate behind a "Show more" — the full list is always
// reachable. Rows mount in pages of this size as the sidebar scrolls.
const CHAT_PAGE_SIZE = 30

type SidebarGroup = 'agentapp' | 'chats'

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
  const { t } = useTranslation(['nav', 'common'])
  const location = useLocation()
  const navigate = useNavigate()

  const utilityNavItems: NavItem[] = useMemo(() => [
    { id: 'dashboard', label: t('nav:items.dashboard'), icon: <LayoutDashboard size={16} />, path: '/dashboard', tourAnchor: 'nav-dashboard' },
    { id: 'memory', label: t('nav:items.memory'), icon: <Waypoints size={16} />, path: '/memory', tourAnchor: 'nav-memory' },
    { id: 'workspace', label: t('nav:items.workspace'), icon: <FolderOpen size={16} />, path: '/workspace', tourAnchor: 'nav-workspace' },
  ], [t])

  const settingsItem: NavItem = useMemo(
    () => ({ id: 'settings', label: t('nav:items.settings'), icon: <Settings size={16} />, path: '/settings' }),
    [t],
  )
  const {
    agentAppProjects,
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
  const runStateBySession = useAppSelector(state => state.agent.runStateBySession)

  const [chatsExpanded, setChatsExpanded] = useState(() => loadGroupExpanded('chats'))
  const [agentAppExpanded, setAgentAppExpanded] = useState(() => loadGroupExpanded('agentapp'))
  // Agent App "Show more" state: only the first GROUP_PREVIEW_COUNT items
  // render until expanded. Not persisted — collapses back to 5 on reload.
  const [showAllAgentApp, setShowAllAgentApp] = useState(false)
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
    { kind: 'agentapp' | 'chats'; top: number; left: number } | null
  >(null)

  const FLYOUT_MAX_HEIGHT = 420

  const openFlyout = (
    kind: 'agentapp' | 'chats',
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
    persistGroupExpanded('agentapp', agentAppExpanded)
  }, [agentAppExpanded])
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

  // The Agent App project currently open (from the route).
  const activeAgentAppId = location.pathname.startsWith('/agent-app/')
    ? location.pathname.slice('/agent-app/'.length)
    : null

  // When the open project sorts past the collapsed fold (e.g. a freshly
  // created app the user was just auto-switched to), expand "Show more" so it
  // is visible in its natural position. Only fires on navigation / list change,
  // so a manual "Show less" afterwards is respected.
  useEffect(() => {
    if (!activeAgentAppId) return
    const idx = agentAppProjects.findIndex(p => p.id === activeAgentAppId)
    if (idx >= GROUP_PREVIEW_COUNT) setShowAllAgentApp(true)
  }, [activeAgentAppId, agentAppProjects])

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

  // Per-session status dot precedence: an in-flight run (orange, pulsing)
  // outranks an unread message (green, steady). Agent App rows pass their
  // backing chat session id; a row with neither state shows no dot.
  type SessionDotKind = 'busy' | 'unread' | null
  const sessionDotKind = (sessionId: string | null | undefined): SessionDotKind => {
    if (!sessionId) return null
    if (runStateBySession[sessionId]) return 'busy'
    if (hasUnread(sessionId)) return 'unread'
    return null
  }
  const renderSessionDot = (sessionId: string | null | undefined): React.ReactNode => {
    const kind = sessionDotKind(sessionId)
    if (kind === 'busy') return <span className={styles.busyDot} aria-label={t('nav:dots.agentWorking')} />
    if (kind === 'unread') return <span className={styles.unreadDot} aria-label={t('nav:dots.newMessages')} />
    return null
  }

  // Collapsed group buttons show one aggregate corner dot: busy wins over
  // unread across all the group's sessions.
  const aggregateDotKind = (ids: (string | null | undefined)[]): SessionDotKind => {
    let unread = false
    for (const id of ids) {
      const kind = sessionDotKind(id)
      if (kind === 'busy') return 'busy'
      if (kind === 'unread') unread = true
    }
    return unread ? 'unread' : null
  }
  const renderCollapsedDot = (ids: (string | null | undefined)[]): React.ReactNode => {
    const kind = aggregateDotKind(ids)
    if (kind === 'busy') return <span className={styles.collapsedBusyDot} aria-label={t('nav:dots.agentWorking')} />
    if (kind === 'unread') return <span className={styles.collapsedUnreadDot} aria-label={t('nav:dots.newMessages')} />
    return null
  }

  // Auto-switch: the wizard/marketplace hand back the new projectId — open
  // its tab so the user lands on the live build view immediately.
  const handleProjectCreated = (projectId: string) => {
    setAgentAppExpanded(true)
    navigate(`/agent-app/${projectId}`)
  }

  // Lazy session creation: "New Chat" only opens the draft view at
  // /session/new. The real session is created by the backend on the first
  // message sent from that view (session_created then navigates us there).
  const startNewChat = () => {
    setChatsExpanded(true)
    navigate('/session/new')
  }

  // Let the guided tour open a fresh New Chat via the exact same action as the
  // button, so the chat is demonstrated on a clean draft, not the Main session.
  useTourEnvAction('openNewChat', startNewChat)

  // Let the tour expand the Chats group so the pinned Main row is on screen
  // before it highlights it.
  useTourEnvAction('ensureChatsExpanded', () => setChatsExpanded(true))

  // Let the tour open and close the "Add Agent App" modal while it walks the
  // creation methods.
  useTourEnvAction('openAgentAppModal', () => setShowCreateModal(true))
  useTourEnvAction('closeAgentAppModal', () => setShowCreateModal(false))

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
  }, [agentAppProjects.length, chatSessions.length, chatsExpanded, agentAppExpanded, chatVisibleCount])

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

  // Flip the "…" menu upward when opening downward would spill past the
  // visible bottom of the sidebar scroll area — otherwise the menu just
  // grows the scroll height and the user has to scroll to reach it.
  const positionSessionMenu = (el: HTMLDivElement | null) => {
    if (!el) return
    const container = scrollRef.current
    const limit = container
      ? Math.min(container.getBoundingClientRect().bottom, window.innerHeight)
      : window.innerHeight
    if (el.getBoundingClientRect().bottom > limit - 4) {
      el.classList.add(styles.sessionMenuUp)
    }
  }

  // "…" context menu attached to a session row. `isMain` limits the menu
  // to Clear conversation + Create skill for the pinned Main session.
  const renderSessionMenu = (session: SessionInfo, isMain: boolean) => {
    if (menu?.sessionId !== session.id) return null
    return (
      <div ref={positionSessionMenu} className={styles.sessionMenu} onMouseDown={e => e.stopPropagation()}>
        {!isMain && (
          <button className={styles.sessionMenuItem} onClick={() => startRename(session)}>
            <Pencil size={13} /> {t('common:actions.rename')}
          </button>
        )}
        <button className={styles.sessionMenuItem} onClick={() => handleClearSession(session.id)}>
          <Eraser size={13} /> {t('nav:sessionMenu.clearConversation')}
        </button>
        {!isMain && (
          <button
            className={`${styles.sessionMenuItem} ${styles.sessionMenuItemDanger}`}
            onClick={() => handleDeleteSession(session.id)}
          >
            <Trash2 size={13} /> {t('common:actions.delete')}
          </button>
        )}
        <button className={styles.sessionMenuItem} onClick={() => handleCreateSkill(session.id)}>
          <Sparkles size={13} /> {t('nav:sessionMenu.createSkill')}
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
        title={opts.isMain ? t('nav:items.main') : session.title}
        {...(opts.isMain ? tourAnchorProps('nav-main-session') : {})}
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
              title={opts.isMain ? t('nav:items.main') : session.title}
            >
              <span className={styles.icon}>
                {opts.isMain ? <MessageSquare size={16} /> : <MessageCircle size={14} />}
              </span>
              <span className={styles.label}>
                {opts.isMain ? t('nav:items.main') : <AnimatedSessionTitle title={session.title} />}
              </span>
              {opts.isMain && (
                <span className={styles.mainInfo} aria-label={t('nav:mainTooltip.aria')} title="">
                  <Info size={12} />
                  <span className={styles.mainInfoTooltip} role="tooltip">
                    <strong>{t('nav:mainTooltip.title')}</strong>
                    <span className={styles.mainInfoLine}>
                      {t('nav:mainTooltip.line1')}
                    </span>
                    <span className={styles.mainInfoLine}>
                      {t('nav:mainTooltip.line2')}
                    </span>
                    <span className={styles.mainInfoLine}>
                      {t('nav:mainTooltip.line3')}
                    </span>
                  </span>
                </span>
              )}
              {renderSessionDot(session.id)}
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
              aria-label={t('nav:sessionMenu.sessionOptions')}
              title={t('nav:sessionMenu.options')}
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
              <a
                href="https://craftbot.live"
                target="_blank"
                rel="noopener noreferrer"
                className={styles.logoLink}
                aria-label={t('nav:sidebar.websiteLabel')}
              >
                <img
                  src={logoSrc}
                  alt="CraftBot"
                  className={styles.logo}
                  draggable={false}
                />
              </a>
            )}
            <button
              type="button"
              className={styles.collapseButton}
              onClick={onToggleCollapsed}
              aria-label={collapsed ? t('nav:sidebar.expand') : t('nav:sidebar.collapse')}
              aria-pressed={collapsed}
              title={collapsed ? t('nav:sidebar.expand') : t('nav:sidebar.collapse')}
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
              title={t('nav:items.newChat')}
              {...tourAnchorProps('nav-new-chat')}
            >
              <span className={styles.icon}><SquarePen size={16} /></span>
              <span className={styles.label}>{t('nav:items.newChat')}</span>
            </button>

            {/* Utility items */}
            {utilityNavItems.map(item => (
              <button
                key={item.id}
                className={`${styles.navItem} ${isActive(item.path) ? styles.active : ''}`}
                onClick={() => navigate(item.path)}
                title={item.label}
                {...(item.tourAnchor ? tourAnchorProps(item.tourAnchor) : {})}
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
                  className={`${styles.navItem} ${flyout?.kind === 'agentapp' ? styles.active : ''}`}
                  onClick={e => openFlyout('agentapp', e)}
                  onMouseDown={e => e.stopPropagation()}
                  title={t('nav:groups.agentApp')}
                  aria-haspopup="menu"
                  aria-expanded={flyout?.kind === 'agentapp'}
                >
                  <span className={styles.icon}><Box size={16} /></span>
                  {renderCollapsedDot(agentAppProjects.map(p => p.sessionId))}
                </button>
                <button
                  className={`${styles.navItem} ${flyout?.kind === 'chats' ? styles.active : ''}`}
                  onClick={e => openFlyout('chats', e)}
                  onMouseDown={e => e.stopPropagation()}
                  title={t('nav:groups.chats')}
                  aria-haspopup="menu"
                  aria-expanded={flyout?.kind === 'chats'}
                >
                  <span className={styles.icon}><MessageCircle size={16} /></span>
                  {renderCollapsedDot(['main', ...chatSessions.map(s => s.id)])}
                </button>
              </>
            ) : (
              <>
            {/* Agent App group */}
            <div className={styles.groupRow} {...tourAnchorProps('nav-agent-app')}>
              <button
                className={styles.groupToggle}
                onClick={() => setAgentAppExpanded(v => !v)}
                aria-expanded={agentAppExpanded}
              >
                <ChevronRight
                  size={14}
                  className={`${styles.groupChevron} ${agentAppExpanded ? styles.groupChevronOpen : ''}`}
                />
                <span className={styles.icon}><Box size={16} /></span>
                <span className={styles.label}>{t('nav:groups.agentApp')}</span>
              </button>
              <button
                className={styles.groupAddButton}
                onClick={() => setShowCreateModal(true)}
                aria-label={t('nav:sidebar.addAgentApp')}
                title={t('nav:sidebar.addAgentApp')}
              >
                <Plus size={14} />
              </button>
            </div>
            {agentAppExpanded && (
              <div className={styles.groupChildren}>
                {(showAllAgentApp
                  ? agentAppProjects
                  : agentAppProjects.slice(0, GROUP_PREVIEW_COUNT)
                ).map(project => {
                  const path = `/agent-app/${project.id}`
                  const active = isActive(path)
                  return (
                    <button
                      key={project.id}
                      className={`${styles.agentAppTab} ${active ? styles.agentAppTabActive : ''}`}
                      onClick={() => navigate(path)}
                      title={project.name}
                    >
                      <span className={styles.agentAppTabIcon}>
                        {project.status === 'creating' || project.status === 'launching' || project.status === 'stopping'
                          ? <Loader2 size={13} className={styles.spinner} />
                          : <AgentAppIcon icon={project.icon} projectId={project.id} size={13} />}
                      </span>
                      <span className={styles.agentAppTabLabel}>{project.name}</span>
                      {renderSessionDot(project.sessionId)}
                    </button>
                  )
                })}
                {agentAppProjects.length > GROUP_PREVIEW_COUNT && (
                  <button
                    className={styles.showMoreRow}
                    onClick={() => setShowAllAgentApp(v => !v)}
                  >
                    {showAllAgentApp
                      ? t('common:actions.showLess')
                      : t('nav:sidebar.showMoreCount', { count: agentAppProjects.length - GROUP_PREVIEW_COUNT })}
                  </button>
                )}
                {agentAppProjects.length === 0 && (
                  <div className={styles.groupEmpty}>{t('nav:sidebar.noAgentAppApps')}</div>
                )}
              </div>
            )}

            <div className={styles.innerDivider} aria-hidden="true" />

            {/* Chats group — Main always pinned first inside it */}
            <div className={styles.groupRow} {...tourAnchorProps('nav-chats')}>
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
                <span className={styles.label}>{t('nav:groups.chats')}</span>
              </button>
              <button
                className={styles.groupAddButton}
                onClick={startNewChat}
                aria-label={t('nav:sidebar.newChat')}
                title={t('nav:sidebar.newChat')}
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
            {flyout.kind === 'agentapp' ? t('nav:groups.agentApp') : t('nav:groups.chats')}
          </div>
          <div className={styles.flyoutList}>
            {flyout.kind === 'agentapp' ? (
              <>
                {agentAppProjects.map(project => {
                  const path = `/agent-app/${project.id}`
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
                          : <AgentAppIcon icon={project.icon} projectId={project.id} size={13} />}
                      </span>
                      <span className={styles.flyoutItemLabel}>{project.name}</span>
                      {renderSessionDot(project.sessionId)}
                    </button>
                  )
                })}
                {agentAppProjects.length === 0 && (
                  <div className={styles.flyoutEmpty}>{t('nav:sidebar.noAgentAppApps')}</div>
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
                    title={isMain ? t('nav:items.main') : session.title}
                  >
                    <span className={styles.flyoutItemIcon}>
                      {isMain ? <MessageSquare size={13} /> : <MessageCircle size={13} />}
                    </span>
                    <span className={styles.flyoutItemLabel}>
                      {isMain ? t('nav:items.main') : <AnimatedSessionTitle title={session.title} />}
                    </span>
                    {renderSessionDot(session.id)}
                  </button>
                )
              })
            )}
          </div>
        </div>,
        document.body,
      )}

      <CreateAgentAppModal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        onInstalled={handleProjectCreated}
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
