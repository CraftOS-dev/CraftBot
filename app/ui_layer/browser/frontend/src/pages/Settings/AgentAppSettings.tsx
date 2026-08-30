import { useState, useEffect } from 'react'
import {
  Play,
  Square,
  Trash2,
  Loader2,
  Check,
  Download,
  Copy,
  ChevronRight,
  Archive,
  RotateCcw,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button, ConfirmModal } from '../../components/ui'
import { useConfirmModal } from '../../hooks'
import i18n from '../../i18n/config'
import { formatNumber, formatDateTime } from '../../i18n/format'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  updateProjectSetting,
  setBackupBusy,
  type AgentAppSettingsProject as AgentAppProject,
  type AgentAppBackupOrphan,
} from '../../store/slices/agentAppSettingsSlice'
import {
  selectAgentAppSettingsProjects,
  selectAgentAppSettingsHasLoadedProjects,
} from '../../store/selectors/agentAppSettings'

export function AgentAppSettings() {
  const { t } = useTranslation(['settings', 'common'])
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const dispatch = useAppDispatch()
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  // Slice-backed: cached across remounts.
  const projects = useAppSelector(selectAgentAppSettingsProjects)
  const hasLoadedProjects = useAppSelector(selectAgentAppSettingsHasLoadedProjects)
  const loading = !hasLoadedProjects

  // Transient UI state.
  const [actionInProgress, setActionInProgress] = useState<string | null>(null)
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(new Set())

  // Fire-once fetch. Slice owns the data; we just trigger the request when
  // not yet loaded.
  useEffect(() => {
    if (!isConnected) return
    if (!hasLoadedProjects) send('agent_app_settings_get')
  }, [isConnected, send, hasLoadedProjects])

  useEffect(() => {
    const handleActionComplete = (data: unknown) => {
      const d = data as { success: boolean }
      setActionInProgress(null)
      if (d.success) send('agent_app_settings_get')
    }
    const cleanups = [
      onMessage('agent_app_launch', handleActionComplete),
      onMessage('agent_app_stop', handleActionComplete),
      onMessage('agent_app_delete', handleActionComplete),
    ]
    return () => cleanups.forEach(c => c())
  }, [send, onMessage])

  useEffect(() => {
    const cleanup = onMessage('agent_app_project_setting_update', (data: unknown) => {
      const d = data as { success: boolean }
      // Refetch to reconcile with authoritative state (response doesn't
      // carry the updated project payload).
      if (d.success) send('agent_app_settings_get')
    })
    return cleanup
  }, [send, onMessage])

  const handleLaunch = (projectId: string) => {
    setActionInProgress(projectId)
    send('agent_app_launch', { projectId })
  }

  const handleStop = (projectId: string) => {
    setActionInProgress(projectId)
    send('agent_app_stop', { projectId })
  }

  const toggleProject = (id: string) => {
    setExpandedProjects(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleDelete = (project: AgentAppProject) => {
    confirm({
      title: t('settings:agentApp.deleteConfirmTitle'),
      message: t('settings:agentApp.deleteConfirmMessage', { name: project.name }),
      confirmText: t('common:actions.delete'),
      variant: 'danger',
    }, () => {
      setActionInProgress(project.id)
      send('agent_app_delete', { projectId: project.id })
    })
  }

  const backupOrphans = useAppSelector(s => s.agentAppSettings.backupOrphans)
  const handleDeleteOrphanBackups = (orphan: { id: string; name: string }) => {
    confirm({
      title: t('settings:agentApp.leftoverDeleteTitle'),
      message: t('settings:agentApp.leftoverDeleteMessage', { name: orphan.name }),
      confirmText: t('settings:agentApp.deleteBackupsButton'),
      variant: 'danger',
    }, () => {
      send('agent_app_backup_delete', { projectId: orphan.id, filename: '', orphan: true })
      send('agent_app_settings_get')
    })
  }

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>{t('settings:agentApp.title')}</h3>
        <p>{t('settings:agentApp.subtitle')}</p>
      </div>

      {/* ── Projects ──────────────────────────────────────── */}
      <div className={styles.subsection}>
        <h4 className={styles.subsectionTitle}>{t('settings:agentApp.projectsTitle')}</h4>
        <p className={styles.subsectionDesc}>
          {t('settings:agentApp.projectsDesc')}
        </p>

        {loading ? (
          <div className={styles.loadingState}>
            <Loader2 size={20} className={styles.spinning} />
            <span>{t('settings:agentApp.loadingProjects')}</span>
          </div>
        ) : projects.length === 0 ? (
          <div className={styles.emptyState}>
            <p>{t('settings:agentApp.noProjects')}</p>
          </div>
        ) : (
          <div className={styles.scheduleList}>
            {projects.map(project => (
              <ProjectCard
                key={project.id}
                project={project}
                actionInProgress={actionInProgress === project.id}
                expanded={expandedProjects.has(project.id)}
                onToggleExpand={() => toggleProject(project.id)}
                onLaunch={() => handleLaunch(project.id)}
                onStop={() => handleStop(project.id)}
                onDelete={() => handleDelete(project)}
                onToggleSetting={(setting, value) => {
                  // Optimistic so the control flips immediately; the refetch
                  // triggered by the response reconciles authoritative state.
                  dispatch(updateProjectSetting({
                    projectId: project.id,
                    setting: setting as
                      | 'autoLaunch'
                      | 'logCleanup'
                      | 'backupsEnabled'
                      | 'backupInterval'
                      | 'backupKeep',
                    value,
                  }))
                  send('agent_app_project_setting_update', { projectId: project.id, setting, value })
                }}
                send={send}
                onMessage={onMessage}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Leftover backups of deleted apps (kept on delete — removable here) ── */}
      {backupOrphans.length > 0 && (
        <div className={styles.subsection}>
          <h4 className={styles.subsectionTitle}>{t('settings:agentApp.leftoverTitle')}</h4>
          <p className={styles.subsectionDesc}>
            {t('settings:agentApp.leftoverDesc')}
          </p>
          <div className={styles.scheduleList}>
            {backupOrphans.map(orphan => (
              <OrphanBackupsRow
                key={orphan.id}
                orphan={orphan}
                projects={projects}
                send={send}
                onDeleteAll={handleDeleteOrphanBackups}
              />
            ))}
          </div>
        </div>
      )}

      <ConfirmModal {...confirmModalProps} />
    </div>
  )
}


// ── Project Card ───────────────────────────────────────────────

interface ProjectCardProps {
  project: AgentAppProject
  actionInProgress: boolean
  expanded: boolean
  onToggleExpand: () => void
  onLaunch: () => void
  onStop: () => void
  onDelete: () => void
  onToggleSetting: (setting: string, value: boolean | string | number) => void
  send: (type: string, data?: Record<string, unknown>) => void
  onMessage: (type: string, handler: (data: unknown) => void) => () => void
}

function getStatusText(status: string): string {
  switch (status) {
    case 'running':
      return i18n.t('settings:agentApp.status.running')
    case 'creating':
      return i18n.t('settings:agentApp.status.creating')
    case 'launching':
      return i18n.t('settings:agentApp.status.launching')
    case 'error':
      return i18n.t('settings:agentApp.status.error')
    default:
      // created, stopped, ready
      return i18n.t('settings:agentApp.status.notRunning')
  }
}

function getStatusColor(status: string): string {
  switch (status) {
    case 'running':
      return 'var(--color-success)'
    case 'creating':
    case 'launching':
      return 'var(--color-warning)'
    case 'error':
      return 'var(--color-error)'
    default:
      return 'var(--text-muted)'
  }
}

function isActiveStatus(status: string): boolean {
  return status === 'running' || status === 'creating' || status === 'launching'
}

function ProjectCard({
  project,
  actionInProgress,
  expanded,
  onToggleExpand,
  onLaunch,
  onStop,
  onDelete,
  onToggleSetting,
  send,
  onMessage,
}: ProjectCardProps) {
  const { t } = useTranslation(['settings', 'common'])
  const canLaunch = ['created', 'stopped', 'ready', 'error'].includes(project.status)
  const isRunning = project.status === 'running'

  const handleExport = () => {
    const link = document.createElement('a')
    link.href = `/api/agent-app/${project.id}/export`
    link.download = ''
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  const handleCopyPath = () => {
    navigator.clipboard.writeText(project.path)
  }

  const settings: Array<{
    key: 'autoLaunch' | 'logCleanup'
    label: string
    desc: string
    value: boolean
  }> = [
    {
      key: 'autoLaunch',
      label: t('settings:agentApp.autoLaunchLabel'),
      desc: t('settings:agentApp.autoLaunchDesc'),
      value: project.autoLaunch,
    },
    {
      key: 'logCleanup',
      label: t('settings:agentApp.logCleanupLabel'),
      desc: t('settings:agentApp.logCleanupDesc'),
      value: project.logCleanup,
    },
  ]

  const sectionLabelStyle: React.CSSProperties = {
    fontSize: '10px',
    fontWeight: 'var(--font-semibold)',
    color: 'var(--text-tertiary)',
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
  }

  const infoLabelStyle: React.CSSProperties = {
    fontSize: 'var(--text-xs)',
    color: 'var(--text-muted)',
  }

  const infoValueStyle: React.CSSProperties = {
    fontSize: 'var(--text-sm)',
    fontFamily: 'var(--font-mono)',
    color: 'var(--text-primary)',
    minWidth: 0,
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--bg-tertiary)',
        border: '1px solid var(--border-primary)',
        borderRadius: 'var(--radius-md)',
        overflow: 'hidden',
      }}
    >
      {/* Zone 1 — Header (clickable to expand/collapse) */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-3)',
          padding: 'var(--space-3)',
          cursor: 'pointer',
          userSelect: 'none',
        }}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={onToggleExpand}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onToggleExpand()
          }
        }}
      >
        <ChevronRight
          size={14}
          style={{
            color: 'var(--text-muted)',
            transition: 'transform 0.15s',
            transform: expanded ? 'rotate(90deg)' : 'none',
            flexShrink: 0,
          }}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 'var(--text-base)',
              fontWeight: 'var(--font-semibold)',
              color: 'var(--text-primary)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {project.name}
          </div>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-2)',
              marginTop: 4,
            }}
          >
            <span
              className={`${styles.statusDot} ${isActiveStatus(project.status) ? styles.statusDotPulse : ''}`}
              style={{ background: getStatusColor(project.status) }}
            />
            <span
              style={{
                fontSize: 'var(--text-xs)',
                color: getStatusColor(project.status),
                fontWeight: 'var(--font-medium)',
              }}
            >
              {getStatusText(project.status)}
            </span>
          </div>
        </div>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-1)',
            flexShrink: 0,
          }}
          onClick={e => e.stopPropagation()}
        >
          {isRunning ? (
            <Button
              size="sm"
              variant="danger"
              icon={actionInProgress ? <Loader2 size={14} className={styles.spinning} /> : <Square size={14} />}
              onClick={onStop}
              disabled={actionInProgress}
            >
              {t('settings:agentApp.stop')}
            </Button>
          ) : canLaunch ? (
            <Button
              size="sm"
              variant="primary"
              icon={actionInProgress ? <Loader2 size={14} className={styles.spinning} /> : <Play size={14} />}
              onClick={onLaunch}
              disabled={actionInProgress}
            >
              {t('settings:agentApp.launch')}
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="ghost"
            icon={<Download size={14} />}
            onClick={handleExport}
            title={t('settings:agentApp.exportProject')}
          />
          <Button
            size="sm"
            variant="ghost"
            icon={<Trash2 size={14} />}
            onClick={onDelete}
            disabled={actionInProgress}
            title={t('settings:agentApp.deleteProject')}
          />
        </div>
      </div>

      {expanded && <>

      {/* Zone 2 — Runtime info (inset, aligned key/value rows) */}
      <div
        style={{
          padding: 'var(--space-3)',
          background: 'var(--bg-primary)',
          borderTop: '1px solid var(--border-primary)',
          display: 'grid',
          gridTemplateColumns: '110px 1fr',
          rowGap: 'var(--space-2)',
          columnGap: 'var(--space-3)',
          alignItems: 'center',
        }}
      >
        <span style={infoLabelStyle}>{t('settings:agentApp.frontendPort')}</span>
        <span style={infoValueStyle}>{project.port != null ? project.port : '—'}</span>

        <span style={infoLabelStyle}>{t('settings:agentApp.backendPort')}</span>
        <span style={infoValueStyle}>{project.backendPort != null ? project.backendPort : '—'}</span>

        <span style={infoLabelStyle}>{t('settings:agentApp.projectId')}</span>
        <span style={infoValueStyle}>{project.id}</span>

        <span style={infoLabelStyle}>{t('settings:agentApp.path')}</span>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-2)',
            minWidth: 0,
          }}
        >
          <span
            style={{
              ...infoValueStyle,
              flex: 1,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
            title={project.path}
          >
            {project.path}
          </span>
          <Button
            size="sm"
            variant="ghost"
            icon={<Copy size={12} />}
            onClick={handleCopyPath}
            title={t('settings:agentApp.copyPath')}
          />
        </div>
      </div>

      {/* Zone 3 — Preferences */}
      <div
        style={{
          padding: 'var(--space-3)',
          borderTop: '1px solid var(--border-primary)',
        }}
      >
        <div style={{ ...sectionLabelStyle, marginBottom: 'var(--space-2)' }}>
          {t('settings:agentApp.preferences')}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {settings.map((s, i) => (
            <div
              key={s.key}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 'var(--space-3)',
                padding: 'var(--space-2) 0',
                borderTop: i > 0 ? '1px solid var(--border-primary)' : 'none',
              }}
            >
              <div className={styles.toggleInfo}>
                <span className={styles.toggleLabel}>{s.label}</span>
                <span className={styles.toggleDesc}>{s.desc}</span>
              </div>
              <input
                type="checkbox"
                className={styles.toggle}
                checked={s.value}
                onChange={e => onToggleSetting(s.key, e.target.checked)}
              />
            </div>
          ))}
        </div>
      </div>

      {/* Zone 3b — Backups (native apps only: externals have no pb_data) */}
      {project.projectType !== 'external' && (
        <div
          style={{
            padding: 'var(--space-3)',
            borderTop: '1px solid var(--border-primary)',
          }}
        >
          <div style={{ ...sectionLabelStyle, marginBottom: 'var(--space-2)' }}>
            {t('settings:agentApp.backups')}
          </div>
          <BackupsSection
            project={project}
            onToggleSetting={onToggleSetting}
            send={send}
          />
        </div>
      )}

      {/* Zone 4 — Share */}
      {isRunning && (
        <div
          style={{
            padding: 'var(--space-3)',
            borderTop: '1px solid var(--border-primary)',
          }}
        >
          <div style={{ ...sectionLabelStyle, marginBottom: 'var(--space-2)' }}>
            {t('settings:agentApp.share')}
          </div>
          <ShareSection projectId={project.id} port={project.port} send={send} onMessage={onMessage} />
        </div>
      )}

      </>}
    </div>
  )
}


