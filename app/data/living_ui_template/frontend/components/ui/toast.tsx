/**
 * Toast notifications (SYSTEM-MANAGED — do not edit)
 *
 * THE way to confirm actions ("Saved", "Deleted", errors). No provider
 * wiring: <AppShell> already hosts the toasts — just call:
 *
 *   import { toast } from './ui'
 *   toast.success('Card saved')
 *   toast.error('Could not delete: ' + e.message)
 *   toast.info('Export started…')
 *
 * If a page does not use AppShell, render <ToastHost /> once at the root.
 */

import { useEffect, useState } from 'react'
import { CheckCircle, AlertCircle, Info, X } from 'lucide-react'

export type ToastVariant = 'success' | 'error' | 'info'

export interface ToastItem {
  id: number
  variant: ToastVariant
  message: string
}

const DISMISS_MS = 4000

let nextId = 1
let items: ToastItem[] = []
const listeners = new Set<(items: ToastItem[]) => void>()

function emit() {
  for (const fn of listeners) fn(items)
}

function push(variant: ToastVariant, message: string) {
  const id = nextId++
  items = [...items, { id, variant, message }]
  emit()
  setTimeout(() => dismiss(id), DISMISS_MS)
}

function dismiss(id: number) {
  if (!items.some(t => t.id === id)) return
  items = items.filter(t => t.id !== id)
  emit()
}

/** Imperative toast API — callable from any handler, no hooks needed. */
export const toast = {
  success: (message: string) => push('success', message),
  error: (message: string) => push('error', message),
  info: (message: string) => push('info', message),
}

const VARIANT_META: Record<ToastVariant, { color: string; Icon: typeof Info }> = {
  success: { color: 'var(--color-success)', Icon: CheckCircle },
  error: { color: 'var(--color-error)', Icon: AlertCircle },
  info: { color: 'var(--color-info)', Icon: Info },
}

/** Renders the active toasts (bottom-right). AppShell includes one. */
export function ToastHost() {
  const [list, setList] = useState<ToastItem[]>(items)

  useEffect(() => {
    listeners.add(setList)
    return () => {
      listeners.delete(setList)
    }
  }, [])

  if (list.length === 0) return null

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: 'fixed',
        bottom: 'var(--space-4)',
        right: 'var(--space-4)',
        zIndex: 'var(--z-toast)' as any,
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-2)',
        maxWidth: 380,
      }}
    >
      {list.map(t => {
        const { color, Icon } = VARIANT_META[t.variant]
        return (
          <div
            key={t.id}
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 'var(--space-2)',
              padding: 'var(--space-3) var(--space-4)',
              backgroundColor: 'var(--bg-secondary)',
              backdropFilter: 'var(--surface-backdrop)',
              border: '1px solid var(--border-primary)',
              borderLeft: `3px solid ${color}`,
              borderRadius: 'var(--radius-md)',
              boxShadow: 'var(--shadow-lg)',
              color: 'var(--text-primary)',
              fontSize: 'var(--font-size-sm)',
              animation: 'slideInRight 0.15s ease-out',
            }}
          >
            <Icon size={16} style={{ color, flexShrink: 0, marginTop: 1 }} />
            <span style={{ flex: 1, minWidth: 0, overflowWrap: 'break-word' }}>{t.message}</span>
            <button
              onClick={() => dismiss(t.id)}
              className="hover:text-ink"
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                color: 'var(--text-muted)',
                padding: 0,
                display: 'inline-flex',
                flexShrink: 0,
              }}
              aria-label="Dismiss notification"
            >
              <X size={14} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
