/**
 * Resolve the WebSocket URL for connecting to the backend.
 *
 * In development (Vite dev server), the proxy forwards /ws to the backend,
 * so we use window.location.host.
 *
 * In production (static server from PyInstaller binary), the frontend is
 * served on a different port than the backend. VITE_BACKEND_PORT is baked
 * in at build time so the frontend knows where to connect directly.
 */
export function getWsUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const backendPort = import.meta.env.VITE_BACKEND_PORT
  if (backendPort && backendPort !== window.location.port) {
    // Connect directly to backend port
    return `${protocol}//${window.location.hostname}:${backendPort}/ws`
  }
  // Dev mode: proxy handles it
  return `${protocol}//${window.location.host}/ws`
}

/**
 * WebSocket subprotocols carrying the backend's per-process session token.
 *
 * The token comes from a same-origin fetch (proxied to the backend in dev and
 * static-server modes); the backend never sends CORS headers for it, so other
 * sites can't read it. Fetched on every connect: a restarted backend has a
 * new token.
 */
export async function getWsProtocols(): Promise<string[]> {
  const resp = await fetch('/api/session-token', { cache: 'no-store' })
  if (!resp.ok) throw new Error(`session token request failed: ${resp.status}`)
  const { token } = (await resp.json()) as { token: string }
  return ['craftbot', `craftbot-auth.${token}`]
}

/**
 * Resolve the base URL for API requests to the backend.
 */
export function getApiBaseUrl(): string {
  const backendPort = import.meta.env.VITE_BACKEND_PORT
  if (backendPort && backendPort !== window.location.port) {
    return `${window.location.protocol}//${window.location.hostname}:${backendPort}`
  }
  return ''
}
