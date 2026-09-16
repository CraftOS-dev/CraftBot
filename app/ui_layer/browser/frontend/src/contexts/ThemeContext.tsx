import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import { broadcastThemeToIframes } from '../pages/AgentApp/iframePool'
import { usePersistedState } from '../hooks/usePersistedState'
import { UI_STATE, type ThemePreference } from '../store/uiState'

type Theme = 'dark' | 'light'

const DARK_SCHEME_QUERY = '(prefers-color-scheme: dark)'

// Collect resolved CSS variable values from the main document
function collectCSSVars(): Record<string, string> {
  const style = getComputedStyle(document.documentElement)
  const names = [
    '--bg-primary', '--bg-secondary', '--bg-tertiary', '--bg-elevated', '--bg-hover',
    '--text-primary', '--text-secondary', '--text-tertiary', '--text-muted',
    '--border-primary', '--border-secondary', '--border-hover',
    '--color-primary', '--color-primary-hover', '--color-primary-light', '--color-primary-subtle',
    '--color-success', '--color-warning', '--color-error', '--color-info',
    '--shadow-sm', '--shadow-md', '--shadow-lg',
    '--font-sans', '--font-mono',
    '--radius-sm', '--radius-md', '--radius-lg', '--radius-xl',
  ]
  const vars: Record<string, string> = {}
  names.forEach(n => {
    const v = style.getPropertyValue(n).trim()
    if (v) vars[n] = v
  })
  return vars
}

interface ThemeContextType {
  /** The theme actually applied: 'system' resolved against the OS setting. */
  theme: Theme
  /** What the user chose (persisted), possibly 'system'. */
  preference: ThemePreference
  toggleTheme: () => void
  setTheme: (preference: ThemePreference) => void
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined)

/** The OS color scheme, kept current while the page is open. */
function useSystemTheme(): Theme {
  const [systemTheme, setSystemTheme] = useState<Theme>(
    () => (window.matchMedia(DARK_SCHEME_QUERY).matches ? 'dark' : 'light'),
  )

  useEffect(() => {
    const query = window.matchMedia(DARK_SCHEME_QUERY)
    const handleChange = () => setSystemTheme(query.matches ? 'dark' : 'light')
    query.addEventListener('change', handleChange)
    return () => query.removeEventListener('change', handleChange)
  }, [])

  return systemTheme
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Persisted UI state: survives reloads and syncs across open tabs.
  const [preference, setPreference] = usePersistedState(UI_STATE.theme)
  const systemTheme = useSystemTheme()
  const theme: Theme = preference === 'system' ? systemTheme : preference

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    // Give browser one frame to resolve CSS variables, then broadcast to iframes
    requestAnimationFrame(() => {
      broadcastThemeToIframes(theme, collectCSSVars())
    })
  }, [theme])

  // Respond to theme-request messages from iframe children on load
  useEffect(() => {
    const handleMessage = (e: MessageEvent) => {
      if (e.data?.type === 'craftbot-theme-request' && e.source) {
        try {
          ;(e.source as WindowProxy).postMessage(
            { type: 'craftbot-theme', theme, cssVars: collectCSSVars() },
            '*'
          )
        } catch (_) {}
      }
    }
    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [theme])

  // Toggling picks the opposite of what is on screen, leaving 'system' behind.
  const toggleTheme = useCallback(() => {
    setPreference(theme === 'dark' ? 'light' : 'dark')
  }, [theme, setPreference])

  return (
    <ThemeContext.Provider value={{ theme, preference, toggleTheme, setTheme: setPreference }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider')
  }
  return context
}
