import { ReactNode, useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { Menu, X } from 'lucide-react'
import { NavBar } from './NavBar'
import { useFullscreen } from '../../contexts/FullscreenContext'
import styles from './Layout.module.css'

interface LayoutProps {
  children: ReactNode
}

const COLLAPSED_KEY = 'craftbot.sidebar.collapsed'

function readCollapsedFromStorage(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === '1'
  } catch {
    return false
  }
}

export function Layout({ children }: LayoutProps) {
  const { isFullscreen } = useFullscreen()
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [collapsed, setCollapsed] = useState<boolean>(readCollapsedFromStorage)

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
    setCollapsed(prev => {
      const next = !prev
      try {
        window.localStorage.setItem(COLLAPSED_KEY, next ? '1' : '0')
      } catch {
        /* storage unavailable — fall through */
      }
      return next
    })
  }

  return (
    <div className={styles.layout}>
      {!isFullscreen && (
        <>
          <button
            type="button"
            className={styles.menuButton}
            onClick={() => setMobileOpen(v => !v)}
            aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={mobileOpen}
          >
            {mobileOpen ? <X size={18} /> : <Menu size={18} />}
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
        </>
      )}
      <main className={`${styles.content} ${!isFullscreen ? styles.contentWithSidebar : ''}`}>
        {children}
      </main>
    </div>
  )
}
