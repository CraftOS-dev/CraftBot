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
} from 'lucide-react'
import { Button, Badge, ConfirmModal } from '../../components/ui'
import { useTheme } from '../../contexts/ThemeContext'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useConfirmModal } from '../../hooks'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'

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

export function GeneralSettings() {
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const { version, agentProfilePictureUrl, agentProfilePictureHasCustom } = useWebSocket()
  const { theme: globalTheme, setTheme: setGlobalTheme } = useTheme()
  const [agentName, setAgentName] = useState(getInitialAgentName)
  const [initialAgentName, setInitialAgentName] = useState(getInitialAgentName)
  const [theme, setTheme] = useState(getInitialTheme)
  const [initialTheme, setInitialTheme] = useState(getInitialTheme)
  const [isResetting, setIsResetting] = useState(false)
  const [resetStatus, setResetStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [isSaving, setIsSaving] = useState(false)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')

  // Agent profile picture
  const [profilePictureUrl, setProfilePictureUrl] = useState<string>(agentProfilePictureUrl)
  const [hasCustomPicture, setHasCustomPicture] = useState<boolean>(agentProfilePictureHasCustom)
  const [pictureError, setPictureError] = useState<string | null>(null)
  const [isUploadingPicture, setIsUploadingPicture] = useState(false)
  const pictureInputRef = useRef<HTMLInputElement | null>(null)

  // Keep local preview in sync with the central context value (e.g. after reconnect)
  useEffect(() => {
    setProfilePictureUrl(agentProfilePictureUrl)
  }, [agentProfilePictureUrl])
  useEffect(() => {
    setHasCustomPicture(agentProfilePictureHasCustom)
  }, [agentProfilePictureHasCustom])

  // Agent file states
  const [userMdContent, setUserMdContent] = useState('')
  const [originalUserMdContent, setOriginalUserMdContent] = useState('')
  const [agentMdContent, setAgentMdContent] = useState('')
  const [originalAgentMdContent, setOriginalAgentMdContent] = useState('')
  const [soulMdContent, setSoulMdContent] = useState('')
  const [originalSoulMdContent, setOriginalSoulMdContent] = useState('')
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

  // Update state
  const [isCheckingUpdate, setIsCheckingUpdate] = useState(true) // starts true — auto-check on mount
  const [updateAvailable, setUpdateAvailable] = useState(false)
  const [latestVersion, setLatestVersion] = useState('')
  const [isUpdating, setIsUpdating] = useState(false)
  const [updateMessages, setUpdateMessages] = useState<string[]>([])
  const [updateCheckDone, setUpdateCheckDone] = useState(false)

  // Confirm modal
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  // Computed dirty states
  const isUserMdDirty = userMdContent !== originalUserMdContent
  const isAgentMdDirty = agentMdContent !== originalAgentMdContent
  const isSoulMdDirty = soulMdContent !== originalSoulMdContent
  const isGeneralSettingsDirty = agentName !== initialAgentName || theme !== initialTheme

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
            agentProfilePictureUrl?: string
            agentProfilePictureHasCustom?: boolean
          }
        }
        if (d.success && d.settings) {
          setAgentName(d.settings.agentName)
          setTheme(d.settings.theme)
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
          setPictureError(d.error || 'Upload failed')
        }
      }),
      onMessage('agent_profile_picture_remove', (data: unknown) => {
        const d = data as { success: boolean; url?: string; has_custom?: boolean; error?: string }
        if (d.success) {
          setProfilePictureUrl(d.url || '/api/agent-profile-picture')
          setHasCustomPicture(d.has_custom ?? false)
          setPictureError(null)
        } else {
          setPictureError(d.error || 'Remove failed')
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
        const d = data as { filename: string; content: string; success: boolean }
        if (d.filename === 'USER.md') {
          setIsLoadingUserMd(false)
          if (d.success) {
            setUserMdContent(d.content)
            setOriginalUserMdContent(d.content)
          }
        } else if (d.filename === 'AGENT.md') {
          setIsLoadingAgentMd(false)
          if (d.success) {
            setAgentMdContent(d.content)
            setOriginalAgentMdContent(d.content)
          }
        } else if (d.filename === 'SOUL.md') {
          setIsLoadingSoulMd(false)
          if (d.success) {
            setSoulMdContent(d.content)
            setOriginalSoulMdContent(d.content)
          }
        }
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
      onMessage('update_check_result', (data: unknown) => {
        const d = data as { updateAvailable: boolean; currentVersion: string; latestVersion: string; error?: string }
        setIsCheckingUpdate(false)
        setUpdateCheckDone(true)
        setUpdateAvailable(d.updateAvailable)
        setLatestVersion(d.latestVersion)
      }),
      onMessage('update_progress', (data: unknown) => {
        const d = data as { message: string }
        setUpdateMessages(prev => [...prev, d.message])
      }),
      onMessage('agent_file_restore', (data: unknown) => {
        const d = data as { filename: string; content: string; success: boolean }
        if (d.filename === 'USER.md') {
          setIsRestoringUserMd(false)
          if (d.success) {
            setUserMdContent(d.content)
            setOriginalUserMdContent(d.content)
            setUserMdSaveStatus('success')
            setTimeout(() => setUserMdSaveStatus('idle'), 3000)
          }
        } else if (d.filename === 'AGENT.md') {
          setIsRestoringAgentMd(false)
          if (d.success) {
            setAgentMdContent(d.content)
            setOriginalAgentMdContent(d.content)
            setAgentMdSaveStatus('success')
            setTimeout(() => setAgentMdSaveStatus('idle'), 3000)
          }
        } else if (d.filename === 'SOUL.md') {
          setIsRestoringSoulMd(false)
          if (d.success) {
            setSoulMdContent(d.content)
            setOriginalSoulMdContent(d.content)
            setSoulMdSaveStatus('success')
            setTimeout(() => setSoulMdSaveStatus('idle'), 3000)
          }
        }
      }),
    ]

    // Request initial data
    send('settings_get')
    // Auto-check for updates
    send('check_update')

    return () => {
      cleanups.forEach(cleanup => cleanup())
    }
  }, [isConnected, send, onMessage])

  // Load advanced files when section is opened
  useEffect(() => {
    if (showAdvanced && isConnected) {
      setIsLoadingUserMd(true)
      setIsLoadingAgentMd(true)
      setIsLoadingSoulMd(true)
      send('agent_file_read', { filename: 'USER.md' })
      send('agent_file_read', { filename: 'AGENT.md' })
      send('agent_file_read', { filename: 'SOUL.md' })
    }
  }, [showAdvanced, isConnected, send])

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

    // Update the initial values to mark as not dirty
    // This triggers the useEffect that applies the theme
    setInitialAgentName(agentName)
    setInitialTheme(theme)

    // Send to backend (for potential server-side persistence)
    send('settings_update', { settings: { agentName, theme } })

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
      setPictureError('Could not read file')
    }
    reader.readAsDataURL(file)
  }

  const handlePictureRemove = () => {
    setPictureError(null)
    send('agent_profile_picture_remove')
  }

  const handleReset = () => {
    confirm({
      title: 'Reset Agent',
      message: 'Are you sure you want to reset the agent? This will clear all current tasks, conversation history, and restore the agent file system to its default state.',
      confirmText: 'Reset',
      variant: 'danger',
    }, () => {
      setIsResetting(true)
      send('reset')
    })
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
      title: 'Restore USER.md',
      message: 'Are you sure you want to restore USER.md to its default template? This will overwrite your current customizations.',
      confirmText: 'Restore',
      variant: 'danger',
    }, () => {
      setIsRestoringUserMd(true)
      send('agent_file_restore', { filename: 'USER.md' })
    })
  }

  const handleRestoreAgentMd = () => {
    confirm({
      title: 'Restore AGENT.md',
      message: 'Are you sure you want to restore AGENT.md to its default template? This will overwrite your current customizations.',
      confirmText: 'Restore',
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
    setIsCheckingUpdate(true)
    setUpdateCheckDone(false)
    setUpdateAvailable(false)
    setUpdateMessages([])
    send('check_update')
  }

  const handleDoUpdate = () => {
    confirm({
      title: 'Update CraftBot',
      message: `Are you sure you want to update CraftBot to v${latestVersion}? The application will restart automatically after the update.`,
      confirmText: 'Update',
      variant: 'danger',
    }, () => {
      setIsUpdating(true)
      setUpdateMessages([])
      send('do_update')
    })
  }

  const handleRestoreSoulMd = () => {
    confirm({
      title: 'Restore SOUL.md',
      message: 'Are you sure you want to restore SOUL.md to its default template? This will overwrite your current personality customizations.',
      confirmText: 'Restore',
      variant: 'danger',
    }, () => {
      setIsRestoringSoulMd(true)
      send('agent_file_restore', { filename: 'SOUL.md' })
    })
  }

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>General Settings</h3>
        <p>Configure basic agent settings and preferences</p>
      </div>

      <div className={styles.settingsForm}>
        <div className={styles.formGroup}>
          <label>Avatar</label>
          <div className={styles.profilePictureRow}>
            <img
              src={profilePictureUrl}
              alt="Agent avatar"
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
                {isUploadingPicture ? 'Uploading...' : 'Upload'}
              </Button>
              {hasCustomPicture && (
                <Button
                  variant="secondary"
                  onClick={handlePictureRemove}
                  disabled={isUploadingPicture}
                  icon={<Trash2 size={14} />}
                >
                  Remove
                </Button>
              )}
            </div>
          </div>
          <span className={styles.hint}>
            Shown next to agent messages in chat. PNG/JPG/WEBP/GIF, max 5 MB.
          </span>
          {pictureError && (
            <span className={styles.statusError}>
              <X size={14} /> {pictureError}
            </span>
          )}
        </div>

        <div className={styles.formGroup}>
          <label>Agent Name</label>
          <input
            type="text"
            value={agentName}
            onChange={(e) => setAgentName(e.target.value)}
            placeholder="Enter agent name"
          />
          <span className={styles.hint}>The name displayed in conversations</span>
        </div>

        <div className={styles.formGroup}>
          <label>Theme</label>
          <select value={theme} onChange={(e) => setTheme(e.target.value)}>
            <option value="dark">Dark</option>
            <option value="light">Light</option>
            <option value="system">System</option>
          </select>
        </div>
      </div>

      <div className={styles.sectionFooter}>
        <Button
          variant="primary"
          onClick={handleSaveSettings}
          disabled={isSaving || !isGeneralSettingsDirty}
        >
          {isSaving ? 'Saving...' : 'Save Changes'}
        </Button>
        {saveStatus === 'success' && (
          <span className={styles.statusSuccess}>
            <Check size={14} /> Settings saved
          </span>
        )}
        {saveStatus === 'error' && (
          <span className={styles.statusError}>
            <X size={14} /> Save failed
          </span>
        )}
      </div>

      {/* Version & Updates Section */}
      <div className={styles.dangerZone} style={{ background: 'rgba(59, 130, 246, 0.05)', borderColor: 'rgba(59, 130, 246, 0.2)' }}>
        <div className={styles.dangerHeader}>
          <Download size={18} style={{ color: 'var(--color-primary)' }} />
          <h4 style={{ color: 'var(--color-primary)' }}>Version & Updates</h4>
        </div>
        <p className={styles.dangerDescription}>
          {isCheckingUpdate ? (<>
            Current version: v{version}<br />
            Checking the latest version from GitHub...
          </>) : updateCheckDone && updateAvailable ? (<>
            Current version: v{version}<br />
            Latest version: v{latestVersion}<br />
            A newer version is available on GitHub. Updating will pull the latest code, install dependencies, and restart CraftBot automatically.
          </>) : updateCheckDone ? (<>
            Current version: v{version}<br />
            Latest version: v{latestVersion || version}<br />
            You are running the latest version. No updates are available at this time.
          </>) : (<>
            Current version: v{version}<br />
            Check GitHub for the latest available version.
          </>)}
        </p>
        {isCheckingUpdate ? (
          <Button
            variant="secondary"
            disabled
            icon={<Loader2 size={14} className={styles.spinning} />}
          >
            Checking...
          </Button>
        ) : updateCheckDone && updateAvailable ? (
          <Button
            variant="primary"
            onClick={handleDoUpdate}
            disabled={isUpdating}
            icon={isUpdating ? <Loader2 size={14} className={styles.spinning} /> : <Download size={14} />}
          >
            {isUpdating ? 'Updating...' : `Update to v${latestVersion}`}
          </Button>
        ) : (
          <Button
            variant="secondary"
            onClick={handleCheckUpdate}
            icon={<RefreshCw size={14} />}
          >
            Check for updates
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
          <h4>Reset Agent</h4>
        </div>
        <p className={styles.dangerDescription}>
          Reset the agent to its initial state. This will clear the current task, conversation history,
          and restore the agent file system from templates. Saved settings and credentials are preserved.
        </p>
        <Button
          variant="danger"
          onClick={handleReset}
          disabled={isResetting}
          icon={isResetting ? <Loader2 size={14} className={styles.spinning} /> : <RotateCcw size={14} />}
        >
          {isResetting ? 'Resetting...' : 'Reset Agent'}
        </Button>
        {resetStatus === 'success' && (
          <span className={styles.statusSuccess}>
            <Check size={14} /> Agent reset successfully
          </span>
        )}
        {resetStatus === 'error' && (
          <span className={styles.statusError}>
            <X size={14} /> Reset failed
          </span>
        )}
      </div>

      {/* Advanced Section */}
      <div className={styles.advancedSection}>
        <button
          className={styles.advancedToggle}
          onClick={() => setShowAdvanced(!showAdvanced)}
        >
          <FileText size={18} />
          <span>Advanced: Agent Configuration Files</span>
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
                  <Badge variant="info">User Profile</Badge>
                </div>
                <p className={styles.fileEditorDescription}>
                  This file contains your personal information and preferences that help the agent
                  understand how to interact with you. Editing this file will change how the agent
                  addresses you and tailors its responses to your preferences.
                </p>
              </div>
              <div className={styles.fileEditorContent}>
                {isLoadingUserMd ? (
                  <div className={styles.fileLoading}>
                    <Loader2 size={20} className={styles.spinning} />
                    <span>Loading USER.md...</span>
                  </div>
                ) : (
                  <textarea
                    className={styles.fileTextarea}
                    value={userMdContent}
                    onChange={(e) => setUserMdContent(e.target.value)}
                    placeholder="Loading..."
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
                  {isRestoringUserMd ? 'Restoring...' : 'Restore Default'}
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleSaveUserMd}
                  disabled={isSavingUserMd || isLoadingUserMd || !isUserMdDirty}
                >
                  {isSavingUserMd ? 'Saving...' : 'Save'}
                </Button>
                {userMdSaveStatus === 'success' && (
                  <span className={styles.statusSuccess}>
                    <Check size={14} /> Saved
                  </span>
                )}
                {userMdSaveStatus === 'error' && (
                  <span className={styles.statusError}>
                    <X size={14} /> Save failed
                  </span>
                )}
                {isUserMdDirty && userMdSaveStatus === 'idle' && (
                  <span className={styles.statusWarning}>
                    Unsaved changes
                  </span>
                )}
              </div>
            </div>

            {/* SOUL.md Editor */}
            <div className={styles.fileEditorCard}>
              <div className={styles.fileEditorHeader}>
                <div className={styles.fileEditorTitle}>
                  <h4>SOUL.md</h4>
                  <Badge variant="success">Personality</Badge>
                </div>
                <p className={styles.fileEditorDescription}>
                  This file defines the agent's personality, tone, and behavioral traits. It is injected
                  directly into the system prompt and shapes how the agent communicates. Edit this to give
                  your agent a unique character.
                </p>
              </div>
              <div className={styles.fileEditorContent}>
                {isLoadingSoulMd ? (
                  <div className={styles.fileLoading}>
                    <Loader2 size={20} className={styles.spinning} />
                    <span>Loading SOUL.md...</span>
                  </div>
                ) : (
                  <textarea
                    className={styles.fileTextarea}
                    value={soulMdContent}
                    onChange={(e) => setSoulMdContent(e.target.value)}
                    placeholder="Loading..."
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
                  {isRestoringSoulMd ? 'Restoring...' : 'Restore Default'}
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleSaveSoulMd}
                  disabled={isSavingSoulMd || isLoadingSoulMd || !isSoulMdDirty}
                >
                  {isSavingSoulMd ? 'Saving...' : 'Save'}
                </Button>
                {soulMdSaveStatus === 'success' && (
                  <span className={styles.statusSuccess}>
                    <Check size={14} /> Saved
                  </span>
                )}
                {soulMdSaveStatus === 'error' && (
                  <span className={styles.statusError}>
                    <X size={14} /> Save failed
                  </span>
                )}
                {isSoulMdDirty && soulMdSaveStatus === 'idle' && (
                  <span className={styles.statusWarning}>
                    Unsaved changes
                  </span>
                )}
              </div>
            </div>

            {/* AGENT.md Editor */}
            <div className={styles.fileEditorCard}>
              <div className={styles.fileEditorHeader}>
                <div className={styles.fileEditorTitle}>
                  <h4>AGENT.md</h4>
                  <Badge variant="warning">Agent Manual</Badge>
                </div>
                <p className={styles.fileEditorDescription}>
                  This file is the agent's instruction manual — it describes how the agent works, including
                  file handling, error handling, self-improvement protocols, and task execution guidelines.
                  The agent reads this on demand when it needs to understand its own mechanisms. Edit with caution.
                </p>
              </div>
              <div className={styles.fileEditorContent}>
                {isLoadingAgentMd ? (
                  <div className={styles.fileLoading}>
                    <Loader2 size={20} className={styles.spinning} />
                    <span>Loading AGENT.md...</span>
                  </div>
                ) : (
                  <textarea
                    className={styles.fileTextarea}
                    value={agentMdContent}
                    onChange={(e) => setAgentMdContent(e.target.value)}
                    placeholder="Loading..."
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
                  {isRestoringAgentMd ? 'Restoring...' : 'Restore Default'}
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleSaveAgentMd}
                  disabled={isSavingAgentMd || isLoadingAgentMd || !isAgentMdDirty}
                >
                  {isSavingAgentMd ? 'Saving...' : 'Save'}
                </Button>
                {agentMdSaveStatus === 'success' && (
                  <span className={styles.statusSuccess}>
                    <Check size={14} /> Saved
                  </span>
                )}
                {agentMdSaveStatus === 'error' && (
                  <span className={styles.statusError}>
                    <X size={14} /> Save failed
                  </span>
                )}
                {isAgentMdDirty && agentMdSaveStatus === 'idle' && (
                  <span className={styles.statusWarning}>
                    Unsaved changes
                  </span>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Confirm Modal */}
      <ConfirmModal {...confirmModalProps} />
    </div>
  )
}
