import i18n from '../../i18n/config'
import { BackupControls, SharingControls, fmtWhen, fmtSize, triggerLabel, RestoreStatusLine } from './AgentAppSettingsControls'
import { useState, useEffect } from 'react'
import {
  Play,
  Square,
  Trash2,
  Loader2,
  Download,
  ChevronRight,
  Archive,
  RotateCcw,
  MessageSquareText,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Badge, Button, ConfirmModal, type BadgeVariant } from '../../components/ui'
import { newTriggerConsentRequestId, sendTriggerConsent } from '../../features/agentApps/triggerConsent'
import { useConfirmModal, usePersistedSet, usePersistedState } from '../../hooks'
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
import { UI_STATE } from '../../store/uiState'
import { RESOURCES, useResource } from '../../store/resources'
import { FrameworkSettingsCards } from '../../features/agentApps/FrameworkSettingsCards'
import { AppSettingsCard, AppSettingsInfo, AppSettingsSection, AppSettingsToggle, appSectionLabelStyle } from './AgentAppSettingsCard'

export function AgentAppSettings() {
  const { t } = useTranslation(['settings', 'common'])
  const { send, onMessage } = useSettingsWebSocket()
  const dispatch = useAppDispatch()
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  // Slice-backed: cached across remounts.
  const projects = useAppSelector(selectAgentAppSettingsProjects)
  const registry = useAppSelector(state => state.agentApp.framework)
  const hasLoadedProjects = useAppSelector(selectAgentAppSettingsHasLoadedProjects)
  const loading = !hasLoadedProjects

  // Transient UI state.
  const [actionInProgress, setActionInProgress] = useState<string | null>(null)
  // Which project cards are open: a persisted preference.
  const [expandedProjects, , toggleProject] = usePersistedSet(UI_STATE.settings.agentAppExpandedProjects)

  // The slice caches the list; ResourceSync fetches it when unloaded or stale
  // and refetches whenever any tab, the agent or a status event changes apps.
  useResource(RESOURCES.agentAppSettings)

  // Clear the card spinner when the action this view started finishes.
  useEffect(() => {
    const clearInProgress = () => setActionInProgress(null)
    const cleanups = [
      onMessage('agent_app_launch', clearInProgress),
      onMessage('agent_app_stop', clearInProgress),
      onMessage('agent_app_delete', clearInProgress),
    ]
    return () => cleanups.forEach(c => c())
  }, [onMessage])

  const handleLaunch = (projectId: string) => {
    setActionInProgress(projectId)
    send('agent_app_launch', { projectId })
  }

  const handleStop = (projectId: string) => {
    setActionInProgress(projectId)
    send('agent_app_stop', { projectId })
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

        {loading && (
          <div className={styles.loadingState}>
            <Loader2 size={20} className={styles.spinning} />
            <span>{t('settings:agentApp.loadingProjects')}</span>
          </div>
        )}
        {!loading && projects.length === 0 && registry.status === 'success' && registry.apps.length === 0 && registry.connected.length === 0 && (
          <div className={styles.emptyState}>
            <p>{t('settings:agentApp.noProjects')}</p>
          </div>
        )}
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
            <FrameworkSettingsCards />
          </div>
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

  const sectionLabelStyle = appSectionLabelStyle
  return (
    <AppSettingsCard
      name={project.name} status={getStatusText(project.status)} statusColor={getStatusColor(project.status)}
      active={isActiveStatus(project.status)} expanded={expanded} onToggle={onToggleExpand}
      actions={<>
        {isRunning ? <Button size="sm" variant="danger"
          icon={actionInProgress ? <Loader2 size={14} className={styles.spinning} /> : <Square size={14} />}
          onClick={onStop} disabled={actionInProgress}>{t('settings:agentApp.stop')}</Button>
          : canLaunch ? <Button size="sm" variant="primary"
            icon={actionInProgress ? <Loader2 size={14} className={styles.spinning} /> : <Play size={14} />}
            onClick={onLaunch} disabled={actionInProgress}>{t('settings:agentApp.launch')}</Button> : null}
        <Button size="sm" variant="ghost" icon={<Download size={14} />} onClick={handleExport} title={t('settings:agentApp.exportProject')} />
        <Button size="sm" variant="ghost" icon={<Trash2 size={14} />} onClick={onDelete} disabled={actionInProgress} title={t('settings:agentApp.deleteProject')} />
      </>}
    >
      {expanded && <>
      <AppSettingsInfo path={project.path} rows={[
        { label: t('settings:agentApp.frontendPort'), value: project.port ?? '—' },
        { label: t('settings:agentApp.backendPort'), value: project.backendPort ?? '—' },
        { label: t('settings:agentApp.projectId'), value: project.id },
      ]} />
      <AppSettingsSection title={t('settings:agentApp.preferences')}>
        {settings.map((setting, index) => <AppSettingsToggle key={setting.key}
          label={setting.label} description={setting.desc} checked={setting.value} divider={index > 0}
          onChange={value => onToggleSetting(setting.key, value)} />)}
      </AppSettingsSection>

      {/* Zone 3a — Requests the app may send to CraftBot */}
      <RequestsSection
        projectId={project.id}
        labelStyle={sectionLabelStyle}
        onMessage={onMessage}
      />

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
          <ShareSection projectId={project.id} send={send} onMessage={onMessage} />
        </div>
      )}

      </>}
    </AppSettingsCard>
  )
}


