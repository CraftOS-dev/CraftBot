import React, { createContext, useContext, useState, useCallback, useRef } from 'react'
import { Check, X, AlertTriangle, Info } from 'lucide-react'
import styles from './ToastContext.module.css'

type ToastType = 'success' | 'error' | 'warning' | 'info'

interface Toast {
  id: string
  type: ToastType
  message: string
}

interface ToastContextValue {
  showToast: (type: ToastType, message: string) => void
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

  const showToast = useCallback((type: ToastType, message: string) => {
    const id = `toast-${++idCounter.current}`
    setToasts(prev => [...prev, { id, type, message }])

    // Auto-dismiss after 3 seconds
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, 3000)
  }, [])

  const dismissToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  const getIcon = (type: ToastType) => {
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
            <span className={styles.icon}>{getIcon(toast.type)}</span>
            <span className={styles.message}>{toast.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
