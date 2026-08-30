import React, { useState, useEffect } from 'react'
import {
  AlertTriangle,
  Loader2,
  Plus,
  Edit2,
  Trash2,
  RotateCcw,
  X,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button, Badge, ConfirmModal } from '../../components/ui'
import { useConfirmModal } from '../../hooks'
import i18n from '../../i18n/config'
import { formatNumber, formatDate, formatTime } from '../../i18n/format'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  setTaskEnabled,
  type ProactiveTask,
} from '../../store/slices/proactiveSettingsSlice'
import {
  selectSchedulerEnabled,
  selectSchedules,
  selectProactiveTasks,
  selectProactiveHasLoadedMode,
  selectProactiveHasLoadedConfig,
  selectProactiveHasLoadedTasks,
} from '../../store/selectors/proactiveSettings'

// Convert cron expression to human-readable format. Uses the i18n instance
// directly (module scope, no hook available); components re-render on language
// change so the localized string refreshes.
function formatCronExpression(cron: string): string {
  const parts = cron.split(' ')
  if (parts.length !== 5) return cron

  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts

  const clock = (h: string, m: string): string => {
    const d = new Date()
    d.setHours(parseInt(h, 10) || 0, parseInt(m, 10) || 0, 0, 0)
    return formatTime(d)
  }

  const dayName = (dow: string): string => {
    const map: Record<string, string> = {
      '0': i18n.t('settings:proactive.cron.days.sun'),
      '7': i18n.t('settings:proactive.cron.days.sun'),
      '1': i18n.t('settings:proactive.cron.days.mon'),
      '2': i18n.t('settings:proactive.cron.days.tue'),
      '3': i18n.t('settings:proactive.cron.days.wed'),
      '4': i18n.t('settings:proactive.cron.days.thu'),
      '5': i18n.t('settings:proactive.cron.days.fri'),
      '6': i18n.t('settings:proactive.cron.days.sat'),
    }
    return map[dow] || dow
  }

  if (hour === '*' && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    const minNum = parseInt(minute, 10)
    if (minNum === 0) return i18n.t('settings:proactive.cron.twiceHourly')
    return i18n.t('settings:proactive.cron.hourly', { minute: minute.padStart(2, '0') })
  }

  if (dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    return i18n.t('settings:proactive.cron.daily', { time: clock(hour, minute) })
  }

  if (dayOfMonth === '*' && month === '*' && dayOfWeek !== '*') {
    return i18n.t('settings:proactive.cron.weekly', { day: dayName(dayOfWeek), time: clock(hour, minute) })
  }

  if (dayOfMonth !== '*' && month === '*' && dayOfWeek === '*') {
    return i18n.t('settings:proactive.cron.monthly', { day: dayOfMonth, time: clock(hour, minute) })
  }

  return i18n.t('settings:proactive.cron.raw', { cron })
}

// Types come from the slice now.

// Helper functions for task display
function getPriorityLabel(value: number): string {
  if (value <= 35) return i18n.t('settings:proactive.priority.high')
  if (value <= 55) return i18n.t('settings:proactive.priority.medium')
  return i18n.t('settings:proactive.priority.low')
}

function getNotificationLabel(tier: number): string {
  return tier >= 1 ? i18n.t('settings:proactive.notify.notifies') : i18n.t('settings:proactive.notify.silent')
}

// Priority level mappings
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

// Task Form Modal Component
interface TaskFormModalProps {
  task: ProactiveTask | null
  onClose: () => void
  onSave: (taskData: Partial<ProactiveTask>) => void
}

