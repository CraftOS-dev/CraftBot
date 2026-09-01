import React, { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react'
import { Check, X, AlertTriangle, Info } from 'lucide-react'
import { getErrorCategoryStyle } from '../constants/errorCategories'
import styles from './ToastContext.module.css'

type ToastType = 'success' | 'error' | 'warning' | 'info'

interface Toast {
  id: string
  type: ToastType
  message: string
  category?: string
  /** Stable caller-supplied identity. A second showToast with the same key
   *  REPLACES the toast in place instead of stacking a new one — that is what
   *  lets one long operation report progress through a single toast. */
  key?: string
  /** Sticky toasts never auto-dismiss. For work that outlives 3 seconds the
   *  toast has to survive until the outcome is known. */
  sticky?: boolean
}

export interface ToastOptions {
  key?: string
  sticky?: boolean
}

interface ToastContextValue {
  /** `category` (an ErrorCategory value, e.g. "auth"/"rate_limit") is optional —
   * when provided on a type='error' toast, its icon/color from
   * errorCategories.ts replaces the generic error icon. Existing call sites
   * that don't pass it keep today's behavior unchanged. */
  showToast: (
    type: ToastType,
    message: string,
    category?: string,
    options?: ToastOptions,
  ) => void
  /** Remove a keyed toast early (e.g. the operation was cancelled). */
  dismissToastKey: (key: string) => void
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
  const keyToId = useRef<Map<string, string>>(new Map())
  const timers = useRef<Map<string, number>>(new Map())

  const showToast = useCallback((
    type: ToastType,
    message: string,
    category?: string,
    options?: ToastOptions,
  ) => {
    const key = options?.key
    const sticky = !!options?.sticky
    const existingId = key ? keyToId.current.get(key) : undefined
    if (existingId) {
      setToasts(prev =>
        prev.some(t => t.id === existingId)
          ? prev.map(t => (t.id === existingId ? { ...t, type, message, category, sticky } : t))
          : [...prev, { id: existingId, type, message, category, key, sticky }],
      )
      return
    }
    const id = `toast-${++idCounter.current}`
    if (key) keyToId.current.set(key, id)
    setToasts(prev => [...prev, { id, type, message, category, key, sticky }])
  }, [])

  // Auto-dismiss lives here rather than inside showToast so that a toast
  // updated in place keeps its ORIGINAL timer, and a sticky toast that later
  // turns non-sticky (progress -> success) gets one armed at that moment.
  useEffect(() => {
    const live = new Set(toasts.map(t => t.id))
    timers.current.forEach((handle, id) => {
      if (!live.has(id)) {
        window.clearTimeout(handle)
        timers.current.delete(id)
      }
    })
    toasts.forEach(t => {
      const handle = timers.current.get(t.id)
      if (t.sticky) {
        if (handle) {
          window.clearTimeout(handle)
          timers.current.delete(t.id)
        }
        return
      }
      if (handle) return
      timers.current.set(
        t.id,
        window.setTimeout(() => {
          timers.current.delete(t.id)
          if (t.key) keyToId.current.delete(t.key)
          setToasts(prev => prev.filter(x => x.id !== t.id))
        }, 3000),
      )
    })
  }, [toasts])

  const dismissToast = useCallback((id: string) => {
    setToasts(prev => {
      const gone = prev.find(t => t.id === id)
      if (gone?.key) keyToId.current.delete(gone.key)
      return prev.filter(t => t.id !== id)
    })
  }, [])

  const dismissToastKey = useCallback((key: string) => {
    const id = keyToId.current.get(key)
    keyToId.current.delete(key)
    if (id) setToasts(prev => prev.filter(t => t.id !== id))
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
    <ToastContext.Provider value={{ showToast, dismissToastKey }}>
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
