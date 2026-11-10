import { Archive, Check, Copy, Loader2, RotateCcw, Square, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../components/ui/Button'
import i18n from '../../i18n/config'
import { formatNumber, formatDateTime } from '../../i18n/format'
import styles from './SettingsPage.module.css'

const INTERVAL_VALUES = ['hourly', '6h', 'daily', 'weekly'] as const

// Localized label for a backup trigger. i18n instance used directly since this
// is called from module-scope helpers; components re-render on language change.
export function triggerLabel(trigger: string): string {
  switch (trigger) {
    case 'scheduled': return i18n.t('settings:agentApp.trigger.scheduled')
    case 'pre_promote': return i18n.t('settings:agentApp.trigger.pre_promote')
    case 'manual': return i18n.t('settings:agentApp.trigger.manual')
    case 'pre_delete': return i18n.t('settings:agentApp.trigger.pre_delete')
    case 'pre_restore': return i18n.t('settings:agentApp.trigger.pre_restore')
    default: return trigger
  }
}

/** Inline "restoring… / restored / failed" line under an archive list. */
export function RestoreStatusLine({
  busy,
  targetName,
  result,
}: {
  busy: boolean
  targetName?: string
  result?: { ok: boolean; message: string }
}) {
  const { t } = useTranslation(['settings', 'common'])
  if (busy)
    return (
      <span
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-2)',
          fontSize: 'var(--text-xs)',
          color: 'var(--text-muted)',
          padding: 'var(--space-2) 0',
        }}
      >
        <Loader2 size={12} className={styles.spinning} />
        {targetName
          ? t('settings:agentApp.restoringInto', { name: targetName })
          : t('settings:agentApp.restoring')}
      </span>
    )
  if (result)
    return (
      <span
        style={{
          fontSize: 'var(--text-xs)',
          color: result.ok ? 'var(--color-success)' : 'var(--color-error)',
          padding: 'var(--space-2) 0',
        }}
      >
        {result.message}
      </span>
    )
  return null
}

export function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function fmtWhen(msEpoch: number): string {
  return formatDateTime(new Date(msEpoch))
}

interface BackupControlsProps {
  project: Pick<AgentAppSettingsProject, 'name' | 'backupsEnabled' | 'backupInterval' | 'backupKeep'>
  backups?: AgentAppBackupEntry[]
  busy: boolean
  disabled?: boolean
  restoring: boolean
  status: AgentAppBackupStatus
  restoreResult?: { ok: boolean; message: string }
  scheduleDescription?: string
  onToggleSetting: (setting: string, value: boolean | string | number) => void
  handleBackupNow: () => void
  handleRestore: (filename: string, ts: number) => void
  handleDeleteEntry: (filename: string, ts: number) => void
}
export function BackupControls({ project, backups, busy, disabled, restoring, status, restoreResult, scheduleDescription, onToggleSetting, handleBackupNow, handleRestore, handleDeleteEntry }: BackupControlsProps) {
  const { t } = useTranslation(['settings', 'common'])
  const rowStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 'var(--space-3)',
    padding: 'var(--space-2) 0',
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {/* Enable toggle */}
      <div style={rowStyle}>
        <div className={styles.toggleInfo}>
          <span className={styles.toggleLabel}>{t('settings:agentApp.scheduledBackups')}</span>
          <span className={styles.toggleDesc}>
            {scheduleDescription || t('settings:agentApp.scheduledBackupsDesc')}
          </span>
        </div>
        <input
          type="checkbox"
          className={styles.toggle}
          aria-label={t('settings:agentApp.scheduledBackups')}
          disabled={disabled}
          checked={project.backupsEnabled}
          onChange={e => onToggleSetting('backupsEnabled', e.target.checked)}
        />
      </div>

      {project.backupsEnabled && (
        <>
          <div style={{ ...rowStyle, borderTop: '1px solid var(--border-primary)' }}>
            <div className={styles.toggleInfo}>
              <span className={styles.toggleLabel}>{t('settings:agentApp.frequency')}</span>
            </div>
            <select
              aria-label={t('settings:agentApp.frequency')} disabled={disabled}
              value={project.backupInterval}
              onChange={e => onToggleSetting('backupInterval', e.target.value)}
              style={{
                background: 'var(--bg-primary)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border-primary)',
                borderRadius: 'var(--radius-sm)',
                padding: '4px 8px',
                fontSize: 'var(--text-sm)',
              }}
            >
              {INTERVAL_VALUES.map(v => (
                <option key={v} value={v}>{t(`settings:agentApp.interval.${v}`)}</option>
              ))}
            </select>
          </div>

          <div style={{ ...rowStyle, borderTop: '1px solid var(--border-primary)' }}>
            <div className={styles.toggleInfo}>
              <span className={styles.toggleLabel}>{t('settings:agentApp.backupsToKeep')}</span>
              <span className={styles.toggleDesc}>
                {t('settings:agentApp.backupsToKeepDesc')}
              </span>
            </div>
            <input
              type="number" aria-label={t('settings:agentApp.backupsToKeep')} disabled={disabled}
              min={1}
              max={30}
              value={project.backupKeep}
              onChange={e => {
                const v = parseInt(e.target.value, 10)
                if (Number.isFinite(v) && v >= 1 && v <= 30)
                  onToggleSetting('backupKeep', v)
              }}
              style={{
                width: 64,
                background: 'var(--bg-primary)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border-primary)',
                borderRadius: 'var(--radius-sm)',
                padding: '4px 8px',
                fontSize: 'var(--text-sm)',
              }}
            />
          </div>
        </>
      )}

      {/* Status line + Back up now */}
      <div style={{ ...rowStyle, borderTop: '1px solid var(--border-primary)' }}>
        <span style={{ fontSize: 'var(--text-xs)', color: status.lastError ? 'var(--color-error)' : 'var(--text-muted)' }}>
          {status.lastError
            ? t('settings:agentApp.lastBackupFailed', { error: status.lastError })
            : status.lastAt
              ? t('settings:agentApp.lastBackupSummary', { when: fmtWhen(status.lastAt * 1000), value: formatNumber(status.count || 0), size: fmtSize(status.totalSize || 0) })
              : t('settings:agentApp.noBackupsYet')}
        </span>
        <Button
          size="sm"
          variant="secondary"
          icon={busy ? <Loader2 size={14} className={styles.spinning} /> : <Archive size={14} />}
          onClick={handleBackupNow}
          disabled={busy || disabled}
        >
          {t('settings:agentApp.backupNow')}
        </Button>
      </div>

      {/* Restore progress/outcome (busy is shared with Back up now — the
          "restoring" line only shows for actual restores) */}
      <RestoreStatusLine
        busy={busy && restoring}
        targetName={project.name}
        result={restoreResult}
      />

      {/* Archive list */}
      {(backups || []).length > 0 && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            borderTop: '1px solid var(--border-primary)',
            maxHeight: 220,
            overflowY: 'auto',
          }}
        >
          {(backups || []).map(b => (
            <div key={b.filename} style={{ ...rowStyle, gap: 'var(--space-2)' }}>
              <span
                style={{
                  flex: 1,
                  fontSize: 'var(--text-xs)',
                  color: 'var(--text-primary)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
                title={b.filename}
              >
                {fmtWhen(b.ts)}
                <span style={{ color: 'var(--text-muted)' }}>
                  {' '}· {triggerLabel(b.trigger)} · {fmtSize(b.size)}
                </span>
              </span>
              <Button
                size="sm"
                variant="ghost"
                icon={<RotateCcw size={13} />}
                onClick={() => handleRestore(b.filename, b.ts)}
                disabled={busy || disabled}
                title={t('settings:agentApp.restoreThisBackup')}
              />
              <Button
                size="sm"
                variant="ghost"
                icon={<Trash2 size={13} />}
                onClick={() => handleDeleteEntry(b.filename, b.ts)}
                disabled={busy || disabled}
                title={t('settings:agentApp.deleteThisBackup')}
              />
            </div>
          ))}
        </div>
      )}


    </div>
  )
}