function TaskFormModal({ task, onClose, onSave }: TaskFormModalProps) {
  const { t } = useTranslation(['settings', 'common'])
  const [name, setName] = useState(task?.name || '')
  const [frequency, setFrequency] = useState(task?.frequency || 'daily')
  const [instruction, setInstruction] = useState(task?.instruction || '')
  const [enabled, setEnabled] = useState(task?.enabled ?? true)
  const [priorityLevel, setPriorityLevel] = useState<PriorityLevel>(
    task ? getPriorityLevel(task.priority) : 'medium'
  )
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
          <h3>{task ? t('settings:proactive.taskForm.editTitle') : t('settings:proactive.taskForm.addTitle')}</h3>
          <button className={styles.modalClose} onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className={styles.modalBody}>
            <div className={styles.formGroup}>
              <label>{t('settings:proactive.taskForm.name')}</label>
              <input
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder={t('settings:proactive.taskForm.namePlaceholder')}
                required
              />
            </div>

            <div className={styles.formRow}>
              <div className={styles.formGroup}>
                <label>{t('settings:proactive.taskForm.frequency')}</label>
                <select value={frequency} onChange={e => setFrequency(e.target.value)}>
                  <option value="hourly">{t('settings:proactive.frequency.hourly')}</option>
                  <option value="daily">{t('settings:proactive.frequency.daily')}</option>
                  <option value="weekly">{t('settings:proactive.frequency.weekly')}</option>
                  <option value="monthly">{t('settings:proactive.frequency.monthly')}</option>
                </select>
              </div>

              <div className={styles.formGroup}>
                <label>{t('settings:proactive.taskForm.priority')} <span className={styles.labelHint}>{t('settings:proactive.taskForm.priorityHint')}</span></label>
                <select value={priorityLevel} onChange={e => setPriorityLevel(e.target.value as PriorityLevel)}>
                  <option value="high">{t('settings:proactive.priority.high')}</option>
                  <option value="medium">{t('settings:proactive.priority.medium')}</option>
                  <option value="low">{t('settings:proactive.priority.low')}</option>
                </select>
              </div>
            </div>

            <div className={styles.formRow}>
              {frequency !== 'hourly' && (
                <div className={styles.formGroup}>
                  <label>{t('settings:proactive.taskForm.time')}</label>
                  <input
                    type="time"
                    value={time}
                    onChange={e => setTime(e.target.value)}
                  />
                </div>
              )}

              {frequency === 'weekly' && (
                <div className={styles.formGroup}>
                  <label>{t('settings:proactive.taskForm.dayOfWeek')}</label>
                  <select value={day} onChange={e => setDay(e.target.value)}>
                    <option value="">{t('settings:proactive.taskForm.selectDay')}</option>
                    <option value="monday">{t('settings:proactive.weekdays.monday')}</option>
                    <option value="tuesday">{t('settings:proactive.weekdays.tuesday')}</option>
                    <option value="wednesday">{t('settings:proactive.weekdays.wednesday')}</option>
                    <option value="thursday">{t('settings:proactive.weekdays.thursday')}</option>
                    <option value="friday">{t('settings:proactive.weekdays.friday')}</option>
                    <option value="saturday">{t('settings:proactive.weekdays.saturday')}</option>
                    <option value="sunday">{t('settings:proactive.weekdays.sunday')}</option>
                  </select>
                </div>
              )}
            </div>

            <div className={styles.toggleGroup}>
              <div className={styles.toggleInfo}>
                <span className={styles.toggleLabel}>{t('settings:proactive.taskForm.notifyLabel')}</span>
                <span className={styles.toggleDesc}>
                  {t('settings:proactive.taskForm.notifyDesc')}
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
              <label>{t('settings:proactive.taskForm.instruction')}</label>
              <textarea
                value={instruction}
                onChange={e => setInstruction(e.target.value)}
                placeholder={t('settings:proactive.taskForm.instructionPlaceholder')}
                rows={4}
                required
              />
              <span className={styles.hint}>
                {t('settings:proactive.taskForm.instructionHint')}
              </span>
            </div>

            <div className={styles.toggleGroup}>
              <div className={styles.toggleInfo}>
                <span className={styles.toggleLabel}>{t('settings:proactive.taskForm.enabledLabel')}</span>
                <span className={styles.toggleDesc}>{t('settings:proactive.taskForm.enabledDesc')}</span>
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
              {t('common:actions.cancel')}
            </Button>
            <Button variant="primary" type="submit">
              {task ? t('common:actions.saveChanges') : t('settings:proactive.addTask')}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

export function ProactiveSettings() {
  const { t } = useTranslation(['settings', 'common'])
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const dispatch = useAppDispatch()

  // Slice-backed
  const schedulerEnabled = useAppSelector(selectSchedulerEnabled)
  const schedules = useAppSelector(selectSchedules)
  const tasks = useAppSelector(selectProactiveTasks)
  const hasLoadedMode = useAppSelector(selectProactiveHasLoadedMode)
  const hasLoadedConfig = useAppSelector(selectProactiveHasLoadedConfig)
  const hasLoadedTasks = useAppSelector(selectProactiveHasLoadedTasks)
  const isLoadingScheduler = !hasLoadedMode || !hasLoadedConfig
  const isLoadingTasks = !hasLoadedTasks

  // UI state (transient)
  const [showTaskForm, setShowTaskForm] = useState(false)
  const [editingTask, setEditingTask] = useState<ProactiveTask | null>(null)
  const [isResettingTasks, setIsResettingTasks] = useState(false)
  const [, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')

  // Confirm modal
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  // Side-effect handlers (success animations, modal close, list refresh).
  // List state is owned by proactiveSettingsSlice via the registry.
  useEffect(() => {
    if (!isConnected) return

    const cleanups = [
      onMessage('proactive_mode_set', (data: unknown) => {
        const d = data as { success: boolean }
        if (d.success) {
          setSaveStatus('success')
          setTimeout(() => setSaveStatus('idle'), 2000)
        }
      }),
      onMessage('scheduler_config_update', (data: unknown) => {
        const d = data as { success: boolean }
        if (d.success) {
          setSaveStatus('success')
          setTimeout(() => setSaveStatus('idle'), 2000)
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
        if (d.success) send('proactive_tasks_get')
      }),
      onMessage('proactive_tasks_reset', (data: unknown) => {
        const d = data as { success: boolean }
        setIsResettingTasks(false)
        if (d.success) send('proactive_tasks_get')
      }),
    ]

    if (!hasLoadedMode) send('proactive_mode_get')
    if (!hasLoadedConfig) send('scheduler_config_get')
    if (!hasLoadedTasks) send('proactive_tasks_get')

    return () => cleanups.forEach(c => c())
  }, [isConnected, send, onMessage, hasLoadedMode, hasLoadedConfig, hasLoadedTasks])

  const getSchedule = (id: string) => schedules.find(s => s.id === id)

  const handleToggleScheduler = (enabled: boolean) => {
    send('proactive_mode_set', { enabled })
  }

  const handleToggleSchedule = (scheduleId: string, enabled: boolean) => {
    send('scheduler_config_update', {
      updates: { schedules: [{ id: scheduleId, enabled }] }
    })
  }

  const handleAddTask = () => {
    setEditingTask(null)
    setShowTaskForm(true)
  }

  const handleEditTask = (task: ProactiveTask) => {
    setEditingTask(task)
    setShowTaskForm(true)
  }

  const handleToggleTask = (taskId: string, enabled: boolean) => {
    send('proactive_task_update', { taskId, updates: { enabled } })
    dispatch(setTaskEnabled({ taskId, enabled }))
  }

  const handleDeleteTask = (taskId: string) => {
    confirm({
      title: t('settings:proactive.deleteConfirmTitle'),
      message: t('settings:proactive.deleteConfirmMessage'),
      confirmText: t('common:actions.delete'),
      variant: 'danger',
    }, () => {
      send('proactive_task_remove', { taskId })
    })
  }

  const handleResetTasks = () => {
    confirm({
      title: t('settings:proactive.resetConfirmTitle'),
      message: t('settings:proactive.resetConfirmMessage'),
      confirmText: t('common:actions.reset'),
      variant: 'danger',
    }, () => {
      setIsResettingTasks(true)
      send('proactive_tasks_reset')
    })
  }

  // Search state for proactive tasks
  const [taskSearchQuery, setTaskSearchQuery] = useState('')

  const filteredTasks = taskSearchQuery
    ? tasks.filter(t =>
        t.name.toLowerCase().includes(taskSearchQuery.toLowerCase()) ||
        t.instruction.toLowerCase().includes(taskSearchQuery.toLowerCase())
      )
    : tasks

  const tasksByFrequency = {
    hourly: filteredTasks.filter(t => t.frequency === 'hourly'),
    daily: filteredTasks.filter(t => t.frequency === 'daily'),
    weekly: filteredTasks.filter(t => t.frequency === 'weekly'),
    monthly: filteredTasks.filter(t => t.frequency === 'monthly'),
  }

  const heartbeatSchedules = [
    { id: 'heartbeat', label: t('settings:proactive.heartbeat.label'), desc: t('settings:proactive.heartbeat.desc') },
  ]

  const plannerSchedules = [
    { id: 'day-planner', label: t('settings:proactive.planners.dayLabel'), desc: t('settings:proactive.planners.dayDesc') },
    { id: 'week-planner', label: t('settings:proactive.planners.weekLabel'), desc: t('settings:proactive.planners.weekDesc') },
    { id: 'month-planner', label: t('settings:proactive.planners.monthLabel'), desc: t('settings:proactive.planners.monthDesc') },
  ]

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>{t('settings:proactive.title')}</h3>
        <p>{t('settings:proactive.subtitle')}</p>
      </div>

      {/* Master Toggle */}
      <div className={styles.settingsForm}>
        <div className={styles.toggleGroup}>
          <div className={styles.toggleInfo}>
            <span className={styles.toggleLabel}>{t('settings:proactive.enableLabel')}</span>
            <span className={styles.toggleDesc}>
              {t('settings:proactive.enableDesc')}
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

      {/* Toggleable Content */}
      <div className={`${styles.toggleableContent} ${!schedulerEnabled ? styles.disabledContent : ''}`}>
        {/* Heartbeat Schedules */}
        <div className={styles.subsection}>
          <h4 className={styles.subsectionTitle}>{t('settings:proactive.heartbeatTitle')}</h4>
          <p className={styles.subsectionDesc}>
            {t('settings:proactive.heartbeatDesc')}
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
          <h4 className={styles.subsectionTitle}>{t('settings:proactive.plannersTitle')}</h4>
          <p className={styles.subsectionDesc}>
            {t('settings:proactive.plannersDesc')}
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
              <h4 className={styles.subsectionTitle}>{t('settings:proactive.tasksTitle')}</h4>
              <p className={styles.subsectionDesc}>
                {t('settings:proactive.tasksDesc')}
              </p>
            </div>
            <Button variant="primary" size="sm" onClick={handleAddTask} icon={<Plus size={14} />} disabled={!schedulerEnabled}>
              {t('settings:proactive.addTask')}
            </Button>
          </div>

          {tasks.length > 0 && (
            <div className={styles.searchContainer}>
              <input
                type="text"
                placeholder={t('settings:proactive.searchTasks')}
                value={taskSearchQuery}
                onChange={(e) => setTaskSearchQuery(e.target.value)}
                className={styles.searchInput}
              />
              {taskSearchQuery && (
                <span className={styles.searchCount}>
                  {t('settings:proactive.searchCount', { shown: filteredTasks.length, total: tasks.length })}
                </span>
              )}
            </div>
          )}

          {isLoadingTasks ? (
            <div className={styles.loadingState}>
              <Loader2 size={20} className={styles.spinning} />
              <span>{t('settings:proactive.loadingTasks')}</span>
            </div>
          ) : tasks.length === 0 ? (
            <div className={styles.emptyState}>
              <p>{t('settings:proactive.noTasks')}</p>
              <Button variant="secondary" size="sm" onClick={handleAddTask} disabled={!schedulerEnabled}>
                {t('settings:proactive.createFirst')}
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
                      <Badge variant="default">{t(`settings:proactive.frequency.${frequency}`)}</Badge>
                      <span className={styles.taskCount}>{t('settings:proactive.taskCount', { count: freqTasks.length })}</span>
                    </div>
                    <div className={styles.taskList}>
                      {freqTasks.map(task => (
                        <div key={task.id} className={`${styles.taskCard} ${!task.enabled ? styles.taskDisabled : ''}`}>
                          <div className={styles.taskMain}>
                            <div className={styles.taskHeader}>
                              <span className={styles.taskName}>{task.name}</span>
                              <div className={styles.taskBadges}>
                                <Badge variant={task.enabled ? 'success' : 'default'}>
                                  {task.enabled ? t('settings:proactive.active') : t('settings:proactive.disabled')}
                                </Badge>
                                <Badge variant="info">{getPriorityLabel(task.priority)}</Badge>
                                <Badge variant={task.permissionTier >= 1 ? 'warning' : 'default'}>
                                  {getNotificationLabel(task.permissionTier)}
                                </Badge>
                              </div>
                            </div>
                            <p className={styles.taskInstruction}>{task.instruction}</p>
                            <div className={styles.taskMeta}>
                              {task.time && <span>{t('settings:proactive.meta.time', { time: task.time })}</span>}
                              {task.day && <span>{t('settings:proactive.meta.day', { day: task.day })}</span>}
                              <span>{t('settings:proactive.meta.runs', { value: formatNumber(task.runCount) })}</span>
                              {task.lastRun && (
                                <span>{t('settings:proactive.meta.last', { date: formatDate(new Date(task.lastRun)) })}</span>
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
      </div>

      {/* Reset Tasks */}
      <div className={styles.dangerZone}>
        <div className={styles.dangerHeader}>
          <AlertTriangle size={18} className={styles.dangerIcon} />
          <h4>{t('settings:proactive.resetTitle')}</h4>
        </div>
        <p className={styles.dangerDescription}>
          {t('settings:proactive.resetDesc')}
        </p>
        <Button
          variant="danger"
          onClick={handleResetTasks}
          disabled={isResettingTasks}
          icon={isResettingTasks ? <Loader2 size={14} className={styles.spinning} /> : <RotateCcw size={14} />}
        >
          {isResettingTasks ? t('settings:proactive.resetting') : t('settings:proactive.resetButton')}
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

      {/* Confirm Modal */}
      <ConfirmModal {...confirmModalProps} />
    </div>
  )
}
