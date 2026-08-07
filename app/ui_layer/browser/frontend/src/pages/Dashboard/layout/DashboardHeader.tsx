import { useState } from 'react'
import { ChevronDown, Pencil, Plus, RotateCcw, Timer, Trash2 } from 'lucide-react'
import { Button, ConfirmModal, IconButton, StatusIndicator } from '../../../components/ui'
import { useConfirmModal, useDerivedAgentStatus } from '../../../hooks'
import { useWebSocket } from '../../../contexts/WebSocketContext'
import { formatUptime } from '../widgets/shared'
import { AddWidgetModal } from './AddWidgetModal'
import { LayoutNameModal } from './LayoutNameModal'
import type { NamedLayout } from './types'
import styles from './DashboardHeader.module.css'

interface DashboardHeaderProps {
  layouts: NamedLayout[]
  activeLayout: NamedLayout
  activeLayoutId: string
  onSelectLayout: (id: string) => void
  onCreateLayout: (name: string) => void
  onRenameLayout: (id: string, name: string) => void
  onDeleteLayout: (id: string) => void
  onResetLayout: () => void
  onAddWidget: (widgetId: string) => void
}

export function DashboardHeader({
  layouts,
  activeLayout,
  activeLayoutId,
  onSelectLayout,
  onCreateLayout,
  onRenameLayout,
  onDeleteLayout,
  onResetLayout,
  onAddWidget,
}: DashboardHeaderProps) {
  const [nameModal, setNameModal] = useState<'create' | 'rename' | null>(null)
  const [addWidgetOpen, setAddWidgetOpen] = useState(false)
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  // The header pulls its own data, the way every widget does — nothing about
  // agent status belongs in DashboardPage's props.
  const { connected, actions, messages, dashboardMetrics } = useWebSocket()
  const status = useDerivedAgentStatus({ actions, messages, connected })
  const uptime = dashboardMetrics?.uptimeSeconds ? formatUptime(dashboardMetrics.uptimeSeconds) : '0m'

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

  const handleReset = () => {
    confirm(
      {
        title: 'Reset layout',
        message: `Reset "${activeLayout.name}" to the default arrangement? Widgets you've added that aren't part of the default layout are kept.`,
        confirmText: 'Reset',
      },
      onResetLayout
    )
  }

  return (
    <div className={styles.header}>
      <div className={styles.status}>
        <StatusIndicator status={status.state} size="lg" variant="dot" />
        <div className={styles.statusText}>
          <h2>Agent Status</h2>
          <p>{status.message}</p>
        </div>
        <div className={styles.uptime}>
          <Timer size={12} />
          <span>Uptime: {uptime}</span>
        </div>
      </div>

      <div className={styles.controls}>
        <span className={styles.selectWrap}>
          <select
            className={styles.layoutSelect}
            value={activeLayoutId}
            onChange={e => onSelectLayout(e.target.value)}
          >
            {layouts.map(l => (
              <option key={l.id} value={l.id}>{l.name}</option>
            ))}
          </select>
          <ChevronDown size={14} className={styles.selectChevron} />
        </span>
        <IconButton icon={<Pencil size={14} />} tooltip="Rename layout" onClick={() => setNameModal('rename')} />
        <IconButton icon={<Plus size={14} />} tooltip="New layout" onClick={() => setNameModal('create')} />
        <IconButton icon={<RotateCcw size={14} />} tooltip="Reset layout" onClick={handleReset} />
        <IconButton
          icon={<Trash2 size={14} />}
          tooltip="Delete layout"
          disabled={layouts.length <= 1}
          onClick={handleDelete}
        />
        <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={() => setAddWidgetOpen(true)}>
          Add Widget
        </Button>
      </div>

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
