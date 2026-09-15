import { useState, useEffect, useRef, type ComponentProps } from 'react'
import {
  ChevronRight,
  RotateCcw,
  FileText,
  AlertTriangle,
  Check,
  X,
  Loader2,
  Download,
  RefreshCw,
  Upload,
  Trash2,
  Package,
  PackageOpen,
  Compass,
  Save,
} from 'lucide-react'
import {
  Button,
  Badge,
  ConfirmModal,
  ResetModal,
  ImportProfileModal,
  type ImportMode,
  type ProfileBundleManifest,
  type ProfileBundlePreview,
} from '../../components/ui'
import { useTranslation, Trans } from 'react-i18next'
import { useTheme } from '../../contexts/ThemeContext'
import {
  selectAgentProfilePictureHasCustom,
  selectAgentProfilePictureUrl,
} from '../../store/selectors/agent'
import { useTour } from '../../tour'
import { useConfirmModal, usePersistedState, useServerDraft } from '../../hooks'
import i18n, { setUiLanguage } from '../../i18n/config'
import { SUPPORTED_LANGUAGES, resolveSupportedLanguage } from '../../i18n/languages'
import { formatList } from '../../i18n/format'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import { RemoteChangeHint } from './RemoteChangeHint'
import type { RootState } from '../../store'
import { useAppSelector, useAppDispatch } from '../../store/hooks'
import { resetUpdateCheck } from '../../store/slices/generalSettingsSlice'
import { UI_STATE, type ThemePreference } from '../../store/uiState'
import { RESOURCES, useResource } from '../../store/resources'
import {
  selectGeneralSettingsValues,
  selectUserMd,
  selectAgentMd,
  selectSoulMd,
  selectHasLoadedUserMd,
  selectHasLoadedAgentMd,
  selectHasLoadedSoulMd,
  selectUpdateChecked,
  selectUpdateAvailable,
  selectLatestVersion,
  selectUpdateBranch,
} from '../../store/selectors/generalSettings'
import { selectVersion } from '../../store/selectors/connection'

// Get initial agent name from localStorage or default
function getInitialAgentName(): string {
  return localStorage.getItem('craftbot-agent-name') || 'CraftBot'
}

// Get initial UI language from the already-resolved i18n instance
function getInitialLanguage(): string {
  return i18n.language || 'en'
}

type ConfirmFn = ReturnType<typeof useConfirmModal>['confirm']

