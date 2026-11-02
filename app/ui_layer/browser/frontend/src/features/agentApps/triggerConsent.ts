import { getSocketClient } from '../../store/socket/socketInstance'

/** Id that the `agent_app_trigger_consent` reply to one decision carries. */
export function newTriggerConsentRequestId(): string {
  return typeof crypto?.randomUUID === 'function'
    ? crypto.randomUUID()
    : `trigger-consent-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

/** Saves an allow / don't-allow decision for the app's current requests. */
export function sendTriggerConsent(projectId: string, revision: string, allow: boolean, requestId: string) {
  getSocketClient().send('agent_app_trigger_consent', { projectId, revision, allow, requestId })
}
