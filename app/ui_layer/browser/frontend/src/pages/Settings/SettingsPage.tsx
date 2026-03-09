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
  Trash2
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

function MemorySettings() {
  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>Memory Settings</h3>
        <p>Manage agent memory and context retention</p>
      </div>
      <div className={styles.settingsForm}>
        <div className={styles.formGroup}>
          <label>Context Window</label>
          <select defaultValue="128k">
            <option value="32k">32K tokens</option>
            <option value="64k">64K tokens</option>
            <option value="128k">128K tokens</option>
            <option value="200k">200K tokens</option>
          </select>
        </div>
        <div className={styles.toggleGroup}>
          <div className={styles.toggleInfo}>
            <span className={styles.toggleLabel}>Persistent Memory</span>
            <span className={styles.toggleDesc}>Remember context across sessions</span>
          </div>
          <input type="checkbox" className={styles.toggle} defaultChecked />
        </div>
        <div className={styles.actionGroup}>
          <Button variant="secondary">Export Memory</Button>
          <Button variant="danger">Clear Memory</Button>
        </div>
      </div>
    </div>
  )
}

function ModelSettings() {
  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>Model Configuration</h3>
        <p>Select AI model and configure API settings</p>
      </div>
      <div className={styles.settingsForm}>
        <div className={styles.formGroup}>
          <label>Provider</label>
          <select defaultValue="anthropic">
            <option value="anthropic">Anthropic</option>
            <option value="openai">OpenAI</option>
            <option value="local">Local (Ollama)</option>
          </select>
        </div>
        <div className={styles.formGroup}>
          <label>Model</label>
          <select defaultValue="claude-3-5-sonnet">
            <option value="claude-3-5-sonnet">Claude 3.5 Sonnet</option>
            <option value="claude-3-opus">Claude 3 Opus</option>
            <option value="claude-3-haiku">Claude 3 Haiku</option>
          </select>
        </div>
        <div className={styles.formGroup}>
          <label>API Key</label>
          <input type="password" placeholder="sk-ant-..." />
          <span className={styles.hint}>Your API key is stored securely</span>
        </div>
      </div>
      <div className={styles.sectionFooter}>
        <Button variant="secondary">Test Connection</Button>
        <Button variant="primary">Save</Button>
      </div>
    </div>
  )
}

function MCPSettings() {
  const servers = [
    { name: 'filesystem', status: 'connected', tools: 5 },
    { name: 'browser', status: 'connected', tools: 8 },
    { name: 'shell', status: 'connected', tools: 3 },
  ]

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>MCP Servers</h3>
        <p>Manage Model Context Protocol server connections</p>
      </div>
      <div className={styles.serverList}>
        {servers.map(server => (
          <div key={server.name} className={styles.serverCard}>
            <div className={styles.serverInfo}>
              <Plug size={16} />
              <span className={styles.serverName}>{server.name}</span>
              <Badge variant={server.status === 'connected' ? 'success' : 'error'}>
                {server.status}
              </Badge>
            </div>
            <span className={styles.toolCount}>{server.tools} tools</span>
            <Button variant="ghost" size="sm">Configure</Button>
          </div>
        ))}
      </div>
      <Button variant="secondary" icon={<Plug size={14} />}>
        Add MCP Server
      </Button>
    </div>
  )
}

function SkillsSettings() {
  const skills = [
    { name: 'Code Analysis', enabled: true, description: 'Analyze and understand code' },
    { name: 'File Management', enabled: true, description: 'Create, edit, and manage files' },
    { name: 'Web Search', enabled: false, description: 'Search the web for information' },
    { name: 'Image Processing', enabled: true, description: 'Analyze and process images' },
  ]

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>Skills</h3>
        <p>Enable or disable agent capabilities</p>
      </div>
      <div className={styles.skillsList}>
        {skills.map(skill => (
          <div key={skill.name} className={styles.skillCard}>
            <div className={styles.skillInfo}>
              <span className={styles.skillName}>{skill.name}</span>
              <span className={styles.skillDesc}>{skill.description}</span>
            </div>
            <input
              type="checkbox"
              className={styles.toggle}
              defaultChecked={skill.enabled}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

function IntegrationsSettings() {
  const integrations = [
    { name: 'Discord', connected: false, icon: '🎮' },
    { name: 'Slack', connected: false, icon: '💬' },
    { name: 'Google Workspace', connected: false, icon: '📧' },
    { name: 'GitHub', connected: true, icon: '🐙' },
  ]

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>External Integrations</h3>
        <p>Connect to external services and tools</p>
      </div>
      <div className={styles.integrationsList}>
        {integrations.map(integration => (
          <div key={integration.name} className={styles.integrationCard}>
            <span className={styles.integrationIcon}>{integration.icon}</span>
            <div className={styles.integrationInfo}>
              <span className={styles.integrationName}>{integration.name}</span>
              <Badge variant={integration.connected ? 'success' : 'default'}>
                {integration.connected ? 'Connected' : 'Not connected'}
              </Badge>
            </div>
            <Button variant="secondary" size="sm">
              {integration.connected ? 'Manage' : 'Connect'}
            </Button>
          </div>
        ))}
      </div>
    </div>
  )
}
