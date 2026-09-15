import { ReactNode, useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Menu, X } from 'lucide-react'
import { NavBar } from './NavBar'
import { useTourEnvAction } from '../../tour'
import { usePersistedState } from '../../hooks'
import { UI_STATE } from '../../store/uiState'
import styles from './Layout.module.css'

// Matches the mobile breakpoint in Layout.module.css, where the sidebar
// becomes an off-canvas drawer.
const MOBILE_QUERY = '(max-width: 768px)'

interface LayoutProps {
  children: ReactNode
}

export function Layout({ children }: LayoutProps) {
  const { t } = useTranslation(['nav', 'common'])
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [collapsedPreference, setCollapsedPreference] = usePersistedState(UI_STATE.sidebar.collapsed)
  // Set when the guided tour reveals the sidebar. It overrides the saved
  // preference on screen without overwriting it, until the user toggles.
  const [revealedByTour, setRevealedByTour] = useState(false)
  const collapsed = collapsedPreference && !revealedByTour

  // Close the mobile drawer on route change so navigating doesn't leave
  // the overlay covering the content.
  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  // Close on Esc for accessibility.
  useEffect(() => {
    if (!mobileOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMobileOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mobileOpen])

  const toggleCollapsed = () => {
    setRevealedByTour(false)
    setCollapsedPreference(!collapsed)
  }

  // Let the guided tour reveal the sidebar before highlighting a nav item.
  useTourEnvAction('ensureSidebarVisible', () => {
    setRevealedByTour(true)
    if (window.matchMedia(MOBILE_QUERY).matches) {
      setMobileOpen(true)
    }
  })

  return (
    <div className={styles.layout}>
      <button
        type="button"
        className={styles.menuButton}
        onClick={() => setMobileOpen(v => !v)}
        aria-label={mobileOpen ? t('nav:layout.closeMenu') : t('nav:layout.openMenu')}
        aria-expanded={mobileOpen}
      >
        {mobileOpen ? <X size={16} /> : <Menu size={16} />}
      </button>
      <div
        className={`${styles.backdrop} ${mobileOpen ? styles.backdropVisible : ''}`}
        onClick={() => setMobileOpen(false)}
        aria-hidden="true"
      />
      <aside
        className={`${styles.sidebar} ${mobileOpen ? styles.sidebarOpen : ''} ${collapsed ? styles.sidebarCollapsed : ''}`}
      >
        <NavBar collapsed={collapsed} onToggleCollapsed={toggleCollapsed} />
      </aside>
      <main className={`${styles.content} ${styles.contentWithSidebar}`}>
        {children}
      </main>
    </div>
  )
}
