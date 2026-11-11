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
import { useConfirmModal, usePersistedState, useServerDraft } from '../../hooks'
import i18n from '../../i18n/config'
import { formatNumber, formatDate } from '../../i18n/format'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import { RemoteChangeHint } from './RemoteChangeHint'
import { useToast } from '../../contexts/ToastContext'
import { RESOURCES, useResource } from '../../store/resources'
import { useAppDispatch, useAppSelector } from '../../store/hooks'
import {
  setTaskEnabled,
  type ProactiveTask,
  type ProactiveSchedule,
} from '../../store/slices/proactiveSettingsSlice'
import {
  selectSchedulerEnabled,
  selectSchedules,
  selectProactiveTasks,
  selectProactiveHasLoadedMode,
  selectProactiveHasLoadedConfig,
  selectProactiveHasLoadedTasks,
  selectProactiveSchedule,
  selectHeartbeatOptions,
} from '../../store/selectors/proactiveSettings'
import { UI_STATE } from '../../store/uiState'

// Types come from the slice now.

const DEFAULT_SCHEDULE: ProactiveSchedule = {
  heartbeatMinutes: 30,
  dayPlannerTime: '07:00',
  weekPlannerDay: 'sunday',
  weekPlannerTime: '17:00',
  monthPlannerDay: 1,
  monthPlannerTime: '08:00',
}

const WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'] as const
const MONTH_DAYS = Array.from({ length: 31 }, (_, i) => i + 1)

// What this tab's auto-save sent, per control.
interface SentTiming {
  heartbeat?: number
  day?: string
  week?: { day: string; time: string }
  month?: { day: number; time: string }
}

const sameValue = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

type PlannerId = 'day-planner' | 'week-planner' | 'month-planner'

const clockParts = (time: string) => time.split(':').map(n => parseInt(n, 10) || 0)

// Catch-up interval option label ("Every 30 minutes", "Every 2 hours").
function formatInterval(minutes: number): string {
  return minutes < 60
    ? i18n.t('settings:proactive.catchUp.everyMinutes', { count: minutes })
    : i18n.t('settings:proactive.catchUp.everyHours', { count: minutes / 60 })
}

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

interface TaskForm {
  name: string
  frequency: string
  instruction: string
  enabled: boolean
  priorityLevel: PriorityLevel
  notifyBeforeRunning: boolean
  time: string
  day: string
}

function taskToForm(task: ProactiveTask | null): TaskForm {
  return {
    name: task?.name || '',
    frequency: task?.frequency || 'daily',
    instruction: task?.instruction || '',
    enabled: task?.enabled ?? true,
    priorityLevel: task ? getPriorityLevel(task.priority) : 'medium',
    notifyBeforeRunning: task ? task.permissionTier >= 1 : true,
    time: task?.time || '',
    day: task?.day || '',
  }
}

