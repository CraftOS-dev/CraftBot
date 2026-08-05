import React, { createContext, useContext, useState, useCallback, useRef } from 'react'
import { Check, X, AlertTriangle, Info } from 'lucide-react'
import { getErrorCategoryStyle } from '../constants/errorCategories'
import styles from './ToastContext.module.css'

type ToastType = 'success' | 'error' | 'warning' | 'info'
// Mirrors Severity in agent_core/core/errors.py / errorSeverity on ChatMessage
// (src/types/index.ts). Only meaningful on error toasts — success/info/warning
// toasts don't carry one and keep the fixed 3s duration below.
export type ToastSeverity = 'info' | 'warning' | 'error' | 'critical'

// How long a toast stays up once its severity is known. A toast with no
// severity (the vast majority of existing call sites — none pass it) keeps
// today's flat 3000ms. `critical` never auto-dismisses; the whole toast is
// still a click-to-dismiss target, so that's not a dead end.
const SEVERITY_DURATION_MS: Record<ToastSeverity, number> = {
  info: 3000,
  warning: 5000,
  error: 6000,
  critical: Infinity,
}

interface Toast {
  id: string
  type: ToastType
  message: string
  category?: string
  severity?: ToastSeverity
}

interface ToastContextValue {
  /** `category` (an ErrorCategory value, e.g. "auth"/"rate_limit") is optional —
   * when provided on a type='error' toast, its icon/color from
   * errorCategories.ts replaces the generic error icon. `severity` drives
   * auto-dismiss duration (see SEVERITY_DURATION_MS). Existing call sites
   * that pass neither keep today's exact behavior unchanged. */
  showToast: (type: ToastType, message: string, category?: string, severity?: ToastSeverity) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

export function useToast() {
  const context = useContext(ToastContext)
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider')
  }
  return context
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const idCounter = useRef(0)

  const showToast = useCallback(
    (type: ToastType, message: string, category?: string, severity?: ToastSeverity) => {
      const id = `toast-${++idCounter.current}`
      setToasts(prev => [...prev, { id, type, message, category, severity }])

      const duration = severity ? SEVERITY_DURATION_MS[severity] : 3000
      if (Number.isFinite(duration)) {
        setTimeout(() => {
          setToasts(prev => prev.filter(t => t.id !== id))
        }, duration)
      }
    },
    []
  )

  const dismissToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  const getIcon = (type: ToastType, category?: string) => {
    if (type === 'error' && category) {
      const { icon: CategoryIcon } = getErrorCategoryStyle(category)
      return <CategoryIcon size={16} />
    }
    switch (type) {
      case 'success':
        return <Check size={16} />
      case 'error':
        return <X size={16} />
      case 'warning':
        return <AlertTriangle size={16} />
      case 'info':
        return <Info size={16} />
    }
  }

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className={styles.toastContainer}>
        {toasts.map(toast => (
          <div
            key={toast.id}
            className={`${styles.toast} ${styles[toast.type]}`}
            onClick={() => dismissToast(toast.id)}
          >
            <span className={styles.icon}>{getIcon(toast.type, toast.category)}</span>
            <span className={styles.message}>{toast.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
