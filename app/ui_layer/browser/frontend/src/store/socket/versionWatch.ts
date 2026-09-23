import { register } from './messageRegistry'
import { resetUpdateCheck } from '../slices/generalSettingsSlice'

// Every connect sends `init` with the backend version. When it differs from
// the version this page last saw, CraftBot was updated or restarted on a new
// build, so a cached "update available" result is out of date
// (docs/plans/ui-data-freshness-plan.md, WS-4.11). Kept in its own module so
// messageRegistry doesn't import a slice that imports it.

let seenVersion: string | null = null

register('init', (data, dispatch) => {
  const version = (data as { version?: string } | undefined)?.version
  if (typeof version !== 'string') return
  if (seenVersion !== null && seenVersion !== version) dispatch(resetUpdateCheck())
  seenVersion = version
})
