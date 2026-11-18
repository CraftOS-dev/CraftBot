import { createContext, useContext } from 'react'

/** Presentation action only: never changes reference membership or agent permissions. */
export const PanelAppContext = createContext<{
  open(projectId: string): void
  canOpen(projectId: string): boolean
} | null>(null)
export const usePanelAppActions = () => useContext(PanelAppContext)
