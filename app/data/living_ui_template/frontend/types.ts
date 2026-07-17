/**
 * Living UI Model Types
 * Define your data structures here
 */

// Base state interface - extend this for your app state.
// Keep the index signature: state flows into helpers typed against
// Record<string, unknown>.
export interface AppState {
  initialized: boolean
  loading: boolean
  error: string | null
  [key: string]: unknown
}

// Example data item - customize for your needs
export interface DataItem {
  id: string
  title: string
  description?: string
  createdAt: number
  updatedAt: number
}
