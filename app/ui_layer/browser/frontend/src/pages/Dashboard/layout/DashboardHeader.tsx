import { useState } from 'react'
import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation(['dashboard', 'common'])
  const [nameModal, setNameModal] = useState<'create' | 'rename' | null>(null)
  const [addWidgetOpen, setAddWidgetOpen] = useState(false)
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  // The header pulls its own data, the way every widget does — nothing about
  // agent status belongs in DashboardPage's props.
  const { connected, actions, messages, dashboardMetrics } = useWebSocket()
  const status = useDerivedAgentStatus({ actions, messages, connected })
  const uptime = formatUptime(dashboardMetrics?.uptimeSeconds ?? 0)

  const handleDelete = () => {
    confirm(
      {
        title: t('dashboard:header.deleteConfirmTitle'),
        message: t('dashboard:header.deleteConfirmMessage', { name: activeLayout.name }),
        confirmText: t('common:actions.delete'),
        variant: 'danger',
      },
      () => onDeleteLayout(activeLayoutId)
    )
  }

  const handleReset = () => {
    confirm(
      {
        title: t('dashboard:header.resetConfirmTitle'),
        message: t('dashboard:header.resetConfirmMessage', { name: activeLayout.name }),
        confirmText: t('common:actions.reset'),
      },
      onResetLayout
    )
  }

  return (
    <div className={styles.header}>
      <div className={styles.status}>
        <StatusIndicator status={status.state} size="lg" variant="dot" />
        <div className={styles.statusText}>
          <h2>{t('dashboard:header.agentStatus')}</h2>
          <p>{status.message}</p>
        </div>
        <div className={styles.uptime}>
          <Timer size={12} />
          <span>{t('dashboard:header.uptime', { uptime })}</span>
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
        <IconButton icon={<Pencil size={14} />} tooltip={t('dashboard:header.renameLayout')} onClick={() => setNameModal('rename')} />
        <IconButton icon={<Plus size={14} />} tooltip={t('dashboard:header.newLayout')} onClick={() => setNameModal('create')} />
        <IconButton icon={<RotateCcw size={14} />} tooltip={t('dashboard:header.resetLayout')} onClick={handleReset} />
        <IconButton
          icon={<Trash2 size={14} />}
          tooltip={t('dashboard:header.deleteLayout')}
          disabled={layouts.length <= 1}
          onClick={handleDelete}
        />
        <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={() => setAddWidgetOpen(true)}>
          {t('dashboard:header.addWidget')}
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
