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
import { Button, ConfirmModal } from '../../components/ui'
import { useConfirmModal } from '../../hooks'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  updateProjectSetting,
  setBackupBusy,
  type LivingUISettingsProject as LivingUIProject,
  type LivingUIBackupOrphan,
} from '../../store/slices/livingUiSettingsSlice'
import {
  selectLivingUiSettingsProjects,
  selectLivingUiSettingsHasLoadedProjects,
} from '../../store/selectors/livingUiSettings'

export function LivingUISettings() {
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const dispatch = useAppDispatch()
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  // Slice-backed: cached across remounts.
  const projects = useAppSelector(selectLivingUiSettingsProjects)
  const hasLoadedProjects = useAppSelector(selectLivingUiSettingsHasLoadedProjects)
  const loading = !hasLoadedProjects

  // Transient UI state.
  const [actionInProgress, setActionInProgress] = useState<string | null>(null)
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(new Set())

  // Fire-once fetch. Slice owns the data; we just trigger the request when
  // not yet loaded.
  useEffect(() => {
    if (!isConnected) return
    if (!hasLoadedProjects) send('living_ui_settings_get')
  }, [isConnected, send, hasLoadedProjects])

  useEffect(() => {
    const handleActionComplete = (data: unknown) => {
      const d = data as { success: boolean }
      setActionInProgress(null)
      if (d.success) send('living_ui_settings_get')
    }
    const cleanups = [
      onMessage('living_ui_launch', handleActionComplete),
      onMessage('living_ui_stop', handleActionComplete),
      onMessage('living_ui_delete', handleActionComplete),
    ]
    return () => cleanups.forEach(c => c())
  }, [send, onMessage])

  useEffect(() => {
    const cleanup = onMessage('living_ui_project_setting_update', (data: unknown) => {
      const d = data as { success: boolean }
      // Refetch to reconcile with authoritative state (response doesn't
      // carry the updated project payload).
      if (d.success) send('living_ui_settings_get')
    })
    return cleanup
  }, [send, onMessage])

  const handleLaunch = (projectId: string) => {
    setActionInProgress(projectId)
    send('living_ui_launch', { projectId })
  }

  const handleStop = (projectId: string) => {
    setActionInProgress(projectId)
    send('living_ui_stop', { projectId })
  }

  const toggleProject = (id: string) => {
    setExpandedProjects(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleDelete = (project: LivingUIProject) => {
    confirm({
      title: 'Delete Living UI',
      message: `Are you sure you want to delete "${project.name}"? This will remove all project files. If the app has any live data, a final backup is saved first and KEPT — leftover backups can be removed below afterwards.`,
      confirmText: 'Delete',
      variant: 'danger',
    }, () => {
      setActionInProgress(project.id)
      send('living_ui_delete', { projectId: project.id })
    })
  }

  const backupOrphans = useAppSelector(s => s.livingUiSettings.backupOrphans)
  const handleDeleteOrphanBackups = (orphan: { id: string; name: string }) => {
    confirm({
      title: 'Delete leftover backups',
      message: `Permanently delete all backup archives of the deleted app "${orphan.name}"? They are the only remaining copy of its data.`,
      confirmText: 'Delete backups',
      variant: 'danger',
    }, () => {
      send('living_ui_backup_delete', { projectId: orphan.id, filename: '', orphan: true })
      send('living_ui_settings_get')
    })
  }

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>Living UI</h3>
        <p>Manage and share your Living UI projects</p>
      </div>

      {/* ── Projects ──────────────────────────────────────── */}
      <div className={styles.subsection}>
        <h4 className={styles.subsectionTitle}>Projects</h4>
        <p className={styles.subsectionDesc}>
          Manage, launch, and share your Living UI projects. Create new ones from the main chat.
        </p>

        {loading ? (
          <div className={styles.loadingState}>
            <Loader2 size={20} className={styles.spinning} />
            <span>Loading projects...</span>
          </div>
        ) : projects.length === 0 ? (
          <div className={styles.emptyState}>
            <p>No Living UI projects yet. Create one from the main chat.</p>
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
                  send('living_ui_project_setting_update', { projectId: project.id, setting, value })
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
          <h4 className={styles.subsectionTitle}>Leftover backups</h4>
          <p className={styles.subsectionDesc}>
            Backup archives of deleted apps. They are kept when an app is deleted; remove them here when you no longer need the data.
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
  project: LivingUIProject
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
      return 'Running'
    case 'creating':
      return 'Creating…'
    case 'launching':
      return 'Launching…'
    case 'error':
      return 'Error'
    default:
      // created, stopped, ready
      return 'Not running'
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
  const canLaunch = ['created', 'stopped', 'ready', 'error'].includes(project.status)
  const isRunning = project.status === 'running'

  const handleExport = () => {
    const link = document.createElement('a')
    link.href = `/api/living-ui/${project.id}/export`
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
      label: 'Auto-launch on startup',
      desc: 'Launch automatically when CraftBot starts',
      value: project.autoLaunch,
    },
    {
      key: 'logCleanup',
      label: 'Clean logs on restart',
      desc: 'Delete old log files when launching',
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
              Stop
            </Button>
          ) : canLaunch ? (
            <Button
              size="sm"
              variant="primary"
              icon={actionInProgress ? <Loader2 size={14} className={styles.spinning} /> : <Play size={14} />}
              onClick={onLaunch}
              disabled={actionInProgress}
            >
              Launch
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="ghost"
            icon={<Download size={14} />}
            onClick={handleExport}
            title="Export project"
          />
          <Button
            size="sm"
            variant="ghost"
            icon={<Trash2 size={14} />}
            onClick={onDelete}
            disabled={actionInProgress}
            title="Delete project"
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
        <span style={infoLabelStyle}>Frontend port</span>
        <span style={infoValueStyle}>{project.port != null ? project.port : '—'}</span>

        <span style={infoLabelStyle}>Backend port</span>
        <span style={infoValueStyle}>{project.backendPort != null ? project.backendPort : '—'}</span>

        <span style={infoLabelStyle}>Project ID</span>
        <span style={infoValueStyle}>{project.id}</span>

        <span style={infoLabelStyle}>Path</span>
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
            title="Copy path"
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
          Preferences
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
            Backups
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
            Share
          </div>
          <ShareSection projectId={project.id} port={project.port} send={send} onMessage={onMessage} />
        </div>
      )}

      </>}
    </div>
  )
}


// ── Backups Section ────────────────────────────────────────────

const INTERVAL_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'hourly', label: 'Every hour' },
  { value: '6h', label: 'Every 6 hours' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
]

