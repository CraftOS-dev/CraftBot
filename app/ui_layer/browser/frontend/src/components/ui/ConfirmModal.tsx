import React from 'react'
import { AlertTriangle } from 'lucide-react'
import { Button } from './Button'
import { Modal, ModalBody, ModalFooter } from './Modal'
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
  return (
    <Modal isOpen={isOpen} onClose={onCancel} title={title} size="sm">
      <ModalBody className={styles.body}>
        {variant === 'danger' && (
          <div className={styles.warningIcon}>
            <AlertTriangle size={24} />
          </div>
        )}
        <p className={styles.message}>{message}</p>
      </ModalBody>
      <ModalFooter>
        <Button variant="secondary" onClick={onCancel}>
          {cancelText}
        </Button>
        <Button variant="primary" onClick={onConfirm}>
          {confirmText}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
