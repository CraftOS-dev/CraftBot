import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, ConfirmModal } from '../../components/ui'
import { useConfirmModal } from '../../hooks'
import type { FrameworkRegistryApp } from '../../types'
import type { AgentAppBackupEntry, AgentAppBackupStatus } from '../../store/slices/agentAppSettingsSlice'
import { AppSettingsSection } from '../../pages/Settings/AgentAppSettingsCard'
import { BackupControls, SharingControls, fmtWhen, type SharingInfo, type ShareChannel } from '../../pages/Settings/AgentAppSettingsControls'
import type { useFrameworkAppSettings } from './FrameworkAppActions'

export interface MaintenanceInfo {
  port?: number
  backups: AgentAppBackupEntry[]
  backupStatus: AgentAppBackupStatus
  links: SharingInfo['links']
  backupSupport?: { mode: string | null; reason?: string }
}

export function FrameworkMaintenanceControls({ app, settings }: { app: FrameworkRegistryApp; settings: ReturnType<typeof useFrameworkAppSettings> }) {
  const { t } = useTranslation(['settings', 'common'])
  const { confirm, modalProps } = useConfirmModal()
  const { attachment, maintenance, connected, busy, loaded } = settings
  const [restoring, setRestoring] = useState(false)
  const [pending, setPending] = useState<ShareChannel | null>(null)
  const [copied, setCopied] = useState<ShareChannel | null>(null)
  const disabled = !connected || busy || !loaded || !maintenance
  const restore = (filename: string, ts: number) => confirm({
    title: t('settings:agentApp.restoreBackupTitle'),
    message: t('settings:agentApp.restoreBackupMessage', { name: app.name, date: fmtWhen(ts) }),
    confirmText: t('common:actions.restore'), variant: 'danger',
  }, () => { setRestoring(true); void settings.manage('restore', filename).finally(() => setRestoring(false)) })
  const remove = (filename: string, ts: number) => confirm({
    title: t('settings:agentApp.deleteBackupTitle'),
    message: t('settings:agentApp.deleteBackupMessage', { date: fmtWhen(ts) }),
    confirmText: t('common:actions.delete'), variant: 'danger',
  }, () => void settings.deleteBackup(filename))
  const share = (action: 'open' | 'close', channel: ShareChannel) => {
    setPending(channel)
    void settings.share(action, channel).finally(() => setPending(null))
  }
  return <>
    <AppSettingsSection title={t('settings:agentApp.backups')}>
      {settings.maintenanceError && <p role="alert">{settings.maintenanceError} <Button size="sm" variant="ghost" onClick={() => void settings.refreshMaintenance()}>Retry</Button></p>}
      {maintenance?.backupSupport?.reason && <p role="status">{maintenance.backupSupport.reason}</p>}
      <BackupControls project={{ name: app.name, backupsEnabled: attachment?.backupsEnabled === true, backupInterval: attachment?.backupInterval || 'daily', backupKeep: attachment?.backupKeep || 7 }}
        backups={maintenance?.backups} status={maintenance?.backupStatus || {}} busy={busy} disabled={disabled || maintenance?.backupSupport?.mode === null} restoring={restoring}
        scheduleDescription="Back up automatically while CraftBot is running. Pauses the app briefly; waits for active tasks."
        onToggleSetting={(setting, value) => void settings.preference(setting, value)} handleBackupNow={() => void settings.manage('backup')}
        handleRestore={restore} handleDeleteEntry={remove} />
    </AppSettingsSection>
    <AppSettingsSection title={t('settings:agentApp.share')}>
      <SharingControls links={settings.links} error={null} pending={pending} copied={copied} disabled={!connected || busy || !['running', 'stopped'].includes(app.status)}
        handleOpen={channel => share('open', channel)} handleClose={channel => share('close', channel)}
        handleCopy={(link, channel) => { void navigator.clipboard.writeText(link).then(() => setCopied(channel)); window.setTimeout(() => setCopied(null), 2000) }} />
    </AppSettingsSection>
    <ConfirmModal {...modalProps} />
  </>
}
