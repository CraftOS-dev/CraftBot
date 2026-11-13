import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import { usePersistedState } from '../hooks/usePersistedState'
import { UI_STATE, type ThemePreference } from '../store/uiState'
import { useAppSelector } from '../store/hooks'
import { syncFrameworkThemes } from '../features/agentApps/frameHost'

type Theme = 'dark' | 'light'

const DARK_SCHEME_QUERY = '(prefers-color-scheme: dark)'

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
  const apps = useAppSelector(state => state.agentApp.framework.apps)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  useEffect(() => { syncFrameworkThemes(theme, apps) }, [theme, apps])

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