// ── Backups Section ────────────────────────────────────────────

const INTERVAL_VALUES = ['hourly', '6h', 'daily', 'weekly'] as const

// Localized label for a backup trigger. i18n instance used directly since this
// is called from module-scope helpers; components re-render on language change.
function triggerLabel(trigger: string): string {
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
function RestoreStatusLine({
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

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function fmtWhen(msEpoch: number): string {
  return formatDateTime(new Date(msEpoch))
}

// ── Leftover (orphan) backups row ──────────────────────────────
// A deleted app's kept archives: expandable to list them, each restorable
// into a still-existing app (the backend rolls back automatically when the
// data doesn't fit), the whole dir deletable.

interface OrphanBackupsRowProps {
  orphan: AgentAppBackupOrphan
  projects: AgentAppProject[]
  send: (type: string, data?: Record<string, unknown>) => void
  onDeleteAll: (orphan: AgentAppBackupOrphan) => void
}

function OrphanBackupsRow({ orphan, projects, send, onDeleteAll }: OrphanBackupsRowProps) {
  const { t } = useTranslation(['settings', 'common'])
  const dispatch = useAppDispatch()
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()
  const [expanded, setExpanded] = useState(false)
  const backups = useAppSelector(
    s => s.agentAppSettings.backupsByProject[orphan.id],
  )
  // Only native apps have pb_data to restore into.
  const targets = projects.filter(p => (p.projectType || 'native') !== 'external')
  const [targetId, setTargetId] = useState('')
  const target = targets.find(p => p.id === targetId) || targets[0]
  const busy = useAppSelector(
    s => (target ? s.agentAppSettings.backupBusy[target.id] : false) || false,
  )
  const restoreResult = useAppSelector(s =>
    target ? s.agentAppSettings.backupRestoreResult[target.id] : undefined,
  )

  const toggle = () => {
    const next = !expanded
    setExpanded(next)
    if (next && backups === undefined)
      send('agent_app_backups_list', { projectId: orphan.id })
  }

  const handleRestore = (filename: string, ts: number) => {
    if (!target) return
    confirm({
      title: t('settings:agentApp.restoreIntoTitle'),
      message: t('settings:agentApp.restoreIntoMessage', { date: fmtWhen(ts), name: orphan.name, target: target.name }),
      confirmText: t('common:actions.restore'),
      variant: 'danger',
    }, () => {
      dispatch(setBackupBusy({ projectId: target.id, busy: true }))
      send('agent_app_backup_restore', {
        projectId: target.id,
        filename,
        sourceProjectId: orphan.id,
      })
    })
  }

  const handleDeleteEntry = (filename: string, ts: number) => {
    confirm({
      title: t('settings:agentApp.deleteBackupTitle'),
      message: t('settings:agentApp.orphanDeleteBackupMessage', { date: fmtWhen(ts), name: orphan.name }),
      confirmText: t('common:actions.delete'),
      variant: 'danger',
    }, () => {
      send('agent_app_backup_delete', { projectId: orphan.id, filename })
    })
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--bg-tertiary)',
        border: '1px solid var(--border-primary)',
        borderRadius: 'var(--radius-md)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-3)',
          padding: 'var(--space-2) var(--space-3)',
          cursor: 'pointer',
        }}
        onClick={toggle}
      >
        <ChevronRight
          size={14}
          style={{
            color: 'var(--text-muted)',
            flexShrink: 0,
            transform: expanded ? 'rotate(90deg)' : 'none',
            transition: 'transform 0.15s',
          }}
        />
        <Archive size={14} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
        <span
          style={{
            flex: 1,
            fontSize: 'var(--text-sm)',
            color: 'var(--text-primary)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={orphan.id}
        >
          {orphan.name}
          {orphan.name !== orphan.id && (
            <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}>
              {' '}· {orphan.id}
            </span>
          )}
        </span>
        <Button
          size="sm"
          variant="ghost"
          icon={<Trash2 size={14} />}
          onClick={e => {
            e.stopPropagation()
            onDeleteAll(orphan)
          }}
          title={t('settings:agentApp.deleteBackupsButton')}
        />
      </div>

      {expanded && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            borderTop: '1px solid var(--border-primary)',
            padding: 'var(--space-1) var(--space-3) var(--space-2)',
            maxHeight: 220,
            overflowY: 'auto',
          }}
        >
          {targets.length > 1 && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--space-2)',
                padding: 'var(--space-2) 0',
                fontSize: 'var(--text-xs)',
                color: 'var(--text-muted)',
              }}
            >
              {t('settings:agentApp.restoreInto')}
              <select
                value={target?.id || ''}
                onChange={e => setTargetId(e.target.value)}
                style={{
                  background: 'var(--bg-primary)',
                  color: 'var(--text-primary)',
                  border: '1px solid var(--border-primary)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '2px 6px',
                  fontSize: 'var(--text-xs)',
                }}
              >
                {targets.map(p => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <RestoreStatusLine
            busy={busy}
            targetName={target?.name}
            result={restoreResult}
          />
          {backups === undefined && (
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', padding: 'var(--space-2) 0' }}>
              {t('settings:agentApp.loadingEllipsis')}
            </span>
          )}
          {backups !== undefined && backups.length === 0 && (
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', padding: 'var(--space-2) 0' }}>
              {t('settings:agentApp.noArchives')}
            </span>
          )}
          {(backups || []).map(b => (
            <div
              key={b.filename}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--space-2)',
                padding: 'var(--space-1) 0',
              }}
            >
              <span
                style={{
                  flex: 1,
                  fontSize: 'var(--text-xs)',
                  color: 'var(--text-secondary)',
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
                disabled={busy || !target}
                title={
                  target
                    ? t('settings:agentApp.restoreBackupInto', { name: target.name })
                    : t('settings:agentApp.noAppToRestore')
                }
              />
              <Button
                size="sm"
                variant="ghost"
                icon={<Trash2 size={13} />}
                onClick={() => handleDeleteEntry(b.filename, b.ts)}
                disabled={busy}
                title={t('settings:agentApp.deleteThisBackup')}
              />
            </div>
          ))}
        </div>
      )}
      <ConfirmModal {...confirmModalProps} />
    </div>
  )
}

