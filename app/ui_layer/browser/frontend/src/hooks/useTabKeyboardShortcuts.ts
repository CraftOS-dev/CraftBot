import { useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useDynamicTabs } from './useDynamicTabs'

/**
 * Keyboard shortcuts for dynamic tab navigation:
 * - Alt+1..9: Switch to dynamic tab by position
 * - Alt+W: Close current dynamic tab
 */
export function useTabKeyboardShortcuts() {
  const { tabs, closeTab } = useDynamicTabs()
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!e.altKey) return

      // Alt+1..9 to switch to dynamic tab by position
      const num = parseInt(e.key, 10)
      if (num >= 1 && num <= 9 && num <= tabs.length) {
        e.preventDefault()
        const tab = tabs[num - 1]
        navigate(tab.path)
        return
      }

      // Alt+W to close current dynamic tab
      if (e.key === 'w' || e.key === 'W') {
        const currentTab = tabs.find(t => location.pathname.startsWith(t.path))
        if (currentTab) {
          e.preventDefault()
          closeTab(currentTab.id)
          navigate('/')
        }
      }
    }

    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [tabs, closeTab, navigate, location.pathname])
}
