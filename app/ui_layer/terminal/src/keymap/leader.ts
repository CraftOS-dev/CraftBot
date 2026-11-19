/**
 * Ctrl+X leader keys and the screens they open. One table drives the key
 * handling, the help screen and the palette, so a binding shows up
 * everywhere it exists.
 */
import type { ScreenId } from '../state/tuiSlice'

export interface LeaderBinding {
  key: string
  /** i18n key (tui namespace) of the label. */
  label: string
  screen?: ScreenId
  action?: 'newChat' | 'enhance' | 'effort'
}

export const LEADER_TIMEOUT_MS = 2000

export const LEADER_BINDINGS: LeaderBinding[] = [
  { key: 's', label: 'screens.sessions', screen: 'sessions' },
  { key: 'a', label: 'screens.apps', screen: 'apps' },
  { key: 'm', label: 'screens.memory', screen: 'memory' },
  { key: 'w', label: 'screens.workspace', screen: 'workspace' },
  { key: 'd', label: 'screens.dashboard', screen: 'dashboard' },
  { key: 'b', label: 'screens.browser', screen: 'browser' },
  { key: ',', label: 'screens.settings', screen: 'settings' },
  { key: 'n', label: 'actions.newChat', action: 'newChat' },
  { key: 'e', label: 'actions.enhance', action: 'enhance' },
  { key: 'r', label: 'actions.effort', action: 'effort' },
]

/** Slash commands the terminal handles itself (never sent to the backend). */
export const LOCAL_COMMANDS: { name: string; label: string; screen?: ScreenId; action?: string }[] = [
  { name: 'sessions', label: 'screens.sessions', screen: 'sessions' },
  { name: 'apps', label: 'screens.apps', screen: 'apps' },
  { name: 'memory', label: 'screens.memory', screen: 'memory' },
  { name: 'workspace', label: 'screens.workspace', screen: 'workspace' },
  { name: 'dashboard', label: 'screens.dashboard', screen: 'dashboard' },
  { name: 'browser', label: 'screens.browser', screen: 'browser' },
  { name: 'settings', label: 'screens.settings', screen: 'settings' },
  { name: 'transcript', label: 'screens.transcript', screen: 'transcript' },
  { name: 'keys', label: 'screens.help', screen: 'help' },
  { name: 'new', label: 'actions.newChat', action: 'newChat' },
  { name: 'effort', label: 'actions.effort', action: 'effort' },
  { name: 'exit', label: 'actions.quit', action: 'quit' },
  { name: 'quit', label: 'actions.quit', action: 'quit' },
]