interface BackupsSectionProps {
  project: AgentAppProject
  onToggleSetting: (setting: string, value: boolean | string | number) => void
  send: (type: string, data?: Record<string, unknown>) => void
}

function BackupsSection({ project, onToggleSetting, send }: BackupsSectionProps) {
  const { t } = useTranslation(['settings', 'common'])
  const dispatch = useAppDispatch()
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()
  const backups = useAppSelector(
    s => s.agentAppSettings.backupsByProject[project.id],
  )
  const busy = useAppSelector(
    s => s.agentAppSettings.backupBusy[project.id] || false,
  )
  const restoreResult = useAppSelector(
    s => s.agentAppSettings.backupRestoreResult[project.id],
  )
  // busy is shared with "Back up now" — only flag restores as such.
  const [restoring, setRestoring] = useState(false)
  useEffect(() => {
    if (!busy) setRestoring(false)
  }, [busy])
  const status = project.backupStatus || {}

  // Fetch the archive list when the section first shows (card expanded).
  useEffect(() => {
    if (backups === undefined)
      send('agent_app_backups_list', { projectId: project.id })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id, send])

  const handleBackupNow = () => {
    dispatch(setBackupBusy({ projectId: project.id, busy: true }))
    send('agent_app_backup_now', { projectId: project.id })
  }

  const handleRestore = (filename: string, ts: number) => {
    // Reversible by design (FR9): the backend captures the current state
    // first and aborts if that fails — hence a plain consequence modal,
    // not a typed confirmation.
    confirm({
      title: t('settings:agentApp.restoreBackupTitle'),
      message: t('settings:agentApp.restoreBackupMessage', { name: project.name, date: fmtWhen(ts) }),
      confirmText: t('common:actions.restore'),
      variant: 'danger',
    }, () => {
      setRestoring(true)
      dispatch(setBackupBusy({ projectId: project.id, busy: true }))
      send('agent_app_backup_restore', { projectId: project.id, filename })
    })
  }

  const handleDeleteEntry = (filename: string, ts: number) => {
    confirm({
      title: t('settings:agentApp.deleteBackupTitle'),
      message: t('settings:agentApp.deleteBackupMessage', { date: fmtWhen(ts) }),
      confirmText: t('common:actions.delete'),
      variant: 'danger',
    }, () => {
      send('agent_app_backup_delete', { projectId: project.id, filename })
    })
  }

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
            {t('settings:agentApp.scheduledBackupsDesc')}
          </span>
        </div>
        <input
          type="checkbox"
          className={styles.toggle}
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
              type="number"
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
          disabled={busy}
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
                disabled={busy}
                title={t('settings:agentApp.restoreThisBackup')}
              />
              <Button
                size="sm"
                variant="ghost"
                icon={<Trash2 size={13} />}
                onClick={() => handleDeleteEntry(b.filename, b.ts)}
                disabled={busy}
                title={t('settings:agentApp.deleteThisBackup')}
              />
            </div>
          ))}
        </div>
      )}

      <ConfirmModal {...confirmModalProps} />
    </div>
  )
}


