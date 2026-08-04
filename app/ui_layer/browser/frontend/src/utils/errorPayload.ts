// Shared shape + hook for the snake_case error tags backend handlers add to
// WS/REST payloads (app/errors/envelope.py::error_fields, PR1 of the error-
// catalogue Phase 2 work). All fields optional and additive: any payload
// that predates this still satisfies WireError, and a call site that never
// migrates keeps compiling and behaving exactly as before.
import { useCallback } from 'react'
import { useToast, type ToastSeverity } from '../contexts/ToastContext'

export interface WireError {
  success?: boolean
  error?: string
  message?: string
  error_category?: string
  error_code?: string
  error_severity?: ToastSeverity
}

/**
 * `useErrorToast()` collapses the repeated
 *   `const d = data as {success: boolean; error?: string}
 *    if (!d.success) showToast('error', d.error || 'fallback')`
 * idiom to one line, and — once a backend handler is ported to
 * `_broadcast_error`/`error_json_response` — starts passing the category and
 * severity through automatically. Call sites that haven't been ported yet
 * just see undefined category/severity, matching today's plain toast.
 */
export function useErrorToast() {
  const { showToast } = useToast()
  return useCallback(
    (data: unknown, fallback: string) => {
      const d = (data ?? {}) as WireError
      showToast('error', d.error || d.message || fallback, d.error_category, d.error_severity)
    },
    [showToast]
  )
}
