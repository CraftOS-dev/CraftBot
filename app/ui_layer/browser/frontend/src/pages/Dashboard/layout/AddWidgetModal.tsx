import { Modal, ModalBody } from '../../../components/ui'
import { WIDGET_REGISTRY } from '../widgets/registry'
import styles from './AddWidgetModal.module.css'

interface AddWidgetModalProps {
  isOpen: boolean
  existingWidgetIds: string[]
  onAdd: (widgetId: string) => void
  onClose: () => void
}

export function AddWidgetModal({ isOpen, existingWidgetIds, onAdd, onClose }: AddWidgetModalProps) {
  const available = Object.values(WIDGET_REGISTRY).filter(
    def => !(def.singleton && existingWidgetIds.includes(def.id))
  )

  const handlePick = (widgetId: string) => {
    onAdd(widgetId)
    onClose()
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Add Widget" size="sm">
      <ModalBody>
        {available.length === 0 ? (
          <div className={styles.empty}>All available widgets are already on this layout.</div>
        ) : (
          <div className={styles.list}>
            {available.map(def => {
              const Icon = def.icon
              return (
                <button key={def.id} type="button" className={styles.row} onClick={() => handlePick(def.id)}>
                  <Icon size={16} className={styles.rowIcon} />
                  <div className={styles.rowText}>
                    <span className={styles.rowTitle}>{def.title}</span>
                    {def.description && <span className={styles.rowDesc}>{def.description}</span>}
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </ModalBody>
    </Modal>
  )
}
