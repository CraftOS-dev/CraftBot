/**
 * GENERATED from config/schema.json — DO NOT EDIT. Typed collection helpers.
 *
 * The backend is PocketBase: full CRUD/filter/sort/realtime per collection
 * comes from the PB SDK. Use these typed helpers (or `pb` directly):
 *
 *   import { api, useCards } from '../api.gen'
 *   const cards = await api.cards.getFullList({ sort: '-created' })
 *   const store = useCards({ filter: 'position > 0' })   // {items, loading, error}
 *
 * ApiService is ONLY for custom pb_hooks endpoints (/api/custom/...).
 */

// No collections declared yet — define them in config/schema.json.
import { pb } from './lib/pb'

export { pb }
export const api = {} as const
