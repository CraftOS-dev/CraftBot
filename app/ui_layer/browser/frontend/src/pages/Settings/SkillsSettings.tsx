import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Loader2,
  Plus,
  Trash2,
  RotateCcw,
  X,
  Wrench,
  Play,
} from 'lucide-react'
import { Button, Badge, ConfirmModal } from '../../components/ui'
import { useToast } from '../../contexts/ToastContext'
import { useConfirmModal } from '../../hooks'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  setEnabled as setSkillEnabled,
  removeSkill,
  type SkillConfig,
} from '../../store/slices/skillsSettingsSlice'
import {
  selectSkills,
  selectTotalSkills,
  selectEnabledSkills,
  selectSkillsHasLoaded,
} from '../../store/selectors/skillsSettings'

interface SkillInfo extends SkillConfig {
  argument_hint?: string
  allowed_tools?: string[]
  instructions?: string
}

export function SkillsSettings() {
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const { showToast } = useToast()
  const navigate = useNavigate()
  const dispatch = useAppDispatch()

  // Slice-backed
  const skills = useAppSelector(selectSkills)
  const totalSkills = useAppSelector(selectTotalSkills)
  const enabledSkills = useAppSelector(selectEnabledSkills)
  const hasLoaded = useAppSelector(selectSkillsHasLoaded)
  const isLoading = !hasLoaded

  // Search
  const [searchQuery, setSearchQuery] = useState('')

  // Install modal state
  const [showInstallModal, setShowInstallModal] = useState(false)
  const [installSource, setInstallSource] = useState('')
  const [isInstalling, setIsInstalling] = useState(false)
  const [installError, setInstallError] = useState('')

  // Create modal state
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newSkillName, setNewSkillName] = useState('')
  const [newSkillDesc, setNewSkillDesc] = useState('')
  const [newSkillContent, setNewSkillContent] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const [createError, setCreateError] = useState('')

  // Info modal state
  const [viewingSkill, setViewingSkill] = useState<SkillInfo | null>(null)

  // Reload state
  const [isReloading, setIsReloading] = useState(false)

  // Confirm modal
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  // Load data when connected
  useEffect(() => {
    if (!isConnected) return

    const cleanups = [
      // skill_list is handled by skillsSettingsSlice via the registry. We
      // only listen for the error toast here.
      onMessage('skill_list', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        if (!d.success && d.error) showToast('error', d.error)
      }),
      onMessage('skill_enable', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        if (!d.success) {
          showToast('error', d.error || 'Failed to enable skill')
        }
      }),
      onMessage('skill_disable', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        if (!d.success) {
          showToast('error', d.error || 'Failed to disable skill')
        }
      }),
      onMessage('skill_install', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        setIsInstalling(false)
        if (d.success) {
          showToast('success', d.message || 'Skill installed')
          setShowInstallModal(false)
          setInstallSource('')
          setInstallError('')
        } else {
          setInstallError(d.error || 'Failed to install skill')
        }
      }),
      onMessage('skill_create', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        setIsCreating(false)
        if (d.success) {
          showToast('success', d.message || 'Skill created')
          setShowCreateModal(false)
          setNewSkillName('')
          setNewSkillDesc('')
          setNewSkillContent('')
          setCreateError('')
        } else {
          setCreateError(d.error || 'Failed to create skill')
        }
      }),
      onMessage('skill_template', (data: unknown) => {
        const d = data as { success: boolean; template?: string; error?: string }
        if (d.success && d.template) {
          setNewSkillContent(d.template)
        }
      }),
      onMessage('skill_remove', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        if (d.success) {
          showToast('success', d.message || 'Skill removed')
        } else {
          showToast('error', d.error || 'Failed to remove skill')
        }
      }),
      onMessage('skill_reload', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        setIsReloading(false)
        if (d.success) {
          showToast('success', d.message || 'Skills reloaded')
        } else {
          showToast('error', d.error || 'Failed to reload skills')
        }
      }),
      onMessage('skill_info', (data: unknown) => {
        const d = data as { success: boolean; skill?: SkillInfo; error?: string }
        if (d.success && d.skill) {
          setViewingSkill(d.skill)
        } else {
          showToast('error', d.error || 'Failed to get skill info')
        }
      }),
      onMessage('skill_run', (data: unknown) => {
        const d = data as { success: boolean; name?: string; error?: string }
        if (!d.success) {
          showToast('error', d.error || 'Failed to run skill')
        }
      }),
    ]

    if (!hasLoaded) send('skill_list')

    return () => cleanups.forEach(c => c())
  }, [isConnected, send, onMessage, hasLoaded, showToast])

  // Handlers
  const handleToggleSkill = (name: string, enabled: boolean) => {
    if (enabled) {
      send('skill_enable', { name })
    } else {
      send('skill_disable', { name })
    }
    dispatch(setSkillEnabled({ name, enabled }))
  }

  const handleRemoveSkill = (name: string) => {
    confirm({
      title: 'Remove Skill',
      message: `Remove skill "${name}"? This will delete it from the skills folder.`,
      confirmText: 'Remove',
      variant: 'danger',
    }, () => {
      send('skill_remove', { name })
      dispatch(removeSkill(name))
    })
  }

  const handleViewSkill = (name: string) => {
    send('skill_info', { name })
  }

  const handleRunSkill = (name: string) => {
    send('skill_run', { name })
    setViewingSkill(null)
    navigate('/chat')
  }

  const handleInstallSkill = () => {
    const source = installSource.trim()
    if (!source) {
      setInstallError('Please enter a path or git URL')
      return
    }
    setInstallError('')
    setIsInstalling(true)
    send('skill_install', { source })
  }

  const handleCreateSkill = () => {
    if (!newSkillName.trim()) {
      setCreateError('Please enter a skill name')
      return
    }
    setCreateError('')
    setIsCreating(true)
    send('skill_create', {
      name: newSkillName.trim(),
      description: newSkillDesc.trim(),
      content: newSkillContent
    })
  }

  const handleOpenCreateModal = () => {
    setShowCreateModal(true)
    setNewSkillName('')
    setNewSkillDesc('')
    setNewSkillContent('')
    setCreateError('')
    send('skill_template', { name: 'my-skill', description: '' })
  }

  const handleReloadSkills = () => {
    setIsReloading(true)
    send('skill_reload')
  }

  const sortedSkills = skills
    .filter(skill => {
      if (!searchQuery) return true
      return skill.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        skill.description.toLowerCase().includes(searchQuery.toLowerCase())
    })
    .sort((a, b) => a.name.localeCompare(b.name))

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionTitleRow}>
          <h3>Skills</h3>
          <Badge variant={enabledSkills > 0 ? 'success' : 'default'}>
            {enabledSkills}/{totalSkills}
          </Badge>
        </div>
        <p>Manage agent skills and capabilities</p>
      </div>

      {/* Toolbar */}
      <div className={styles.skillsToolbar}>
        <div className={styles.skillsSearch}>
          <input
            type="text"
            placeholder="Search skills..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className={styles.searchInput}
          />
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={handleReloadSkills}
          disabled={isReloading}
          icon={isReloading ? <Loader2 size={14} className={styles.spinning} /> : <RotateCcw size={14} />}
        >
          Reload
        </Button>
      </div>

      {/* Skills List */}
      {isLoading ? (
        <div className={styles.loadingState}>
          <Loader2 size={20} className={styles.spinning} />
          <span>Loading skills...</span>
        </div>
      ) : sortedSkills.length === 0 ? (
        <div className={styles.emptyState}>
          {searchQuery ? (
            <p>No skills match your search.</p>
          ) : (
            <>
              <p>No skills discovered.</p>
              <p className={styles.emptyHint}>Install skills from a local path or git repository.</p>
            </>
          )}
        </div>
      ) : (
        <div className={styles.skillsList}>
          {sortedSkills.map(skill => (
            <div
              key={skill.name}
              className={`${styles.skillItem} ${!skill.enabled ? styles.skillItemDisabled : ''}`}
            >
              <div className={styles.skillItemMain}>
                <div className={styles.skillItemHeader}>
                  <span className={styles.skillItemName}>{skill.name}</span>
                  <Badge variant={skill.enabled ? 'success' : 'default'}>
                    {skill.enabled ? 'Enabled' : 'Disabled'}
                  </Badge>
                  {skill.user_invocable && (
                    <Badge variant="info">/{skill.name}</Badge>
                  )}
                </div>
                <p className={styles.skillItemDesc}>{skill.description || 'No description'}</p>
                {skill.action_sets && skill.action_sets.length > 0 && (
                  <div className={styles.skillItemMeta}>
                    <span className={styles.metaLabel}>Actions:</span>
                    {skill.action_sets.slice(0, 3).map(action => (
                      <Badge key={action} variant="default">{action}</Badge>
                    ))}
                    {skill.action_sets.length > 3 && (
                      <span className={styles.metaMore}>+{skill.action_sets.length - 3}</span>
                    )}
                  </div>
                )}
              </div>
              <div className={styles.skillItemActions}>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleViewSkill(skill.name)}
                  icon={<Wrench size={14} />}
                  title="View details"
                />
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleRemoveSkill(skill.name)}
                  icon={<Trash2 size={14} />}
                  title="Remove"
                />
                <input
                  type="checkbox"
                  className={styles.toggle}
                  checked={skill.enabled}
                  onChange={(e) => handleToggleSkill(skill.name, e.target.checked)}
                  title={skill.enabled ? 'Disable' : 'Enable'}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Add Skills Section */}
      <div className={styles.skillsAddSection}>
        <Button
          variant="secondary"
          onClick={() => setShowInstallModal(true)}
          icon={<Plus size={14} />}
        >
          Install Skill
        </Button>
        <Button
          variant="secondary"
          onClick={handleOpenCreateModal}
          icon={<Plus size={14} />}
        >
          Create Skill
        </Button>
        <span className={styles.hint}>Add skills from git or create a new one</span>
      </div>

      {/* Install Skill Modal */}
      {showInstallModal && (
        <div className={styles.modalOverlay} onClick={() => { setShowInstallModal(false); setInstallError('') }}>
          <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Install Skill</h3>
              <button className={styles.modalClose} onClick={() => { setShowInstallModal(false); setInstallError('') }}>
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <p className={styles.hint}>
                Install a skill from a local directory path or a Git repository URL.
              </p>
              <div className={styles.formGroup}>
                <label>Path or Git URL</label>
                <input
                  type="text"
                  value={installSource}
                  onChange={(e) => setInstallSource(e.target.value)}
                  placeholder="./my-skill or https://github.com/user/skill-repo"
                />
                <span className={styles.hint}>
                  Supports local paths and GitHub/GitLab URLs
                </span>
              </div>
              {installError && (
                <div className={styles.errorText}>{installError}</div>
              )}
            </div>
            <div className={styles.modalFooter}>
              <Button variant="secondary" onClick={() => { setShowInstallModal(false); setInstallError('') }}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleInstallSkill}
                disabled={isInstalling || !installSource.trim()}
              >
                {isInstalling ? 'Installing...' : 'Install'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Create Skill Modal */}
      {showCreateModal && (
        <div className={styles.modalOverlay} onClick={() => { setShowCreateModal(false); setCreateError('') }}>
          <div className={`${styles.modalContent} ${styles.createSkillModal}`} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Create New Skill</h3>
              <button className={styles.modalClose} onClick={() => { setShowCreateModal(false); setCreateError('') }}>
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <div className={styles.formGroup}>
                <label>Skill Name</label>
                <input
                  type="text"
                  value={newSkillName}
                  onChange={(e) => {
                    setNewSkillName(e.target.value)
                    if (e.target.value.trim()) {
                      send('skill_template', { name: e.target.value.trim(), description: newSkillDesc })
                    }
                  }}
                  placeholder="my-skill"
                />
                <span className={styles.hint}>
                  Use lowercase letters, numbers, and hyphens
                </span>
              </div>
              <div className={styles.formGroup}>
                <label>SKILL.md Content</label>
                <textarea
                  className={styles.skillContentEditor}
                  value={newSkillContent}
                  onChange={(e) => setNewSkillContent(e.target.value)}
                  placeholder="Loading template..."
                  rows={16}
                />
                <span className={styles.hint}>
                  Edit the SKILL.md content. The frontmatter (between ---) defines metadata.
                </span>
              </div>
              {createError && (
                <div className={styles.errorText}>{createError}</div>
              )}
            </div>
            <div className={styles.modalFooter}>
              <Button variant="secondary" onClick={() => { setShowCreateModal(false); setCreateError('') }}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleCreateSkill}
                disabled={isCreating || !newSkillName.trim()}
              >
                {isCreating ? 'Creating...' : 'Create'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Skill Info Modal */}
      {viewingSkill && (
        <div className={styles.modalOverlay} onClick={() => setViewingSkill(null)}>
          <div className={`${styles.modalContent} ${styles.skillInfoModal}`} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>{viewingSkill.name}</h3>
              <button className={styles.modalClose} onClick={() => setViewingSkill(null)}>
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <div className={styles.skillInfoGrid}>
                <div className={styles.skillInfoRow}>
                  <span className={styles.skillInfoLabel}>Description</span>
                  <span className={styles.skillInfoValue}>{viewingSkill.description || 'No description'}</span>
                </div>
                <div className={styles.skillInfoRow}>
                  <span className={styles.skillInfoLabel}>Status</span>
                  <Badge variant={viewingSkill.enabled ? 'success' : 'default'}>
                    {viewingSkill.enabled ? 'Enabled' : 'Disabled'}
                  </Badge>
                </div>
                <div className={styles.skillInfoRow}>
                  <span className={styles.skillInfoLabel}>User Invocable</span>
                  <span className={styles.skillInfoValue}>
                    {viewingSkill.user_invocable ? `Yes (/${viewingSkill.name})` : 'No'}
                  </span>
                </div>
                {viewingSkill.argument_hint && (
                  <div className={styles.skillInfoRow}>
                    <span className={styles.skillInfoLabel}>Usage</span>
                    <code className={styles.skillInfoCode}>/{viewingSkill.name} {viewingSkill.argument_hint}</code>
                  </div>
                )}
                {viewingSkill.action_sets && viewingSkill.action_sets.length > 0 && (
                  <div className={styles.skillInfoRow}>
                    <span className={styles.skillInfoLabel}>Action Sets</span>
                    <div className={styles.skillInfoBadges}>
                      {viewingSkill.action_sets.map(action => (
                        <Badge key={action} variant="default">{action}</Badge>
                      ))}
                    </div>
                  </div>
                )}
                <div className={styles.skillInfoRow}>
                  <span className={styles.skillInfoLabel}>Source</span>
                  <span className={styles.skillInfoValue} style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}>
                    {viewingSkill.source}
                  </span>
                </div>
              </div>
              {viewingSkill.instructions && (
                <div className={styles.skillInstructions}>
                  <h4>Instructions</h4>
                  <pre className={styles.skillInstructionsContent}>
                    {viewingSkill.instructions.length > 1000
                      ? viewingSkill.instructions.slice(0, 1000) + '...'
                      : viewingSkill.instructions}
                  </pre>
                </div>
              )}
            </div>
            <div className={styles.modalFooter}>
              <Button variant="secondary" onClick={() => setViewingSkill(null)}>
                Close
              </Button>
              {viewingSkill.enabled && (
                <Button
                  variant="primary"
                  onClick={() => handleRunSkill(viewingSkill.name)}
                  icon={<Play size={14} />}
                >
                  Run Skill
                </Button>
              )}
              <Button
                variant={viewingSkill.enabled ? 'danger' : 'primary'}
                onClick={() => {
                  handleToggleSkill(viewingSkill.name, !viewingSkill.enabled)
                  setViewingSkill({ ...viewingSkill, enabled: !viewingSkill.enabled })
                }}
              >
                {viewingSkill.enabled ? 'Disable' : 'Enable'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm Modal */}
      <ConfirmModal {...confirmModalProps} />
    </div>
  )
}
