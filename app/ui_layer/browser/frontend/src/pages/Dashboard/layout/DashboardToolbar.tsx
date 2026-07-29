import { useState } from 'react'
import { LayoutGrid, Pencil, Plus, Trash2 } from 'lucide-react'
import { Button, ConfirmModal, IconButton } from '../../../components/ui'
import { useConfirmModal } from '../../../hooks'
import { AddWidgetModal } from './AddWidgetModal'
import { LayoutNameModal } from './LayoutNameModal'
import type { NamedLayout } from './types'
import styles from './DashboardToolbar.module.css'

interface DashboardToolbarProps {
  layouts: NamedLayout[]
  activeLayout: NamedLayout
  activeLayoutId: string
  onSelectLayout: (id: string) => void
  onCreateLayout: (name: string) => void
  onRenameLayout: (id: string, name: string) => void
  onDeleteLayout: (id: string) => void
  onAddWidget: (widgetId: string) => void
}

export function DashboardToolbar({
  layouts,
  activeLayout,
  activeLayoutId,
  onSelectLayout,
  onCreateLayout,
  onRenameLayout,
  onDeleteLayout,
  onAddWidget,
}: DashboardToolbarProps) {
  const [nameModal, setNameModal] = useState<'create' | 'rename' | null>(null)
  const [addWidgetOpen, setAddWidgetOpen] = useState(false)
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  const handleDelete = () => {
    confirm(
      {
        title: 'Delete layout',
        message: `Delete "${activeLayout.name}"? This can't be undone.`,
        confirmText: 'Delete',
        variant: 'danger',
      },
      () => onDeleteLayout(activeLayoutId)
    )
  }

  return (
    <div className={styles.toolbar}>
      <div className={styles.left}>
        <LayoutGrid size={14} className={styles.layoutIcon} />
        <select
          className={styles.layoutSelect}
          value={activeLayoutId}
          onChange={e => onSelectLayout(e.target.value)}
        >
          {layouts.map(l => (
            <option key={l.id} value={l.id}>{l.name}</option>
          ))}
        </select>
        <IconButton icon={<Pencil size={14} />} tooltip="Rename layout" onClick={() => setNameModal('rename')} />
        <IconButton icon={<Plus size={14} />} tooltip="New layout" onClick={() => setNameModal('create')} />
        <IconButton
          icon={<Trash2 size={14} />}
          tooltip="Delete layout"
          disabled={layouts.length <= 1}
          onClick={handleDelete}
        />
      </div>
      <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={() => setAddWidgetOpen(true)}>
        Add Widget
      </Button>

      <LayoutNameModal
        isOpen={nameModal !== null}
        mode={nameModal ?? 'create'}
        initialName={nameModal === 'rename' ? activeLayout.name : ''}
        onSubmit={name => {
          if (nameModal === 'rename') {
            onRenameLayout(activeLayoutId, name)
          } else {
            onCreateLayout(name)
          }
        }}
        onClose={() => setNameModal(null)}
      />

      <AddWidgetModal
        isOpen={addWidgetOpen}
        existingWidgetIds={activeLayout.widgetIds}
        onAdd={onAddWidget}
        onClose={() => setAddWidgetOpen(false)}
      />

      <ConfirmModal {...confirmModalProps} />
    </div>
  )
}
