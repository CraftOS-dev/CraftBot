import React, { useState, useEffect, useCallback, useRef } from 'react'
import {
  Settings,
  Brain,
  Database,
  Cpu,
  Plug,
  Package,
  Globe,
  ChevronRight,
  RotateCcw,
  FileText,
  AlertTriangle,
  Check,
  X,
  Loader2,
  Plus,
  Edit2,
  Trash2,
  Power,
  Wrench
} from 'lucide-react'
import { Button, Badge } from '../../components/ui'
import styles from './SettingsPage.module.css'

type SettingsCategory =
  | 'general'
  | 'proactive'
  | 'memory'
  | 'model'
  | 'mcps'
  | 'skills'
  | 'integrations'

interface SettingsCategoryItem {
  id: SettingsCategory
  label: string
  icon: React.ReactNode
  description: string
}

const categories: SettingsCategoryItem[] = [
  {
    id: 'general',
    label: 'General',
    icon: <Settings size={18} />,
    description: 'Agent name, theme, and reset options',
  },
  {
    id: 'proactive',
    label: 'Proactive',
    icon: <Brain size={18} />,
    description: 'Autonomous behavior settings',
  },
  {
    id: 'memory',
    label: 'Memory',
    icon: <Database size={18} />,
    description: 'Agent memory and context settings',
  },
  {
    id: 'model',
    label: 'Model',
    icon: <Cpu size={18} />,
    description: 'AI model selection and API keys',
  },
  {
    id: 'mcps',
    label: 'MCPs',
    icon: <Plug size={18} />,
    description: 'Model Context Protocol servers',
  },
  {
    id: 'skills',
    label: 'Skills',
    icon: <Package size={18} />,
    description: 'Manage agent skills',
  },
  {
    id: 'integrations',
    label: 'Integrations',
    icon: <Globe size={18} />,
    description: 'Discord, Slack, Google Workspace',
  },
]

// Custom hook for settings-related WebSocket operations
function useSettingsWebSocket() {
  const wsRef = useRef<WebSocket | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const messageHandlersRef = useRef<Map<string, (data: unknown) => void>>(new Map())

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => setIsConnected(true)
    ws.onclose = () => setIsConnected(false)

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        const handler = messageHandlersRef.current.get(msg.type)
        if (handler) {
          handler(msg.data)
        }
      } catch (err) {
        console.error('[Settings WS] Failed to parse message:', err)
      }
    }

    return () => {
      ws.close()
    }
  }, [])

  const send = useCallback((type: string, data: Record<string, unknown> = {}) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type, ...data }))
    }
  }, [])

  const onMessage = useCallback((type: string, handler: (data: unknown) => void) => {
    messageHandlersRef.current.set(type, handler)
    return () => {
      messageHandlersRef.current.delete(type)
    }
  }, [])

  return { send, onMessage, isConnected }
}

export function SettingsPage() {
  const [activeCategory, setActiveCategory] = useState<SettingsCategory>('general')

  const renderSettingsContent = () => {
    switch (activeCategory) {
      case 'general':
        return <GeneralSettings />
      case 'proactive':
        return <ProactiveSettings />
      case 'memory':
        return <MemorySettings />
      case 'model':
        return <ModelSettings />
      case 'mcps':
        return <MCPSettings />
      case 'skills':
        return <SkillsSettings />
      case 'integrations':
        return <IntegrationsSettings />
      default:
        return null
    }
  }

  return (
    <div className={styles.settingsPage}>
      {/* Sidebar */}
      <nav className={styles.sidebar}>
        <div className={styles.sidebarHeader}>
          <h2>Settings</h2>
        </div>
        <div className={styles.categoryList}>
          {categories.map(cat => (
            <button
              key={cat.id}
              className={`${styles.categoryItem} ${activeCategory === cat.id ? styles.active : ''}`}
              onClick={() => setActiveCategory(cat.id)}
            >
              <span className={styles.categoryIcon}>{cat.icon}</span>
              <div className={styles.categoryInfo}>
                <span className={styles.categoryLabel}>{cat.label}</span>
                <span className={styles.categoryDesc}>{cat.description}</span>
              </div>
              <ChevronRight size={14} className={styles.chevron} />
            </button>
          ))}
        </div>
      </nav>

      {/* Content */}
      <div className={styles.content}>
        {renderSettingsContent()}
      </div>
    </div>
  )
}

// Settings Sections

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

// Convert cron expression to human-readable format
function formatCronExpression(cron: string): string {
  const parts = cron.split(' ')
  if (parts.length !== 5) return cron // Return as-is if invalid

  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts

  // Helper to format time
  const formatTime = (h: string, m: string): string => {
    const hourNum = parseInt(h, 10)
    const minNum = parseInt(m, 10)
    const period = hourNum >= 12 ? 'PM' : 'AM'
    const displayHour = hourNum === 0 ? 12 : hourNum > 12 ? hourNum - 12 : hourNum
    const displayMin = minNum.toString().padStart(2, '0')
    return `${displayHour}:${displayMin} ${period}`
  }

  // Helper for day suffix
  const getDaySuffix = (day: number): string => {
    if (day >= 11 && day <= 13) return 'th'
    switch (day % 10) {
      case 1: return 'st'
      case 2: return 'nd'
      case 3: return 'rd'
      default: return 'th'
    }
  }

  // Day of week names
  const dayNames: Record<string, string> = {
    '0': 'Sunday', '7': 'Sunday',
    '1': 'Monday', '2': 'Tuesday', '3': 'Wednesday',
    '4': 'Thursday', '5': 'Friday', '6': 'Saturday'
  }

  // Hourly: minute is fixed, everything else is *
  if (hour === '*' && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    const minNum = parseInt(minute, 10)
    if (minNum === 0) return 'Every hour at :00'
    return `Every hour at :${minute.padStart(2, '0')}`
  }

  // Daily: hour and minute fixed, rest is *
  if (dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    return `Daily at ${formatTime(hour, minute)}`
  }

  // Weekly: day of week is set
  if (dayOfMonth === '*' && month === '*' && dayOfWeek !== '*') {
    const dayName = dayNames[dayOfWeek] || dayOfWeek
    return `Weekly on ${dayName} at ${formatTime(hour, minute)}`
  }

  // Monthly: day of month is set
  if (dayOfMonth !== '*' && month === '*' && dayOfWeek === '*') {
    const dayNum = parseInt(dayOfMonth, 10)
    return `Monthly on the ${dayNum}${getDaySuffix(dayNum)} at ${formatTime(hour, minute)}`
  }

  // Default: return a more readable version
  return `Cron: ${cron}`
}