const TRIGGER_LABELS: Record<string, string> = {
  scheduled: 'scheduled',
  pre_promote: 'pre-update',
  manual: 'manual',
  pre_delete: 'before delete',
  pre_restore: 'before restore',
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
        Restoring{targetName ? ` into "${targetName}"` : ''}… this can take a
        minute.
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
  return new Date(msEpoch).toLocaleString()
}

// ── Leftover (orphan) backups row ──────────────────────────────
// A deleted app's kept archives: expandable to list them, each restorable
// into a still-existing app (the backend rolls back automatically when the
// data doesn't fit), the whole dir deletable.

interface OrphanBackupsRowProps {
  orphan: LivingUIBackupOrphan
  projects: LivingUIProject[]
  send: (type: string, data?: Record<string, unknown>) => void
  onDeleteAll: (orphan: LivingUIBackupOrphan) => void
}

function OrphanBackupsRow({ orphan, projects, send, onDeleteAll }: OrphanBackupsRowProps) {
  const dispatch = useAppDispatch()
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()
  const [expanded, setExpanded] = useState(false)
  const backups = useAppSelector(
    s => s.livingUiSettings.backupsByProject[orphan.id],
  )
  // Only native apps have pb_data to restore into.
  const targets = projects.filter(p => (p.projectType || 'native') !== 'external')
  const [targetId, setTargetId] = useState('')
  const target = targets.find(p => p.id === targetId) || targets[0]
  const busy = useAppSelector(
    s => (target ? s.livingUiSettings.backupBusy[target.id] : false) || false,
  )
  const restoreResult = useAppSelector(s =>
    target ? s.livingUiSettings.backupRestoreResult[target.id] : undefined,
  )

  const toggle = () => {
    const next = !expanded
    setExpanded(next)
    if (next && backups === undefined)
      send('living_ui_backups_list', { projectId: orphan.id })
  }

  const handleRestore = (filename: string, ts: number) => {
    if (!target) return
    confirm({
      title: 'Restore into app',
      message: `Restore the backup from ${fmtWhen(ts)} of the deleted app "${orphan.name}" into "${target.name}"? The current data of "${target.name}" will be replaced — a backup of that state is saved first, and if the restored data doesn't fit the app it is rolled back automatically.`,
      confirmText: 'Restore',
      variant: 'danger',
    }, () => {
      dispatch(setBackupBusy({ projectId: target.id, busy: true }))
      send('living_ui_backup_restore', {
        projectId: target.id,
        filename,
        sourceProjectId: orphan.id,
      })
    })
  }

  const handleDeleteEntry = (filename: string, ts: number) => {
    confirm({
      title: 'Delete backup',
      message: `Permanently delete the backup from ${fmtWhen(ts)} of the deleted app "${orphan.name}"?`,
      confirmText: 'Delete',
      variant: 'danger',
    }, () => {
      send('living_ui_backup_delete', { projectId: orphan.id, filename })
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
          title="Delete these backups"
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
              Restore into
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
              Loading…
            </span>
          )}
          {backups !== undefined && backups.length === 0 && (
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', padding: 'var(--space-2) 0' }}>
              No archives.
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
                  {' '}· {TRIGGER_LABELS[b.trigger] || b.trigger} · {fmtSize(b.size)}
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
                    ? `Restore this backup into "${target.name}"`
                    : 'No app to restore into'
                }
              />
              <Button
                size="sm"
                variant="ghost"
                icon={<Trash2 size={13} />}
                onClick={() => handleDeleteEntry(b.filename, b.ts)}
                disabled={busy}
                title="Delete this backup"
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
  project: LivingUIProject
  onToggleSetting: (setting: string, value: boolean | string | number) => void
  send: (type: string, data?: Record<string, unknown>) => void
}

function BackupsSection({ project, onToggleSetting, send }: BackupsSectionProps) {
  const dispatch = useAppDispatch()
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()
  const backups = useAppSelector(
    s => s.livingUiSettings.backupsByProject[project.id],
  )
  const busy = useAppSelector(
    s => s.livingUiSettings.backupBusy[project.id] || false,
  )
  const restoreResult = useAppSelector(
    s => s.livingUiSettings.backupRestoreResult[project.id],
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
      send('living_ui_backups_list', { projectId: project.id })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id, send])

  const handleBackupNow = () => {
    dispatch(setBackupBusy({ projectId: project.id, busy: true }))
    send('living_ui_backup_now', { projectId: project.id })
  }

  const handleRestore = (filename: string, ts: number) => {
    // Reversible by design (FR9): the backend captures the current state
    // first and aborts if that fails — hence a plain consequence modal,
    // not a typed confirmation.
    confirm({
      title: 'Restore backup',
      message: `Restore "${project.name}" to its state from ${fmtWhen(ts)}? Data created after that point will be removed — a backup of the current state is taken first, so this can be undone.`,
      confirmText: 'Restore',
      variant: 'danger',
    }, () => {
      setRestoring(true)
      dispatch(setBackupBusy({ projectId: project.id, busy: true }))
      send('living_ui_backup_restore', { projectId: project.id, filename })
    })
  }

  const handleDeleteEntry = (filename: string, ts: number) => {
    confirm({
      title: 'Delete backup',
      message: `Permanently delete the backup from ${fmtWhen(ts)}?`,
      confirmText: 'Delete',
      variant: 'danger',
    }, () => {
      send('living_ui_backup_delete', { projectId: project.id, filename })
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
          <span className={styles.toggleLabel}>Scheduled backups</span>
          <span className={styles.toggleDesc}>
            Back up this app's data and files automatically
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
              <span className={styles.toggleLabel}>Frequency</span>
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
              {INTERVAL_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>

          <div style={{ ...rowStyle, borderTop: '1px solid var(--border-primary)' }}>
            <div className={styles.toggleInfo}>
              <span className={styles.toggleLabel}>Backups to keep</span>
              <span className={styles.toggleDesc}>
                Oldest scheduled backups are removed beyond this count
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
            ? `Last backup failed: ${status.lastError}`
            : status.lastAt
              ? `Last backup ${fmtWhen(status.lastAt * 1000)} · ${status.count || 0} kept · ${fmtSize(status.totalSize || 0)}`
              : 'No backups yet'}
        </span>
        <Button
          size="sm"
          variant="secondary"
          icon={busy ? <Loader2 size={14} className={styles.spinning} /> : <Archive size={14} />}
          onClick={handleBackupNow}
          disabled={busy}
        >
          Back up now
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
                  {' '}· {TRIGGER_LABELS[b.trigger] || b.trigger} · {fmtSize(b.size)}
                </span>
              </span>
              <Button
                size="sm"
                variant="ghost"
                icon={<RotateCcw size={13} />}
                onClick={() => handleRestore(b.filename, b.ts)}
                disabled={busy}
                title="Restore this backup"
              />
              <Button
                size="sm"
                variant="ghost"
                icon={<Trash2 size={13} />}
                onClick={() => handleDeleteEntry(b.filename, b.ts)}
                disabled={busy}
                title="Delete this backup"
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
  const [lanUrl, setLanUrl] = useState<string | null>(null)
  const [tunnelUrl, setTunnelUrl] = useState<string | null>(null)
  const [tunnelLoading, setTunnelLoading] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)

  useEffect(() => {
    send('living_ui_sharing_info', { projectId })

    const unsub1 = onMessage('living_ui_sharing_info', (data: any) => {
      if (data.projectId === projectId) {
        setLanUrl(data.lanUrl)
        setTunnelUrl(data.tunnelUrl)
      }
    })
    const unsub2 = onMessage('living_ui_tunnel_status', (data: any) => {
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
    send('living_ui_tunnel_start', { projectId, provider: 'cloudflared' })
  }

  const handleStopTunnel = () => {
    send('living_ui_tunnel_stop', { projectId })
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
          <span className={styles.modelLabel}>LAN</span>
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
          <span className={styles.modelLabel}>Public</span>
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
          <span className={styles.modelLabel}>Public</span>
          <span style={{ flex: 1, fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
            Not shared
          </span>
          <Button
            size="sm"
            variant="secondary"
            onClick={handleStartTunnel}
            disabled={tunnelLoading}
            icon={tunnelLoading ? <Loader2 size={14} className={styles.spinning} /> : undefined}
          >
            {tunnelLoading ? 'Starting...' : 'Create Tunnel'}
          </Button>
        </div>
      )}
    </div>
  )
}
