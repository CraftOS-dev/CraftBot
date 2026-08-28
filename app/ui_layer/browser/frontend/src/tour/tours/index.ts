import type { TourDefinition, TourId } from '../types'
import { coreTour } from './core'

// Registry of every tour the app can run. Add a new mini-tour by dropping a
// definition file beside core.ts and registering it here — no engine changes.
export const TOURS: Record<TourId, TourDefinition> = {
  core: coreTour,
}
