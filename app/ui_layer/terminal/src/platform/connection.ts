/**
 * Terminal replacement for the browser frontend's `utils/connection.ts`.
 *
 * The build swaps this module in wherever the shared store imports that file
 * (build.mjs). The browser derives the backend address from its page; the
 * terminal client is told the port on its command line.
 */
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { config } from '../config'

export function getWsUrl(): string {
  return `ws://localhost:${config().port}/ws`
}

/**
 * Subprotocols carrying the backend's per-process session token, read on
 * every connect (a restarted backend has a new token). The backend writes it
 * to an owner-only file in the state directory (ws_auth.py token_file);
 * /api/session-token answers browsers only. A backend from before that file
 * existed still answers the endpoint, so it stays as the fallback.
 */
export async function getWsProtocols(): Promise<string[]> {
  const token = (await readTokenFile()) ?? (await fetchToken())
  return ['craftbot', `craftbot-auth.${token}`]
}

async function readTokenFile(): Promise<string | null> {
  const path = join(config().stateDir, 'run', `session-${config().port}.token`)
  try {
    const token = (await readFile(path, 'utf8')).trim()
    return token || null
  } catch {
    return null
  }
}

async function fetchToken(): Promise<string> {
  const resp = await fetch(`${getApiBaseUrl()}/api/session-token`, { cache: 'no-store' })
  if (!resp.ok) throw new Error(`session token request failed: ${resp.status}`)
  const { token } = (await resp.json()) as { token: string }
  return token
}

export function getApiBaseUrl(): string {
  return `http://localhost:${config().port}`
}
