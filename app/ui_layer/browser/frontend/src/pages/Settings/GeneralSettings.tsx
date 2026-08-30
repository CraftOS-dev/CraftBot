import { useState, useEffect, useRef } from 'react'
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
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useTour } from '../../tour'
import { useConfirmModal } from '../../hooks'
import i18n, { setUiLanguage } from '../../i18n/config'
import { SUPPORTED_LANGUAGES, resolveSupportedLanguage } from '../../i18n/languages'
import { formatList } from '../../i18n/format'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import { useAppSelector, useAppDispatch } from '../../store/hooks'
import { resetUpdateCheck } from '../../store/slices/generalSettingsSlice'
import {
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

// Theme application helper
function applyTheme(theme: string) {
  const root = document.documentElement

  if (theme === 'system') {
    // Check system preference
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
    root.setAttribute('data-theme', prefersDark ? 'dark' : 'light')
  } else {
    root.setAttribute('data-theme', theme)
  }

  // Persist to localStorage
  localStorage.setItem('craftbot-theme', theme)
}

// Get initial theme from localStorage or default
function getInitialTheme(): string {
  return localStorage.getItem('craftbot-theme') || 'dark'
}

// Get initial agent name from localStorage or default
function getInitialAgentName(): string {
  return localStorage.getItem('craftbot-agent-name') || 'CraftBot'
}

// Get initial UI language from the already-resolved i18n instance
function getInitialLanguage(): string {
  return i18n.language || 'en'
}

export function GeneralSettings() {
  const { t } = useTranslation(['settings', 'common'])
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const { agentProfilePictureUrl, agentProfilePictureHasCustom } = useWebSocket()
  const { startTour } = useTour()
  const version = useAppSelector(selectVersion)
  const dispatch = useAppDispatch()
  const { theme: globalTheme, setTheme: setGlobalTheme } = useTheme()
  const [agentName, setAgentName] = useState(getInitialAgentName)
  const [initialAgentName, setInitialAgentName] = useState(getInitialAgentName)
  const [theme, setTheme] = useState(getInitialTheme)
  const [initialTheme, setInitialTheme] = useState(getInitialTheme)
  const [language, setLanguage] = useState(getInitialLanguage)
  const [initialLanguage, setInitialLanguage] = useState(getInitialLanguage)
  const [isResetting, setIsResetting] = useState(false)
  const [resetStatus, setResetStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [showResetModal, setShowResetModal] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')

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

  // Agent files: server-canonical "original" content lives in
  // generalSettingsSlice (cached across tab remounts). The in-progress
  // editor draft stays local so typing doesn't dispatch on every keystroke.
  const sliceUserMd = useAppSelector(selectUserMd)
  const sliceAgentMd = useAppSelector(selectAgentMd)
  const sliceSoulMd = useAppSelector(selectSoulMd)
  const hasLoadedUserMd = useAppSelector(selectHasLoadedUserMd)
  const hasLoadedAgentMd = useAppSelector(selectHasLoadedAgentMd)
  const hasLoadedSoulMd = useAppSelector(selectHasLoadedSoulMd)
  const [userMdContent, setUserMdContent] = useState('')
  const [originalUserMdContent, setOriginalUserMdContent] = useState('')
  const [agentMdContent, setAgentMdContent] = useState('')
  const [originalAgentMdContent, setOriginalAgentMdContent] = useState('')
  const [soulMdContent, setSoulMdContent] = useState('')
  const [originalSoulMdContent, setOriginalSoulMdContent] = useState('')

  // Hydrate local drafts from slice on first load (and any time the slice
  // refreshes, e.g. after restore-from-default).
  useEffect(() => {
    if (hasLoadedUserMd) {
      setUserMdContent(sliceUserMd)
      setOriginalUserMdContent(sliceUserMd)
    }
  }, [hasLoadedUserMd, sliceUserMd])
  useEffect(() => {
    if (hasLoadedAgentMd) {
      setAgentMdContent(sliceAgentMd)
      setOriginalAgentMdContent(sliceAgentMd)
    }
  }, [hasLoadedAgentMd, sliceAgentMd])
  useEffect(() => {
    if (hasLoadedSoulMd) {
      setSoulMdContent(sliceSoulMd)
      setOriginalSoulMdContent(sliceSoulMd)
    }
  }, [hasLoadedSoulMd, sliceSoulMd])
  // Refs to track current content for closure-safe callbacks
  const userMdContentRef = useRef(userMdContent)
  const agentMdContentRef = useRef(agentMdContent)
  const soulMdContentRef = useRef(soulMdContent)
  userMdContentRef.current = userMdContent
  agentMdContentRef.current = agentMdContent
  soulMdContentRef.current = soulMdContent
  const [isLoadingUserMd, setIsLoadingUserMd] = useState(false)
  const [isLoadingAgentMd, setIsLoadingAgentMd] = useState(false)
  const [isLoadingSoulMd, setIsLoadingSoulMd] = useState(false)
  const [isSavingUserMd, setIsSavingUserMd] = useState(false)
  const [isSavingAgentMd, setIsSavingAgentMd] = useState(false)
  const [isSavingSoulMd, setIsSavingSoulMd] = useState(false)
  const [isRestoringUserMd, setIsRestoringUserMd] = useState(false)
  const [isRestoringAgentMd, setIsRestoringAgentMd] = useState(false)
  const [isRestoringSoulMd, setIsRestoringSoulMd] = useState(false)
  const [userMdSaveStatus, setUserMdSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [agentMdSaveStatus, setAgentMdSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [soulMdSaveStatus, setSoulMdSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [showAdvanced, setShowAdvanced] = useState(false)

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

  // Computed dirty states
  const isUserMdDirty = userMdContent !== originalUserMdContent
  const isAgentMdDirty = agentMdContent !== originalAgentMdContent
  const isSoulMdDirty = soulMdContent !== originalSoulMdContent
  const isGeneralSettingsDirty =
    agentName !== initialAgentName || theme !== initialTheme || language !== initialLanguage

  // Sync local theme when global theme changes (e.g., from TopBar button)
  useEffect(() => {
    // Only sync if current theme is not 'system' (system theme should stay as 'system')
    if (initialTheme !== 'system' && globalTheme !== initialTheme) {
      setTheme(globalTheme)
      setInitialTheme(globalTheme)
      applyTheme(globalTheme)
    }
  }, [globalTheme, initialTheme])

  // Apply theme on mount and when saved (initialTheme changes after save)
  useEffect(() => {
    applyTheme(initialTheme)
  }, [initialTheme])

  // Listen for system theme changes when using 'system' theme
  useEffect(() => {
    if (initialTheme !== 'system') return

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const handleChange = () => applyTheme('system')

    mediaQuery.addEventListener('change', handleChange)
    return () => mediaQuery.removeEventListener('change', handleChange)
  }, [initialTheme])

  // Load initial settings and files
  useEffect(() => {
    if (!isConnected) return

    // Set up message handlers
    const cleanups = [
      onMessage('settings_get', (data: unknown) => {
        const d = data as {
          success: boolean
          settings?: {
            agentName: string
            theme: string
            language?: string
            agentProfilePictureUrl?: string
            agentProfilePictureHasCustom?: boolean
          }
        }
        if (d.success && d.settings) {
          setAgentName(d.settings.agentName)
          setTheme(d.settings.theme)
          if (d.settings.language) {
            // Server value is authoritative; normalize to a supported UI language.
            const resolved = resolveSupportedLanguage(d.settings.language) ?? 'en'
            setLanguage(resolved)
            setInitialLanguage(resolved)
            setUiLanguage(resolved)
          }
          if (d.settings.agentProfilePictureUrl) {
            setProfilePictureUrl(d.settings.agentProfilePictureUrl)
          }
          if (typeof d.settings.agentProfilePictureHasCustom === 'boolean') {
            setHasCustomPicture(d.settings.agentProfilePictureHasCustom)
          }
        }
      }),
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
        const d = data as { success: boolean }
        setIsSaving(false)
        if (d.success) {
          // Settings saved
        }
      }),
      onMessage('reset', (data: unknown) => {
        const d = data as { success: boolean }
        setIsResetting(false)
        setResetStatus(d.success ? 'success' : 'error')
        setTimeout(() => setResetStatus('idle'), 3000)
      }),
      onMessage('agent_file_read', (data: unknown) => {
        // Content goes to the slice; we only need to flip the per-file
        // loading flag locally.
        const d = data as { filename: string; success: boolean }
        if (d.filename === 'USER.md') setIsLoadingUserMd(false)
        else if (d.filename === 'AGENT.md') setIsLoadingAgentMd(false)
        else if (d.filename === 'SOUL.md') setIsLoadingSoulMd(false)
      }),
      onMessage('agent_file_write', (data: unknown) => {
        const d = data as { filename: string; success: boolean }
        if (d.filename === 'USER.md') {
          setIsSavingUserMd(false)
          if (d.success) {
            setOriginalUserMdContent(userMdContentRef.current)
          }
          setUserMdSaveStatus(d.success ? 'success' : 'error')
          setTimeout(() => setUserMdSaveStatus('idle'), 3000)
        } else if (d.filename === 'AGENT.md') {
          setIsSavingAgentMd(false)
          if (d.success) {
            setOriginalAgentMdContent(agentMdContentRef.current)
          }
          setAgentMdSaveStatus(d.success ? 'success' : 'error')
          setTimeout(() => setAgentMdSaveStatus('idle'), 3000)
        } else if (d.filename === 'SOUL.md') {
          setIsSavingSoulMd(false)
          if (d.success) {
            setOriginalSoulMdContent(soulMdContentRef.current)
          }
          setSoulMdSaveStatus(d.success ? 'success' : 'error')
          setTimeout(() => setSoulMdSaveStatus('idle'), 3000)
        }
      }),
      // update_check_result is handled by generalSettingsSlice via the registry.
      onMessage('update_progress', (data: unknown) => {
        const d = data as { message: string }
        setUpdateMessages(prev => [...prev, d.message])
      }),
      onMessage('agent_file_restore', (data: unknown) => {
        // Content goes to the slice; we only flip local flags + show toast.
        const d = data as { filename: string; success: boolean }
        if (d.filename === 'USER.md') {
          setIsRestoringUserMd(false)
          if (d.success) {
            setUserMdSaveStatus('success')
            setTimeout(() => setUserMdSaveStatus('idle'), 3000)
          }
        } else if (d.filename === 'AGENT.md') {
          setIsRestoringAgentMd(false)
          if (d.success) {
            setAgentMdSaveStatus('success')
            setTimeout(() => setAgentMdSaveStatus('idle'), 3000)
          }
        } else if (d.filename === 'SOUL.md') {
          setIsRestoringSoulMd(false)
          if (d.success) {
            setSoulMdSaveStatus('success')
            setTimeout(() => setSoulMdSaveStatus('idle'), 3000)
          }
        }
      }),
    ]

    // Request initial data
    send('settings_get')
    // Auto-check for updates (only on first mount of this session)
    if (!updateCheckDone) send('check_update')

    return () => {
      cleanups.forEach(cleanup => cleanup())
    }
  }, [isConnected, send, onMessage])

  // Load advanced files when section is opened (cached after first load).
  useEffect(() => {
    if (!showAdvanced || !isConnected) return
    if (!hasLoadedUserMd) {
      setIsLoadingUserMd(true)
      send('agent_file_read', { filename: 'USER.md' })
    }
    if (!hasLoadedAgentMd) {
      setIsLoadingAgentMd(true)
      send('agent_file_read', { filename: 'AGENT.md' })
    }
    if (!hasLoadedSoulMd) {
      setIsLoadingSoulMd(true)
      send('agent_file_read', { filename: 'SOUL.md' })
    }
  }, [showAdvanced, isConnected, send, hasLoadedUserMd, hasLoadedAgentMd, hasLoadedSoulMd])

  const handleSaveSettings = () => {
    setIsSaving(true)

    // Persist agent name to localStorage
    localStorage.setItem('craftbot-agent-name', agentName)

    // Sync the global theme context (for TopBar)
    // Resolve 'system' to actual theme for the context
    if (theme === 'system') {
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
      setGlobalTheme(prefersDark ? 'dark' : 'light')
    } else {
      setGlobalTheme(theme as 'dark' | 'light')
    }

    // Language is applied live on selection; persist the choice on save.
    setUiLanguage(language)

    // Update the initial values to mark as not dirty
    // This triggers the useEffect that applies the theme
    setInitialAgentName(agentName)
    setInitialTheme(theme)
    setInitialLanguage(language)

    // Send to backend (for potential server-side persistence)
    send('settings_update', { settings: { agentName, theme, language } })

    // Show success feedback
    setIsSaving(false)
    setSaveStatus('success')
    setTimeout(() => setSaveStatus('idle'), 3000)
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

  const handleSaveUserMd = () => {
    setIsSavingUserMd(true)
    send('agent_file_write', { filename: 'USER.md', content: userMdContent })
  }

  const handleSaveAgentMd = () => {
    setIsSavingAgentMd(true)
    send('agent_file_write', { filename: 'AGENT.md', content: agentMdContent })
  }

  const handleRestoreUserMd = () => {
    confirm({
      title: t('settings:general.advanced.restoreConfirmTitle', { file: 'USER.md' }),
      message: t('settings:general.advanced.restoreConfirmMessage', { file: 'USER.md' }),
      confirmText: t('common:actions.restore'),
      variant: 'danger',
    }, () => {
      setIsRestoringUserMd(true)
      send('agent_file_restore', { filename: 'USER.md' })
    })
  }

  const handleRestoreAgentMd = () => {
    confirm({
      title: t('settings:general.advanced.restoreConfirmTitle', { file: 'AGENT.md' }),
      message: t('settings:general.advanced.restoreConfirmMessage', { file: 'AGENT.md' }),
      confirmText: t('common:actions.restore'),
      variant: 'danger',
    }, () => {
      setIsRestoringAgentMd(true)
      send('agent_file_restore', { filename: 'AGENT.md' })
    })
  }

  const handleSaveSoulMd = () => {
    setIsSavingSoulMd(true)
    send('agent_file_write', { filename: 'SOUL.md', content: soulMdContent })
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

  const handleRestoreSoulMd = () => {
    confirm({
      title: t('settings:general.advanced.restoreConfirmTitle', { file: 'SOUL.md' }),
      message: t('settings:general.advanced.restoreConfirmMessageSoul'),
      confirmText: t('common:actions.restore'),
      variant: 'danger',
    }, () => {
      setIsRestoringSoulMd(true)
      send('agent_file_restore', { filename: 'SOUL.md' })
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
      const livingUiCount =
        (summary.living_ui_added?.length || 0) + (summary.living_ui_renamed?.length || 0)
      if (livingUiCount) {
        parts.push(t('settings:general.profile.livingUiCount', { count: livingUiCount }))
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
            value={agentName}
            onChange={(e) => setAgentName(e.target.value)}
            placeholder={t('settings:general.agentName.placeholder')}
          />
          <span className={styles.hint}>{t('settings:general.agentName.hint')}</span>
        </div>

        <div className={styles.formGroup}>
          <label>{t('settings:general.theme.label')}</label>
          <select value={theme} onChange={(e) => setTheme(e.target.value)}>
            <option value="dark">{t('settings:general.theme.dark')}</option>
            <option value="light">{t('settings:general.theme.light')}</option>
            <option value="system">{t('settings:general.theme.system')}</option>
          </select>
        </div>

        <div className={styles.formGroup}>
          <label>{t('settings:general.language.label')}</label>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
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

        {showAdvanced && (
          <div className={styles.advancedContent}>
            {/* USER.md Editor */}
            <div className={styles.fileEditorCard}>
              <div className={styles.fileEditorHeader}>
                <div className={styles.fileEditorTitle}>
                  <h4>USER.md</h4>
                  <Badge variant="info">{t('settings:general.advanced.badgeUserProfile')}</Badge>
                </div>
                <p className={styles.fileEditorDescription}>
                  {t('settings:general.advanced.userDescription')}
                </p>
              </div>
              <div className={styles.fileEditorContent}>
                {isLoadingUserMd ? (
                  <div className={styles.fileLoading}>
                    <Loader2 size={20} className={styles.spinning} />
                    <span>{t('settings:general.advanced.loading', { file: 'USER.md' })}</span>
                  </div>
                ) : (
                  <textarea
                    className={styles.fileTextarea}
                    value={userMdContent}
                    onChange={(e) => setUserMdContent(e.target.value)}
                    placeholder={t('common:status.loading')}
                    spellCheck={false}
                  />
                )}
              </div>
              <div className={styles.fileEditorActions}>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleRestoreUserMd}
                  disabled={isRestoringUserMd || isLoadingUserMd}
                  icon={isRestoringUserMd ? <Loader2 size={14} className={styles.spinning} /> : <RotateCcw size={14} />}
                >
                  {isRestoringUserMd ? t('common:status.restoring') : t('common:actions.restoreDefault')}
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleSaveUserMd}
                  disabled={isSavingUserMd || isLoadingUserMd || !isUserMdDirty}
                >
                  {isSavingUserMd ? t('common:status.saving') : t('common:actions.save')}
                </Button>
                {userMdSaveStatus === 'success' && (
                  <span className={styles.statusSuccess}>
                    <Check size={14} /> {t('common:status.saved')}
                  </span>
                )}
                {userMdSaveStatus === 'error' && (
                  <span className={styles.statusError}>
                    <X size={14} /> {t('common:status.saveFailed')}
                  </span>
                )}
                {isUserMdDirty && userMdSaveStatus === 'idle' && (
                  <span className={styles.statusWarning}>
                    {t('common:status.unsavedChanges')}
                  </span>
                )}
              </div>
            </div>

            {/* SOUL.md Editor */}
            <div className={styles.fileEditorCard}>
              <div className={styles.fileEditorHeader}>
                <div className={styles.fileEditorTitle}>
                  <h4>SOUL.md</h4>
                  <Badge variant="success">{t('settings:general.advanced.badgePersonality')}</Badge>
                </div>
                <p className={styles.fileEditorDescription}>
                  {t('settings:general.advanced.soulDescription')}
                </p>
              </div>
              <div className={styles.fileEditorContent}>
                {isLoadingSoulMd ? (
                  <div className={styles.fileLoading}>
                    <Loader2 size={20} className={styles.spinning} />
                    <span>{t('settings:general.advanced.loading', { file: 'SOUL.md' })}</span>
                  </div>
                ) : (
                  <textarea
                    className={styles.fileTextarea}
                    value={soulMdContent}
                    onChange={(e) => setSoulMdContent(e.target.value)}
                    placeholder={t('common:status.loading')}
                    spellCheck={false}
                  />
                )}
              </div>
              <div className={styles.fileEditorActions}>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleRestoreSoulMd}
                  disabled={isRestoringSoulMd || isLoadingSoulMd}
                  icon={isRestoringSoulMd ? <Loader2 size={14} className={styles.spinning} /> : <RotateCcw size={14} />}
                >
                  {isRestoringSoulMd ? t('common:status.restoring') : t('common:actions.restoreDefault')}
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleSaveSoulMd}
                  disabled={isSavingSoulMd || isLoadingSoulMd || !isSoulMdDirty}
                >
                  {isSavingSoulMd ? t('common:status.saving') : t('common:actions.save')}
                </Button>
                {soulMdSaveStatus === 'success' && (
                  <span className={styles.statusSuccess}>
                    <Check size={14} /> {t('common:status.saved')}
                  </span>
                )}
                {soulMdSaveStatus === 'error' && (
                  <span className={styles.statusError}>
                    <X size={14} /> {t('common:status.saveFailed')}
                  </span>
                )}
                {isSoulMdDirty && soulMdSaveStatus === 'idle' && (
                  <span className={styles.statusWarning}>
                    {t('common:status.unsavedChanges')}
                  </span>
                )}
              </div>
            </div>

            {/* AGENT.md Editor */}
            <div className={styles.fileEditorCard}>
              <div className={styles.fileEditorHeader}>
                <div className={styles.fileEditorTitle}>
                  <h4>AGENT.md</h4>
                  <Badge variant="warning">{t('settings:general.advanced.badgeAgentManual')}</Badge>
                </div>
                <p className={styles.fileEditorDescription}>
                  {t('settings:general.advanced.agentDescription')}
                </p>
              </div>
              <div className={styles.fileEditorContent}>
                {isLoadingAgentMd ? (
                  <div className={styles.fileLoading}>
                    <Loader2 size={20} className={styles.spinning} />
                    <span>{t('settings:general.advanced.loading', { file: 'AGENT.md' })}</span>
                  </div>
                ) : (
                  <textarea
                    className={styles.fileTextarea}
                    value={agentMdContent}
                    onChange={(e) => setAgentMdContent(e.target.value)}
                    placeholder={t('common:status.loading')}
                    spellCheck={false}
                  />
                )}
              </div>
              <div className={styles.fileEditorActions}>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleRestoreAgentMd}
                  disabled={isRestoringAgentMd || isLoadingAgentMd}
                  icon={isRestoringAgentMd ? <Loader2 size={14} className={styles.spinning} /> : <RotateCcw size={14} />}
                >
                  {isRestoringAgentMd ? t('common:status.restoring') : t('common:actions.restoreDefault')}
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleSaveAgentMd}
                  disabled={isSavingAgentMd || isLoadingAgentMd || !isAgentMdDirty}
                >
                  {isSavingAgentMd ? t('common:status.saving') : t('common:actions.save')}
                </Button>
                {agentMdSaveStatus === 'success' && (
                  <span className={styles.statusSuccess}>
                    <Check size={14} /> {t('common:status.saved')}
                  </span>
                )}
                {agentMdSaveStatus === 'error' && (
                  <span className={styles.statusError}>
                    <X size={14} /> {t('common:status.saveFailed')}
                  </span>
                )}
                {isAgentMdDirty && agentMdSaveStatus === 'idle' && (
                  <span className={styles.statusWarning}>
                    {t('common:status.unsavedChanges')}
                  </span>
                )}
              </div>
            </div>
          </div>
        )}
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
