import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Box, Globe, Loader2, MoreHorizontal, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router-dom'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { SidebarPopover } from '../../components/layout/SidebarPopover'
import { useAppSelector } from '../../store/hooks'
import { frameworkAppKey } from '../../store/slices/agentAppSlice'
import type { FrameworkRegistryApp, FrameworkConnectedApp, SessionInfo } from '../../types'
import type { useSortableList } from '../../hooks'
import { FrameworkAppControls, FrameworkAppFeedback } from './FrameworkAppControls'
import { FrameworkAppDelete } from './FrameworkAppDialogs'
import { frameworkSessionIdentity } from './frameworkIdentity'
import navStyles from '../../components/layout/NavBar.module.css'
import styles from './FrameworkAppList.module.css'

export type SidebarAppEntry =
  | { kind: 'framework'; id: string; app: FrameworkRegistryApp }
  | { kind: 'connected'; id: string; app: FrameworkConnectedApp }
  | { kind: 'pending'; id: string; session: SessionInfo }

/** Registry apps and pending builds share the existing sidebar layout. */
export function FrameworkAppList({ entries, renderPending, renderSessionDot, sortable, onOpen, onMenuOpen, otherMenuOpen, flyout = false }: {
  entries: SidebarAppEntry[]
  renderPending?: (session: SessionInfo) => ReactNode
  renderSessionDot?: (app: FrameworkRegistryApp) => ReactNode
  sortable?: ReturnType<typeof useSortableList>
  onOpen?: () => void
  onMenuOpen?: () => void
  otherMenuOpen?: boolean
  flyout?: boolean
}) {
  const { t } = useTranslation(['agentapp', 'nav', 'common'])
  const navigate = useNavigate()
  const location = useLocation()
  const { requestAgentAppList } = useWebSocket()
  const selected = new URLSearchParams(location.search)
  const viewedSession = useAppSelector(state => state.sessions.sessions.find(session => location.pathname === `/session/${session.id}`))
  const viewedApp = frameworkSessionIdentity(viewedSession?.agentAppFrameworkKey)
  const snapshot = useAppSelector(state => state.agentApp.framework)
  const jobs = useAppSelector(state => state.agentApp.frameworkLifecycle)
  const connected = useAppSelector(state => state.connection.connected)
  const [menu, setMenu] = useState<{ key: string; anchor: DOMRect } | null>(null)
  const [dialog, setDialog] = useState<{ kind: 'delete'; app: FrameworkRegistryApp } | null>(null)
  const menuButton = useRef<HTMLButtonElement | null>(null)
  const menuApp = snapshot.apps.find(app => frameworkAppKey(app.path, app.id) === menu?.key)
  useEffect(() => { if (otherMenuOpen) setMenu(null) }, [otherMenuOpen])

  // Registry notices and lifecycle feedback can move the row without scrolling.
  // Keep an open menu attached to its button when that happens.
  useLayoutEffect(() => {
    if (!menu || !menuButton.current) return
    const anchor = menuButton.current.getBoundingClientRect()
    if (anchor.top !== menu.anchor.top || anchor.left !== menu.anchor.left) {
      setMenu({ ...menu, anchor })
    }
  })

  useEffect(() => {
    if (!menu) return
    const close = () => setMenu(null)
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        close()
        menuButton.current?.focus()
      }
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', escape)
    window.addEventListener('blur', close)
    window.addEventListener('resize', close)
    window.addEventListener('scroll', close, true)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', escape)
      window.removeEventListener('blur', close)
      window.removeEventListener('resize', close)
      window.removeEventListener('scroll', close, true)
    }
  }, [menu])

  const hasApps = entries.length > 0
  if (!hasApps && snapshot.status === 'success' && !snapshot.warning && !dialog) return null
  const stale = !connected || snapshot.status !== 'success'
  const statusLabel = (status: FrameworkRegistryApp['status'] | FrameworkConnectedApp['status']) => {
    const label = t(`registry.status.${status}`)
    return stale ? t('registry.lastKnown', { status: label }) : label
  }

  return <section className={styles.registry} aria-label={t('registry.title')}>
    {!connected && <p className={styles.notice}>{t('registry.disconnected')}</p>}
    {connected && !snapshot.hasSnapshot && (snapshot.status === 'loading' || snapshot.status === 'idle') &&
      <p className={styles.notice} role="status"><Loader2 size={12} className={styles.spinner} />{t('registry.loading')}</p>}
    {snapshot.status === 'error' && <p className={styles.notice} role="alert" title={snapshot.error || undefined}>
      {t('registry.failed')}
    </p>}
    {snapshot.warning && <details className={styles.notice}>
      <summary>{t('registry.warning')}</summary><p>{snapshot.warning}</p>
    </details>}
    <ul className={`${styles.list} ${flyout ? styles.flyoutList : ''}`}>
      {entries.map(entry => {
        if (entry.kind === 'pending') return <li key={entry.id} ref={sortable?.rowRef(entry.id)} style={sortable?.rowStyle(entry.id)}>{renderPending?.(entry.session)}</li>
        if (entry.kind === 'connected') {
          const app = entry.app
          return <li key={entry.id} ref={sortable?.rowRef(entry.id)} style={sortable?.rowStyle(entry.id)}
            className={`${navStyles.sessionRow} ${app.status !== 'online' ? navStyles.agentAppRowDimmed : ''} ${sortable?.draggingId === entry.id ? navStyles.rowDragging : ''}`}
            title={[app.name, t('registry.remote'), statusLabel(app.status), app.origin, app.principalName].filter(Boolean).join(' · ')}>
            <div {...sortable?.handleProps(entry.id)} className={`${flyout ? `${navStyles.flyoutItem} ${styles.flyoutButton} ${app.status !== 'online' ? navStyles.flyoutItemDimmed : ''}` : navStyles.agentAppTab} ${styles.remote}`}>
              <span className={flyout ? navStyles.flyoutItemIcon : navStyles.agentAppTabIcon}><Globe size={13} aria-hidden="true" /></span>
              <span className={flyout ? navStyles.flyoutItemLabel : navStyles.agentAppTabLabel}>{app.name}</span>
            </div>
          </li>
        }
        const app = entry.app
        const key = frameworkAppKey(app.path, app.id)
        const busy = jobs[key]?.status === 'running'
        const active = (location.pathname === '/framework-app' && selected.get('path') === app.path && selected.get('id') === app.id)
          || (viewedApp?.path === app.path && viewedApp?.appId === app.id)
        const dimmed = app.status !== 'running' && !busy
        return <li key={entry.id} ref={sortable?.rowRef(entry.id)} style={sortable?.rowStyle(entry.id)} className={sortable?.draggingId === entry.id ? navStyles.rowDragging : undefined}>
          <div className={`${navStyles.sessionRow} ${navStyles.agentAppRow} ${active ? navStyles.agentAppRowActive : ''} ${dimmed ? navStyles.agentAppRowDimmed : ''}`}>
            <button className={flyout
              ? `${navStyles.flyoutItem} ${styles.flyoutButton} ${active ? navStyles.flyoutItemActive : ''} ${dimmed ? navStyles.flyoutItemDimmed : ''}`
              : `${navStyles.agentAppTab} ${active ? navStyles.agentAppTabActive : ''}`}
              title={`${app.name} · ${statusLabel(app.status)}\n${app.path}`}
              aria-label={t('registry.open', { name: app.name })}
              aria-current={active ? 'page' : undefined}
              {...sortable?.handleProps(entry.id)}
              onClick={() => {
                setMenu(null)
                navigate(`/framework-app?${new URLSearchParams({ path: app.path, id: app.id })}`)
                onOpen?.()
              }}>
              <span className={flyout ? navStyles.flyoutItemIcon : navStyles.agentAppTabIcon}>
                {busy ? <Loader2 size={13} className={navStyles.spinner} /> : <Box size={13} aria-hidden="true" />}
              </span>
              <span className={flyout ? navStyles.flyoutItemLabel : navStyles.agentAppTabLabel}>{app.name}</span>
              {renderSessionDot?.(app)}
            </button>
            <button className={navStyles.sessionMenuButton}
              aria-label={`${t('nav:sessionMenu.options')}: ${app.name}`} title={t('nav:sessionMenu.options')}
              aria-haspopup="menu" aria-expanded={menu?.key === key}
              onMouseDown={event => event.stopPropagation()}
              onClick={event => {
                onMenuOpen?.()
                menuButton.current = event.currentTarget
                setMenu(menu?.key === key ? null : { key, anchor: event.currentTarget.getBoundingClientRect() })
              }}>
              <MoreHorizontal size={14} />
            </button>
          </div>
          <div className={styles.rowFeedback}><FrameworkAppFeedback app={app} /></div>
        </li>
      })}
    </ul>
    {menu && menuApp && <SidebarPopover anchor={menu.anchor} className={navStyles.sessionMenu} role="menu">
      <FrameworkAppControls app={menuApp} menu />
      <button className={`${navStyles.sessionMenuItem} ${navStyles.sessionMenuItemDanger}`}
        disabled={stale || jobs[frameworkAppKey(menuApp.path, menuApp.id)]?.status === 'running'}
        onClick={() => { setDialog({ kind: 'delete', app: menuApp }); setMenu(null) }}>
        <Trash2 size={13} />{t('common:actions.delete')}
      </button>
    </SidebarPopover>}
    {dialog?.kind === 'delete' && <FrameworkAppDelete app={dialog.app} onClose={() => setDialog(null)} onDeleted={() => {
      setDialog(null)
      requestAgentAppList()
      if (location.pathname === '/framework-app' && selected.get('path') === dialog.app.path && selected.get('id') === dialog.app.id) navigate('/')
    }} />}
  </section>
}
