import React, { useEffect } from 'react'
import ReactDOM from 'react-dom'
import { X } from 'lucide-react'
import styles from './Modal.module.css'

export type ModalSize = 'sm' | 'md' | 'lg' | 'full' | 'auto'

export interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title?: React.ReactNode
  size?: ModalSize
  children: React.ReactNode
  closeOnOverlayClick?: boolean
  closeOnEsc?: boolean
  showCloseButton?: boolean
  closeDisabled?: boolean
  contentClassName?: string
}

export function Modal({
  isOpen,
  onClose,
  title,
  size = 'sm',
  children,
  closeOnOverlayClick = true,
  closeOnEsc = true,
  showCloseButton = true,
  closeDisabled = false,
  contentClassName,
}: ModalProps) {
  useEffect(() => {
    if (!isOpen || !closeOnEsc || closeDisabled) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isOpen, closeOnEsc, closeDisabled, onClose])

  if (!isOpen) return null

  const handleOverlayClick = () => {
    if (closeOnOverlayClick && !closeDisabled) onClose()
  }

  const showHeader = title !== undefined || showCloseButton

  // Render via a portal so the modal escapes any ancestor stacking context
  // (e.g. virtualized chat rows that use CSS `transform`, which would otherwise
  // pin a `position: fixed` modal inside that ancestor's stacking layer).
  return ReactDOM.createPortal(
    <div className={styles.overlay} onClick={handleOverlayClick}>
      <div
        className={`${styles.content} ${styles[`size_${size}`]} ${contentClassName ?? ''}`}
        onClick={e => e.stopPropagation()}
      >
        {showHeader && (
          <div className={styles.header}>
            {title !== undefined ? <h3 className={styles.title}>{title}</h3> : <span />}
            {showCloseButton && (
              <button
                type="button"
                className={styles.close}
                onClick={onClose}
                disabled={closeDisabled}
                aria-label="Close"
              >
                <X size={16} />
              </button>
            )}
          </div>
        )}
        {children}
      </div>
    </div>,
    document.body
  )
}

export interface ModalSectionProps {
  children: React.ReactNode
  className?: string
}

export function ModalBody({ children, className }: ModalSectionProps) {
  return <div className={`${styles.body} ${className ?? ''}`}>{children}</div>
}

export function ModalFooter({ children, className }: ModalSectionProps) {
  return <div className={`${styles.footer} ${className ?? ''}`}>{children}</div>
}