export function GeneralSettings() {
  const { t } = useTranslation(['settings', 'common'])
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const agentProfilePictureUrl = useAppSelector(selectAgentProfilePictureUrl)
  const agentProfilePictureHasCustom = useAppSelector(selectAgentProfilePictureHasCustom)
  const { startTour } = useTour()
  const version = useAppSelector(selectVersion)
  const dispatch = useAppDispatch()
  // The theme is owned by ThemeContext (persisted UI state). This form edits a
  // draft of the preference and applies it on Save.
  const { preference: themePreference, setTheme: setThemePreference } = useTheme()

  // Saved name + language, cached in generalSettingsSlice and kept fresh by
  // ResourceSync. The form fields are drafts over them: untouched fields
  // follow changes made elsewhere (another tab, the TopBar theme toggle);
  // edited ones keep the edit and show a "changed elsewhere" hint.
  const savedSettings = useAppSelector(selectGeneralSettingsValues)
  useResource(RESOURCES.generalSettings)
  // Server value is authoritative; normalize to a supported UI language.
  const savedLanguage = savedSettings?.language
    ? resolveSupportedLanguage(savedSettings.language) ?? 'en'
    : null
  const agentNameDraft = useServerDraft(savedSettings?.agentName || getInitialAgentName())
  const themeDraft = useServerDraft<string>(themePreference)
  const languageDraft = useServerDraft(savedLanguage ?? getInitialLanguage())
  const { reset: settleAgentName } = agentNameDraft
  const [isResetting, setIsResetting] = useState(false)
  const [resetStatus, setResetStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [showResetModal, setShowResetModal] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')
  // Set while this tab's settings_update is in flight; only its reply
  // settles the drafts and shows the result.
  const savingSettingsRef = useRef(false)

  // Agent profile picture
  const [profilePictureUrl, setProfilePictureUrl] = useState<string>(agentProfilePictureUrl)
  const [hasCustomPicture, setHasCustomPicture] = useState<boolean>(agentProfilePictureHasCustom)
  const [pictureError, setPictureError] = useState<string | null>(null)
  const [isUploadingPicture, setIsUploadingPicture] = useState(false)
  const pictureInputRef = useRef<HTMLInputElement | null>(null)

  // Agent profile bundle (import/export)
  const [isExportingProfile, setIsExportingProfile] = useState(false)
  const [profileStatus, setProfileStatus] = useState<
    { type: 'success' | 'error' | 'info'; message: string } | null
  >(null)
  const [showImportModal, setShowImportModal] = useState(false)
  const [importBundleToken, setImportBundleToken] = useState<string | null>(null)
  const [importManifest, setImportManifest] = useState<ProfileBundleManifest | null>(null)
  const [importPreview, setImportPreview] = useState<ProfileBundlePreview | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const [isApplyingImport, setIsApplyingImport] = useState(false)
  const profileImportInputRef = useRef<HTMLInputElement | null>(null)

  // Keep local preview in sync with the central context value (e.g. after reconnect)
  useEffect(() => {
    setProfilePictureUrl(agentProfilePictureUrl)
  }, [agentProfilePictureUrl])
  useEffect(() => {
    setHasCustomPicture(agentProfilePictureHasCustom)
  }, [agentProfilePictureHasCustom])

  const [showAdvanced, setShowAdvanced] = usePersistedState(UI_STATE.settings.generalShowAdvanced)

  // Update state: result is cached in slice; in-progress flow is local.
  const updateAvailable = useAppSelector(selectUpdateAvailable)
  const latestVersion = useAppSelector(selectLatestVersion)
  // Non-empty only when this checkout is off the main update channel.
  const updateBranch = useAppSelector(selectUpdateBranch)
  // Same tag, new commits on main — showing two identical versions reads as a
  // bug, so the copy talks about the channel instead.
  const isSameVersionUpdate = updateAvailable && latestVersion === version
  const updateCheckDone = useAppSelector(selectUpdateChecked)
  const isCheckingUpdate = !updateCheckDone
  const [isUpdating, setIsUpdating] = useState(false)
  const [updateMessages, setUpdateMessages] = useState<string[]>([])

  // Confirm modal
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  const isGeneralSettingsDirty = agentNameDraft.isDirty || themeDraft.isDirty || languageDraft.isDirty
  const generalRemoteChanged =
    agentNameDraft.remoteChanged || themeDraft.remoteChanged || languageDraft.remoteChanged
  const { reset: settleLanguage } = languageDraft

  // The saved language drives the UI language.
  useEffect(() => {
    if (savedLanguage) setUiLanguage(savedLanguage)
  }, [savedLanguage])

  // Results of this view's own requests.
  useEffect(() => {
    const cleanups = [
      onMessage('agent_profile_picture_upload', (data: unknown) => {
        const d = data as { success: boolean; url?: string; has_custom?: boolean; error?: string }
        setIsUploadingPicture(false)
        if (d.success && d.url) {
          setProfilePictureUrl(d.url)
          setHasCustomPicture(d.has_custom ?? true)
          setPictureError(null)
        } else {
          setPictureError(d.error || t('common:status.uploadFailed'))
        }
      }),
      onMessage('agent_profile_picture_remove', (data: unknown) => {
        const d = data as { success: boolean; url?: string; has_custom?: boolean; error?: string }
        if (d.success) {
          setProfilePictureUrl(d.url || '/api/agent-profile-picture')
          setHasCustomPicture(d.has_custom ?? false)
          setPictureError(null)
        } else {
          setPictureError(d.error || t('common:status.removeFailed'))
        }
      }),
      onMessage('settings_update', (data: unknown) => {
        if (!savingSettingsRef.current) return
        savingSettingsRef.current = false
        const d = data as { success: boolean }
        setIsSaving(false)
        if (d.success) {
          settleAgentName()
          settleLanguage()
        }
        setSaveStatus(d.success ? 'success' : 'error')
        setTimeout(() => setSaveStatus('idle'), 3000)
      }),
      onMessage('reset', (data: unknown) => {
        const d = data as { success: boolean }
        setIsResetting(false)
        setResetStatus(d.success ? 'success' : 'error')
        setTimeout(() => setResetStatus('idle'), 3000)
      }),
      // update_check_result is handled by generalSettingsSlice via the registry.
      onMessage('update_progress', (data: unknown) => {
        const d = data as { message: string }
        setUpdateMessages(prev => [...prev, d.message])
      }),
    ]

    return () => {
      cleanups.forEach(cleanup => cleanup())
    }
  }, [onMessage, settleAgentName, settleLanguage])

  // Auto-check for updates (only on first mount of this session)
  useEffect(() => {
    if (isConnected && !updateCheckDone) send('check_update')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isConnected, send])

  const handleSaveSettings = () => {
    setIsSaving(true)
    const agentName = agentNameDraft.value
    const theme = themeDraft.value
    const language = languageDraft.value

    // Persist agent name to localStorage
    localStorage.setItem('craftbot-agent-name', agentName)

    // ThemeContext applies (and resolves 'system') and persists the choice.
    setThemePreference(theme as ThemePreference)
    themeDraft.reset()

    // Language is applied live on selection; persist the choice on save.
    setUiLanguage(language)

    // Send to backend; its reply settles the name and language drafts.
    savingSettingsRef.current = true
    send('settings_update', { settings: { agentName, theme, language } })
  }

  const loadLatestGeneralSettings = () => {
    agentNameDraft.acceptRemote()
    themeDraft.acceptRemote()
    languageDraft.acceptRemote()
  }

  const handlePictureSelect = () => {
    pictureInputRef.current?.click()
  }

  const handlePictureChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''  // allow re-selecting the same file later
    if (!file) return

    setPictureError(null)
    setIsUploadingPicture(true)

    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      // Strip data URL prefix → raw base64
      const base64 = result.includes(',') ? result.split(',', 2)[1] : result
      send('agent_profile_picture_upload', {
        name: file.name,
        mimeType: file.type || 'application/octet-stream',
        content: base64,
      })
    }
    reader.onerror = () => {
      setIsUploadingPicture(false)
      setPictureError(t('common:status.couldNotReadFile'))
    }
    reader.readAsDataURL(file)
  }

  const handlePictureRemove = () => {
    setPictureError(null)
    send('agent_profile_picture_remove')
  }

  const handleReset = () => {
    setShowResetModal(true)
  }

  const handleResetConfirm = (components: string[]) => {
    setShowResetModal(false)
    if (components.length === 0) return
    setIsResetting(true)
    send('reset', { components })
  }

  const handleCheckUpdate = () => {
    dispatch(resetUpdateCheck())
    setUpdateMessages([])
    send('check_update')
  }

  const handleDoUpdate = () => {
    confirm({
      title: t('settings:general.update.confirmTitle'),
      message: latestVersion === version
        ? t('settings:general.update.confirmMessageMain')
        : t('settings:general.update.confirmMessage', { version: latestVersion }),
      confirmText: t('settings:general.update.confirmButton'),
      variant: 'danger',
    }, () => {
      setIsUpdating(true)
      setUpdateMessages([])
      send('do_update')
    })
  }

  // ─── Agent profile bundle ───────────────────────────────────────────

  const handleExportProfile = async () => {
    setIsExportingProfile(true)
    setProfileStatus(null)
    try {
      const response = await fetch('/api/profile/export')
      if (!response.ok) {
        const body = await response.json().catch(() => ({}))
        throw new Error(body.error || t('settings:general.profile.exportFailedStatus', { status: response.status }))
      }
      const blob = await response.blob()
      const disposition = response.headers.get('Content-Disposition') || ''
      const match = /filename="([^"]+)"/.exec(disposition)
      const filename = match ? match[1] : 'agent-profile.craftbot'

      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)

      setProfileStatus({ type: 'success', message: t('settings:general.profile.exported') })
    } catch (err) {
      const msg = err instanceof Error ? err.message : t('settings:general.profile.exportFailed')
      setProfileStatus({ type: 'error', message: msg })
    } finally {
      setIsExportingProfile(false)
      setTimeout(() => setProfileStatus(null), 4000)
    }
  }

  const handleImportProfileClick = () => {
    profileImportInputRef.current?.click()
  }

  const handleProfileFileSelected = async (
    e: React.ChangeEvent<HTMLInputElement>
  ) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return

    setProfileStatus(null)
    setImportManifest(null)
    setImportPreview(null)
    setImportError(null)
    setImportBundleToken(null)
    setShowImportModal(true)

    try {
      const form = new FormData()
      form.append('file', file)
      const response = await fetch('/api/profile/inspect', {
        method: 'POST',
        body: form,
      })
      const data = await response.json()
      if (!response.ok || !data.success) {
        throw new Error(data.error || t('settings:general.profile.couldNotReadBundle'))
      }
      setImportManifest(data.manifest)
      setImportPreview(data.preview)
      setImportBundleToken(data.bundle_token)
    } catch (err) {
      const msg = err instanceof Error ? err.message : t('settings:general.profile.couldNotReadBundle')
      setImportError(msg)
    }
  }

  const handleImportCancel = () => {
    setShowImportModal(false)
    setImportManifest(null)
    setImportPreview(null)
    setImportError(null)
    setImportBundleToken(null)
  }

  const handleImportApply = async (mode: ImportMode) => {
    if (!importBundleToken) return
    setIsApplyingImport(true)
    setImportError(null)
    try {
      const response = await fetch('/api/profile/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bundle_token: importBundleToken, mode }),
      })
      const data = await response.json()
      if (!response.ok || !data.success) {
        throw new Error(data.error || t('settings:general.profile.importFailed'))
      }

      const summary = data.summary || {}
      const parts: string[] = []
      if (summary.skills_added?.length) {
        parts.push(t('settings:general.profile.skillCount', { count: summary.skills_added.length }))
      }
      if (summary.mcp_added?.length) {
        parts.push(t('settings:general.profile.mcpCount', { count: summary.mcp_added.length }))
      }
      const agentAppCount =
        (summary.agent_app_added?.length || 0) + (summary.agent_app_renamed?.length || 0)
      if (agentAppCount) {
        parts.push(t('settings:general.profile.agentAppCount', { count: agentAppCount }))
      }
      const what = parts.length > 0 ? formatList(parts) : t('settings:general.profile.profileWord')

      setProfileStatus({
        type: 'success',
        message:
          mode === 'overwrite'
            ? t('settings:general.profile.importedOverwrite', { what })
            : t('settings:general.profile.importedMerge', { what }),
      })
      setShowImportModal(false)
      setImportManifest(null)
      setImportPreview(null)
      setImportBundleToken(null)
    } catch (err) {
      const msg = err instanceof Error ? err.message : t('settings:general.profile.importFailed')
      setImportError(msg)
    } finally {
      setIsApplyingImport(false)
    }
  }

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>{t('settings:general.title')}</h3>
        <p>{t('settings:general.subtitle')}</p>
      </div>

      <div className={styles.settingsForm}>
        <div className={styles.formGroup}>
          <label>{t('settings:general.avatar.label')}</label>
          <div className={styles.profilePictureRow}>
            <img
              src={profilePictureUrl}
              alt={t('settings:general.avatar.alt')}
              className={styles.profilePreview}
            />
            <div className={styles.profilePictureActions}>
              <input
                ref={pictureInputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                onChange={handlePictureChange}
                style={{ display: 'none' }}
              />
              <Button
                variant="secondary"
                onClick={handlePictureSelect}
                disabled={isUploadingPicture}
                icon={
                  isUploadingPicture ? (
                    <Loader2 size={14} className={styles.spinning} />
                  ) : (
                    <Upload size={14} />
                  )
                }
              >
                {isUploadingPicture ? t('common:status.uploading') : t('common:actions.upload')}
              </Button>
              {hasCustomPicture && (
                <Button
                  variant="secondary"
                  onClick={handlePictureRemove}
                  disabled={isUploadingPicture}
                  icon={<Trash2 size={14} />}
                >
                  {t('common:actions.remove')}
                </Button>
              )}
            </div>
          </div>
          <span className={styles.hint}>
            {t('settings:general.avatar.hint')}
          </span>
          {pictureError && (
            <span className={styles.statusError}>
              <X size={14} /> {pictureError}
            </span>
          )}
        </div>

        <div className={styles.formGroup}>
          <label>{t('settings:general.agentName.label')}</label>
          <input
            type="text"
            value={agentNameDraft.value}
            onChange={(e) => agentNameDraft.set(e.target.value)}
            placeholder={t('settings:general.agentName.placeholder')}
          />
          <span className={styles.hint}>{t('settings:general.agentName.hint')}</span>
        </div>

        <div className={styles.formGroup}>
          <label>{t('settings:general.theme.label')}</label>
          <select value={themeDraft.value} onChange={(e) => themeDraft.set(e.target.value)}>
            <option value="dark">{t('settings:general.theme.dark')}</option>
            <option value="light">{t('settings:general.theme.light')}</option>
            <option value="system">{t('settings:general.theme.system')}</option>
          </select>
        </div>

        <div className={styles.formGroup}>
          <label>{t('settings:general.language.label')}</label>
          <select
            value={languageDraft.value}
            onChange={(e) => languageDraft.set(e.target.value)}
          >
            {SUPPORTED_LANGUAGES.map(l => (
              <option key={l.code} value={l.code}>{l.label}</option>
            ))}
          </select>
          <span className={styles.hint}>{t('settings:general.language.hint')}</span>
        </div>

        <div className={styles.formGroup}>
          <label>{t('settings:general.tour.label')}</label>
          <div>
            <Button
              variant="secondary"
              icon={<Compass size={14} />}
              onClick={() => startTour('core', { restart: true })}
            >
              {t('settings:general.tour.button')}
            </Button>
          </div>
          <span className={styles.hint}>
            {t('settings:general.tour.hint')}
          </span>
        </div>
      </div>

      <div className={styles.generalSaveRow}>
        <Button
          variant="primary"
          onClick={handleSaveSettings}
          disabled={isSaving || !isGeneralSettingsDirty}
          icon={isSaving ? <Loader2 size={14} className={styles.spinning} /> : <Save size={14} />}
        >
          {isSaving ? t('common:status.saving') : t('common:actions.saveChanges')}
        </Button>
        {saveStatus === 'success' && (
          <span className={styles.statusSuccess}>
            <Check size={14} /> {t('common:status.settingsSaved')}
          </span>
        )}
        {saveStatus === 'error' && (
          <span className={styles.statusError}>
            <X size={14} /> {t('common:status.saveFailed')}
          </span>
        )}
        {saveStatus === 'idle' && generalRemoteChanged && (
          <RemoteChangeHint onLoadLatest={loadLatestGeneralSettings} />
        )}
      </div>

      <div className={styles.generalDivider} />

      {/* Version & Updates Section */}
      <div className={styles.dangerZone} style={{ background: 'rgba(59, 130, 246, 0.05)', borderColor: 'rgba(59, 130, 246, 0.2)' }}>
        <div className={styles.dangerHeader}>
          <Download size={18} style={{ color: 'var(--text-primary)' }} />
          <h4 style={{ color: 'var(--text-primary)' }}>{t('settings:general.update.title')}</h4>
        </div>
        <p className={styles.dangerDescription}>
          {isCheckingUpdate ? (<>
            {t('settings:general.update.currentVersion', { version })}<br />
            {t('settings:general.update.checking')}
          </>) : updateCheckDone && updateAvailable ? (<>
            {t('settings:general.update.currentVersion', { version })}<br />
            {!isSameVersionUpdate && <>{t('settings:general.update.latestVersion', { latestVersion })}<br /></>}
            {isSameVersionUpdate
              ? t('settings:general.update.availableBodyMain')
              : t('settings:general.update.availableBodyGeneric')}
          </>) : updateCheckDone && updateBranch ? (<>
            {t('settings:general.update.currentVersion', { version })}<br />
            <Trans
              ns="settings"
              i18nKey="general.update.onBranch"
              values={{ branch: updateBranch }}
              components={{ 1: <strong /> }}
            />
          </>) : updateCheckDone ? (<>
            {t('settings:general.update.currentVersion', { version })}<br />
            {t('settings:general.update.upToDate')}
          </>) : (<>
            {t('settings:general.update.currentVersion', { version })}<br />
            {t('settings:general.update.checkPrompt')}
          </>)}
        </p>
        {isCheckingUpdate ? (
          <Button
            variant="secondary"
            disabled
            icon={<Loader2 size={14} className={styles.spinning} />}
          >
            {t('settings:general.update.checkingButton')}
          </Button>
        ) : updateCheckDone && updateAvailable ? (
          <Button
            variant="primary"
            onClick={handleDoUpdate}
            disabled={isUpdating}
            icon={isUpdating ? <Loader2 size={14} className={styles.spinning} /> : <Download size={14} />}
          >
            {isUpdating
              ? t('settings:general.update.updatingButton')
              : isSameVersionUpdate
                ? t('settings:general.update.updateToLatest')
                : t('settings:general.update.updateButton', { latestVersion })}
          </Button>
        ) : (
          <Button
            variant="secondary"
            onClick={handleCheckUpdate}
            icon={<RefreshCw size={14} />}
          >
            {t('settings:general.update.checkButton')}
          </Button>
        )}
        {updateMessages.length > 0 && (
          <div style={{
            marginTop: 'var(--space-3)',
            padding: 'var(--space-2) var(--space-3)',
            background: 'var(--bg-tertiary)',
            borderRadius: 'var(--radius-sm)',
            maxHeight: '150px',
            overflowY: 'auto',
            fontSize: 'var(--text-xs)',
            fontFamily: 'monospace',
            color: 'var(--text-secondary)',
          }}>
            {updateMessages.map((msg, i) => (
              <div key={i}>{msg}</div>
            ))}
          </div>
        )}
      </div>

      {/* Reset Section */}
      <div className={styles.dangerZone}>
        <div className={styles.dangerHeader}>
          <AlertTriangle size={18} className={styles.dangerIcon} />
          <h4>{t('settings:general.reset.title')}</h4>
        </div>
        <p className={styles.dangerDescription}>
          {t('settings:general.reset.description')}
        </p>
        <Button
          variant="danger"
          onClick={handleReset}
          disabled={isResetting}
          icon={isResetting ? <Loader2 size={14} className={styles.spinning} /> : <RotateCcw size={14} />}
        >
          {isResetting ? t('settings:general.reset.resetting') : t('settings:general.reset.button')}
        </Button>
        {resetStatus === 'success' && (
          <span className={styles.statusSuccess}>
            <Check size={14} /> {t('settings:general.reset.success')}
          </span>
        )}
        {resetStatus === 'error' && (
          <span className={styles.statusError}>
            <X size={14} /> {t('settings:general.reset.failed')}
          </span>
        )}
      </div>

      {/* Agent Profile (import/export) */}
      <div className={styles.profileSection}>
        <div className={styles.profileHeader}>
          <Package size={18} className={styles.profileIcon} />
          <h4>{t('settings:general.profile.title')}</h4>
        </div>
        <p className={styles.profileDescription}>
          <Trans ns="settings" i18nKey="general.profile.description" components={{ 0: <code /> }} />
        </p>
        <div className={styles.profileActions}>
          <input
            ref={profileImportInputRef}
            type="file"
            accept=".craftbot,application/octet-stream,application/zip"
            onChange={handleProfileFileSelected}
            style={{ display: 'none' }}
          />
          <Button
            variant="primary"
            onClick={handleExportProfile}
            disabled={isExportingProfile}
            icon={
              isExportingProfile ? (
                <Loader2 size={14} className={styles.spinning} />
              ) : (
                <Download size={14} />
              )
            }
          >
            {isExportingProfile ? t('common:status.exporting') : t('settings:general.profile.export')}
          </Button>
          <Button
            variant="secondary"
            onClick={handleImportProfileClick}
            disabled={isApplyingImport}
            icon={<PackageOpen size={14} />}
          >
            {t('settings:general.profile.import')}
          </Button>
          {profileStatus?.type === 'success' && (
            <span className={styles.statusSuccess}>
              <Check size={14} /> {profileStatus.message}
            </span>
          )}
          {profileStatus?.type === 'error' && (
            <span className={styles.statusError}>
              <X size={14} /> {profileStatus.message}
            </span>
          )}
        </div>
      </div>

      {/* Advanced Section */}
      <div className={styles.advancedSection}>
        <button
          className={styles.advancedToggle}
          onClick={() => setShowAdvanced(!showAdvanced)}
        >
          <FileText size={18} />
          <span>{t('settings:general.advanced.toggle')}</span>
          <ChevronRight
            size={14}
            className={`${styles.advancedChevron} ${showAdvanced ? styles.open : ''}`}
          />
        </button>

        {showAdvanced && <AgentFilesSection confirm={confirm} />}
      </div>

      {/* Confirm Modal */}
      <ConfirmModal {...confirmModalProps} />

      {/* Reset Agent checklist */}
      <ResetModal
        isOpen={showResetModal}
        onConfirm={handleResetConfirm}
        onCancel={() => setShowResetModal(false)}
      />

      {/* Import Profile Modal */}
      <ImportProfileModal
        isOpen={showImportModal}
        manifest={importManifest}
        preview={importPreview}
        isApplying={isApplyingImport}
        error={importError}
        onCancel={handleImportCancel}
        onApply={handleImportApply}
      />
    </div>
  )
}

