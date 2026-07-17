/**
 * ApiService — client for CUSTOM backend endpoints (SYSTEM-MANAGED).
 *
 * Entity CRUD does NOT go through here — use the typed helpers from
 * `api.gen.ts`. This client exists only for the custom routes an app
 * declares in `pb_hooks/main.pb.js` (paths under /api/custom/...).
 */

import { notifyEntitiesChanged } from './data'

class ApiServiceClass {
  // Same-origin: the Vite dev/preview server proxies /api to PocketBase.
  private baseUrl = ''

  /**
   * Call a CUSTOM endpoint (path WITHOUT the /api prefix):
   *
   *   const stats = await ApiService.request('GET', '/custom/stats?groupBy=status')
   *   await ApiService.request('POST', '/custom/archive-done', { columnId: 'abc123' })
   *
   * Mutating calls automatically refresh every mounted useEntities list, so
   * custom-endpoint changes appear in the UI without manual wiring.
   */
  async request<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}/api${path}`, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
    if (!response.ok) {
      let detail = `${response.status}`
      try {
        const data = await response.json()
        detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? data)
      } catch {
        /* non-JSON error body */
      }
      throw new Error(`${method} /api${path} failed: ${detail}`)
    }
    let result: T = undefined as T
    try {
      result = (await response.json()) as T
    } catch {
      /* empty body (204 etc.) */
    }
    if (method.toUpperCase() !== 'GET') {
      // A custom endpoint may touch any entity — refresh all mounted lists.
      notifyEntitiesChanged('*')
    }
    return result
  }
}

// Export singleton instance
export const ApiService = new ApiServiceClass()
