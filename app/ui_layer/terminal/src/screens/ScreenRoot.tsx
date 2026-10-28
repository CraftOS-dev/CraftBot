/**
 * The full-screen root, rendered on the terminal's alternate screen while
 * any screen is open. Screens form a stack (Esc goes back one level, q
 * closes them all and returns to the chat). The frame is one row shorter
 * than the terminal so the renderer diffs lines instead of repainting the
 * whole screen.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ComponentType } from 'react'
import { Box, useInput, useWindowSize, type Key } from 'ink'
import { useAppDispatch, useAppSelector } from '../state/hooks'
import { closeAllScreens, closeScreen, expireToasts, openScreen, type ScreenId } from '../state/tuiSlice'
import { FRAME_SIDES } from '../ui/Frame'
import { ToastLine } from '../ui/ToastLine'
import { ScreenContext, type ScreenKeyHandler } from './context'
import { HelpScreen } from './HelpScreen'
import { SessionsScreen } from './SessionsScreen'
import { PaletteScreen } from './PaletteScreen'
import { TranscriptScreen } from './TranscriptScreen'
import { SettingsScreen } from './settings/SettingsScreen'
import { MemoryScreen } from './MemoryScreen'
import { WorkspaceScreen } from './WorkspaceScreen'
import { DashboardScreen } from './DashboardScreen'
import { BrowserScreen } from './BrowserScreen'
import { AppsScreen } from './apps/AppsScreen'
import { AppScreen } from './apps/AppScreen'
import { AppCreateScreen } from './apps/AppCreateScreen'
import { OnboardingScreen } from './OnboardingScreen'

export interface ScreenProps {
  arg?: string
}

const SCREENS: Record<ScreenId, ComponentType<ScreenProps>> = {
  sessions: SessionsScreen,
  palette: PaletteScreen,
  help: HelpScreen,
  transcript: TranscriptScreen,
  settings: SettingsScreen,
  memory: MemoryScreen,
  workspace: WorkspaceScreen,
  dashboard: DashboardScreen,
  browser: BrowserScreen,
  apps: AppsScreen,
  app: AppScreen,
  appCreate: AppCreateScreen,
  onboarding: OnboardingScreen,
}

export function ScreenRoot() {
  const dispatch = useAppDispatch()
  const { columns, rows } = useWindowSize()
  const stack = useAppSelector(s => s.tui.screens)
  const top = stack[stack.length - 1]
  const handlerRef = useRef<ScreenKeyHandler | null>(null)
  const [textFocus, setTextFocus] = useState(false)

  const setHandler = useCallback((handler: ScreenKeyHandler | null) => {
    handlerRef.current = handler
  }, [])

  // Toasts take the bottom lines; the screen gives them its rows, so the
  // whole frame stays one row short of the terminal.
  const toasts = useAppSelector(s => s.tui.toasts)
  useEffect(() => {
    if (toasts.length === 0) return
    const timer = setInterval(() => dispatch(expireToasts(Date.now())), 500)
    return () => clearInterval(timer)
  }, [toasts.length, dispatch])
  const height = Math.max(8, rows - 1 - toasts.length)
  // Screens lay out to the width inside their frame's border and padding.
  const inner = Math.max(20, columns - FRAME_SIDES)
  const context = useMemo(
    () => ({ setHandler, columns: inner, rows: height, setTextFocus }),
    [setHandler, inner, height],
  )

  useInput((input: string, key: Key) => {
    // Keys typed fast can arrive in one chunk ("jj"). Shortcuts are single
    // keys, so outside text fields hand them over one character at a time;
    // a focused text field takes the chunk whole and inserts it.
    const plain = !textFocus && !key.ctrl && !key.meta && !key.return && !key.escape && !key.tab
    const chars = plain ? Array.from(new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(input), s => s.segment) : []
    if (chars.length > 1) {
      for (const ch of chars) handleKey(ch, key)
      return
    }
    handleKey(input, key)
  })

  function handleKey(input: string, key: Key): void {
    if (key.ctrl && input === 'c') {
      dispatch(closeAllScreens())
      return
    }
    if (handlerRef.current?.(input, key)) return
    if (key.escape) {
      dispatch(closeScreen())
      return
    }
    if (textFocus) return
    if (input === 'q') {
      dispatch(closeAllScreens())
      return
    }
    if (key.ctrl && input === 'p' && top?.id !== 'palette') {
      dispatch(openScreen({ id: 'palette' }))
      return
    }
    if (input === '?' && top?.id !== 'help') {
      dispatch(openScreen({ id: 'help' }))
    }
  }

  if (!top) return null
  const Screen = SCREENS[top.id]
  return (
    <ScreenContext.Provider value={context}>
      <Box width={columns} height={height} flexDirection="column">
        <Screen key={`${top.id}:${top.arg ?? ''}:${stack.length}`} arg={top.arg} />
      </Box>
      {toasts.map(toast => (
        <ToastLine key={toast.id} toast={toast} columns={columns} />
      ))}
    </ScreenContext.Provider>
  )
}
