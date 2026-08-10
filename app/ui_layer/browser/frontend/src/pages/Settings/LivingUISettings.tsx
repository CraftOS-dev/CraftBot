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
} from 'lucide-react'
import { Button, ConfirmModal } from '../../components/ui'
import { useConfirmModal } from '../../hooks'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  updateProjectSetting,
  type LivingUISettingsProject as LivingUIProject,
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
      message: `Are you sure you want to delete "${project.name}"? This will remove all project files and cannot be undone.`,
      confirmText: 'Delete',
      variant: 'danger',
    }, () => {
      setActionInProgress(project.id)
      send('living_ui_delete', { projectId: project.id })
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
                  // Optimistic so the toggle flips immediately; the refetch
                  // triggered by the response reconciles authoritative state.
                  dispatch(updateProjectSetting({
                    projectId: project.id,
                    setting: setting as 'autoLaunch' | 'logCleanup',
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
  onToggleSetting: (setting: string, value: boolean) => void
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