function TaskFormModal({ task, onClose, onSave }: TaskFormModalProps) {
  const { t } = useTranslation(['settings', 'common'])
  // Drafted over the live task, so an edit made elsewhere (another tab, the
  // agent) is flagged instead of silently lost on save.
  const form = useServerDraft(taskToForm(task))
  const { name, frequency, instruction, enabled, priorityLevel, notifyBeforeRunning, time, day } = form.value
  const setField = <K extends keyof TaskForm>(key: K) => (value: TaskForm[K]) =>
    form.set(prev => ({ ...prev, [key]: value }))
  const setName = setField('name')
  const setFrequency = setField('frequency')
  const setInstruction = setField('instruction')
  const setEnabled = setField('enabled')
  const setPriorityLevel = setField('priorityLevel')
  const setNotifyBeforeRunning = setField('notifyBeforeRunning')
  const setTime = setField('time')
  const setDay = setField('day')

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
            {form.remoteChanged && <RemoteChangeHint onLoadLatest={form.acceptRemote} />}
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
  const { send, onMessage } = useSettingsWebSocket()
  const dispatch = useAppDispatch()
  const { showToast } = useToast()

  // Slice-backed
  const schedulerEnabled = useAppSelector(selectSchedulerEnabled)
  const schedules = useAppSelector(selectSchedules)
  const tasks = useAppSelector(selectProactiveTasks)
  const hasLoadedMode = useAppSelector(selectProactiveHasLoadedMode)
  const hasLoadedConfig = useAppSelector(selectProactiveHasLoadedConfig)
  const hasLoadedTasks = useAppSelector(selectProactiveHasLoadedTasks)
  const isLoadingScheduler = !hasLoadedMode || !hasLoadedConfig
  const isLoadingTasks = !hasLoadedTasks

  // The slice caches mode, schedules and tasks; ResourceSync fetches them when
  // unloaded or stale and refetches them whenever they change (any tab, a reset).
  useResource(RESOURCES.proactiveMode)
  useResource(RESOURCES.schedulerConfig)
  useResource(RESOURCES.proactiveTasks)
  useResource(RESOURCES.proactiveSchedule)

  // Heartbeat interval + planner schedules: one draft per control over the
  // saved values, so a change made elsewhere shows up here unless that
  // control is mid-edit. Auto-saved while edited, like Settings → Memory's
  // daily time.
  const savedTiming = useAppSelector(selectProactiveSchedule)
  const heartbeatOptions = useAppSelector(selectHeartbeatOptions)
  const hasLoadedTiming = savedTiming !== null
  const saved = savedTiming ?? DEFAULT_SCHEDULE
  const heartbeatDraft = useServerDraft(saved.heartbeatMinutes)
  const dayDraft = useServerDraft(saved.dayPlannerTime)
  const weekDraft = useServerDraft({ day: saved.weekPlannerDay, time: saved.weekPlannerTime })
  const monthDraft = useServerDraft({ day: saved.monthPlannerDay, time: saved.monthPlannerTime })
  const resetHeartbeat = heartbeatDraft.reset
  const resetDay = dayDraft.reset
  const resetWeek = weekDraft.reset
  const resetMonth = monthDraft.reset
  // What this tab's auto-save sent, until its reply arrives. A draft settles
  // only if it still holds that value (the user may have kept editing).
  const sentTimingRef = React.useRef<SentTiming | null>(null)
  const timingValueRef = React.useRef<SentTiming>({})
  timingValueRef.current = {
    heartbeat: heartbeatDraft.value,
    day: dayDraft.value,
    week: weekDraft.value,
    month: monthDraft.value,
  }
  const timingTimerRef = React.useRef<number | undefined>(undefined)

  // UI state (transient)
  const [showTaskForm, setShowTaskForm] = useState(false)
  const [editingTask, setEditingTask] = useState<ProactiveTask | null>(null)
  // The form drafts over the live task; the snapshot stands in if it's removed.
  const liveEditingTask = editingTask ? tasks.find(x => x.id === editingTask.id) ?? editingTask : null
  const [isResettingTasks, setIsResettingTasks] = useState(false)
  // Set while this tab's add/update is in flight, so another tab's save
  // doesn't close this tab's form.
  const savingTaskRef = React.useRef(false)

  // Confirm modal
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  // Results of this view's own actions (close the form, clear the reset
  // spinner). List state is owned by proactiveSettingsSlice via the registry.
  useEffect(() => {
    const closeFormOnSaved = (data: unknown) => {
      if (!savingTaskRef.current) return
      savingTaskRef.current = false
      if ((data as { success: boolean }).success) {
        setShowTaskForm(false)
        setEditingTask(null)
      }
    }
    const cleanups = [
      onMessage('proactive_task_add', closeFormOnSaved),
      onMessage('proactive_task_update', closeFormOnSaved),
      onMessage('proactive_tasks_reset', () => setIsResettingTasks(false)),
      onMessage('proactive_schedule_set', (data: unknown) => {
        const sent = sentTimingRef.current
        if (!sent) return
        sentTimingRef.current = null
        const d = data as { success: boolean; error?: string }
        if (!d.success) {
          showToast('error', d.error || t('settings:proactive.toast.scheduleFailed'))
          return
        }
        const current = timingValueRef.current
        if (sent.heartbeat !== undefined && current.heartbeat === sent.heartbeat) resetHeartbeat()
        if (sent.day !== undefined && current.day === sent.day) resetDay()
        if (sent.week !== undefined && sameValue(current.week, sent.week)) resetWeek()
        if (sent.month !== undefined && sameValue(current.month, sent.month)) resetMonth()
      }),
    ]
    return () => cleanups.forEach(c => c())
  }, [onMessage, showToast, t, resetHeartbeat, resetDay, resetWeek, resetMonth])

  // Auto-save the heartbeat interval / planner schedules while edited
  // (debounced). Clean drafts are the saved values, so loads and remote
  // changes aren't echoed back; only the edited controls are sent.
  const anyTimingDirty = heartbeatDraft.isDirty || dayDraft.isDirty || weekDraft.isDirty || monthDraft.isDirty
  useEffect(() => {
    if (!anyTimingDirty) return
    window.clearTimeout(timingTimerRef.current)
    timingTimerRef.current = window.setTimeout(() => {
      const update: Record<string, number | string> = {}
      const sent: SentTiming = {}
      if (heartbeatDraft.isDirty) {
        update.heartbeatMinutes = heartbeatDraft.value
        sent.heartbeat = heartbeatDraft.value
      }
      if (dayDraft.isDirty && dayDraft.value) {
        const [h, m] = clockParts(dayDraft.value)
        update.dayPlannerHour = h
        update.dayPlannerMinute = m
        sent.day = dayDraft.value
      }
      if (weekDraft.isDirty && weekDraft.value.time) {
        const [h, m] = clockParts(weekDraft.value.time)
        update.weekPlannerDay = weekDraft.value.day
        update.weekPlannerHour = h
        update.weekPlannerMinute = m
        sent.week = weekDraft.value
      }
      if (monthDraft.isDirty && monthDraft.value.time) {
        const [h, m] = clockParts(monthDraft.value.time)
        update.monthPlannerDay = monthDraft.value.day
        update.monthPlannerHour = h
        update.monthPlannerMinute = m
        sent.month = monthDraft.value
      }
      if (Object.keys(update).length === 0) return
      sentTimingRef.current = sent
      send('proactive_schedule_set', update)
    }, 500)
    return () => window.clearTimeout(timingTimerRef.current)
  }, [
    anyTimingDirty,
    heartbeatDraft.isDirty, heartbeatDraft.value,
    dayDraft.isDirty, dayDraft.value,
    weekDraft.isDirty, weekDraft.value,
    monthDraft.isDirty, monthDraft.value,
    send,
  ])

  const getSchedule = (id: string) => schedules.find(s => s.id === id)

  const handleToggleScheduler = (enabled: boolean) => {
    send('proactive_mode_set', { enabled })
  }

  const handleToggleSchedule = (scheduleId: PlannerId, enabled: boolean) => {
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
  const [taskSearchQuery, setTaskSearchQuery] = usePersistedState(UI_STATE.settings.proactiveTaskSearch)

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

  const plannerRows: { id: PlannerId; label: string; desc: string }[] = [
    { id: 'day-planner', label: t('settings:proactive.planners.dayLabel'), desc: t('settings:proactive.planners.dayDesc') },
    { id: 'week-planner', label: t('settings:proactive.planners.weekLabel'), desc: t('settings:proactive.planners.weekDesc') },
    { id: 'month-planner', label: t('settings:proactive.planners.monthLabel'), desc: t('settings:proactive.planners.monthDesc') },
  ]

  // A planner row's "Runs on" and "Time" cells, plus its out-of-date hint.
  const plannerCells = (id: PlannerId, label: string, disabled: boolean) => {
    const runsOnLabel = `${label}: ${t('settings:proactive.planners.runsOn')}`
    const timeLabel = `${label}: ${t('settings:proactive.planners.time')}`
    if (id === 'day-planner') {
      return {
        runsOn: <span className={styles.plannerStatic}>{t('settings:proactive.planners.everyDay')}</span>,
        time: <input type="time" className={styles.plannerInput} aria-label={timeLabel} value={dayDraft.value} onChange={e => dayDraft.set(e.target.value)} disabled={disabled} />,
        hint: dayDraft.remoteChanged && <RemoteChangeHint onLoadLatest={dayDraft.acceptRemote} />,
      }
    }
    if (id === 'week-planner') {
      return {
        runsOn: (
          <select className={styles.plannerInput} aria-label={runsOnLabel} value={weekDraft.value.day} onChange={e => weekDraft.set(v => ({ ...v, day: e.target.value }))} disabled={disabled}>
            {WEEKDAYS.map(day => <option key={day} value={day}>{t(`settings:proactive.weekdays.${day}`)}</option>)}
          </select>
        ),
        time: <input type="time" className={styles.plannerInput} aria-label={timeLabel} value={weekDraft.value.time} onChange={e => weekDraft.set(v => ({ ...v, time: e.target.value }))} disabled={disabled} />,
        hint: weekDraft.remoteChanged && <RemoteChangeHint onLoadLatest={weekDraft.acceptRemote} />,
      }
    }
    return {
      runsOn: (
        <select className={styles.plannerInput} aria-label={runsOnLabel} title={t('settings:proactive.planners.monthDayHint')} value={monthDraft.value.day} onChange={e => monthDraft.set(v => ({ ...v, day: Number(e.target.value) }))} disabled={disabled}>
          {MONTH_DAYS.map(day => <option key={day} value={day}>{t('settings:proactive.planners.monthDay', { day: formatNumber(day) })}</option>)}
        </select>
      ),
      time: <input type="time" className={styles.plannerInput} aria-label={timeLabel} value={monthDraft.value.time} onChange={e => monthDraft.set(v => ({ ...v, time: e.target.value }))} disabled={disabled} />,
      hint: monthDraft.remoteChanged && <RemoteChangeHint onLoadLatest={monthDraft.acceptRemote} />,
    }
  }

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>{t('settings:proactive.title')}</h3>
        <p>{t('settings:proactive.subtitle')}</p>
      </div>

      {/* Master Toggle: the one switch for tasks and planners */}
      <div className={styles.settingsForm}>
        <div className={styles.toggleGroup}>
          <div className={styles.toggleInfo}>
            <span className={styles.toggleLabel}>{t('settings:proactive.enableLabel')}</span>
            <span className={`${styles.toggleDesc} ${styles.readableDesc}`}>
              {t('settings:proactive.enableDesc')}
            </span>
          </div>
          <input
            type="checkbox"
            className={styles.toggle}
            aria-label={t('settings:proactive.enableLabel')}
            checked={schedulerEnabled}
            onChange={(e) => handleToggleScheduler(e.target.checked)}
            disabled={isLoadingScheduler}
          />
        </div>
      </div>

      {/* Toggleable Content */}
      <div className={`${styles.toggleableContent} ${!schedulerEnabled ? styles.disabledContent : ''}`}>
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

          {/* How often missed tasks are picked up (the heartbeat interval) */}
          {hasLoadedTiming && (
            <div className={styles.catchUpRow}>
              <div className={styles.plannerText}>
                <label htmlFor="proactive-catch-up" className={styles.plannerName}>{t('settings:proactive.catchUp.label')}</label>
                <span className={styles.plannerDesc}>{t('settings:proactive.catchUp.desc')}</span>
                {heartbeatDraft.remoteChanged && <RemoteChangeHint onLoadLatest={heartbeatDraft.acceptRemote} />}
              </div>
              <select
                id="proactive-catch-up"
                className={styles.plannerInput}
                value={heartbeatDraft.value}
                onChange={e => heartbeatDraft.set(Number(e.target.value))}
                disabled={!schedulerEnabled}
              >
                {heartbeatOptions.map(minutes => (
                  <option key={minutes} value={minutes}>{formatInterval(minutes)}</option>
                ))}
              </select>
            </div>
          )}
        </div>

        {/* Planners: one aligned row each (name, runs on, time, on/off) */}
        <div className={styles.subsection}>
          <h4 className={styles.subsectionTitle}>{t('settings:proactive.plannersTitle')}</h4>
          <p className={styles.subsectionDesc}>
            {t('settings:proactive.plannersDesc')}
          </p>
          {hasLoadedTiming && (
            <div className={styles.plannerTable}>
              <div className={styles.plannerHead} aria-hidden="true">
                <span />
                <span>{t('settings:proactive.planners.runsOn')}</span>
                <span>{t('settings:proactive.planners.time')}</span>
                <span />
              </div>
              {plannerRows.map(item => {
                const schedule = getSchedule(item.id)
                const enabled = schedule?.enabled ?? false
                const cells = plannerCells(item.id, item.label, !schedulerEnabled || !enabled)
                return (
                  <div key={item.id} className={`${styles.plannerRow} ${!enabled ? styles.plannerOff : ''}`}>
                    <div className={styles.plannerText}>
                      <span className={styles.plannerName}>{item.label}</span>
                      <span className={styles.plannerDesc}>{item.desc}</span>
                      {cells.hint}
                    </div>
                    {cells.runsOn}
                    {cells.time}
                    <input
                      type="checkbox"
                      className={styles.toggle}
                      aria-label={item.label}
                      checked={enabled}
                      onChange={(e) => handleToggleSchedule(item.id, e.target.checked)}
                      disabled={isLoadingScheduler || !schedulerEnabled}
                    />
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
          task={liveEditingTask}
          onClose={() => {
            setShowTaskForm(false)
            setEditingTask(null)
          }}
          onSave={(taskData) => {
            savingTaskRef.current = true
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
