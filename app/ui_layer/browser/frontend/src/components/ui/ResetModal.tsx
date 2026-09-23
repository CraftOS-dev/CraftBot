import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from './Button'
import { Modal, ModalBody, ModalFooter } from './Modal'
import styles from './ResetModal.module.css'

/** A resettable component. `id` must match AgentBase.RESET_COMPONENTS.
 *  Labels/descriptions live in the `components:resetModal.items.*` catalog,
 *  keyed by `id`. */
interface ResetItem {
  id: string
  /** Destructive/expensive to rebuild — off by default and visually flagged. */
  destructive?: boolean
}

export const RESET_ITEMS: ResetItem[] = [
  { id: 'sessions' },
  { id: 'memory' },
  { id: 'triggers' },
  { id: 'workspace', destructive: true },
  { id: 'agentapp', destructive: true },
]

/** Default selection: everything except the destructive items. */
const DEFAULT_SELECTED = RESET_ITEMS.filter(i => !i.destructive).map(i => i.id)

export interface ResetModalProps {
  isOpen: boolean
  onConfirm: (components: string[]) => void
  onCancel: () => void
}

export function ResetModal({ isOpen, onConfirm, onCancel }: ResetModalProps) {
  const { t } = useTranslation(['components', 'common'])
  const [selected, setSelected] = useState<string[]>(DEFAULT_SELECTED)

  // Explicit (type-checked) key literals per resettable component, keyed by id.
  const itemText: Record<string, { label: string; description: string }> = {
    sessions: {
      label: t('components:resetModal.items.sessions.label'),
      description: t('components:resetModal.items.sessions.description'),
    },
    memory: {
      label: t('components:resetModal.items.memory.label'),
      description: t('components:resetModal.items.memory.description'),
    },
    triggers: {
      label: t('components:resetModal.items.triggers.label'),
      description: t('components:resetModal.items.triggers.description'),
    },
    workspace: {
      label: t('components:resetModal.items.workspace.label'),
      description: t('components:resetModal.items.workspace.description'),
    },
    agentapp: {
      label: t('components:resetModal.items.agentapp.label'),
      description: t('components:resetModal.items.agentapp.description'),
    },
  }

  // Reset the selection to defaults each time the modal is opened.
  useEffect(() => {
    if (isOpen) setSelected(DEFAULT_SELECTED)
  }, [isOpen])

  const toggle = (id: string) => {
    setSelected(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    )
  }

  const anySelected = selected.length > 0
  const anyDestructive = RESET_ITEMS.some(
    i => i.destructive && selected.includes(i.id)
  )

  return (
    <Modal isOpen={isOpen} onClose={onCancel} title={t('components:resetModal.title')} size="sm">
      <ModalBody className={styles.body}>
        <p className={styles.intro}>
          {t('components:resetModal.intro')}
        </p>
        <div className={styles.list}>
          {RESET_ITEMS.map(item => {
            const checked = selected.includes(item.id)
            return (
              <label
                key={item.id}
                className={`${styles.item} ${checked ? styles.itemChecked : ''}`}
              >
                <input
                  type="checkbox"
                  className={styles.checkbox}
                  checked={checked}
                  onChange={() => toggle(item.id)}
                />
                <span className={styles.itemText}>
                  <span className={styles.itemLabel}>
                    {itemText[item.id]?.label}
                    {item.destructive && (
                      <span className={styles.destructiveTag}>
                        <AlertTriangle size={12} /> {t('components:resetModal.cantBeUndone')}
                      </span>
                    )}
                  </span>
                  <span className={styles.itemDescription}>
                    {itemText[item.id]?.description}
                  </span>
                </span>
              </label>
            )
          })}
        </div>
      </ModalBody>
      <ModalFooter>
        <Button variant="secondary" onClick={onCancel}>
          {t('common:actions.cancel')}
        </Button>
        <Button
          variant={anyDestructive ? 'danger' : 'primary'}
          onClick={() => onConfirm(selected)}
          disabled={!anySelected}
        >
          {t('components:resetModal.confirmButton')}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