// ── Agent files (Advanced) ─────────────────────────────────────────

/** The USER.md / SOUL.md / AGENT.md editors; loads the files while shown. */
function AgentFilesSection({ confirm }: { confirm: ConfirmFn }) {
  const { t } = useTranslation(['settings', 'common'])
  // Cached in generalSettingsSlice; fetched on first open and refetched when
  // a file is saved or restored from any tab.
  useResource(RESOURCES.agentFiles)

  return (
    <div className={styles.advancedContent}>
      <AgentFileEditor
        filename="USER.md"
        badge={t('settings:general.advanced.badgeUserProfile')}
        badgeVariant="info"
        description={t('settings:general.advanced.userDescription')}
        restoreMessage={t('settings:general.advanced.restoreConfirmMessage', { file: 'USER.md' })}
        confirm={confirm}
      />
      <AgentFileEditor
        filename="SOUL.md"
        badge={t('settings:general.advanced.badgePersonality')}
        badgeVariant="success"
        description={t('settings:general.advanced.soulDescription')}
        restoreMessage={t('settings:general.advanced.restoreConfirmMessageSoul')}
        confirm={confirm}
      />
      <AgentFileEditor
        filename="AGENT.md"
        badge={t('settings:general.advanced.badgeAgentManual')}
        badgeVariant="warning"
        description={t('settings:general.advanced.agentDescription')}
        restoreMessage={t('settings:general.advanced.restoreConfirmMessage', { file: 'AGENT.md' })}
        confirm={confirm}
      />
    </div>
  )
}

