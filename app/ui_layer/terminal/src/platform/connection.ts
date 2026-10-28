/**
 * Terminal replacement for the browser frontend's `utils/connection.ts`.
 *
 * The build swaps this module in wherever the shared store imports that file
 * (build.mjs). The browser derives the backend address from its page; the
 * terminal client is told the port on its command line.
 */
import { config } from '../config'

export function getWsUrl(): string {
  return `ws://localhost:${config().port}/ws`
}

/**
 * Subprotocols carrying the backend's per-process session token, fetched on
 * every connect (a restarted backend has a new token). The token endpoint
 * accepts callers without an Origin, like this one (ws_auth.py).
 */
export async function getWsProtocols(): Promise<string[]> {
  const resp = await fetch(`${getApiBaseUrl()}/api/session-token`, { cache: 'no-store' })
  if (!resp.ok) throw new Error(`session token request failed: ${resp.status}`)
  const { token } = (await resp.json()) as { token: string }
  return ['craftbot', `craftbot-auth.${token}`]
}

export function getApiBaseUrl(): string {
  return `http://localhost:${config().port}`
}