// ── Requests Section ───────────────────────────────────────────

const REQUEST_BADGE: Record<'new' | 'changed' | 'approved', BadgeVariant> = {
  new: 'info',
  changed: 'warning',
  approved: 'success',
}

/** Allow or stop an app's requests at any time after the first review. Reads
 *  the consent snapshot the app catalog keeps live for every client. */
function RequestsSection({
  projectId,
  labelStyle,
  onMessage,
}: {
  projectId: string
  labelStyle: React.CSSProperties
  onMessage: (type: string, handler: (data: unknown) => void) => () => void
}) {
  const { t } = useTranslation('agentapp')
  const consent = useAppSelector(s => s.agentApp.projects.find(p => p.id === projectId)?.triggerConsent)
  const connected = useAppSelector(s => s.connection.connected)
  const [pending, setPending] = useState<{ requestId: string; allow: boolean } | null>(null)
  const [error, setError] = useState<string | null>(null)
  // The switch is the setting; the list is reference, shown on request.
  const [listOpen, setListOpen] = useState(false)

  useEffect(() => {
    if (!pending) return
    return onMessage('agent_app_trigger_consent', raw => {
      const data = raw as { requestId?: string; error?: string | null }
      if (data.requestId !== pending.requestId) return
      setPending(null)
      setError(data.error || null)
    })
  }, [pending, onMessage])

  // A reply can't arrive over a dropped connection; free the switch.
  useEffect(() => {
    if (!connected) setPending(null)
  }, [connected])

  if (!consent || (consent.triggers.length === 0 && !consent.error)) return null
  const allowed = !consent.required && consent.triggers.length > 0
  // Only an update leaves some requests allowed and others not; those that
  // still need a choice are listed first.
  const showChange = consent.required && consent.triggers.some(trigger => trigger.change === 'approved')
  const ordered = showChange
    ? [...consent.triggers.filter(trigger => trigger.change !== 'approved'), ...consent.triggers.filter(trigger => trigger.change === 'approved')]
    : consent.triggers
  const disabled = !!pending || !connected || (!allowed && !!consent.error)

  const choose = (allow: boolean) => {
    const requestId = newTriggerConsentRequestId()
    setError(null)
    setPending({ requestId, allow })
    sendTriggerConsent(projectId, consent.revision, allow, requestId)
  }

  return (
    <div
      style={{
        padding: 'var(--space-3)',
        borderTop: '1px solid var(--border-primary)',
      }}
    >
      <div style={{ ...labelStyle, marginBottom: 'var(--space-2)' }}>
        {t('triggerConsent.settingsTitle')}
      </div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 'var(--space-3)',
          padding: 'var(--space-2) 0',
        }}
      >
        <div className={styles.toggleInfo}>
          <span className={styles.toggleLabel}>{t('triggerConsent.settingsLabel')}</span>
          {consent.triggers.length > 0 && (
            <button
              type="button"
              className={styles.requestsLink}
              aria-expanded={listOpen}
              onClick={() => setListOpen(open => !open)}
            >
              {listOpen ? t('triggerConsent.hideRequests') : t('triggerConsent.viewRequests', { count: consent.triggers.length })}
            </button>
          )}
        </div>
        <input
          type="checkbox"
          className={styles.toggle}
          aria-label={t('triggerConsent.settingsLabel')}
          checked={pending ? pending.allow : allowed}
          disabled={disabled}
          style={disabled ? { opacity: 0.5, cursor: 'not-allowed' } : undefined}
          onChange={e => choose(e.target.checked)}
        />
      </div>
      {listOpen && (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {ordered.map(trigger => (
            <li
              key={trigger.name}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 'var(--space-3)',
                padding: 'var(--space-2) 0',
                borderTop: '1px solid var(--border-primary)',
              }}
            >
              <MessageSquareText size={14} style={{ flexShrink: 0, marginTop: 3, color: 'var(--text-secondary)' }} aria-hidden />
              <span
                style={{
                  flex: 1,
                  minWidth: 0,
                  fontSize: 'var(--text-sm)',
                  lineHeight: 1.5,
                  color: 'var(--text-primary)',
                  overflowWrap: 'anywhere',
                }}
              >
                {trigger.description || trigger.name}
              </span>
              {showChange && (
                <Badge variant={REQUEST_BADGE[trigger.change]}>{t(`triggerConsent.${trigger.change}`)}</Badge>
              )}
            </li>
          ))}
        </ul>
      )}
      {(error || consent.error) && (
        <p role="alert" style={{ margin: 'var(--space-2) 0 0', fontSize: 'var(--text-sm)', color: 'var(--color-error)' }}>
          {error || consent.error}
        </p>
      )}
    </div>
  )
}