// One row per channel, in display order. Both are shared the same way — by
// a link that carries its secret; closing a channel revokes every visitor.
const SHARE_CHANNELS = [
  { id: 'lan', label: 'settings:agentApp.lan', hint: 'settings:agentApp.lanHint', create: 'settings:agentApp.createLanLink' },
  { id: 'tunnel', label: 'settings:agentApp.public', hint: 'settings:agentApp.publicHint', create: 'settings:agentApp.createTunnel' },
] as const satisfies readonly { id: ShareChannel; label: string; hint: string; create: string }[]

export type ShareChannel = 'lan' | 'tunnel'
export interface SharingInfo {
  links: Partial<Record<ShareChannel, string | null>>
  error: { channel: ShareChannel; message: string } | null
}
interface SharingControlsProps extends SharingInfo {
  pending: ShareChannel | null
  copied: ShareChannel | null
  disabled?: boolean
  handleCopy: (url: string, channel: ShareChannel) => void
  handleOpen: (channel: ShareChannel) => void
  handleClose: (channel: ShareChannel) => void
}
export function SharingControls({ links, error, pending, copied, disabled, handleCopy, handleOpen, handleClose }: SharingControlsProps) {
  const { t } = useTranslation(['settings', 'common'])
return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-2)',
      }}
    >
      {SHARE_CHANNELS.map(({ id, label, hint, create }) => {
        const link = links[id]
        return (
          <div key={id} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
            <div className={styles.modelRow}>
              <span className={styles.modelLabel} title={t(hint)}>{t(label)}</span>
              {link ? (
                <>
                  <code
                    className={styles.modelValue}
                    // width 0 + flex 1: fill the row without the (secret-long) link
                    // widening the settings column to its full text width.
                    style={{ flex: 1, width: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  >
                    {link}
                  </code>
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={copied === id ? <Check size={14} /> : <Copy size={14} />}
                    title={t('common:actions.copy')} onClick={() => handleCopy(link, id)}
                  />
                  <Button size="sm" variant="ghost" icon={<Square size={14} />} disabled={disabled || pending !== null} title={t('settings:agentApp.stop')} onClick={() => handleClose(id)} />
                </>
              ) : (
                <>
                  <span style={{ flex: 1, fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                    {t(hint)}
                  </span>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => handleOpen(id)}
                    disabled={disabled || pending !== null}
                    icon={pending === id ? <Loader2 size={14} className={styles.spinning} /> : undefined}
                  >
                    {pending === id ? t('settings:agentApp.starting') : t(create)}
                  </Button>
                </>
              )}
            </div>
            {error?.channel === id && (
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-error)' }}>{error.message}</span>
            )}
          </div>
        )
      })}
    </div>
  )
}

export interface AgentAppBackupStatus {
  lastAt?: number | null
  lastError?: string | null
  count?: number
  totalSize?: number
}

export interface AgentAppBackupEntry {
  filename: string
  ts: number // ms epoch
  trigger: 'scheduled' | 'pre_promote' | 'manual' | 'pre_delete' | 'pre_restore'
  size: number
}

export interface AgentAppSettingsProject {
  id: string
  name: string
  status: string
  port: number | null
  backendPort: number | null
  path: string
  projectType?: string
  autoLaunch: boolean
  logCleanup: boolean
  backupsEnabled: boolean
  backupInterval: 'hourly' | '6h' | 'daily' | 'weekly'
  backupKeep: number
  backupStatus?: AgentAppBackupStatus
}
