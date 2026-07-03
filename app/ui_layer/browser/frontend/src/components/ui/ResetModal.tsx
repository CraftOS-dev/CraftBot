import React, { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Button } from './Button'
import { Modal, ModalBody, ModalFooter } from './Modal'
import styles from './ResetModal.module.css'

/** A resettable component. `id` must match AgentBase.RESET_COMPONENTS. */
interface ResetItem {
  id: string
  label: string
  description: string
  /** Destructive/expensive to rebuild — off by default and visually flagged. */
  destructive?: boolean
}

export const RESET_ITEMS: ResetItem[] = [
  {
    id: 'conversation',
    label: 'Conversation history',
    description: 'Chat messages and the action log.',
  },
  {
    id: 'tasks',
    label: 'Tasks',
    description: 'Current and past task history.',
  },
  {
    id: 'memory',
    label: 'Memory',
    description: 'AGENT / MEMORY / PROACTIVE notes and the memory index.',
  },
  {
    id: 'triggers',
    label: 'Triggers & scheduled tasks',
    description: 'Automations, schedules, and the activity log.',
  },
  {
    id: 'workspace',
    label: 'Workspace files',
    description: 'Files the agent created in its workspace.',
    destructive: true,
  },
  {
    id: 'livingui',
    label: 'LivingUI apps',
    description: 'Deletes every app the agent has built.',
    destructive: true,
  },
]

/** Default selection: everything except the destructive items. */
const DEFAULT_SELECTED = RESET_ITEMS.filter(i => !i.destructive).map(i => i.id)

export interface ResetModalProps {
  isOpen: boolean
  onConfirm: (components: string[]) => void
  onCancel: () => void
}

export function ResetModal({ isOpen, onConfirm, onCancel }: ResetModalProps) {
  const [selected, setSelected] = useState<string[]>(DEFAULT_SELECTED)

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
    <Modal isOpen={isOpen} onClose={onCancel} title="Reset Agent" size="sm">
      <ModalBody className={styles.body}>
        <p className={styles.intro}>
          Choose what to reset. Anything left unchecked is kept. Settings and
          credentials are never affected.
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
                    {item.label}
                    {item.destructive && (
                      <span className={styles.destructiveTag}>
                        <AlertTriangle size={12} /> can’t be undone
                      </span>
                    )}
                  </span>
                  <span className={styles.itemDescription}>
                    {item.description}
                  </span>
                </span>
              </label>
            )
          })}
        </div>
      </ModalBody>
      <ModalFooter>
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          variant={anyDestructive ? 'danger' : 'primary'}
          onClick={() => onConfirm(selected)}
          disabled={!anySelected}
        >
          Reset selected
        </Button>
      </ModalFooter>
    </Modal>
  )
}
