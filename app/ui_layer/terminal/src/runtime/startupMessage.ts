/**
 * A prompt given on the command line (`--message`), as a launcher such as
 * Omarchy's agent key passes one: it opens a new chat as if it had been typed
 * there, once the agent can take it. That is after the backend's first `init`
 * and, when the agent still needs onboarding, after onboarding, so a prompt
 * never reaches an agent that has no model yet.
 */
import type { RootState } from '../state/store'

/** Whether the agent can take the startup message now. */
export function startupMessageReady(state: RootState, initSeen: boolean): boolean {
  return initSeen
    && state.connection.connected
    && state.tui.hello !== null
    && !state.onboarding.needsHardOnboarding
    && !state.tui.screens.some(screen => screen.id === 'onboarding')
}
