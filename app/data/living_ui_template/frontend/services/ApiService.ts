/**
 * ApiService - Backend API client for Living UI
 *
 * Provides methods to communicate with the FastAPI backend.
 * All state is stored in the backend, making it persistent across
 * page reloads and tab switches.
 */

import { notifyEntitiesChanged } from './data'

// Backend URL — detected from manifest at runtime, falls back to creation-time port
const BACKEND_URL = (window as any).__CRAFTBOT_BACKEND_URL__ || 'http://localhost:{{BACKEND_PORT}}'

export interface ActionRequest {
  action: string
  payload?: Record<string, unknown>
}

export interface ActionResponse {
  status: string
  data?: Record<string, unknown>
  [key: string]: unknown
}

class ApiServiceClass {
  private baseUrl: string

  constructor() {
    this.baseUrl = BACKEND_URL
  }

  /**
   * Call a CUSTOM endpoint from routes.py (path WITHOUT the /api prefix):
   *
   *   const stats = await ApiService.request('GET', '/cards/_stats?groupBy=status')
   *   await ApiService.request('POST', '/cards/archive-done', { columnId: 3 })
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

  /**
   * Check if the backend is healthy/available
   */
  async healthCheck(): Promise<boolean> {
    try {
      const response = await fetch(`${this.baseUrl}/health`, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      })
      return response.ok
    } catch {
      return false
    }
  }

  // ============================================================================
  // State Management
  // ============================================================================

  /**
   * Get the current application state from backend
   *
   * Call this on component mount to restore persisted state.
   */
  async getState<T = Record<string, unknown>>(): Promise<T> {
    const response = await fetch(`${this.baseUrl}/api/state`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    })
    if (!response.ok) {
      throw new Error(`Failed to get state: ${response.statusText}`)
    }
    return response.json()
  }

  /**
   * Update the application state (merge with existing)
   *
   * @param updates - Partial state to merge with existing state
   * @returns The complete updated state
   */
  async updateState<T = Record<string, unknown>>(
    updates: Partial<T>
  ): Promise<T> {
    const response = await fetch(`${this.baseUrl}/api/state`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: updates }),
    })
    if (!response.ok) {
      throw new Error(`Failed to update state: ${response.statusText}`)
    }
    return response.json()
  }

  /**
   * Replace the entire application state
   *
   * Unlike updateState, this completely replaces rather than merges.
   * Use with caution.
   */
  async replaceState<T = Record<string, unknown>>(state: T): Promise<T> {
    const response = await fetch(`${this.baseUrl}/api/state/replace`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: state }),
    })
    if (!response.ok) {
      throw new Error(`Failed to replace state: ${response.statusText}`)
    }
    return response.json()
  }

  /**
   * Clear all application state
   */
  async clearState(): Promise<void> {
    const response = await fetch(`${this.baseUrl}/api/state`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
    })
    if (!response.ok) {
      throw new Error(`Failed to clear state: ${response.statusText}`)
    }
  }

  // ============================================================================
  // Actions
  // ============================================================================

  /**
   * Execute a named action on the backend
   *
   * @param action - The action name (e.g., "feed_pet", "reset")
   * @param payload - Optional data for the action
   * @returns Action result with updated state
   */
  async executeAction(
    action: string,
    payload?: Record<string, unknown>
  ): Promise<ActionResponse> {
    const response = await fetch(`${this.baseUrl}/api/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, payload }),
    })
    if (!response.ok) {
      throw new Error(`Failed to execute action: ${response.statusText}`)
    }
    const result = await response.json()
    // Actions mutate state — refresh every mounted entity list.
    notifyEntitiesChanged('*')
    return result
  }
}

// Export singleton instance
export const ApiService = new ApiServiceClass()