function GeneralSettings() {
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const [agentName, setAgentName] = useState(getInitialAgentName)
  const [initialAgentName, setInitialAgentName] = useState(getInitialAgentName)
  const [theme, setTheme] = useState(getInitialTheme)
  const [initialTheme, setInitialTheme] = useState(getInitialTheme)
  const [isResetting, setIsResetting] = useState(false)
  const [resetStatus, setResetStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [isSaving, setIsSaving] = useState(false)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')

  // Agent file states
  const [userMdContent, setUserMdContent] = useState('')
  const [originalUserMdContent, setOriginalUserMdContent] = useState('')
  const [agentMdContent, setAgentMdContent] = useState('')
  const [originalAgentMdContent, setOriginalAgentMdContent] = useState('')
  // Refs to track current content for closure-safe callbacks
  const userMdContentRef = useRef(userMdContent)
  const agentMdContentRef = useRef(agentMdContent)
  userMdContentRef.current = userMdContent
  agentMdContentRef.current = agentMdContent
  const [isLoadingUserMd, setIsLoadingUserMd] = useState(false)
  const [isLoadingAgentMd, setIsLoadingAgentMd] = useState(false)
  const [isSavingUserMd, setIsSavingUserMd] = useState(false)
  const [isSavingAgentMd, setIsSavingAgentMd] = useState(false)
  const [isRestoringUserMd, setIsRestoringUserMd] = useState(false)
  const [isRestoringAgentMd, setIsRestoringAgentMd] = useState(false)
  const [userMdSaveStatus, setUserMdSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [agentMdSaveStatus, setAgentMdSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')
  const [showAdvanced, setShowAdvanced] = useState(false)

  // Computed dirty states
  const isUserMdDirty = userMdContent !== originalUserMdContent
  const isAgentMdDirty = agentMdContent !== originalAgentMdContent
  const isGeneralSettingsDirty = agentName !== initialAgentName || theme !== initialTheme

  // Apply theme on mount and when it changes
  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  // Listen for system theme changes when using 'system' theme
  useEffect(() => {
    if (theme !== 'system') return

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const handleChange = () => applyTheme('system')

    mediaQuery.addEventListener('change', handleChange)
    return () => mediaQuery.removeEventListener('change', handleChange)
  }, [theme])

  // Load initial settings and files
  useEffect(() => {
    if (!isConnected) return

    // Set up message handlers
    const cleanups = [
      onMessage('settings_get', (data: unknown) => {
        const d = data as { success: boolean; settings?: { agentName: string; theme: string } }
        if (d.success && d.settings) {
          setAgentName(d.settings.agentName)
          setTheme(d.settings.theme)
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
        }
      }),
      onMessage('agent_file_write', (data: unknown) => {
        const d = data as { filename: string; success: boolean }
        if (d.filename === 'USER.md') {
          setIsSavingUserMd(false)
          if (d.success) {
            setOriginalUserMdContent(userMdContentRef.current) // Use ref for closure-safe access
          }
          setUserMdSaveStatus(d.success ? 'success' : 'error')
          setTimeout(() => setUserMdSaveStatus('idle'), 3000)
        } else if (d.filename === 'AGENT.md') {
          setIsSavingAgentMd(false)
          if (d.success) {
            setOriginalAgentMdContent(agentMdContentRef.current) // Use ref for closure-safe access
          }
          setAgentMdSaveStatus(d.success ? 'success' : 'error')
          setTimeout(() => setAgentMdSaveStatus('idle'), 3000)
        }
      }),
      onMessage('agent_file_restore', (data: unknown) => {
        const d = data as { filename: string; content: string; success: boolean }
        if (d.filename === 'USER.md') {
          setIsRestoringUserMd(false)
          if (d.success) {
            setUserMdContent(d.content)
            setOriginalUserMdContent(d.content) // Also update original
            setUserMdSaveStatus('success')
            setTimeout(() => setUserMdSaveStatus('idle'), 3000)
          }
        } else if (d.filename === 'AGENT.md') {
          setIsRestoringAgentMd(false)
          if (d.success) {
            setAgentMdContent(d.content)
            setOriginalAgentMdContent(d.content) // Also update original
            setAgentMdSaveStatus('success')
            setTimeout(() => setAgentMdSaveStatus('idle'), 3000)
          }
        }
      }),
    ]

    // Request initial data
    send('settings_get')

    return () => {
      cleanups.forEach(cleanup => cleanup())
    }
  }, [isConnected, send, onMessage])

  // Load advanced files when section is opened
  useEffect(() => {
    if (showAdvanced && isConnected) {
      setIsLoadingUserMd(true)
      setIsLoadingAgentMd(true)
      send('agent_file_read', { filename: 'USER.md' })
      send('agent_file_read', { filename: 'AGENT.md' })
    }
  }, [showAdvanced, isConnected, send])

  const handleSaveSettings = () => {
    setIsSaving(true)

    // Persist agent name to localStorage
    localStorage.setItem('craftbot-agent-name', agentName)

    // Theme is already applied and persisted via applyTheme()
    // Just update the initial values to mark as not dirty
    setInitialAgentName(agentName)
    setInitialTheme(theme)

    // Send to backend (for potential server-side persistence)
    send('settings_update', { settings: { agentName, theme } })

    // Show success feedback
    setIsSaving(false)
    setSaveStatus('success')
    setTimeout(() => setSaveStatus('idle'), 3000)
  }

  const handleReset = () => {
    if (window.confirm('Are you sure you want to reset the agent? This will clear all current tasks, conversation history, and restore the agent file system to its default state.')) {
      setIsResetting(true)
      send('reset')
    }
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
    if (window.confirm('Are you sure you want to restore USER.md to its default template? This will overwrite your current customizations.')) {
      setIsRestoringUserMd(true)
      send('agent_file_restore', { filename: 'USER.md' })
    }
  }

  const handleRestoreAgentMd = () => {
    if (window.confirm('Are you sure you want to restore AGENT.md to its default template? This will overwrite your current customizations.')) {
      setIsRestoringAgentMd(true)
      send('agent_file_restore', { filename: 'AGENT.md' })
    }
  }

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>General Settings</h3>
        <p>Configure basic agent settings and preferences</p>
      </div>

      <div className={styles.settingsForm}>
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

            {/* AGENT.md Editor */}
            <div className={styles.fileEditorCard}>
              <div className={styles.fileEditorHeader}>
                <div className={styles.fileEditorTitle}>
                  <h4>AGENT.md</h4>
                  <Badge variant="warning">Agent Identity</Badge>
                </div>
                <p className={styles.fileEditorDescription}>
                  This file defines the agent's identity, behavior guidelines, documentation standards,
                  and error handling philosophy. Changes here will affect how the agent approaches tasks,
                  handles errors, and formats its outputs. Edit with caution.
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
    </div>
  )
}

// Types for proactive settings
interface ScheduleConfig {
  id: string
  name: string
  schedule: string
  enabled: boolean
  priority: number
  payload?: { type: string; frequency?: string; scope?: string }
}

interface ProactiveTask {
  id: string
  name: string
  frequency: string
  instruction: string
  enabled: boolean
  priority: number
  permissionTier: number
  time?: string
  day?: string
  runCount: number
  lastRun?: string
  nextRun?: string
  outcomeHistory: Array<{ timestamp: string; result: string; success: boolean }>
}

function ProactiveSettings() {
  const { send, onMessage, isConnected } = useSettingsWebSocket()

  // Scheduler state
  const [schedulerEnabled, setSchedulerEnabled] = useState(true)
  const [schedules, setSchedules] = useState<ScheduleConfig[]>([])
  const [isLoadingScheduler, setIsLoadingScheduler] = useState(true)

  // Proactive tasks state
  const [tasks, setTasks] = useState<ProactiveTask[]>([])
  const [isLoadingTasks, setIsLoadingTasks] = useState(true)

  // UI state
  const [showTaskForm, setShowTaskForm] = useState(false)
  const [editingTask, setEditingTask] = useState<ProactiveTask | null>(null)
  const [isResettingTasks, setIsResettingTasks] = useState(false)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')

  // Load data when connected
  useEffect(() => {
    if (!isConnected) return

    const cleanups = [
      onMessage('scheduler_config_get', (data: unknown) => {
        const d = data as { success: boolean; config?: { enabled: boolean; schedules: ScheduleConfig[] } }
        setIsLoadingScheduler(false)
        if (d.success && d.config) {
          setSchedulerEnabled(d.config.enabled)
          setSchedules(d.config.schedules || [])
        }
      }),
      onMessage('scheduler_config_update', (data: unknown) => {
        const d = data as { success: boolean; config?: { enabled: boolean; schedules: ScheduleConfig[] } }
        if (d.success && d.config) {
          setSchedulerEnabled(d.config.enabled)
          setSchedules(d.config.schedules || [])
          setSaveStatus('success')
          setTimeout(() => setSaveStatus('idle'), 2000)
        }
      }),
      onMessage('proactive_tasks_get', (data: unknown) => {
        const d = data as { success: boolean; tasks: ProactiveTask[] }
        setIsLoadingTasks(false)
        if (d.success) {
          setTasks(d.tasks || [])
        }
      }),
      onMessage('proactive_task_add', (data: unknown) => {
        const d = data as { success: boolean }
        if (d.success) {
          send('proactive_tasks_get')
          setShowTaskForm(false)
          setEditingTask(null)
        }
      }),
      onMessage('proactive_task_update', (data: unknown) => {
        const d = data as { success: boolean }
        if (d.success) {
          send('proactive_tasks_get')
          setShowTaskForm(false)
          setEditingTask(null)
        }
      }),
      onMessage('proactive_task_remove', (data: unknown) => {
        const d = data as { success: boolean }
        if (d.success) {
          send('proactive_tasks_get')
        }
      }),
      onMessage('proactive_tasks_reset', (data: unknown) => {
        const d = data as { success: boolean }
        setIsResettingTasks(false)
        if (d.success) {
          send('proactive_tasks_get')
        }
      }),
    ]

    // Load initial data
    send('scheduler_config_get')
    send('proactive_tasks_get')

    return () => cleanups.forEach(c => c())
  }, [isConnected, send, onMessage])

  // Get schedule by ID
  const getSchedule = (id: string) => schedules.find(s => s.id === id)

  // Toggle scheduler globally
  const handleToggleScheduler = (enabled: boolean) => {
    setSchedulerEnabled(enabled)
    send('scheduler_config_update', { updates: { enabled } })
  }

  // Toggle individual schedule
  const handleToggleSchedule = (scheduleId: string, enabled: boolean) => {
    send('scheduler_config_update', {
      updates: { schedules: [{ id: scheduleId, enabled }] }
    })
  }

  // Handle adding a new task
  const handleAddTask = () => {
    setEditingTask(null)
    setShowTaskForm(true)
  }

  // Handle editing a task
  const handleEditTask = (task: ProactiveTask) => {
    setEditingTask(task)
    setShowTaskForm(true)
  }

  // Handle task toggle
  const handleToggleTask = (taskId: string, enabled: boolean) => {
    send('proactive_task_update', { taskId, updates: { enabled } })
    // Optimistic update
    setTasks(prev => prev.map(t => t.id === taskId ? { ...t, enabled } : t))
  }

  // Handle task deletion
  const handleDeleteTask = (taskId: string) => {
    if (window.confirm('Are you sure you want to delete this task?')) {
      send('proactive_task_remove', { taskId })
    }
  }

  // Handle reset all tasks
  const handleResetTasks = () => {
    if (window.confirm('Are you sure you want to reset all proactive tasks? This will restore the default PROACTIVE.md from template.')) {
      setIsResettingTasks(true)
      send('proactive_tasks_reset')
    }
  }

  // Group tasks by frequency
  const tasksByFrequency = {
    hourly: tasks.filter(t => t.frequency === 'hourly'),
    daily: tasks.filter(t => t.frequency === 'daily'),
    weekly: tasks.filter(t => t.frequency === 'weekly'),
    monthly: tasks.filter(t => t.frequency === 'monthly'),
  }

  // Heartbeat schedules
  const heartbeatSchedules = [
    { id: 'hourly-heartbeat', label: 'Hourly Heartbeat', desc: 'Runs every hour to check and execute hourly tasks' },
    { id: 'daily-heartbeat', label: 'Daily Heartbeat', desc: 'Runs once daily to execute daily tasks' },
    { id: 'weekly-heartbeat', label: 'Weekly Heartbeat', desc: 'Runs weekly to execute weekly tasks' },
    { id: 'monthly-heartbeat', label: 'Monthly Heartbeat', desc: 'Runs monthly to execute monthly tasks' },
  ]

  // Planner schedules
  const plannerSchedules = [
    { id: 'day-planner', label: 'Daily Planner', desc: 'Plans daily activities and priorities' },
    { id: 'week-planner', label: 'Weekly Planner', desc: 'Plans weekly goals and tasks' },
    { id: 'month-planner', label: 'Monthly Planner', desc: 'Plans monthly objectives and reviews' },
  ]

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>Proactive Behavior</h3>
        <p>Configure when the agent acts autonomously and manages scheduled tasks</p>
      </div>

      {/* Master Toggle */}
      <div className={styles.settingsForm}>
        <div className={styles.toggleGroup}>
          <div className={styles.toggleInfo}>
            <span className={styles.toggleLabel}>Enable Proactive Mode</span>
            <span className={styles.toggleDesc}>
              Allow agent to execute scheduled tasks and proactive behaviors automatically
            </span>
          </div>
          <input
            type="checkbox"
            className={styles.toggle}
            checked={schedulerEnabled}
            onChange={(e) => handleToggleScheduler(e.target.checked)}
            disabled={isLoadingScheduler}
          />
        </div>
      </div>

      {/* Heartbeat Schedules */}
      <div className={styles.subsection}>
        <h4 className={styles.subsectionTitle}>Heartbeat Schedules</h4>
        <p className={styles.subsectionDesc}>
          Heartbeats periodically check and execute proactive tasks based on their frequency
        </p>
        <div className={styles.scheduleList}>
          {heartbeatSchedules.map(item => {
            const schedule = getSchedule(item.id)
            return (
              <div key={item.id} className={styles.scheduleCard}>
                <div className={styles.scheduleInfo}>
                  <span className={styles.scheduleName}>{item.label}</span>
                  <span className={styles.scheduleDesc}>{item.desc}</span>
                  {schedule && (
                    <span className={styles.scheduleTime}>{formatCronExpression(schedule.schedule)}</span>
                  )}
                </div>
                <input
                  type="checkbox"
                  className={styles.toggle}
                  checked={schedule?.enabled ?? false}
                  onChange={(e) => handleToggleSchedule(item.id, e.target.checked)}
                  disabled={isLoadingScheduler || !schedulerEnabled}
                />
              </div>
            )
          })}
        </div>
      </div>

      {/* Planners */}
      <div className={styles.subsection}>
        <h4 className={styles.subsectionTitle}>Planners</h4>
        <p className={styles.subsectionDesc}>
          Planners review recent interactions and plan proactive activities
        </p>
        <div className={styles.scheduleList}>
          {plannerSchedules.map(item => {
            const schedule = getSchedule(item.id)
            return (
              <div key={item.id} className={styles.scheduleCard}>
                <div className={styles.scheduleInfo}>
                  <span className={styles.scheduleName}>{item.label}</span>
                  <span className={styles.scheduleDesc}>{item.desc}</span>
                  {schedule && (
                    <span className={styles.scheduleTime}>{formatCronExpression(schedule.schedule)}</span>
                  )}
                </div>
                <input
                  type="checkbox"
                  className={styles.toggle}
                  checked={schedule?.enabled ?? false}
                  onChange={(e) => handleToggleSchedule(item.id, e.target.checked)}
                  disabled={isLoadingScheduler || !schedulerEnabled}
                />
              </div>
            )
          })}
        </div>
      </div>

      {/* Proactive Tasks */}
      <div className={styles.subsection}>
        <div className={styles.subsectionHeader}>
          <div>
            <h4 className={styles.subsectionTitle}>Proactive Tasks</h4>
            <p className={styles.subsectionDesc}>
              Tasks defined in PROACTIVE.md that the agent executes during heartbeats
            </p>
          </div>
          <Button variant="primary" size="sm" onClick={handleAddTask} icon={<Plus size={14} />}>
            Add Task
          </Button>
        </div>

        {isLoadingTasks ? (
          <div className={styles.loadingState}>
            <Loader2 size={20} className={styles.spinning} />
            <span>Loading tasks...</span>
          </div>
        ) : tasks.length === 0 ? (
          <div className={styles.emptyState}>
            <p>No proactive tasks defined yet.</p>
            <Button variant="secondary" size="sm" onClick={handleAddTask}>
              Create your first task
            </Button>
          </div>
        ) : (
          <div className={styles.taskGroups}>
            {(['hourly', 'daily', 'weekly', 'monthly'] as const).map(frequency => {
              const freqTasks = tasksByFrequency[frequency]
              if (freqTasks.length === 0) return null

              return (
                <div key={frequency} className={styles.taskGroup}>
                  <div className={styles.taskGroupHeader}>
                    <Badge variant="default">{frequency}</Badge>
                    <span className={styles.taskCount}>{freqTasks.length} task{freqTasks.length !== 1 ? 's' : ''}</span>
                  </div>
                  <div className={styles.taskList}>
                    {freqTasks.map(task => (
                      <div key={task.id} className={`${styles.taskCard} ${!task.enabled ? styles.taskDisabled : ''}`}>
                        <div className={styles.taskMain}>
                          <div className={styles.taskHeader}>
                            <span className={styles.taskName}>{task.name}</span>
                            <div className={styles.taskBadges}>
                              <Badge variant={task.enabled ? 'success' : 'default'}>
                                {task.enabled ? 'Active' : 'Disabled'}
                              </Badge>
                              <Badge variant="info">{getPriorityLabel(task.priority)}</Badge>
                              <Badge variant={task.permissionTier >= 1 ? 'warning' : 'default'}>
                                {getNotificationLabel(task.permissionTier)}
                              </Badge>
                            </div>
                          </div>
                          <p className={styles.taskInstruction}>{task.instruction}</p>
                          <div className={styles.taskMeta}>
                            {task.time && <span>Time: {task.time}</span>}
                            {task.day && <span>Day: {task.day}</span>}
                            <span>Runs: {task.runCount}</span>
                            {task.lastRun && (
                              <span>Last: {new Date(task.lastRun).toLocaleDateString()}</span>
                            )}
                          </div>
                        </div>
                        <div className={styles.taskActions}>
                          <input
                            type="checkbox"
                            className={styles.toggle}
                            checked={task.enabled}
                            onChange={(e) => handleToggleTask(task.id, e.target.checked)}
                          />
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleEditTask(task)}
                            icon={<Edit2 size={14} />}
                          />
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDeleteTask(task.id)}
                            icon={<Trash2 size={14} />}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Reset Tasks */}
      <div className={styles.dangerZone}>
        <div className={styles.dangerHeader}>
          <AlertTriangle size={18} className={styles.dangerIcon} />
          <h4>Reset Proactive Tasks</h4>
        </div>
        <p className={styles.dangerDescription}>
          This will remove all proactive tasks and restore PROACTIVE.md from the default template.
          This action cannot be undone.
        </p>
        <Button
          variant="danger"
          onClick={handleResetTasks}
          disabled={isResettingTasks}
          icon={isResettingTasks ? <Loader2 size={14} className={styles.spinning} /> : <RotateCcw size={14} />}
        >
          {isResettingTasks ? 'Resetting...' : 'Reset All Tasks'}
        </Button>
      </div>

      {/* Task Form Modal */}
      {showTaskForm && (
        <TaskFormModal
          task={editingTask}
          onClose={() => {
            setShowTaskForm(false)
            setEditingTask(null)
          }}
          onSave={(taskData) => {
            if (editingTask) {
              send('proactive_task_update', { taskId: editingTask.id, updates: taskData })
            } else {
              send('proactive_task_add', { task: taskData })
            }
          }}
        />
      )}
    </div>
  )
}

// Helper functions for task display
function getPriorityLabel(value: number): string {
  if (value <= 35) return 'High'
  if (value <= 55) return 'Medium'
  return 'Low'
}

function getNotificationLabel(tier: number): string {
  return tier >= 1 ? 'Notifies' : 'Silent'
}

// Task Form Modal Component
interface TaskFormModalProps {
  task: ProactiveTask | null
  onClose: () => void
  onSave: (taskData: Partial<ProactiveTask>) => void
}

// Priority level mappings (lower number = higher priority)
type PriorityLevel = 'high' | 'medium' | 'low'
const PRIORITY_VALUES: Record<PriorityLevel, number> = {
  high: 30,
  medium: 50,
  low: 70,
}

function getPriorityLevel(value: number): PriorityLevel {
  if (value <= 35) return 'high'
  if (value <= 55) return 'medium'
  return 'low'
}

function TaskFormModal({ task, onClose, onSave }: TaskFormModalProps) {
  const [name, setName] = useState(task?.name || '')
  const [frequency, setFrequency] = useState(task?.frequency || 'daily')
  const [instruction, setInstruction] = useState(task?.instruction || '')
  const [enabled, setEnabled] = useState(task?.enabled ?? true)
  const [priorityLevel, setPriorityLevel] = useState<PriorityLevel>(
    task ? getPriorityLevel(task.priority) : 'medium'
  )
  // Checkbox: true = notify before running (tier 1), false = silent (tier 0)
  const [notifyBeforeRunning, setNotifyBeforeRunning] = useState(
    task ? task.permissionTier >= 1 : true
  )
  const [time, setTime] = useState(task?.time || '')
  const [day, setDay] = useState(task?.day || '')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSave({
      name,
      frequency,
      instruction,
      enabled,
      priority: PRIORITY_VALUES[priorityLevel],
      permissionTier: notifyBeforeRunning ? 1 : 0,
      time: time || undefined,
      day: day || undefined,
    })
  }

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <h3>{task ? 'Edit Task' : 'Add Proactive Task'}</h3>
          <button className={styles.modalClose} onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className={styles.modalBody}>
            <div className={styles.formGroup}>
              <label>Task Name</label>
              <input
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="e.g., Check emails"
                required
              />
            </div>

            <div className={styles.formRow}>
              <div className={styles.formGroup}>
                <label>Frequency</label>
                <select value={frequency} onChange={e => setFrequency(e.target.value)}>
                  <option value="hourly">Hourly</option>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                </select>
              </div>

              <div className={styles.formGroup}>
                <label>Priority <span className={styles.labelHint}>(higher runs first)</span></label>
                <select value={priorityLevel} onChange={e => setPriorityLevel(e.target.value as PriorityLevel)}>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
              </div>
            </div>

            <div className={styles.formRow}>
              {frequency !== 'hourly' && (
                <div className={styles.formGroup}>
                  <label>Time (HH:MM)</label>
                  <input
                    type="time"
                    value={time}
                    onChange={e => setTime(e.target.value)}
                  />
                </div>
              )}

              {frequency === 'weekly' && (
                <div className={styles.formGroup}>
                  <label>Day of Week</label>
                  <select value={day} onChange={e => setDay(e.target.value)}>
                    <option value="">Select day</option>
                    <option value="monday">Monday</option>
                    <option value="tuesday">Tuesday</option>
                    <option value="wednesday">Wednesday</option>
                    <option value="thursday">Thursday</option>
                    <option value="friday">Friday</option>
                    <option value="saturday">Saturday</option>
                    <option value="sunday">Sunday</option>
                  </select>
                </div>
              )}
            </div>

            <div className={styles.toggleGroup}>
              <div className={styles.toggleInfo}>
                <span className={styles.toggleLabel}>Notify me before running</span>
                <span className={styles.toggleDesc}>
                  When enabled, the agent will inform you before executing this task.
                  When disabled, the task runs silently.
                </span>
              </div>
              <input
                type="checkbox"
                className={styles.toggle}
                checked={notifyBeforeRunning}
                onChange={e => setNotifyBeforeRunning(e.target.checked)}
              />
            </div>

            <div className={styles.formGroup}>
              <label>Instruction</label>
              <textarea
                value={instruction}
                onChange={e => setInstruction(e.target.value)}
                placeholder="Describe what the agent should do..."
                rows={4}
                required
              />
              <span className={styles.hint}>
                Be specific and actionable. The agent will follow these instructions during execution.
              </span>
            </div>

            <div className={styles.toggleGroup}>
              <div className={styles.toggleInfo}>
                <span className={styles.toggleLabel}>Enabled</span>
                <span className={styles.toggleDesc}>Task will be executed during heartbeats</span>
              </div>
              <input
                type="checkbox"
                className={styles.toggle}
                checked={enabled}
                onChange={e => setEnabled(e.target.checked)}
              />
            </div>
          </div>

          <div className={styles.modalFooter}>
            <Button variant="secondary" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" type="submit">
              {task ? 'Save Changes' : 'Add Task'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

// Types for memory settings
interface MemoryItem {
  id: string
  timestamp: string
  category: string
  content: string
  raw: string
}

function MemorySettings() {
  const { send, onMessage, isConnected } = useSettingsWebSocket()

  // Memory mode state
  const [memoryEnabled, setMemoryEnabled] = useState(true)
  const [isLoadingMode, setIsLoadingMode] = useState(true)

  // Memory items state
  const [items, setItems] = useState<MemoryItem[]>([])
  const [isLoadingItems, setIsLoadingItems] = useState(true)

  // UI state
  const [showItemForm, setShowItemForm] = useState(false)
  const [editingItem, setEditingItem] = useState<MemoryItem | null>(null)
  const [isResetting, setIsResetting] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // Sort state
  const [sortOrder, setSortOrder] = useState<'latest' | 'oldest'>('latest')

  // Load data when connected
  useEffect(() => {
    if (!isConnected) return

    const cleanups = [
      onMessage('memory_mode_get', (data: unknown) => {
        const d = data as { success: boolean; enabled: boolean }
        setIsLoadingMode(false)
        if (d.success) {
          setMemoryEnabled(d.enabled)
        }
      }),
      onMessage('memory_mode_set', (data: unknown) => {
        const d = data as { success: boolean; enabled: boolean; error?: string }
        if (d.success) {
          setMemoryEnabled(d.enabled)
          showStatus('success', `Memory ${d.enabled ? 'enabled' : 'disabled'}`)
        } else {
          showStatus('error', d.error || 'Failed to update memory mode')
        }
      }),
      onMessage('memory_items_get', (data: unknown) => {
        const d = data as { success: boolean; items: MemoryItem[] }
        setIsLoadingItems(false)
        if (d.success) {
          setItems(d.items || [])
        }
      }),
      onMessage('memory_item_add', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        if (d.success) {
          send('memory_items_get')
          setShowItemForm(false)
          setEditingItem(null)
          showStatus('success', 'Memory item added')
        } else {
          showStatus('error', d.error || 'Failed to add memory item')
        }
      }),
      onMessage('memory_item_update', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        if (d.success) {
          send('memory_items_get')
          setShowItemForm(false)
          setEditingItem(null)
          showStatus('success', 'Memory item updated')
        } else {
          showStatus('error', d.error || 'Failed to update memory item')
        }
      }),
      onMessage('memory_item_remove', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        if (d.success) {
          send('memory_items_get')
          showStatus('success', 'Memory item deleted')
        } else {
          showStatus('error', d.error || 'Failed to delete memory item')
        }
      }),
      onMessage('memory_reset', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        setIsResetting(false)
        if (d.success) {
          send('memory_items_get')
          showStatus('success', 'Memory reset to default')
        } else {
          showStatus('error', d.error || 'Failed to reset memory')
        }
      }),
      onMessage('memory_process_trigger', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        setIsProcessing(false)
        if (d.success) {
          showStatus('success', d.message || 'Memory processing started')
        } else {
          showStatus('error', d.error || 'Failed to start memory processing')
        }
      }),
    ]

    // Load initial data
    send('memory_mode_get')
    send('memory_items_get')

    return () => cleanups.forEach(c => c())
  }, [isConnected, send, onMessage])

  const showStatus = (type: 'success' | 'error', text: string) => {
    setStatusMessage({ type, text })
    setTimeout(() => setStatusMessage(null), 3000)
  }

  // Toggle memory mode
  const handleToggleMemory = (enabled: boolean) => {
    setMemoryEnabled(enabled)
    send('memory_mode_set', { enabled })
  }

  // Handle adding a new memory item
  const handleAddItem = () => {
    setEditingItem(null)
    setShowItemForm(true)
  }

  // Handle editing a memory item
  const handleEditItem = (item: MemoryItem) => {
    setEditingItem(item)
    setShowItemForm(true)
  }

  // Handle deleting a memory item
  const handleDeleteItem = (itemId: string) => {
    if (window.confirm('Are you sure you want to delete this memory item?')) {
      send('memory_item_remove', { itemId })
    }
  }

  // Handle manual memory processing
  const handleProcessMemory = () => {
    if (window.confirm('This will process all unprocessed events into long-term memory. Continue?')) {
      setIsProcessing(true)
      send('memory_process_trigger')
    }
  }

  // Handle reset memory
  const handleResetMemory = () => {
    if (window.confirm('Are you sure you want to reset all memory? This will clear all memory items and unprocessed events. This action cannot be undone.')) {
      setIsResetting(true)
      send('memory_reset')
    }
  }

  // Sort items by timestamp
  const sortedItems = [...items].sort((a, b) => {
    const dateA = new Date(a.timestamp).getTime()
    const dateB = new Date(b.timestamp).getTime()
    return sortOrder === 'latest' ? dateB - dateA : dateA - dateB
  })

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>Memory Settings</h3>
        <p>Manage agent memory, stored facts, and event processing</p>
      </div>

      {/* Status Message */}
      {statusMessage && (
        <div className={`${styles.statusBanner} ${statusMessage.type === 'success' ? styles.statusSuccess : styles.statusError}`}>
          {statusMessage.type === 'success' ? <Check size={14} /> : <X size={14} />}
          {statusMessage.text}
        </div>
      )}

      {/* Master Toggle */}
      <div className={styles.settingsForm}>
        <div className={styles.toggleGroup}>
          <div className={styles.toggleInfo}>
            <span className={styles.toggleLabel}>Enable Memory</span>
            <span className={styles.toggleDesc}>
              When enabled, the agent remembers facts from conversations and uses them in context.
              When disabled, memory search is skipped and new events are not logged.
            </span>
          </div>
          <input
            type="checkbox"
            className={styles.toggle}
            checked={memoryEnabled}
            onChange={(e) => handleToggleMemory(e.target.checked)}
            disabled={isLoadingMode}
          />
        </div>
      </div>

      {/* Memory Items */}
      <div className={styles.subsection}>
        <div className={styles.subsectionHeader}>
          <h4 className={styles.subsectionTitle}>Memory Items</h4>
          <div className={styles.headerActions}>
            <select
              className={styles.filterSelect}
              value={sortOrder}
              onChange={(e) => setSortOrder(e.target.value as 'latest' | 'oldest')}
            >
              <option value="latest">Newest first</option>
              <option value="oldest">Oldest first</option>
            </select>
            <Button variant="primary" size="sm" onClick={handleAddItem} icon={<Plus size={14} />}>
              Add Memory
            </Button>
          </div>
        </div>
        <p className={styles.subsectionDesc}>
          Long-term memories stored in MEMORY.md. These are facts the agent has learned from interactions.
        </p>

        {isLoadingItems ? (
          <div className={styles.loadingState}>
            <Loader2 size={20} className={styles.spinning} />
            <span>Loading memory items...</span>
          </div>
        ) : items.length === 0 ? (
          <div className={styles.emptyState}>
            <Database size={32} className={styles.emptyIcon} />
            <p>No memory items yet.</p>
            <p className={styles.emptyHint}>
              Memory items are created when the agent processes events or when you add them manually.
            </p>
            <Button variant="secondary" size="sm" onClick={handleAddItem}>
              Add your first memory
            </Button>
          </div>
        ) : (
          <div className={styles.memoryList}>
            {sortedItems.map(item => (
              <div key={item.id} className={styles.memoryCard}>
                <div className={styles.memoryMain}>
                  <div className={styles.memoryHeader}>
                    <Badge variant="info">{item.category}</Badge>
                    <span className={styles.memoryTimestamp}>{item.timestamp}</span>
                  </div>
                  <p className={styles.memoryContent}>{item.content}</p>
                </div>
                <div className={styles.memoryActions}>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleEditItem(item)}
                    icon={<Edit2 size={14} />}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleDeleteItem(item.id)}
                    icon={<Trash2 size={14} />}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Memory Processing */}
      <div className={styles.subsection}>
        <h4 className={styles.subsectionTitle}>Memory Processing</h4>
        <p className={styles.subsectionDesc}>
          Memory processing analyzes unprocessed events and extracts important facts into long-term memory.
          This normally runs automatically at 3 AM daily.
        </p>
        <Button
          variant="secondary"
          onClick={handleProcessMemory}
          disabled={isProcessing || !memoryEnabled}
          icon={isProcessing ? <Loader2 size={14} className={styles.spinning} /> : <Brain size={14} />}
        >
          {isProcessing ? 'Processing...' : 'Process Memory Now'}
        </Button>
        {!memoryEnabled && (
          <span className={styles.hint}>Enable memory to use this feature</span>
        )}
      </div>

      {/* Reset Memory */}
      <div className={styles.dangerZone}>
        <div className={styles.dangerHeader}>
          <AlertTriangle size={18} className={styles.dangerIcon} />
          <h4>Reset Memory</h4>
        </div>
        <p className={styles.dangerDescription}>
          This will clear all memory items in MEMORY.md and restore it from the default template.
          All unprocessed events will also be cleared. This action cannot be undone.
        </p>
        <Button
          variant="danger"
          onClick={handleResetMemory}
          disabled={isResetting}
          icon={isResetting ? <Loader2 size={14} className={styles.spinning} /> : <RotateCcw size={14} />}
        >
          {isResetting ? 'Resetting...' : 'Reset All Memory'}
        </Button>
      </div>

      {/* Memory Item Form Modal */}
      {showItemForm && (
        <MemoryItemFormModal
          item={editingItem}
          onClose={() => {
            setShowItemForm(false)
            setEditingItem(null)
          }}
          onSave={(itemData) => {
            if (editingItem) {
              send('memory_item_update', { itemId: editingItem.id, ...itemData })
            } else {
              send('memory_item_add', itemData)
            }
          }}
        />
      )}
    </div>
  )
}

// Memory Item Form Modal Component
interface MemoryItemFormModalProps {
  item: MemoryItem | null
  onClose: () => void
  onSave: (itemData: { category: string; content: string }) => void
}

function MemoryItemFormModal({ item, onClose, onSave }: MemoryItemFormModalProps) {
  const [category, setCategory] = useState(item?.category || 'preference')
  const [content, setContent] = useState(item?.content || '')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSave({ category: category.toLowerCase().trim(), content })
  }

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <h3>{item ? 'Edit Memory' : 'Add Memory Item'}</h3>
          <button className={styles.modalClose} onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className={styles.modalBody}>
            <div className={styles.formGroup}>
              <label>Category</label>
              <input
                type="text"
                value={category}
                onChange={e => setCategory(e.target.value)}
                placeholder="e.g., preference, fact, work, reminder"
                required
              />
              <span className={styles.hint}>
                Use categories like preference, fact, work, event, or reminder
              </span>
            </div>

            <div className={styles.formGroup}>
              <label>Content</label>
              <textarea
                value={content}
                onChange={e => setContent(e.target.value)}
                placeholder="Enter the memory content. Use clear, factual statements like 'User prefers dark mode' or 'John's birthday is March 15th'"
                rows={4}
                required
              />
              <span className={styles.hint}>
                Write in third person. The agent will reference this information in future conversations.
              </span>
            </div>
          </div>

          <div className={styles.modalFooter}>
            <Button variant="secondary" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" type="submit">
              {item ? 'Save Changes' : 'Add Memory'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

// Provider info type
interface ProviderInfo {
  id: string
  name: string
  requires_api_key: boolean
  api_key_env?: string
  base_url_env?: string
  llm_model: string | null
  vlm_model: string | null
  has_vlm: boolean
}

// API key status type
interface ApiKeyStatus {
  has_key: boolean
  masked_key: string
}

// Connection test result type
interface TestResult {
  success: boolean
  message: string
  error?: string
}

function ModelSettings() {
  const { send, onMessage, isConnected } = useSettingsWebSocket()

  // Provider list state
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [isLoading, setIsLoading] = useState(true)

  // Current settings state
  const [provider, setProvider] = useState('anthropic')
  const [apiKeys, setApiKeys] = useState<Record<string, ApiKeyStatus>>({})
  const [baseUrls, setBaseUrls] = useState<Record<string, string>>({})

  // Form state
  const [newApiKey, setNewApiKey] = useState('')
  const [newBaseUrl, setNewBaseUrl] = useState('')

  // UI state
  const [isSaving, setIsSaving] = useState(false)
  const [isTesting, setIsTesting] = useState(false)
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [hasChanges, setHasChanges] = useState(false)
  const [testResult, setTestResult] = useState<TestResult | null>(null)

  const showStatus = (type: 'success' | 'error', text: string) => {
    setStatusMessage({ type, text })
    setTimeout(() => setStatusMessage(null), 4000)
  }

  // Load data when connected
  useEffect(() => {
    if (!isConnected) return

    const cleanups = [
      onMessage('model_providers_get', (data: unknown) => {
        const d = data as { success: boolean; providers: ProviderInfo[] }
        if (d.success && d.providers) {
          setProviders(d.providers)
        }
        setIsLoading(false)
      }),
      onMessage('model_settings_get', (data: unknown) => {
        const d = data as {
          success: boolean
          llm_provider: string
          api_keys: Record<string, ApiKeyStatus>
          base_urls: Record<string, string>
        }
        if (d.success) {
          setProvider(d.llm_provider || 'anthropic')
          setApiKeys(d.api_keys || {})
          setBaseUrls(d.base_urls || {})
        }
      }),
      onMessage('model_settings_update', (data: unknown) => {
        const d = data as {
          success: boolean
          llm_provider?: string
          api_keys?: Record<string, ApiKeyStatus>
          base_urls?: Record<string, string>
          error?: string
        }
        setIsSaving(false)
        if (d.success) {
          if (d.llm_provider) setProvider(d.llm_provider)
          if (d.api_keys) setApiKeys(d.api_keys)
          if (d.base_urls) setBaseUrls(d.base_urls)
          setNewApiKey('')
          setNewBaseUrl('')
          setHasChanges(false)
          showStatus('success', 'Settings saved')
        } else {
          showStatus('error', d.error || 'Failed to save')
        }
      }),
      onMessage('model_connection_test', (data: unknown) => {
        const d = data as { success: boolean; message: string; error?: string }
        setIsTesting(false)
        setTestResult({
          success: d.success,
          message: d.message,
          error: d.error,
        })
      }),
    ]

    send('model_providers_get')
    send('model_settings_get')

    return () => cleanups.forEach(cleanup => cleanup())
  }, [isConnected, send, onMessage])

  const currentProvider = providers.find(p => p.id === provider)
  const hasKey = apiKeys[provider]?.has_key || newApiKey.length > 0
  const needsKey = currentProvider?.requires_api_key && !hasKey

  const handleProviderChange = (newProvider: string) => {
    setProvider(newProvider)
    setNewApiKey('')
    setNewBaseUrl('')
    setHasChanges(true)
  }

  const handleTestConnection = () => {
    setIsTesting(true)
    send('model_connection_test', {
      provider,
      apiKey: newApiKey || undefined,
      baseUrl: newBaseUrl || baseUrls[provider],
    })
  }

  const handleSave = () => {
    if (needsKey) {
      showStatus('error', 'API key is required')
      return
    }

    setIsSaving(true)
    send('model_settings_update', {
      llmProvider: provider,
      vlmProvider: provider,
      apiKey: newApiKey || undefined,
      providerForKey: newApiKey ? provider : undefined,
      baseUrl: newBaseUrl || undefined,
      providerForUrl: newBaseUrl ? provider : undefined,
    })
  }

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>Model Configuration</h3>
        <p>Configure AI provider and API key</p>
      </div>

      {statusMessage && (
        <div className={`${styles.statusMessage} ${styles[statusMessage.type]}`}>
          {statusMessage.type === 'success' ? <Check size={16} /> : <X size={16} />}
          <span>{statusMessage.text}</span>
        </div>
      )}

      {isLoading ? (
        <div className={styles.loadingState}>
          <Loader2 size={20} className={styles.spinning} />
          <span>Loading...</span>
        </div>
      ) : (
        <div className={styles.settingsForm}>
          {/* Provider Selection */}
          <div className={styles.formGroup}>
            <label>Provider</label>
            <select value={provider} onChange={(e) => handleProviderChange(e.target.value)}>
              {providers.map(p => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>

          {/* Model Info */}
          {currentProvider && (
            <div className={styles.modelInfo}>
              <div className={styles.modelRow}>
                <span className={styles.modelLabel}>LLM:</span>
                <span className={styles.modelValue}>{currentProvider.llm_model || 'N/A'}</span>
              </div>
              {currentProvider.has_vlm && (
                <div className={styles.modelRow}>
                  <span className={styles.modelLabel}>VLM:</span>
                  <span className={styles.modelValue}>{currentProvider.vlm_model || 'N/A'}</span>
                </div>
              )}
            </div>
          )}

          {/* API Key */}
          {currentProvider?.requires_api_key && (
            <div className={styles.formGroup}>
              <label>
                API Key
                {apiKeys[provider]?.has_key ? (
                  <Badge variant="success" style={{ marginLeft: 8 }}>Configured</Badge>
                ) : (
                  <Badge variant="warning" style={{ marginLeft: 8 }}>Required</Badge>
                )}
              </label>
              {apiKeys[provider]?.has_key && (
                <div className={styles.maskedKey}>{apiKeys[provider].masked_key}</div>
              )}
              <input
                type="password"
                value={newApiKey}
                onChange={(e) => { setNewApiKey(e.target.value); setHasChanges(true) }}
                placeholder={apiKeys[provider]?.has_key ? 'Enter new key to replace...' : 'Enter API key...'}
              />
            </div>
          )}

          {/* Base URL (for Ollama/BytePlus) */}
          {currentProvider?.base_url_env && (
            <div className={styles.formGroup}>
              <label>Server URL</label>
              <input
                type="text"
                value={newBaseUrl || baseUrls[provider] || ''}
                onChange={(e) => { setNewBaseUrl(e.target.value); setHasChanges(true) }}
                placeholder={provider === 'remote' ? 'http://localhost:11434' : 'Enter base URL...'}
              />
            </div>
          )}

          {/* Actions */}
          <div className={styles.sectionFooter}>
            <Button
              variant="secondary"
              onClick={handleTestConnection}
              disabled={isTesting || needsKey}
            >
              {isTesting ? (
                <>
                  <Loader2 size={14} className={styles.spinning} />
                  Testing...
                </>
              ) : (
                'Test Connection'
              )}
            </Button>
            <Button
              variant="primary"
              onClick={handleSave}
              disabled={isSaving || needsKey || !hasChanges}
            >
              {isSaving ? (
                <>
                  <Loader2 size={14} className={styles.spinning} />
                  Saving...
                </>
              ) : (
                'Save'
              )}
            </Button>
          </div>
        </div>
      )}

      {/* Connection Test Result Modal */}
      {testResult && (
        <div className={styles.modalOverlay} onClick={() => setTestResult(null)}>
          <div className={styles.testResultModal} onClick={e => e.stopPropagation()}>
            <div className={`${styles.testResultIcon} ${testResult.success ? styles.success : styles.error}`}>
              {testResult.success ? <Check size={32} /> : <X size={32} />}
            </div>
            <h3 className={styles.testResultTitle}>
              {testResult.success ? 'Connection Successful' : 'Connection Failed'}
            </h3>
            <p className={styles.testResultMessage}>
              {testResult.success ? testResult.message : (testResult.error || testResult.message)}
            </p>
            <Button variant="secondary" onClick={() => setTestResult(null)}>
              Close
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

// MCP Server config type
interface MCPServerConfig {
  name: string
  description: string
  enabled: boolean
  transport: string
  command?: string
  action_set: string
  env: Record<string, string>
}

// MCP item type for display
interface MCPItem {
  name: string
  description: string
  enabled: boolean
  transport?: string
  action_set?: string
  env?: Record<string, string>
  needsConfig?: boolean  // has empty env vars
}

function MCPSettings() {
  const { send, onMessage, isConnected } = useSettingsWebSocket()

  // State
  const [servers, setServers] = useState<MCPServerConfig[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // Search and reload
  const [searchQuery, setSearchQuery] = useState('')
  const [isReloading, setIsReloading] = useState(false)

  // Add custom server modal state
  const [showAddModal, setShowAddModal] = useState(false)
  const [customJsonConfig, setCustomJsonConfig] = useState('')
  const [isAdding, setIsAdding] = useState(false)
  const [addError, setAddError] = useState('')

  // Configure env state
  const [configServer, setConfigServer] = useState<MCPServerConfig | null>(null)
  const [envValues, setEnvValues] = useState<Record<string, string>>({})
  const [isSavingEnv, setIsSavingEnv] = useState(false)

  const showStatus = (type: 'success' | 'error', text: string) => {
    setStatusMessage({ type, text })
    setTimeout(() => setStatusMessage(null), 3000)
  }

  // Load data when connected
  useEffect(() => {
    if (!isConnected) return

    const cleanups = [
      onMessage('mcp_list', (data: unknown) => {
        const d = data as { success: boolean; servers?: MCPServerConfig[]; error?: string }
        setIsLoading(false)
        if (d.success && d.servers) {
          setServers(d.servers)
        } else if (d.error) {
          showStatus('error', d.error)
        }
      }),
      onMessage('mcp_enable', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        if (!d.success) {
          showStatus('error', d.error || 'Failed to enable server')
        }
      }),
      onMessage('mcp_disable', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        if (!d.success) {
          showStatus('error', d.error || 'Failed to disable server')
        }
      }),
      onMessage('mcp_remove', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        if (d.success) {
          showStatus('success', d.message || 'Server removed')
          // Refresh list
          send('mcp_list')
        } else {
          showStatus('error', d.error || 'Failed to remove server')
        }
      }),
      onMessage('mcp_add_json', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        setIsAdding(false)
        if (d.success) {
          showStatus('success', d.message || 'Server added')
          setShowAddModal(false)
          setCustomJsonConfig('')
          setAddError('')
          // Refresh list
          send('mcp_list')
        } else {
          setAddError(d.error || 'Failed to add server')
        }
      }),
      onMessage('mcp_get_env', (data: unknown) => {
        const d = data as { success: boolean; name: string; env?: Record<string, string> }
        if (d.success && d.env) {
          setEnvValues(d.env)
        }
      }),
      onMessage('mcp_update_env', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        setIsSavingEnv(false)
        if (d.success) {
          showStatus('success', d.message || 'Configuration saved')
          setConfigServer(null)
          // Refresh list
          send('mcp_list')
        } else {
          showStatus('error', d.error || 'Failed to update configuration')
        }
      }),
    ]

    // Load initial data
    send('mcp_list')

    return () => cleanups.forEach(c => c())
  }, [isConnected, send, onMessage])

  // Build MCP list from configured servers, filter and sort
  const mcpList: MCPItem[] = servers
    .filter(s => {
      if (!searchQuery) return true
      return s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (s.description && s.description.toLowerCase().includes(searchQuery.toLowerCase()))
    })
    .map(s => ({
      name: s.name,
      description: s.description,
      enabled: s.enabled,
      transport: s.transport,
      action_set: s.action_set,
      env: s.env,
      needsConfig: s.env && Object.keys(s.env).length > 0 && Object.values(s.env).some(v => !v || v.trim() === '')
    }))
    .sort((a, b) => a.name.localeCompare(b.name))

  // Stats
  const totalServers = servers.length
  const enabledServers = servers.filter(s => s.enabled).length

  // Handlers
  const handleReloadServers = () => {
    setIsReloading(true)
    send('mcp_list')
    // Reset after a short delay since mcp_list doesn't have a specific "reload" response
    setTimeout(() => setIsReloading(false), 500)
  }

  const handleToggleServer = (name: string, enabled: boolean) => {
    if (enabled) {
      send('mcp_enable', { name })
    } else {
      send('mcp_disable', { name })
    }
    // Optimistic update
    setServers(prev => prev.map(s => s.name === name ? { ...s, enabled } : s))
  }

  const handleRemoveServer = (name: string) => {
    if (window.confirm(`Remove "${name}" from configured servers?`)) {
      send('mcp_remove', { name })
      // Optimistic update
      setServers(prev => prev.filter(s => s.name !== name))
    }
  }

  const handleConfigureServer = (server: MCPServerConfig) => {
    setConfigServer(server)
    setEnvValues({ ...server.env })
    send('mcp_get_env', { name: server.name })
  }

  const handleSaveEnv = () => {
    if (!configServer) return
    setIsSavingEnv(true)

    // Update each env var
    const envEntries = Object.entries(envValues)
    if (envEntries.length === 0) {
      setIsSavingEnv(false)
      setConfigServer(null)
      return
    }

    envEntries.forEach(([key, value]) => {
      send('mcp_update_env', { name: configServer.name, key, value })
    })
  }

  const handleAddCustomServer = () => {
    setAddError('')
    try {
      const config = JSON.parse(customJsonConfig)
      if (!config.name) {
        setAddError('Configuration must include a "name" field')
        return
      }
      setIsAdding(true)
      send('mcp_add_json', { name: config.name, config: customJsonConfig })
    } catch {
      setAddError('Invalid JSON format')
    }
  }

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionTitleRow}>
          <h3>MCP Servers</h3>
          <Badge variant={enabledServers > 0 ? 'success' : 'default'}>
            {enabledServers}/{totalServers}
          </Badge>
        </div>
        <p>Manage Model Context Protocol server connections</p>
      </div>

      {/* Status Message */}
      {statusMessage && (
        <div className={`${styles.statusBanner} ${statusMessage.type === 'success' ? styles.statusSuccess : styles.statusError}`}>
          {statusMessage.type === 'success' ? <Check size={14} /> : <X size={14} />}
          {statusMessage.text}
        </div>
      )}

      {/* Toolbar */}
      <div className={styles.mcpToolbar}>
        <div className={styles.mcpSearch}>
          <input
            type="text"
            placeholder="Search servers..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className={styles.searchInput}
          />
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={handleReloadServers}
          disabled={isReloading}
          icon={isReloading ? <Loader2 size={14} className={styles.spinning} /> : <RotateCcw size={14} />}
        >
          Reload
        </Button>
      </div>

      {isLoading ? (
        <div className={styles.loadingState}>
          <Loader2 size={20} className={styles.spinning} />
          <span>Loading MCP servers...</span>
        </div>
      ) : mcpList.length === 0 ? (
        <div className={styles.emptyState}>
          {searchQuery ? (
            <p>No servers match your search.</p>
          ) : (
            <p>No MCP servers configured. Add a custom server to get started.</p>
          )}
        </div>
      ) : (
        <div className={styles.mcpList}>
          {mcpList.map(item => (
            <div
              key={item.name}
              className={`${styles.mcpItem} ${!item.enabled ? styles.mcpItemDisabled : ''}`}
            >
              <div className={styles.mcpItemMain}>
                <div className={styles.mcpItemHeader}>
                  <span className={styles.mcpItemName}>{item.name}</span>
                  <Badge variant={item.enabled ? 'success' : 'default'}>
                    {item.enabled ? 'Enabled' : 'Disabled'}
                  </Badge>
                  {item.needsConfig && (
                    <Badge variant="warning">Needs Config</Badge>
                  )}
                </div>
                <p className={styles.mcpItemDesc}>{item.description}</p>
              </div>
              <div className={styles.mcpItemActions}>
                {item.env && Object.keys(item.env).length > 0 && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      const server = servers.find(s => s.name === item.name)
                      if (server) handleConfigureServer(server)
                    }}
                    icon={<Edit2 size={14} />}
                    title="Configure"
                  />
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleRemoveServer(item.name)}
                  icon={<Trash2 size={14} />}
                  title="Remove"
                />
                <input
                  type="checkbox"
                  className={styles.toggle}
                  checked={item.enabled}
                  onChange={(e) => handleToggleServer(item.name, e.target.checked)}
                  title={item.enabled ? 'Disable' : 'Enable'}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Add Server Section */}
      <div className={styles.mcpAddSection}>
        <Button
          variant="secondary"
          onClick={() => setShowAddModal(true)}
          icon={<Plus size={14} />}
        >
          Add Server
        </Button>
        <span className={styles.hint}>Add a new MCP server with JSON configuration</span>
      </div>

      {/* Add Custom Server Modal */}
      {showAddModal && (
        <div className={styles.modalOverlay} onClick={() => { setShowAddModal(false); setAddError('') }}>
          <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Add Custom MCP Server</h3>
              <button className={styles.modalClose} onClick={() => { setShowAddModal(false); setAddError('') }}>
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <p className={styles.hint}>
                Enter the MCP server configuration in JSON format. This will be added to mcp_config.json.
              </p>
              <div className={styles.formGroup}>
                <label>Server Configuration (JSON)</label>
                <textarea
                  value={customJsonConfig}
                  onChange={(e) => setCustomJsonConfig(e.target.value)}
                  placeholder={`{
  "name": "my-server",
  "description": "My custom MCP server",
  "transport": "stdio",
  "command": "npx @my-org/my-mcp-server",
  "action_set": "default",
  "env": {}
}`}
                  rows={10}
                  style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}
                />
              </div>
              {addError && (
                <div className={styles.errorText}>{addError}</div>
              )}
            </div>
            <div className={styles.modalFooter}>
              <Button variant="secondary" onClick={() => { setShowAddModal(false); setAddError('') }}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleAddCustomServer}
                disabled={isAdding || !customJsonConfig.trim()}
              >
                {isAdding ? 'Adding...' : 'Add Server'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Environment Configuration Modal */}
      {configServer && (
        <div className={styles.modalOverlay} onClick={() => setConfigServer(null)}>
          <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Configure {configServer.name}</h3>
              <button className={styles.modalClose} onClick={() => setConfigServer(null)}>
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <p className={styles.hint}>
                Set the required environment variables for this MCP server.
              </p>
              {Object.keys(configServer.env).length === 0 ? (
                <p>No environment variables to configure.</p>
              ) : (
                Object.entries(configServer.env).map(([key]) => (
                  <div key={key} className={styles.formGroup}>
                    <label>{key}</label>
                    <input
                      type={key.toLowerCase().includes('key') || key.toLowerCase().includes('token') || key.toLowerCase().includes('secret') ? 'password' : 'text'}
                      value={envValues[key] || ''}
                      onChange={(e) => setEnvValues(prev => ({ ...prev, [key]: e.target.value }))}
                      placeholder={`Enter ${key}...`}
                    />
                  </div>
                ))
              )}
            </div>
            <div className={styles.modalFooter}>
              <Button variant="secondary" onClick={() => setConfigServer(null)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleSaveEnv}
                disabled={isSavingEnv}
              >
                {isSavingEnv ? 'Saving...' : 'Save'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// Skill types
interface SkillConfig {
  name: string
  description: string
  enabled: boolean
  user_invocable: boolean
  action_sets: string[]
  source: string
}

interface SkillInfo extends SkillConfig {
  argument_hint?: string
  allowed_tools?: string[]
  instructions?: string
}

function SkillsSettings() {
  const { send, onMessage, isConnected } = useSettingsWebSocket()

  // State
  const [skills, setSkills] = useState<SkillConfig[]>([])
  const [totalSkills, setTotalSkills] = useState(0)
  const [enabledSkills, setEnabledSkills] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

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

  const showStatus = (type: 'success' | 'error', text: string) => {
    setStatusMessage({ type, text })
    setTimeout(() => setStatusMessage(null), 3000)
  }

  // Load data when connected
  useEffect(() => {
    if (!isConnected) return

    const cleanups = [
      onMessage('skill_list', (data: unknown) => {
        const d = data as { success: boolean; skills?: SkillConfig[]; total?: number; enabled?: number; error?: string }
        setIsLoading(false)
        if (d.success && d.skills) {
          setSkills(d.skills)
          setTotalSkills(d.total ?? d.skills.length)
          setEnabledSkills(d.enabled ?? d.skills.filter(s => s.enabled).length)
        } else if (d.error) {
          showStatus('error', d.error)
        }
      }),
      onMessage('skill_enable', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        if (!d.success) {
          showStatus('error', d.error || 'Failed to enable skill')
        }
      }),
      onMessage('skill_disable', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        if (!d.success) {
          showStatus('error', d.error || 'Failed to disable skill')
        }
      }),
      onMessage('skill_install', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        setIsInstalling(false)
        if (d.success) {
          showStatus('success', d.message || 'Skill installed')
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
          showStatus('success', d.message || 'Skill created')
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
          showStatus('success', d.message || 'Skill removed')
        } else {
          showStatus('error', d.error || 'Failed to remove skill')
        }
      }),
      onMessage('skill_reload', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        setIsReloading(false)
        if (d.success) {
          showStatus('success', d.message || 'Skills reloaded')
        } else {
          showStatus('error', d.error || 'Failed to reload skills')
        }
      }),
      onMessage('skill_info', (data: unknown) => {
        const d = data as { success: boolean; skill?: SkillInfo; error?: string }
        if (d.success && d.skill) {
          setViewingSkill(d.skill)
        } else {
          showStatus('error', d.error || 'Failed to get skill info')
        }
      }),
    ]

    // Load initial data
    send('skill_list')

    return () => cleanups.forEach(c => c())
  }, [isConnected, send, onMessage])

  // Handlers
  const handleToggleSkill = (name: string, enabled: boolean) => {
    if (enabled) {
      send('skill_enable', { name })
    } else {
      send('skill_disable', { name })
    }
    // Optimistic update
    setSkills(prev => prev.map(s => s.name === name ? { ...s, enabled } : s))
    setEnabledSkills(prev => enabled ? prev + 1 : prev - 1)
  }

  const handleRemoveSkill = (name: string) => {
    if (window.confirm(`Remove skill "${name}"? This will delete it from the skills folder.`)) {
      send('skill_remove', { name })
      // Optimistic update
      setSkills(prev => prev.filter(s => s.name !== name))
      setTotalSkills(prev => prev - 1)
    }
  }

  const handleViewSkill = (name: string) => {
    send('skill_info', { name })
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

  // Request template when modal opens
  const handleOpenCreateModal = () => {
    setShowCreateModal(true)
    setNewSkillName('')
    setNewSkillDesc('')
    setNewSkillContent('')
    setCreateError('')
    // Request initial template
    send('skill_template', { name: 'my-skill', description: '' })
  }

  const handleReloadSkills = () => {
    setIsReloading(true)
    send('skill_reload')
  }

  // Filter by search and sort alphabetically
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

      {/* Status Message */}
      {statusMessage && (
        <div className={`${styles.statusBanner} ${statusMessage.type === 'success' ? styles.statusSuccess : styles.statusError}`}>
          {statusMessage.type === 'success' ? <Check size={14} /> : <X size={14} />}
          {statusMessage.text}
        </div>
      )}

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
                    // Update template when name changes
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
    </div>
  )
}

// Integration types
interface IntegrationField {
  key: string
  label: string
  placeholder: string
  password: boolean
}

interface IntegrationAccount {
  display: string
  id: string
}

interface Integration {
  id: string
  name: string
  description: string
  auth_type: 'oauth' | 'token' | 'both' | 'interactive'
  connected: boolean
  accounts: IntegrationAccount[]
  fields: IntegrationField[]
}

// Integration icons mapping
const INTEGRATION_ICONS: Record<string, string> = {
  google: '📧',
  slack: '💬',
  notion: '📝',
  linkedin: '💼',
  zoom: '📹',
  discord: '🎮',
  telegram: '✈️',
  whatsapp: '📱',
  recall: '🎤',
}

function IntegrationsSettings() {
  const { send, onMessage, isConnected } = useSettingsWebSocket()

  // State
  const [integrations, setIntegrations] = useState<Integration[]>([])
  const [totalIntegrations, setTotalIntegrations] = useState(0)
  const [connectedCount, setConnectedCount] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // Search
  const [searchQuery, setSearchQuery] = useState('')

  // Reload state
  const [isReloading, setIsReloading] = useState(false)

  // Connect modal state
  const [showConnectModal, setShowConnectModal] = useState(false)
  const [selectedIntegration, setSelectedIntegration] = useState<Integration | null>(null)
  const [credentials, setCredentials] = useState<Record<string, string>>({})
  const [connectError, setConnectError] = useState('')
  const [isConnecting, setIsConnecting] = useState(false)

  // Manage modal state
  const [showManageModal, setShowManageModal] = useState(false)
  const [managingIntegration, setManagingIntegration] = useState<Integration | null>(null)

  const showStatus = (type: 'success' | 'error', text: string) => {
    setStatusMessage({ type, text })
    setTimeout(() => setStatusMessage(null), 3000)
  }

  // Load data when connected
  useEffect(() => {
    if (!isConnected) return

    const cleanups = [
      onMessage('integration_list', (data: unknown) => {
        const d = data as { success: boolean; integrations?: Integration[]; total?: number; connected?: number; error?: string }
        setIsLoading(false)
        setIsReloading(false)
        if (d.success && d.integrations) {
          setIntegrations(d.integrations)
          setTotalIntegrations(d.total ?? d.integrations.length)
          setConnectedCount(d.connected ?? d.integrations.filter(i => i.connected).length)
        } else if (d.error) {
          showStatus('error', d.error)
        }
      }),
      onMessage('integration_connect_result', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string; id?: string }
        setIsConnecting(false)
        if (d.success) {
          showStatus('success', d.message || 'Connected successfully')
          setShowConnectModal(false)
          setCredentials({})
          setConnectError('')
        } else {
          setConnectError(d.error || d.message || 'Connection failed')
        }
      }),
      onMessage('integration_disconnect_result', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        if (d.success) {
          showStatus('success', d.message || 'Disconnected successfully')
          setShowManageModal(false)
          setManagingIntegration(null)
        } else {
          showStatus('error', d.error || 'Failed to disconnect')
        }
      }),
      onMessage('integration_info', (data: unknown) => {
        const d = data as { success: boolean; integration?: Integration; error?: string }
        if (d.success && d.integration) {
          setManagingIntegration(d.integration)
          setShowManageModal(true)
        } else {
          showStatus('error', d.error || 'Failed to get integration info')
        }
      }),
    ]

    // Load initial data
    send('integration_list')

    return () => cleanups.forEach(c => c())
  }, [isConnected, send, onMessage])

  // Handlers
  const handleReload = () => {
    setIsReloading(true)
    send('integration_list')
  }

  const handleOpenConnect = (integration: Integration) => {
    setSelectedIntegration(integration)
    setCredentials({})
    setConnectError('')
    setShowConnectModal(true)
  }

  const handleOpenManage = (integration: Integration) => {
    send('integration_info', { id: integration.id })
  }

  const handleConnectToken = () => {
    if (!selectedIntegration) return
    setIsConnecting(true)
    setConnectError('')
    send('integration_connect_token', {
      id: selectedIntegration.id,
      credentials,
    })
  }

  const handleConnectOAuth = () => {
    if (!selectedIntegration) return
    setIsConnecting(true)
    setConnectError('')
    send('integration_connect_oauth', { id: selectedIntegration.id })
  }

  const handleDisconnect = (accountId?: string) => {
    if (!managingIntegration) return
    send('integration_disconnect', {
      id: managingIntegration.id,
      account_id: accountId,
    })
  }

  const handleAddAnother = () => {
    if (!managingIntegration) return
    setShowManageModal(false)
    handleOpenConnect(managingIntegration)
  }

  // Filter by search and sort alphabetically
  const filteredIntegrations = integrations
    .filter(integration => {
      if (!searchQuery) return true
      const query = searchQuery.toLowerCase()
      return integration.name.toLowerCase().includes(query) ||
        integration.description.toLowerCase().includes(query)
    })
    .sort((a, b) => a.name.localeCompare(b.name))

  if (isLoading) {
    return (
      <div className={styles.settingsSection}>
        <div className={styles.loadingState}>
          <Loader2 className={styles.spinner} />
          <span>Loading integrations...</span>
        </div>
      </div>
    )
  }

  return (
    <div className={styles.settingsSection}>
      {/* Header */}
      <div className={styles.sectionHeader}>
        <div className={styles.sectionTitleRow}>
          <h3>External Integrations</h3>
          <Badge variant="default">{connectedCount}/{totalIntegrations} connected</Badge>
        </div>
        <p>Connect to external services and tools</p>
      </div>

      {/* Status message */}
      {statusMessage && (
        <div className={`${styles.statusMessage} ${styles[statusMessage.type]}`}>
          {statusMessage.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}
          <span>{statusMessage.text}</span>
        </div>
      )}

      {/* Toolbar */}
      <div className={styles.integrationsToolbar}>
        <div className={styles.integrationsSearch}>
          <input
            type="text"
            className={styles.searchInput}
            placeholder="Search integrations..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={handleReload}
          disabled={isReloading}
        >
          <RotateCcw size={16} className={isReloading ? styles.spinning : ''} />
          Reload
        </Button>
      </div>

      {/* Integrations list */}
      <div className={styles.integrationsList}>
        {filteredIntegrations.length === 0 ? (
          <div className={styles.emptyState}>
            <Package size={24} />
            <span>
              {searchQuery ? 'No integrations match your search' : 'No integrations available'}
            </span>
          </div>
        ) : (
          filteredIntegrations.map(integration => (
            <div key={integration.id} className={styles.integrationCard}>
              <span className={styles.integrationIcon}>
                {INTEGRATION_ICONS[integration.id] || '🔗'}
              </span>
              <div className={styles.integrationInfo}>
                <span className={styles.integrationName}>{integration.name}</span>
                <span className={styles.integrationDesc}>{integration.description}</span>
                <div className={styles.integrationMeta}>
                  <Badge variant={integration.connected ? 'success' : 'default'}>
                    {integration.connected ? 'Connected' : 'Not connected'}
                  </Badge>
                  {integration.connected && integration.accounts.length > 0 && (
                    <span className={styles.integrationAccounts}>
                      {integration.accounts.length} account{integration.accounts.length > 1 ? 's' : ''}
                    </span>
                  )}
                </div>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => integration.connected ? handleOpenManage(integration) : handleOpenConnect(integration)}
              >
                {integration.connected ? 'Manage' : 'Connect'}
              </Button>
            </div>
          ))
        )}
      </div>

      {/* Connect Modal */}
      {showConnectModal && selectedIntegration && (
        <div className={styles.modalOverlay} onClick={() => setShowConnectModal(false)}>
          <div className={styles.modal} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Connect {selectedIntegration.name}</h3>
              <button className={styles.modalClose} onClick={() => setShowConnectModal(false)}>
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              {/* OAuth-only integrations */}
              {selectedIntegration.auth_type === 'oauth' && (
                <div className={styles.connectForm}>
                  <p className={styles.connectDesc}>
                    Click the button below to sign in with {selectedIntegration.name}.
                    A browser window will open for authentication.
                  </p>
                  {connectError && (
                    <div className={styles.formError}>{connectError}</div>
                  )}
                  <Button
                    variant="primary"
                    onClick={handleConnectOAuth}
                    disabled={isConnecting}
                  >
                    {isConnecting ? (
                      <>
                        <Loader2 size={16} className={styles.spinning} />
                        Connecting...
                      </>
                    ) : (
                      <>Sign in with {selectedIntegration.name}</>
                    )}
                  </Button>
                </div>
              )}

              {/* Token-only integrations */}
              {selectedIntegration.auth_type === 'token' && (
                <div className={styles.connectForm}>
                  {selectedIntegration.fields.map(field => (
                    <div key={field.key} className={styles.formGroup}>
                      <label className={styles.formLabel}>{field.label}</label>
                      <input
                        type={field.password ? 'password' : 'text'}
                        className={styles.formInput}
                        placeholder={field.placeholder}
                        value={credentials[field.key] || ''}
                        onChange={(e) => setCredentials(prev => ({
                          ...prev,
                          [field.key]: e.target.value
                        }))}
                      />
                    </div>
                  ))}
                  {connectError && (
                    <div className={styles.formError}>{connectError}</div>
                  )}
                  <Button
                    variant="primary"
                    onClick={handleConnectToken}
                    disabled={isConnecting}
                  >
                    {isConnecting ? (
                      <>
                        <Loader2 size={16} className={styles.spinning} />
                        Connecting...
                      </>
                    ) : (
                      'Connect'
                    )}
                  </Button>
                </div>
              )}

              {/* Both OAuth and Token integrations */}
              {selectedIntegration.auth_type === 'both' && (
                <div className={styles.connectForm}>
                  {selectedIntegration.fields.map(field => (
                    <div key={field.key} className={styles.formGroup}>
                      <label className={styles.formLabel}>{field.label}</label>
                      <input
                        type={field.password ? 'password' : 'text'}
                        className={styles.formInput}
                        placeholder={field.placeholder}
                        value={credentials[field.key] || ''}
                        onChange={(e) => setCredentials(prev => ({
                          ...prev,
                          [field.key]: e.target.value
                        }))}
                      />
                    </div>
                  ))}
                  {connectError && (
                    <div className={styles.formError}>{connectError}</div>
                  )}
                  <Button
                    variant="primary"
                    onClick={handleConnectToken}
                    disabled={isConnecting}
                  >
                    {isConnecting ? (
                      <>
                        <Loader2 size={16} className={styles.spinning} />
                        Connecting...
                      </>
                    ) : (
                      'Connect with Token'
                    )}
                  </Button>
                  <div className={styles.connectFormDivider}>or</div>
                  <Button
                    variant="secondary"
                    onClick={handleConnectOAuth}
                    disabled={isConnecting}
                  >
                    Use OAuth Instead
                  </Button>
                </div>
              )}

              {/* Interactive integrations (WhatsApp) */}
              {selectedIntegration.auth_type === 'interactive' && (
                <div className={styles.connectForm}>
                  <p className={styles.connectDesc}>
                    This integration requires interactive authentication.
                    Please use the TUI interface to complete the connection.
                  </p>
                  <Button variant="secondary" onClick={() => setShowConnectModal(false)}>
                    Close
                  </Button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Manage Modal */}
      {showManageModal && managingIntegration && (
        <div className={styles.modalOverlay} onClick={() => setShowManageModal(false)}>
          <div className={styles.modal} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>Manage {managingIntegration.name}</h3>
              <button className={styles.modalClose} onClick={() => setShowManageModal(false)}>
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <h4 className={styles.manageSubtitle}>Connected Accounts</h4>
              {managingIntegration.accounts.length === 0 ? (
                <p className={styles.noAccounts}>No accounts connected</p>
              ) : (
                <div className={styles.accountsList}>
                  {managingIntegration.accounts.map(account => (
                    <div key={account.id} className={styles.accountItem}>
                      <span className={styles.accountName}>{account.display}</span>
                      <Button
                        variant="danger"
                        size="sm"
                        onClick={() => handleDisconnect(account.id)}
                      >
                        Disconnect
                      </Button>
                    </div>
                  ))}
                </div>
              )}
              <div className={styles.modalActions}>
                <Button variant="secondary" onClick={handleAddAnother}>
                  <Plus size={16} />
                  Add Another Account
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
