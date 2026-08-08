import { useState, useEffect, useRef } from 'react'
import {
  Play,
  Square,
  Trash2,
  Loader2,
  RotateCcw,
  Check,
  X,
  Plus,
  Download,
  Copy,
  ChevronRight,
} from 'lucide-react'
import { Button, Badge, ConfirmModal } from '../../components/ui'
import { useConfirmModal } from '../../hooks'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  setGlobalConfig as setSliceGlobalConfig,
  updateProjectSetting,
  type LivingUISettingsProject as LivingUIProject,
} from '../../store/slices/livingUiSettingsSlice'
import {
  selectLivingUiSettingsProjects,
  selectLivingUiSettingsHasLoadedProjects,
  selectLivingUiGlobalConfig,
  selectLivingUiHasLoadedGlobalConfig,
} from '../../store/selectors/livingUiSettings'

interface ParsedRule {
  enabled: boolean
  text: string
  lineIndex: number
}

interface ParsedPref {
  key: string
  value: string
  lineIndex: number
}

interface ParsedSection {
  title: string
  rules: ParsedRule[]
  prefs: ParsedPref[]
}

const FONT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'System default (Segoe UI, sans-serif)', label: 'System Default' },
  { value: 'Inter, sans-serif', label: 'Inter' },
  { value: 'Roboto, sans-serif', label: 'Roboto' },
  { value: 'Open Sans, sans-serif', label: 'Open Sans' },
  { value: 'Poppins, sans-serif', label: 'Poppins' },
  { value: 'Lato, sans-serif', label: 'Lato' },
  { value: 'Nunito, sans-serif', label: 'Nunito' },
  { value: 'Source Sans Pro, sans-serif', label: 'Source Sans Pro' },
  { value: 'JetBrains Mono, monospace', label: 'JetBrains Mono' },
  { value: 'Fira Code, monospace', label: 'Fira Code' },
]

