import { register } from '../../store/socket/messageRegistry'
import { getSocketClient } from '../../store/socket/socketInstance'

const pending = new Map<string, { resolve: (value: unknown) => void; reject: (error: Error) => void; timer: number }>()
register('agent_app_framework_response', value => {
  const data = value as { requestId: string; status: string; result?: unknown; message?: string }
  const call = pending.get(data.requestId)
  if (!call) return
  clearTimeout(call.timer)
  pending.delete(data.requestId)
  if (data.status === 'success') call.resolve(data.result)
  else call.reject(new Error(data.message || 'Agent-App request failed.'))
})

/** Mutations are never queued across a disconnected socket or replayed. */
export function frameworkRequest<T = unknown>(data: Record<string, unknown>, timeout = 90_000): Promise<T> {
  const requestId = typeof data.requestId === 'string' ? data.requestId : crypto.randomUUID()
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      pending.delete(requestId)
      reject(new Error('No response. Refresh the app state before retrying.'))
    }, timeout)
    pending.set(requestId, { resolve: result => resolve(result as T), reject, timer })
    if (!getSocketClient().sendNow('agent_app_framework_request', { ...data, requestId })) {
      clearTimeout(timer)
      pending.delete(requestId)
      reject(new Error('Reconnect to CraftBot before continuing.'))
    }
  })
}

export interface FrameworkAttachment { key: string; path: string; appId: string; name: string; sessionId: string; tasksAllowed?: boolean; ownerToolsAllowed?: boolean; bridgeError?: string; autoStart?: boolean; startError?: string; logCleanup?: boolean; backupsEnabled?: boolean; backupInterval?: 'hourly' | '6h' | 'daily' | 'weekly'; backupKeep?: number }
export interface FrameworkInstallJob {
  id: string; status: string; request: { id?: string; from?: string }; error?: string; stderr?: string; sessionId?: string; linkError?: string
  steps: { step: string; status: string; error?: string }[]
  result?: { dir?: string; id?: string; served?: boolean; trust?: string; next?: string[]; gate?: unknown }
}
export interface FrameworkHostSnapshot { attachments: FrameworkAttachment[]; jobs: FrameworkInstallJob[]; deliveries: { key: string; sessionId: string; taskId: string; appId?: string; status: string; retryApproved?: boolean }[] }
