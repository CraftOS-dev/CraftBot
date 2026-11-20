/**
 * The Agent App registry as the terminal reads and changes it, over the same
 * messages as the browser: the `agent_app_framework_list` snapshot (the
 * agentApp slice), start and stop (`agent_app_framework_lifecycle`), and the
 * host's request channel (`frameworkRequest`) for everything else. Apps are
 * addressed by their (path, id) pair, as the host does.
 */
import { useEffect, useState } from 'react'
import { useAppDispatch, useAppSelector } from '../state/hooks'
import type { RootState } from '../state/store'
import type { FrameworkRegistryApp, SessionInfo } from '../../../browser/frontend/src/types'
import {
  frameworkAppKey,
  receiveFrameworkAttachment,
  receiveFrameworkLifecycle,
} from '../../../browser/frontend/src/store/slices/agentAppSlice'
import { frameworkKey, frameworkSessionIdentity } from '../../../browser/frontend/src/features/agentApps/frameworkIdentity'
import { frameworkRequest, type FrameworkAttachment } from '../../../browser/frontend/src/features/agentApps/frameworkApi'
import { getSocketClient } from '../../../browser/frontend/src/store/socket/socketInstance'

export { frameworkAppKey, frameworkKey, frameworkRequest, type FrameworkAttachment }

/** A registry row with the fields the list command also sends (not in the browser's type). */
export type RegistryApp = FrameworkRegistryApp & {
  url?: string | null
  dev?: { port: number; url: string; answering: boolean } | null
  agentWork?: { tasksWaiting?: number } | null
}

/** What a row shows: the registry status, or the start or stop on its way. */
export type AppPhase = 'starting' | 'stopping' | 'running' | 'stopped' | 'missing' | 'unreachable'

export function appPhase(app: FrameworkRegistryApp, job: { status: string; operation: string } | undefined): AppPhase {
  if (job?.status === 'running') return job.operation === 'start' ? 'starting' : 'stopping'
  return app.status
}

export const isTransitional = (phase: AppPhase): boolean => phase === 'starting' || phase === 'stopping'

/** Start and stop are for local apps the host can see: running or stopped. */
export function canChangeState(app: FrameworkRegistryApp): boolean {
  return !app.connection && (app.status === 'running' || app.status === 'stopped')
}

/** The id an app has in the sidebar's saved order (UI_STATE.nav.agentAppOrder). */
export const orderIdOf = (app: { path: string; id: string }): string => frameworkKey(app.path, app.id)
export const pendingOrderId = (sessionId: string): string => `pending:${sessionId}`

/** One row of the Apps list: a registry app, or a build still being made. */
export type AppEntry =
  | { kind: 'app'; orderId: string; app: RegistryApp }
  | { kind: 'pending'; orderId: string; session: SessionInfo }

/** Saved order first, then the rest in the order given. */
export function orderEntries(entries: AppEntry[], order: string[]): AppEntry[] {
  const rank = new Map(order.map((id, i) => [id, i]))
  return [...entries].sort((a, b) => (rank.get(a.orderId) ?? Infinity) - (rank.get(b.orderId) ?? Infinity))
}

/** Move `id` by `delta` places in `ids`; the same array when it cannot move. */
export function moveId(ids: string[], id: string, delta: -1 | 1): string[] {
  const i = ids.indexOf(id)
  const j = i + delta
  if (i < 0 || j < 0 || j >= ids.length) return ids
  const next = [...ids]
  ;[next[i], next[j]] = [next[j], next[i]]
  return next
}

/** Sessions of builds that are not in the registry yet. */
export function pendingBuilds(state: RootState): SessionInfo[] {
  return state.sessions.sessions.filter(s => s.type === 'agent_app' && s.agentAppFrameworkPending && !s.agentAppFrameworkKey)
}

/** The app's own conversation, when this connection knows it. */
export function appSessionId(state: RootState, path: string, appId: string): string | undefined {
  const attached = state.agentApp.frameworkSessions[frameworkAppKey(path, appId)]
  if (attached) return attached
  return state.sessions.sessions.find(s => {
    const identity = frameworkSessionIdentity(s.agentAppFrameworkKey)
    return identity?.path === path && identity.appId === appId
  })?.id
}

/**
 * Start or stop a local app. The row shows the change at once; the host's
 * frames replace it. Nothing is queued while disconnected.
 */
export function changeAppState(dispatch: ReturnType<typeof useAppDispatch>, app: FrameworkRegistryApp, operation: 'start' | 'stop'): boolean {
  const request = { requestId: crypto.randomUUID(), path: app.path, appId: app.id, operation }
  dispatch(receiveFrameworkLifecycle({ ...request, status: 'running' }))
  if (!getSocketClient().sendNow('agent_app_framework_lifecycle', request)) {
    dispatch(receiveFrameworkLifecycle({ ...request, status: 'unknown' }))
    return false
  }
  return true
}

/**
 * The app's conversation: known, or attached on first use (attaching starts
 * no turn and grants nothing). Undefined until the host answers.
 */
export function useAppSession(app: { path: string; id: string } | undefined): { sessionId?: string; error?: string } {
  const dispatch = useAppDispatch()
  const connected = useAppSelector(s => s.connection.connected)
  const sessionId = useAppSelector(s => (app ? appSessionId(s, app.path, app.id) : undefined))
  const [error, setError] = useState<string>()
  const path = app?.path
  const id = app?.id
  useEffect(() => {
    if (sessionId || !connected || !path || !id) return
    let active = true
    setError(undefined)
    frameworkRequest<FrameworkAttachment>({ operation: 'attach', path, appId: id })
      .then(value => {
        if (active && value.path === path && value.appId === id && value.sessionId) dispatch(receiveFrameworkAttachment(value))
      })
      .catch(err => {
        if (active) setError(errorText(err))
      })
    return () => {
      active = false
    }
  }, [sessionId, connected, path, id, dispatch])
  return { sessionId, error }
}

/** Ask the host for a fresh registry snapshot (it is broadcast to every client). */
export function requestAppList(): void {
  getSocketClient().send('agent_app_list', {})
}

/** The error text of a failed request, for one line on screen. */
export function errorText(err: unknown): string {
  return String((err as Error)?.message ?? err)
}
