/**
 * PocketBase client singleton (SYSTEM-MANAGED — do not edit).
 *
 * Same-origin: dev goes through the Vite proxy (/api → PB port), prod is
 * served by PocketBase itself. Import from here everywhere:
 *
 *   import { pb } from '@/lib/pb'
 *   const cards = await pb.collection('cards').getFullList({ sort: '-created' })
 */
import PocketBase from 'pocketbase'

export const pb = new PocketBase('/')

// Local single-user apps: no auth persistence surprises across reloads.
pb.autoCancellation(false)