// ── Backups Section ────────────────────────────────────────────

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
  const [expanded, setExpanded] = usePersistedState(UI_STATE.settings.agentAppOrphanBackupsExpanded(orphan.id))
  const backups = useAppSelector(
    s => s.agentAppSettings.backupsByProject[orphan.id],
  )
  // A row remembered as expanded still needs its archive list on mount.
  useEffect(() => {
    if (expanded && backups === undefined) send('agent_app_backups_list', { projectId: orphan.id })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
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

  return <>
    <BackupControls project={project} backups={backups} busy={busy} restoring={restoring} status={status} restoreResult={restoreResult}
      onToggleSetting={onToggleSetting} handleBackupNow={handleBackupNow} handleRestore={handleRestore} handleDeleteEntry={handleDeleteEntry} />
    <ConfirmModal {...confirmModalProps} />
  </>
}

// ── Share Section ──────────────────────────────────────────────

interface ShareSectionProps {
  projectId: string
  send: (type: string, data?: Record<string, unknown>) => void
  onMessage: (type: string, handler: (data: unknown) => void) => () => void
}

type ShareChannel = 'lan' | 'tunnel'

interface SharingInfo {
  projectId: string
  links: Partial<Record<ShareChannel, string | null>>
  error: { channel: ShareChannel; message: string } | null
}

function ShareSection({ projectId, send, onMessage }: ShareSectionProps) {
  const [links, setLinks] = useState<SharingInfo['links']>({})
  const [error, setError] = useState<SharingInfo['error']>(null)
  const [pending, setPending] = useState<ShareChannel | null>(null)
  const [copied, setCopied] = useState<ShareChannel | null>(null)

  useEffect(() => {
    send('agent_app_sharing_info', { projectId })
    return onMessage('agent_app_sharing_info', (raw: unknown) => {
      const data = raw as SharingInfo
      if (data.projectId !== projectId) return
      setLinks(data.links ?? {})
      setError(data.error ?? null)
      setPending(null)
    })
  }, [projectId, send, onMessage])

  const handleCopy = (url: string, channel: ShareChannel) => {
    navigator.clipboard.writeText(url)
    setCopied(channel)
    setTimeout(() => setCopied(null), 2000)
  }

  const handleOpen = (channel: ShareChannel) => {
    setPending(channel)
    setError(null)
    send('agent_app_share_open', { projectId, channel })
  }

  const handleClose = (channel: ShareChannel) => {
    send('agent_app_share_close', { projectId, channel })
  }

  return <SharingControls links={links} error={error} pending={pending} copied={copied} handleCopy={handleCopy} handleOpen={handleOpen} handleClose={handleClose} />
}
