import { useEffect, useState } from 'react'
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
    <Modal isOpen={isOpen} onClose={onClose} title={mode === 'create' ? 'New Layout' : 'Rename Layout'} size="sm">
      <ModalBody>
        <input
          type="text"
          className={styles.fieldInput}
          value={name}
          onChange={e => setName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleSubmit() }}
          placeholder="Layout name"
          autoFocus
        />
      </ModalBody>
      <ModalFooter>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant="primary" onClick={handleSubmit} disabled={!name.trim()}>
          {mode === 'create' ? 'Create' : 'Rename'}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
