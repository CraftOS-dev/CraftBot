import React from 'react'
import { X, AlertTriangle } from 'lucide-react'
import { Button } from './Button'
import styles from './ConfirmModal.module.css'

export interface ConfirmModalProps {
  isOpen: boolean
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  variant?: 'default' | 'danger'
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmModal({
  isOpen,
  title,
  message,
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  variant = 'default',
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  if (!isOpen) return null

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <h3>{title}</h3>
          <button className={styles.modalClose} onClick={onCancel}>
            <X size={16} />
          </button>
        </div>
        <div className={styles.modalBody}>
          {variant === 'danger' && (
            <div className={styles.warningIcon}>
              <AlertTriangle size={24} />
            </div>
          )}
          <p className={styles.message}>{message}</p>
        </div>
        <div className={styles.modalFooter}>
          <Button variant="secondary" onClick={onCancel}>
            {cancelText}
          </Button>
          <Button
            variant="primary"
            onClick={onConfirm}
          >
            {confirmText}
          </Button>
        </div>
      </div>
    </div>
  )
}
