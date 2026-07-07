/**
 * Services Layer - API clients, persistence, and UI capture utilities
 *
 * Primary exports:
 * - ApiService: Backend API client for state management
 * - StatePersistence: localStorage persistence for UI state
 * - UICapture: HTTP-based UI observation for agents
 */

// Main API service for backend communication
export { ApiService } from './ApiService'
export type { ActionRequest, ActionResponse } from './ApiService'

// localStorage persistence utilities
export {
  StatePersistence,
  uiPreferences,
  draftStorage,
  stateCache,
} from './StatePersistence'
export type { PersistenceOptions } from './StatePersistence'

// UI capture for agent observation (HTTP-based, replaces WebSocket)
export { UICapture, uiCapture } from './UICapture'
export type { UISnapshot, ComponentRegistration } from './UICapture'

/**
 * Base API client for making HTTP requests
 *
 * Use this for custom API integrations beyond the built-in backend.
 */
export class ApiClient {
  private baseUrl: string

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl
  }

  async get<T>(endpoint: string): Promise<T> {
    const response = await fetch(`${this.baseUrl}${endpoint}`)
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }
    return response.json()
  }

  async post<T>(endpoint: string, data: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    })
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }
    return response.json()
  }

  async put<T>(endpoint: string, data: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    })
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }
    return response.json()
  }

  async delete<T>(endpoint: string): Promise<T> {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      method: 'DELETE',
    })
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }
    return response.json()
  }
}
