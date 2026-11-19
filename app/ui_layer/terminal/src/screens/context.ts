/**
 * Key routing for full-screen screens. The screen root owns the only input
 * handler; the open screen registers its own handler here and returns true
 * for keys it used. Unused keys fall through to the root's defaults
 * (Esc back, q close, Ctrl+P palette, ? help).
 */
import { createContext, useContext, useEffect, useRef } from 'react'
import type { Key } from 'ink'

export type ScreenKeyHandler = (input: string, key: Key) => boolean

export interface ScreenContextValue {
  setHandler: (handler: ScreenKeyHandler | null) => void
  /** Width and height available to the screen body. */
  columns: number
  rows: number
  /** A text field has focus: single letters belong to it, not to shortcuts. */
  setTextFocus: (focused: boolean) => void
}

export const ScreenContext = createContext<ScreenContextValue>({
  setHandler: () => {},
  columns: 80,
  rows: 24,
  setTextFocus: () => {},
})

export function useScreen(): ScreenContextValue {
  return useContext(ScreenContext)
}

/** Register the screen's key handler (latest closure always used). */
export function useScreenKeys(handler: ScreenKeyHandler): void {
  const { setHandler } = useContext(ScreenContext)
  const ref = useRef(handler)
  ref.current = handler
  useEffect(() => {
    setHandler((input, key) => ref.current(input, key))
    return () => setHandler(null)
  }, [setHandler])
}
