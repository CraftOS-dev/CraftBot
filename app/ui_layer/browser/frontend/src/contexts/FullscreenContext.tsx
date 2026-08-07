import { createContext, useContext, useState, useCallback, ReactNode } from 'react'

interface FullscreenContextType {
  isFullscreen: boolean
  setFullscreen: (value: boolean) => void
  toggleFullscreen: () => void
}

const FullscreenContext = createContext<FullscreenContextType | undefined>(undefined)

export function FullscreenProvider({ children }: { children: ReactNode }) {
  const [isFullscreen, setIsFullscreen] = useState(false)

  const setFullscreen = useCallback((value: boolean) => {
    setIsFullscreen(value)
  }, [])

  const toggleFullscreen = useCallback(() => {
    setIsFullscreen(prev => !prev)
  }, [])

  return (
    <FullscreenContext.Provider value={{ isFullscreen, setFullscreen, toggleFullscreen }}>
      {children}
    </FullscreenContext.Provider>
  )
}

export function useFullscreen() {
  const context = useContext(FullscreenContext)
  if (!context) {
    throw new Error('useFullscreen must be used within a FullscreenProvider')
  }
  return context
}