// ── Share Section ──────────────────────────────────────────────

interface ShareSectionProps {
  projectId: string
  port: number | null
  send: (type: string, data?: Record<string, unknown>) => void
  onMessage: (type: string, handler: (data: unknown) => void) => () => void
}

function ShareSection({ projectId, send, onMessage }: ShareSectionProps) {
  const { t } = useTranslation(['settings', 'common'])
  const [lanUrl, setLanUrl] = useState<string | null>(null)
  const [tunnelUrl, setTunnelUrl] = useState<string | null>(null)
  const [tunnelLoading, setTunnelLoading] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)

  useEffect(() => {
    send('agent_app_sharing_info', { projectId })

    const unsub1 = onMessage('agent_app_sharing_info', (data: any) => {
      if (data.projectId === projectId) {
        setLanUrl(data.lanUrl)
        setTunnelUrl(data.tunnelUrl)
      }
    })
    const unsub2 = onMessage('agent_app_tunnel_status', (data: any) => {
      if (data.projectId === projectId) {
        setTunnelUrl(data.tunnelUrl)
        setTunnelLoading(false)
      }
    })
    return () => { unsub1(); unsub2() }
  }, [projectId, send, onMessage])

  const handleCopy = (url: string, label: string) => {
    navigator.clipboard.writeText(url)
    setCopied(label)
    setTimeout(() => setCopied(null), 2000)
  }

  const handleStartTunnel = () => {
    setTunnelLoading(true)
    send('agent_app_tunnel_start', { projectId, provider: 'cloudflared' })
  }

  const handleStopTunnel = () => {
    send('agent_app_tunnel_stop', { projectId })
    setTunnelUrl(null)
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-2)',
      }}
    >
      {/* LAN URL */}
      {lanUrl && (
        <div className={styles.modelRow}>
          <span className={styles.modelLabel}>{t('settings:agentApp.lan')}</span>
          <code
            className={styles.modelValue}
            style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          >
            {lanUrl}
          </code>
          <Button
            size="sm"
            variant="ghost"
            icon={copied === 'lan' ? <Check size={14} /> : <Copy size={14} />}
            onClick={() => handleCopy(lanUrl, 'lan')}
          />
        </div>
      )}

      {/* Tunnel URL */}
      {tunnelUrl ? (
        <div className={styles.modelRow}>
          <span className={styles.modelLabel}>{t('settings:agentApp.public')}</span>
          <code
            className={styles.modelValue}
            style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          >
            {tunnelUrl}
          </code>
          <Button
            size="sm"
            variant="ghost"
            icon={copied === 'tunnel' ? <Check size={14} /> : <Copy size={14} />}
            onClick={() => handleCopy(tunnelUrl, 'tunnel')}
          />
          <Button
            size="sm"
            variant="ghost"
            icon={<Square size={14} />}
            onClick={handleStopTunnel}
          />
        </div>
      ) : (
        <div className={styles.modelRow}>
          <span className={styles.modelLabel}>{t('settings:agentApp.public')}</span>
          <span style={{ flex: 1, fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
            {t('settings:agentApp.notShared')}
          </span>
          <Button
            size="sm"
            variant="secondary"
            onClick={handleStartTunnel}
            disabled={tunnelLoading}
            icon={tunnelLoading ? <Loader2 size={14} className={styles.spinning} /> : undefined}
          >
            {tunnelLoading ? t('settings:agentApp.starting') : t('settings:agentApp.createTunnel')}
          </Button>
        </div>
      )}
    </div>
  )
}