function parseGlobalConfig(content: string): { sections: ParsedSection[]; rawLines: string[] } {
  const lines = content.split('\n')
  const sections: ParsedSection[] = []
  let currentSection: ParsedSection | null = null

  lines.forEach((line, i) => {
    const sectionMatch = line.match(/^##\s+(.+)/)
    if (sectionMatch) {
      currentSection = { title: sectionMatch[1], rules: [], prefs: [] }
      sections.push(currentSection)
      return
    }
    const ruleMatch = line.match(/^- \[(x| )\]\s+(.+)/)
    if (ruleMatch && currentSection) {
      currentSection.rules.push({ enabled: ruleMatch[1] === 'x', text: ruleMatch[2], lineIndex: i })
      return
    }
    const prefMatch = line.match(/^- \*\*(.+?):\*\*\s*(.*)/)
    if (prefMatch && currentSection) {
      currentSection.prefs.push({ key: prefMatch[1], value: prefMatch[2], lineIndex: i })
    }
  })

  return { sections, rawLines: lines }
}

function rebuildConfig(rawLines: string[], changes: Map<number, string>): string {
  return rawLines.map((line, i) => {
    if (changes.has(i)) {
      const newVal = changes.get(i)!
      if (newVal === 'true' || newVal === 'false') {
        return line.replace(/^- \[(x| )\]/, newVal === 'true' ? '- [x]' : '- [ ]')
      }
      const prefMatch = line.match(/^(- \*\*.+?:\*\*\s*)(.*)/)
      if (prefMatch) return prefMatch[1] + newVal
    }
    return line
  }).join('\n')
}

export function LivingUISettings() {
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const dispatch = useAppDispatch()
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  // Slice-backed: cached across remounts.
  const projects = useAppSelector(selectLivingUiSettingsProjects)
  const hasLoadedProjects = useAppSelector(selectLivingUiSettingsHasLoadedProjects)
  const originalConfig = useAppSelector(selectLivingUiGlobalConfig)
  const hasLoadedGlobalConfig = useAppSelector(selectLivingUiHasLoadedGlobalConfig)
  const loading = !hasLoadedProjects
  const globalLoading = !hasLoadedGlobalConfig

  // Transient UI state.
  const [actionInProgress, setActionInProgress] = useState<string | null>(null)
  const [globalConfig, setLocalGlobalConfig] = useState('')
  const [globalSaving, setGlobalSaving] = useState(false)
  const [globalSaveStatus, setGlobalSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [newRule, setNewRule] = useState('')
  const [rulesExpanded, setRulesExpanded] = useState(true)
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(new Set())
  const [lineChanges, setLineChanges] = useState<Map<number, string>>(new Map())
  const globalConfigRef = useRef(globalConfig)
  globalConfigRef.current = globalConfig

  // Sync local editable copy to the slice's source-of-truth whenever the
  // server-known content changes (initial load or post-restore refetch).
  useEffect(() => {
    setLocalGlobalConfig(originalConfig)
  }, [originalConfig])

  const isGlobalDirty = globalConfig !== originalConfig

  // Fire-once fetches. Slice owns the data; we just trigger requests when
  // not yet loaded.
  useEffect(() => {
    if (!isConnected) return
    if (!hasLoadedProjects) send('living_ui_settings_get')
    if (!hasLoadedGlobalConfig) send('agent_file_read', { filename: 'GLOBAL_LIVING_UI.md' })
  }, [isConnected, send, hasLoadedProjects, hasLoadedGlobalConfig])

  // Side-effect handlers — toasts, success animations, modal close, action
  // completion. List/config state itself flows through the slice registry.
  useEffect(() => {
    const cleanups = [
      onMessage('agent_file_write', (data: unknown) => {
        const d = data as { filename: string; success: boolean }
        if (d.filename === 'GLOBAL_LIVING_UI.md') {
          setGlobalSaving(false)
          if (d.success) {
            // Persist the just-saved content as the new server-known baseline
            // so isDirty flips back to false.
            dispatch(setSliceGlobalConfig(globalConfigRef.current))
            setGlobalSaveStatus('success')
            setTimeout(() => setGlobalSaveStatus('idle'), 2000)
          } else {
            setGlobalSaveStatus('error')
            setTimeout(() => setGlobalSaveStatus('idle'), 3000)
          }
        }
      }),
      onMessage('agent_file_restore', (data: unknown) => {
        const d = data as { filename: string; content: string; success: boolean }
        if (d.filename === 'GLOBAL_LIVING_UI.md' && d.success) {
          // Slice handler already updated originalConfig; clear local edits.
          setLineChanges(new Map())
        }
      }),
    ]
    return () => cleanups.forEach(c => c())
  }, [onMessage, dispatch])

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

  const handleToggleRule = (lineIndex: number, enabled: boolean) => {
    const newChanges = new Map<number, string>(lineChanges)
    newChanges.set(lineIndex, String(enabled))
    setLineChanges(newChanges)
    setLocalGlobalConfig(rebuildConfig(parseGlobalConfig(originalConfig).rawLines, newChanges))
  }

  const handlePrefChange = (lineIndex: number, value: string) => {
    const newChanges = new Map<number, string>(lineChanges)
    newChanges.set(lineIndex, value)
    setLineChanges(newChanges)
    setLocalGlobalConfig(rebuildConfig(parseGlobalConfig(originalConfig).rawLines, newChanges))
  }

  const handleAddRule = () => {
    if (!newRule.trim()) return
    setLocalGlobalConfig(prev => prev.trimEnd() + '\n- [x] ' + newRule.trim() + '\n')
    setNewRule('')
  }


  const handleDeleteRule = (lineIndex: number) => {
    const lines = globalConfig.split('\n')
    lines.splice(lineIndex, 1)
    setLocalGlobalConfig(lines.join('\n'))
  }

  const handleSaveGlobal = () => {
    setGlobalSaving(true)
    send('agent_file_write', { filename: 'GLOBAL_LIVING_UI.md', content: globalConfig })
  }

  const handleRestoreGlobal = () => {
    confirm({
      title: 'Restore Defaults',
      message: 'Reset global Living UI configuration to defaults? Your custom rules and changes will be lost.',
      confirmText: 'Restore',
      variant: 'danger',
    }, () => {
      send('agent_file_restore', { filename: 'GLOBAL_LIVING_UI.md' })
    })
  }

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

  const { sections } = parseGlobalConfig(globalConfig)

  // Collect design prefs (colors/fonts) across all sections
  const designPrefs: ParsedPref[] = sections.flatMap(s =>
    s.prefs.filter(p => {
      const k = p.key.toLowerCase()
      return k.includes('color') || k.includes('font')
    })
  )

  const ruleSections = sections.filter(s => s.rules.length > 0)
  const totalRules = ruleSections.reduce((acc, s) => acc + s.rules.length, 0)
  const activeRules = ruleSections.reduce(
    (acc, s) =>
      acc +
      s.rules.filter(r =>
        lineChanges.has(r.lineIndex) ? lineChanges.get(r.lineIndex) === 'true' : r.enabled
      ).length,
    0
  )

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>Living UI</h3>
        <p>Global design, rules, and project management</p>
      </div>

      {/* ── Design ────────────────────────────────────────── */}
      <div className={styles.subsection}>
        <h4 className={styles.subsectionTitle}>Design</h4>
        <p className={styles.subsectionDesc}>
          Colors and typography applied globally to every Living UI
        </p>

        {globalLoading ? (
          <div className={styles.loadingState}>
            <Loader2 size={20} className={styles.spinning} />
            <span>Loading design...</span>
          </div>
        ) : designPrefs.length === 0 ? (
          <div className={styles.emptyState}>
            <p>No design preferences found in GLOBAL_LIVING_UI.md</p>
          </div>
        ) : (
          <div className={styles.settingsForm}>
            {designPrefs.map(pref => {
              const val = lineChanges.has(pref.lineIndex)
                ? lineChanges.get(pref.lineIndex)!
                : pref.value
              const key = pref.key.toLowerCase()
              const isColor = key.includes('color')
              const isFont = key.includes('font')

              return (
                <div key={pref.lineIndex} className={styles.formGroup}>
                  <label>{pref.key}</label>
                  {isColor ? (
                    <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
                      <label
                        className={styles.colorSwatch}
                        style={{ background: val.startsWith('#') ? val : '#000000' }}
                      >
                        <input
                          type="color"
                          value={val.startsWith('#') ? val : '#000000'}
                          onChange={e => handlePrefChange(pref.lineIndex, e.target.value)}
                        />
                      </label>
                      <input
                        type="text"
                        value={val}
                        onChange={e => handlePrefChange(pref.lineIndex, e.target.value)}
                        style={{ flex: 1 }}
                      />
                    </div>
                  ) : isFont ? (
                    <select value={val} onChange={e => handlePrefChange(pref.lineIndex, e.target.value)}>
                      {FONT_OPTIONS.map(opt => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={val}
                      onChange={e => handlePrefChange(pref.lineIndex, e.target.value)}
                    />
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* ── Rules ─────────────────────────────────────────── */}
      <div className={styles.subsection}>
        <h4 className={styles.subsectionTitle}>Rules</h4>
        <p className={styles.subsectionDesc}>
          Toggle global behavior rules or add your own custom rules
        </p>

        {globalLoading ? (
          <div className={styles.loadingState}>
            <Loader2 size={20} className={styles.spinning} />
            <span>Loading rules...</span>
          </div>
        ) : (
          <div className={styles.fileEditorCard}>
            <div
              className={styles.fileEditorHeader}
              onClick={() => setRulesExpanded(v => !v)}
              role="button"
              tabIndex={0}
              onKeyDown={e => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  setRulesExpanded(v => !v)
                }
              }}
              aria-expanded={rulesExpanded}
              style={{
                cursor: 'pointer',
                borderBottom: rulesExpanded ? '1px solid var(--border-primary)' : 'none',
                userSelect: 'none',
              }}
            >
              <div className={styles.fileEditorTitle}>
                <h4>Rules</h4>
                <Badge variant="default">
                  {activeRules}/{totalRules} active
                </Badge>
                <ChevronRight
                  size={14}
                  className={`${styles.advancedChevron} ${rulesExpanded ? styles.open : ''}`}
                  style={{ marginLeft: 'auto' }}
                />
              </div>
              <p className={styles.fileEditorDescription}>
                Toggle behavior rules applied globally to every Living UI, or add your own custom rules.
              </p>
            </div>

            {rulesExpanded && (
              <>
                <div
                  style={{
                    background: 'var(--bg-primary)',
                    maxHeight: '500px',
                    overflowY: 'auto',
                  }}
                >
                  {ruleSections.length === 0 ? (
                    <div
                      style={{
                        padding: 'var(--space-4)',
                        textAlign: 'center',
                        color: 'var(--text-muted)',
                        fontSize: 'var(--text-sm)',
                      }}
                    >
                      No rules defined yet. Add one below.
                    </div>
                  ) : (
                    ruleSections.map((section, sIdx) => {
                      const isCustom = section.title === 'Custom Rules'
                      return (
                        <div key={section.title}>
                          <div
                            style={{
                              padding: 'var(--space-2) var(--space-3)',
                              background: 'var(--bg-secondary)',
                              borderTop: sIdx > 0 ? '1px solid var(--border-primary)' : 'none',
                              borderBottom: '1px solid var(--border-primary)',
                              fontSize: 'var(--text-xs)',
                              fontWeight: 'var(--font-semibold)',
                              color: 'var(--text-secondary)',
                              textTransform: 'uppercase',
                              letterSpacing: '0.05em',
                            }}
                          >
                            {section.title}
                          </div>
                          {section.rules.map((rule, idx) => {
                            const checked = lineChanges.has(rule.lineIndex)
                              ? lineChanges.get(rule.lineIndex) === 'true'
                              : rule.enabled
                            return (
                              <div
                                key={rule.lineIndex}
                                style={{
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: 'var(--space-3)',
                                  padding: 'var(--space-3)',
                                  borderTop: idx > 0 ? '1px solid var(--border-primary)' : 'none',
                                }}
                              >
                                <span
                                  style={{
                                    flex: 1,
                                    fontSize: 'var(--text-sm)',
                                    color: 'var(--text-primary)',
                                    lineHeight: 1.4,
                                  }}
                                >
                                  {rule.text}
                                </span>
                                <div
                                  style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 'var(--space-1)',
                                    flexShrink: 0,
                                  }}
                                >
                                  {isCustom ? (
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      icon={<Trash2 size={14} />}
                                      onClick={() => handleDeleteRule(rule.lineIndex)}
                                    />
                                  ) : (
                                    <input
                                      type="checkbox"
                                      className={styles.toggle}
                                      checked={checked}
                                      onChange={e => handleToggleRule(rule.lineIndex, e.target.checked)}
                                    />
                                  )}
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      )
                    })
                  )}
                </div>

                <div className={styles.fileEditorActions}>
                  <input
                    type="text"
                    className={styles.searchInput}
                    value={newRule}
                    onChange={e => setNewRule(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleAddRule()}
                    placeholder="Add a custom rule..."
                    style={{ flex: 1 }}
                  />
                  <Button
                    size="sm"
                    variant="primary"
                    icon={<Plus size={14} />}
                    onClick={handleAddRule}
                    disabled={!newRule.trim()}
                  >
                    Add
                  </Button>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* ── Save / Restore ────────────────────────────────── */}
      <div className={styles.sectionFooter} style={{ borderTop: 'none', paddingTop: 0 }}>
        <Button
          variant="secondary"
          icon={<RotateCcw size={14} />}
          onClick={handleRestoreGlobal}
          disabled={globalLoading || globalSaving}
        >
          Restore Defaults
        </Button>
        <Button
          variant="primary"
          onClick={handleSaveGlobal}
          disabled={!isGlobalDirty || globalSaving || globalLoading}
          icon={globalSaving ? <Loader2 size={14} className={styles.spinning} /> : undefined}
        >
          {globalSaving ? 'Saving...' : 'Save Changes'}
        </Button>
        {globalSaveStatus === 'success' && (
          <span className={styles.statusSuccess}>
            <Check size={14} /> Saved
          </span>
        )}
        {globalSaveStatus === 'error' && (
          <span className={styles.statusError}>
            <X size={14} /> Save failed
          </span>
        )}
        {isGlobalDirty && globalSaveStatus === 'idle' && !globalSaving && (
          <span className={styles.statusWarning}>Unsaved changes</span>
        )}
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
