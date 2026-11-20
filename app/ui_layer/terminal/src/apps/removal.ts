/**
 * Deleting an Agent App, as the browser's delete dialog does: a local app is
 * removed with its files (stopped first), a missing one is forgotten, an app
 * whose files the framework cannot vouch for is offered "remove from the
 * list, keep the files", and a connected app is disconnected (the app and
 * its data stay on its host).
 */
import type { FrameworkRegistryApp } from '../../../browser/frontend/src/types'
import { frameworkRequest } from './framework'

interface RemovalResult {
  status: string
  stderr?: string
  data?: {
    ok?: boolean
    reason?: string
    removed?: { id: string; path: string }
    forgot?: { id: string; path: string }
  }
}

export type RemovalOutcome = 'removed' | 'forgotten' | 'disconnected' | 'needsKeepFiles'

/** What deleting this app will do, before asking. */
export function removalKind(app: FrameworkRegistryApp, keepFiles: boolean): 'disconnect' | 'forget' | 'remove' {
  if (app.connection) return 'disconnect'
  return app.status === 'missing' || keepFiles ? 'forget' : 'remove'
}

/** Throws with the host's own words when the app was not removed. */
export async function removeApp(app: FrameworkRegistryApp, keepFiles = false): Promise<RemovalOutcome> {
  const kind = removalKind(app, keepFiles)
  const missing = app.status === 'missing'
  const result = await frameworkRequest<RemovalResult>(
    {
      operation: kind === 'disconnect' ? 'disconnect' : 'manage',
      path: app.path,
      appId: app.id,
      verb: kind === 'remove' ? 'remove' : 'forget',
      confirm: app.id,
      stopFirst: !missing,
      ...(keepFiles ? { keepFiles: true } : {}),
    },
    1_250_000,
  )
  if (kind === 'remove' && result.data?.reason === 'no-canon') return 'needsKeepFiles'
  if (kind === 'disconnect') {
    if (result.status !== 'success') throw new Error(result.stderr?.trim() || 'The app could not be disconnected.')
    return 'disconnected'
  }
  const gone = kind === 'forget' ? result.data?.forgot : result.data?.removed
  if (result.status !== 'success' || result.data?.ok !== true || gone?.id !== app.id || gone.path !== app.path) {
    throw new Error(result.stderr?.trim() || 'The app could not be deleted.')
  }
  return kind === 'forget' ? 'forgotten' : 'removed'
}
