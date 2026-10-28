/**
 * What a settings tab gets from the settings screen: whether it has focus,
 * its size, a place to register its key handler (return true for keys it
 * used) and a place to publish its own footer hints.
 */
import { createContext, useContext, useEffect, useRef } from 'react'
import type { Key } from 'ink'

export type TabKeyHandler = (input: string, key: Key) => boolean

export interface TabContextValue {
  active: boolean
  width: number
  height: number
  setHandler: (handler: TabKeyHandler | null) => void
  setHints: (hints: { keys: string; label: string }[]) => void
}

export const TabContext = createContext<TabContextValue>({
  active: false,
  width: 60,
  height: 20,
  setHandler: () => {},
  setHints: () => {},
})

export function useTab(): TabContextValue {
  return useContext(TabContext)
}

/** Register the tab's key handler (latest closure always used). */
export function useTabKeys(handler: TabKeyHandler): void {
  const { setHandler } = useContext(TabContext)
  const ref = useRef(handler)
  ref.current = handler
  useEffect(() => {
    setHandler((input, key) => ref.current(input, key))
    return () => setHandler(null)
  }, [setHandler])
}
