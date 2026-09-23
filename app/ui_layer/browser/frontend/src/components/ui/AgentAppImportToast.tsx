import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useToast } from '../../contexts/ToastContext'
import { useSettingsWebSocket } from '../../pages/Settings/useSettingsWebSocket'

/**
 * Import progress, as a single self-updating toast.
 *
 * Mounted at the app root ON PURPOSE. The import modal used to stay open for
 * the whole operation, because closing it early "hid every failure (nothing
 * happened, no error)" — but importing github.com/odoo/odoo takes minutes
 * (~300MB, ~58k files), and holding a modal over the app that long is worse
 * than the problem it solved. So the modal closes immediately and this owns
 * the outcome instead: progress while it runs, success or error at the end.
 * It has to live outside the modal precisely BECAUSE the modal unmounts.
 */

const TOAST_KEY = 'agent-app-import'

function humanBytes(n: number): string {
  if (!n) return '0B'
  const units = ['B', 'KB', 'MB', 'GB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return i === 0 ? `${Math.round(v)}B` : `${v.toFixed(1)}${units[i]}`
}

interface ProgressEvent {
  phase?: string
  done?: number
  total?: number
  unit?: string
  name?: string
  source?: string
}

export function AgentAppImportToast() {
  const { t } = useTranslation()
  const { showToast, dismissToastKey } = useToast()
  const { onMessage } = useSettingsWebSocket()
  // The result message carries no name, so remember what we are importing.
  const labelRef = useRef<string>('')

  useEffect(() => {
    const cleanups = [
      onMessage('agent_app_import_progress', (raw: unknown) => {
        const data = (raw || {}) as ProgressEvent
        const label =
          data.name || (data.source ? data.source.split(/[\\/]/).pop() || '' : '')
        if (label) labelRef.current = label

        const { phase = 'starting', done = 0, total = 0, unit } = data
        const amount =
          unit === 'bytes'
            ? humanBytes(done) + (total ? ` / ${humanBytes(total)}` : '')
            : total
              ? `${done.toLocaleString()} / ${total.toLocaleString()}`
              : done.toLocaleString()
        const pct = total ? ` (${Math.floor((done / total) * 100)}%)` : ''
        const detail =
          phase === 'starting' || (!done && !total) ? '' : ` — ${amount}${pct}`

        showToast(
          'info',
          t('components:createAgentApp.importProgress', {
            name: labelRef.current || 'app',
            phase,
            detail,
            defaultValue: `Importing ${labelRef.current || 'app'}: ${phase}${detail}`,
          }),
          undefined,
          { key: TOAST_KEY, sticky: true },
        )
      }),
      onMessage('agent_app_import_result', (raw: unknown) => {
        const data = (raw || {}) as { success?: boolean; error?: string }
        const name = labelRef.current || 'app'
        labelRef.current = ''
        if (data.success) {
          // Not sticky: the success message auto-dismisses like any other.
          showToast(
            'success',
            t('components:createAgentApp.importDone', {
              name,
              defaultValue: `Imported ${name}`,
            }),
            undefined,
            { key: TOAST_KEY },
          )
        } else {
          // Errors DO stay put — this toast is the only place the failure
          // surfaces now that the modal is gone. Click to dismiss.
          showToast(
            'error',
            data.error ||
              t('components:createAgentApp.importFailed', {
                defaultValue: 'Import failed',
              }),
            undefined,
            { key: TOAST_KEY, sticky: true },
          )
        }
      }),
    ]
    return () => {
      cleanups.forEach(fn => fn())
      dismissToastKey(TOAST_KEY)
    }
  }, [onMessage, showToast, dismissToastKey, t])

  return null
}

export default AgentAppImportToast
