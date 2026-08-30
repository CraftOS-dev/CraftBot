import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Modal, ModalBody, ModalFooter } from '../../../components/ui'
import styles from './LayoutNameModal.module.css'

interface LayoutNameModalProps {
  isOpen: boolean
  mode: 'create' | 'rename'
  initialName?: string
  onSubmit: (name: string) => void
  onClose: () => void
}

export function LayoutNameModal({ isOpen, mode, initialName = '', onSubmit, onClose }: LayoutNameModalProps) {
  const { t } = useTranslation(['dashboard', 'common'])
  const [name, setName] = useState(initialName)

  useEffect(() => {
    if (isOpen) setName(initialName)
  }, [isOpen, initialName])

  const handleSubmit = () => {
    const trimmed = name.trim()
    if (!trimmed) return
    onSubmit(trimmed)
    onClose()
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={mode === 'create' ? t('dashboard:layoutModal.createTitle') : t('dashboard:layoutModal.renameTitle')} size="sm">
      <ModalBody>
        <input
          type="text"
          className={styles.fieldInput}
          value={name}
          onChange={e => setName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleSubmit() }}
          placeholder={t('dashboard:layoutModal.placeholder')}
          autoFocus
        />
      </ModalBody>
      <ModalFooter>
        <Button variant="secondary" onClick={onClose}>{t('common:actions.cancel')}</Button>
        <Button variant="primary" onClick={handleSubmit} disabled={!name.trim()}>
          {mode === 'create' ? t('common:actions.create') : t('common:actions.rename')}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
