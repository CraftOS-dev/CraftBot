import { AlertTriangle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
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
  confirmText,
  cancelText,
  variant = 'default',
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  const { t } = useTranslation('common')
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
          {cancelText ?? t('actions.cancel')}
        </Button>
        <Button variant="primary" onClick={onConfirm}>
          {confirmText ?? t('actions.confirm')}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