type AgentFileName = 'USER.md' | 'AGENT.md' | 'SOUL.md'

const AGENT_FILE_SELECTORS: Record<
  AgentFileName,
  { content: (state: RootState) => string; hasLoaded: (state: RootState) => boolean }
> = {
  'USER.md': { content: selectUserMd, hasLoaded: selectHasLoadedUserMd },
  'AGENT.md': { content: selectAgentMd, hasLoaded: selectHasLoadedAgentMd },
  'SOUL.md': { content: selectSoulMd, hasLoaded: selectHasLoadedSoulMd },
}

interface AgentFileEditorProps {
  filename: AgentFileName
  badge: string
  badgeVariant: ComponentProps<typeof Badge>['variant']
  description: string
  restoreMessage: string
  confirm: ConfirmFn
}

function AgentFileEditor({ filename, badge, badgeVariant, description, restoreMessage, confirm }: AgentFileEditorProps) {
  const { t } = useTranslation(['settings', 'common'])
  const { send, onMessage } = useSettingsWebSocket()

  const savedContent = useAppSelector(AGENT_FILE_SELECTORS[filename].content)
  const hasLoaded = useAppSelector(AGENT_FILE_SELECTORS[filename].hasLoaded)
  // A draft over the saved file: a save no longer looks reverted after
  // switching tabs, and a load or save in another tab can't clobber an edit.
  const draft = useServerDraft(savedContent)
  const { reset: settleDraft, acceptRemote: loadLatest } = draft
  const draftValueRef = useRef(draft.value)
  draftValueRef.current = draft.value

  const [readFailed, setReadFailed] = useState(false)
  const isLoading = !hasLoaded && !readFailed
  const [isSaving, setIsSaving] = useState(false)
  const [isRestoring, setIsRestoring] = useState(false)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')
  // This tab's in-flight requests: the content it saved, and whether it
  // restored. Replies to other tabs' requests only update data.
  const savingContentRef = useRef<string | null>(null)
  const restoringRef = useRef(false)

  useEffect(() => {
    const flashStatus = (status: 'success' | 'error') => {
      setSaveStatus(status)
      setTimeout(() => setSaveStatus('idle'), 3000)
    }
    const cleanups = [
      onMessage('agent_file_read', (data: unknown) => {
        // Content goes to the slice; a failed read just stops the spinner.
        const d = data as { filename: string; success: boolean }
        if (d.filename === filename && !d.success) setReadFailed(true)
      }),
      onMessage('agent_file_write', (data: unknown) => {
        const d = data as { filename: string; success: boolean }
        const sent = savingContentRef.current
        if (d.filename !== filename || sent === null) return
        savingContentRef.current = null
        setIsSaving(false)
        // Typing that continued during the save stays an unsaved edit.
        if (d.success && draftValueRef.current === sent) settleDraft()
        flashStatus(d.success ? 'success' : 'error')
      }),
      onMessage('agent_file_restore', (data: unknown) => {
        // Content goes to the slice; this tab drops its edit for the default.
        const d = data as { filename: string; success: boolean }
        if (d.filename !== filename || !restoringRef.current) return
        restoringRef.current = false
        setIsRestoring(false)
        if (d.success) {
          loadLatest()
          flashStatus('success')
        }
      }),
    ]
    return () => cleanups.forEach(c => c())
  }, [filename, onMessage, settleDraft, loadLatest])

  const handleSave = () => {
    savingContentRef.current = draft.value
    setIsSaving(true)
    send('agent_file_write', { filename, content: draft.value })
  }

  const handleRestore = () => {
    confirm({
      title: t('settings:general.advanced.restoreConfirmTitle', { file: filename }),
      message: restoreMessage,
      confirmText: t('common:actions.restore'),
      variant: 'danger',
    }, () => {
      restoringRef.current = true
      setIsRestoring(true)
      send('agent_file_restore', { filename })
    })
  }

  return (
    <div className={styles.fileEditorCard}>
      <div className={styles.fileEditorHeader}>
        <div className={styles.fileEditorTitle}>
          <h4>{filename}</h4>
          <Badge variant={badgeVariant}>{badge}</Badge>
        </div>
        <p className={styles.fileEditorDescription}>
          {description}
        </p>
      </div>
      <div className={styles.fileEditorContent}>
        {isLoading ? (
          <div className={styles.fileLoading}>
            <Loader2 size={20} className={styles.spinning} />
            <span>{t('settings:general.advanced.loading', { file: filename })}</span>
          </div>
        ) : (
          <textarea
            className={styles.fileTextarea}
            value={draft.value}
            onChange={(e) => draft.set(e.target.value)}
            placeholder={t('common:status.loading')}
            spellCheck={false}
          />
        )}
      </div>
      <div className={styles.fileEditorActions}>
        <Button
          variant="secondary"
          size="sm"
          onClick={handleRestore}
          disabled={isRestoring || isLoading}
          icon={isRestoring ? <Loader2 size={14} className={styles.spinning} /> : <RotateCcw size={14} />}
        >
          {isRestoring ? t('common:status.restoring') : t('common:actions.restoreDefault')}
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={handleSave}
          disabled={isSaving || isLoading || !draft.isDirty}
        >
          {isSaving ? t('common:status.saving') : t('common:actions.save')}
        </Button>
        {saveStatus === 'success' && (
          <span className={styles.statusSuccess}>
            <Check size={14} /> {t('common:status.saved')}
          </span>
        )}
        {saveStatus === 'error' && (
          <span className={styles.statusError}>
            <X size={14} /> {t('common:status.saveFailed')}
          </span>
        )}
        {saveStatus === 'idle' && (draft.remoteChanged ? (
          <RemoteChangeHint onLoadLatest={loadLatest} />
        ) : draft.isDirty && (
          <span className={styles.statusWarning}>
            {t('common:status.unsavedChanges')}
          </span>
        ))}
      </div>
    </div>
  )
}
