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
import { useTranslation } from 'react-i18next'
import { Button, Badge, ConfirmModal } from '../../components/ui'
import { useToast } from '../../contexts/ToastContext'
import { useConfirmModal } from '../../hooks'
import { formatNumber, localeCompare } from '../../i18n/format'
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
  const { t } = useTranslation(['settings', 'common'])
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
          showToast('error', d.error || t('settings:skills.toast.enableFailed'))
        }
      }),
      onMessage('skill_disable', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        if (!d.success) {
          showToast('error', d.error || t('settings:skills.toast.disableFailed'))
        }
      }),
      onMessage('skill_install', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        setIsInstalling(false)
        if (d.success) {
          showToast('success', d.message || t('settings:skills.toast.installed'))
          setShowInstallModal(false)
          setInstallSource('')
          setInstallError('')
        } else {
          setInstallError(d.error || t('settings:skills.toast.installFailed'))
        }
      }),
      onMessage('skill_create', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        setIsCreating(false)
        if (d.success) {
          showToast('success', d.message || t('settings:skills.toast.created'))
          setShowCreateModal(false)
          setNewSkillName('')
          setNewSkillDesc('')
          setNewSkillContent('')
          setCreateError('')
        } else {
          setCreateError(d.error || t('settings:skills.toast.createFailed'))
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
          showToast('success', d.message || t('settings:skills.toast.removed'))
        } else {
          showToast('error', d.error || t('settings:skills.toast.removeFailed'))
        }
      }),
      onMessage('skill_reload', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        setIsReloading(false)
        if (d.success) {
          showToast('success', d.message || t('settings:skills.toast.reloaded'))
        } else {
          showToast('error', d.error || t('settings:skills.toast.reloadFailed'))
        }
      }),
      onMessage('skill_info', (data: unknown) => {
        const d = data as { success: boolean; skill?: SkillInfo; error?: string }
        if (d.success && d.skill) {
          setViewingSkill(d.skill)
        } else {
          showToast('error', d.error || t('settings:skills.toast.infoFailed'))
        }
      }),
      onMessage('skill_run', (data: unknown) => {
        const d = data as { success: boolean; name?: string; error?: string }
        if (!d.success) {
          showToast('error', d.error || t('settings:skills.toast.runFailed'))
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
      title: t('settings:skills.removeConfirmTitle'),
      message: t('settings:skills.removeConfirmMessage', { name }),
      confirmText: t('common:actions.remove'),
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
      setInstallError(t('settings:skills.installValidation'))
      return
    }
    setInstallError('')
    setIsInstalling(true)
    send('skill_install', { source })
  }

  const handleCreateSkill = () => {
    if (!newSkillName.trim()) {
      setCreateError(t('settings:skills.createValidation'))
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
    .sort((a, b) => localeCompare(a.name, b.name))

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionTitleRow}>
          <h3>{t('settings:skills.title')}</h3>
          <Badge variant={enabledSkills > 0 ? 'success' : 'default'}>
            {formatNumber(enabledSkills)}/{formatNumber(totalSkills)}
          </Badge>
        </div>
        <p>{t('settings:skills.subtitle')}</p>
      </div>

      {/* Toolbar */}
      <div className={styles.skillsToolbar}>
        <div className={styles.skillsSearch}>
          <input
            type="text"
            placeholder={t('settings:skills.search')}
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
          {t('settings:skills.reload')}
        </Button>
      </div>

      {/* Skills List */}
      {isLoading ? (
        <div className={styles.loadingState}>
          <Loader2 size={20} className={styles.spinning} />
          <span>{t('settings:skills.loading')}</span>
        </div>
      ) : sortedSkills.length === 0 ? (
        <div className={styles.emptyState}>
          {searchQuery ? (
            <p>{t('settings:skills.noMatch')}</p>
          ) : (
            <>
              <p>{t('settings:skills.noneDiscovered')}</p>
              <p className={styles.emptyHint}>{t('settings:skills.installHint')}</p>
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
                    {skill.enabled ? t('common:status.enabled') : t('common:status.disabled')}
                  </Badge>
                  {skill.user_invocable && (
                    <Badge variant="info">/{skill.name}</Badge>
                  )}
                </div>
                <p className={styles.skillItemDesc}>{skill.description || t('settings:skills.noDescription')}</p>
                {skill.action_sets && skill.action_sets.length > 0 && (
                  <div className={styles.skillItemMeta}>
                    <span className={styles.metaLabel}>{t('settings:skills.actionsLabel')}</span>
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
                  title={t('settings:skills.viewDetails')}
                />
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleRemoveSkill(skill.name)}
                  icon={<Trash2 size={14} />}
                  title={t('settings:skills.remove')}
                />
                <input
                  type="checkbox"
                  className={styles.toggle}
                  checked={skill.enabled}
                  onChange={(e) => handleToggleSkill(skill.name, e.target.checked)}
                  title={skill.enabled ? t('common:actions.disable') : t('common:actions.enable')}
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
          {t('settings:skills.installSkill')}
        </Button>
        <Button
          variant="secondary"
          onClick={handleOpenCreateModal}
          icon={<Plus size={14} />}
        >
          {t('settings:skills.createSkill')}
        </Button>
        <span className={styles.hint}>{t('settings:skills.addHint')}</span>
      </div>

      {/* Install Skill Modal */}
      {showInstallModal && (
        <div className={styles.modalOverlay} onClick={() => { setShowInstallModal(false); setInstallError('') }}>
          <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>{t('settings:skills.install.title')}</h3>
              <button className={styles.modalClose} onClick={() => { setShowInstallModal(false); setInstallError('') }}>
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <p className={styles.hint}>
                {t('settings:skills.install.desc')}
              </p>
              <div className={styles.formGroup}>
                <label>{t('settings:skills.install.label')}</label>
                <input
                  type="text"
                  value={installSource}
                  onChange={(e) => setInstallSource(e.target.value)}
                  placeholder={t('settings:skills.install.placeholder')}
                />
                <span className={styles.hint}>
                  {t('settings:skills.install.hint')}
                </span>
              </div>
              {installError && (
                <div className={styles.errorText}>{installError}</div>
              )}
            </div>
            <div className={styles.modalFooter}>
              <Button variant="secondary" onClick={() => { setShowInstallModal(false); setInstallError('') }}>
                {t('common:actions.cancel')}
              </Button>
              <Button
                variant="primary"
                onClick={handleInstallSkill}
                disabled={isInstalling || !installSource.trim()}
              >
                {isInstalling ? t('common:status.installing') : t('common:actions.install')}
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
              <h3>{t('settings:skills.create.title')}</h3>
              <button className={styles.modalClose} onClick={() => { setShowCreateModal(false); setCreateError('') }}>
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <div className={styles.formGroup}>
                <label>{t('settings:skills.create.name')}</label>
                <input
                  type="text"
                  value={newSkillName}
                  onChange={(e) => {
                    setNewSkillName(e.target.value)
                    if (e.target.value.trim()) {
                      send('skill_template', { name: e.target.value.trim(), description: newSkillDesc })
                    }
                  }}
                  placeholder={t('settings:skills.create.namePlaceholder')}
                />
                <span className={styles.hint}>
                  {t('settings:skills.create.nameHint')}
                </span>
              </div>
              <div className={styles.formGroup}>
                <label>{t('settings:skills.create.content')}</label>
                <textarea
                  className={styles.skillContentEditor}
                  value={newSkillContent}
                  onChange={(e) => setNewSkillContent(e.target.value)}
                  placeholder={t('settings:skills.create.contentPlaceholder')}
                  rows={16}
                />
                <span className={styles.hint}>
                  {t('settings:skills.create.contentHint')}
                </span>
              </div>
              {createError && (
                <div className={styles.errorText}>{createError}</div>
              )}
            </div>
            <div className={styles.modalFooter}>
              <Button variant="secondary" onClick={() => { setShowCreateModal(false); setCreateError('') }}>
                {t('common:actions.cancel')}
              </Button>
              <Button
                variant="primary"
                onClick={handleCreateSkill}
                disabled={isCreating || !newSkillName.trim()}
              >
                {isCreating ? t('settings:skills.create.creating') : t('common:actions.create')}
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
                  <span className={styles.skillInfoLabel}>{t('settings:skills.info.description')}</span>
                  <span className={styles.skillInfoValue}>{viewingSkill.description || t('settings:skills.noDescription')}</span>
                </div>
                <div className={styles.skillInfoRow}>
                  <span className={styles.skillInfoLabel}>{t('settings:skills.info.status')}</span>
                  <Badge variant={viewingSkill.enabled ? 'success' : 'default'}>
                    {viewingSkill.enabled ? t('common:status.enabled') : t('common:status.disabled')}
                  </Badge>
                </div>
                <div className={styles.skillInfoRow}>
                  <span className={styles.skillInfoLabel}>{t('settings:skills.info.userInvocable')}</span>
                  <span className={styles.skillInfoValue}>
                    {viewingSkill.user_invocable ? t('settings:skills.info.userInvocableYes', { name: viewingSkill.name }) : t('settings:skills.info.userInvocableNo')}
                  </span>
                </div>
                {viewingSkill.argument_hint && (
                  <div className={styles.skillInfoRow}>
                    <span className={styles.skillInfoLabel}>{t('settings:skills.info.usage')}</span>
                    <code className={styles.skillInfoCode}>/{viewingSkill.name} {viewingSkill.argument_hint}</code>
                  </div>
                )}
                {viewingSkill.action_sets && viewingSkill.action_sets.length > 0 && (
                  <div className={styles.skillInfoRow}>
                    <span className={styles.skillInfoLabel}>{t('settings:skills.info.actionSets')}</span>
                    <div className={styles.skillInfoBadges}>
                      {viewingSkill.action_sets.map(action => (
                        <Badge key={action} variant="default">{action}</Badge>
                      ))}
                    </div>
                  </div>
                )}
                <div className={styles.skillInfoRow}>
                  <span className={styles.skillInfoLabel}>{t('settings:skills.info.source')}</span>
                  <span className={styles.skillInfoValue} style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}>
                    {viewingSkill.source}
                  </span>
                </div>
              </div>
              {viewingSkill.instructions && (
                <div className={styles.skillInstructions}>
                  <h4>{t('settings:skills.info.instructions')}</h4>
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
                {t('common:actions.close')}
              </Button>
              {viewingSkill.enabled && (
                <Button
                  variant="primary"
                  onClick={() => handleRunSkill(viewingSkill.name)}
                  icon={<Play size={14} />}
                >
                  {t('settings:skills.info.runSkill')}
                </Button>
              )}
              <Button
                variant={viewingSkill.enabled ? 'danger' : 'primary'}
                onClick={() => {
                  handleToggleSkill(viewingSkill.name, !viewingSkill.enabled)
                  setViewingSkill({ ...viewingSkill, enabled: !viewingSkill.enabled })
                }}
              >
                {viewingSkill.enabled ? t('common:actions.disable') : t('common:actions.enable')}
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
