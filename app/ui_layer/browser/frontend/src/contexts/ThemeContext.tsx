import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import { broadcastThemeToIframes } from '../pages/AgentApp/iframePool'

type Theme = 'dark' | 'light'

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
  theme: Theme
  toggleTheme: () => void
  setTheme: (theme: Theme) => void
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined)

const STORAGE_KEY = 'craftbot-theme'

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') {
      return stored
    }
    return 'dark'
  })

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem(STORAGE_KEY, theme)
    // Give browser one frame to resolve CSS variables, then broadcast to iframes
    requestAnimationFrame(() => {
      broadcastThemeToIframes(theme, collectCSSVars())
    })
  }, [theme])

  // Listen for localStorage changes from Settings page
  useEffect(() => {
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY && e.newValue) {
        // Resolve 'system' to actual theme
        if (e.newValue === 'system') {
          const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
          setThemeState(prefersDark ? 'dark' : 'light')
        } else if (e.newValue === 'dark' || e.newValue === 'light') {
          setThemeState(e.newValue)
        }
      }
    }

    window.addEventListener('storage', handleStorageChange)
    return () => window.removeEventListener('storage', handleStorageChange)
  }, [])

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

  const setTheme = useCallback((newTheme: Theme) => {
    setThemeState(newTheme)
  }, [])

  const toggleTheme = useCallback(() => {
    setThemeState(prev => prev === 'dark' ? 'light' : 'dark')
  }, [])

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, setTheme }}>
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
