/**
 * App-level actions any root can trigger: quitting and starting a new chat.
 */
import { config } from '../config'
import { persistentStorage } from '../platform/globals'
import { send } from '../state/hooks'
import { store } from '../state/store'
import { closeAllScreens, setActiveSession } from '../state/tuiSlice'
import { setBusyProgress } from '../caps/terminal'

let quitting = false

export function isQuitting(): boolean {
  return quitting
}

/**
 * Leave the terminal client. An owner client (started by `run.py --tui`)
 * also stops CraftBot through the backend's own /exit command, so sessions
 * are saved and Agent Apps stopped; an attached client just detaches and the
 * service keeps running.
 */
export function requestQuit(exit: (value?: unknown) => void): void {
  if (quitting) return
  quitting = true
  persistentStorage.flush()
  setBusyProgress(false)
  if (config().owner) {
    send('command', { command: '/exit', sessionId: 'main' })
    // Give the socket a moment to deliver it.
    setTimeout(() => exit(), 150)
  } else {
    exit()
  }
}

/** Open a fresh chat; the backend creates it with the first message. */
export function startNewChat(): void {
  store.dispatch(closeAllScreens())
  store.dispatch(setActiveSession('new'))
}
