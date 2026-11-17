declare global {
  interface Window {
    /**
     * Written into index.html by whichever server delivers it (run.py's static
     * server, or the backend itself) with the backend port this run actually
     * uses. Absent under the Vite dev server.
     */
    __CRAFTBOT__?: { backendPort?: number | string }
  }
}

/**
 * The backend port to connect to.
 *
 * A production bundle is compiled once with VITE_BACKEND_PORT baked in, but
 * the backend can run on another port (--backend-port, or a busy 7926), so
 * the port the serving process injects at runtime wins. The build-time value
 * remains for the Vite dev server, which run.py starts with the right port.
 */
function backendPort(): string | undefined {
  const injected = window.__CRAFTBOT__?.backendPort
  if (injected) return String(injected)
  return import.meta.env.VITE_BACKEND_PORT
}

/**
 * Resolve the WebSocket URL for connecting to the backend.
 *
 * In development (Vite dev server), the proxy forwards /ws to the backend,
 * so we use window.location.host.
 *
 * In production (run.py's static server), the frontend is served on a
 * different port than the backend, so it connects to the backend port
 * directly.
 */
export function getWsUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const port = backendPort()
  if (port && port !== window.location.port) {
    // Connect directly to backend port
    return `${protocol}//${window.location.hostname}:${port}/ws`
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
  const port = backendPort()
  if (port && port !== window.location.port) {
    return `${window.location.protocol}//${window.location.hostname}:${port}`
  }
  return ''
}
