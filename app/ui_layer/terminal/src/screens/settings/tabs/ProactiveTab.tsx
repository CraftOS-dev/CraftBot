/**
 * Settings > Proactive, as the browser's Proactive tab: proactive mode, the
 * heartbeat and the day, week and month planners (scheduler schedules), the
 * task table (name, frequency, next run, on) with a filter, the add and edit
 * form, removal and reset (both confirmed).
 *
 * The edit form is a draft over the live task: a change made elsewhere while
 * it is open shows a "load latest" row instead of being lost on save.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector, send } from '../../../state/hooks'
import { RESOURCES, useResource } from '../../../../../browser/frontend/src/store/resources'
import { useServerDraft } from '../../../../../browser/frontend/src/hooks/useServerDraft'
import { setTaskEnabled, type ProactiveTask } from '../../../../../browser/frontend/src/store/slices/proactiveSettingsSlice'
import {
  selectProactiveHasLoadedConfig,
  selectProactiveHasLoadedMode,
  selectProactiveHasLoadedTasks,
  selectProactiveTasks,
  selectSchedulerEnabled,
  selectSchedules,
} from '../../../../../browser/frontend/src/store/selectors/proactiveSettings'
import * as TB from '../../../input/TextBuffer'
import { glyphs } from '../../../theme/theme'
import { useTab, useTabKeys } from '../tabContext'
import { FormView, useForm, type FormRow } from '../coreForm'
import { useExternalEditor, useFlash, useInbound } from '../coreHooks'
import {
  FREQUENCIES,
  PRIORITY_VALUES,
  WEEKDAYS,
  describeCron,
  parseClock,
  priorityLevel,
  type PriorityLevel,
} from '../coreLogic'
import { fieldKey } from '../../../ui/TextField'
import { padEnd } from '../../../text/width'

interface TaskForm {
  name: string
  frequency: string
  instruction: string
  enabled: boolean
  priority: PriorityLevel
  notify: boolean
  time: string
  day: string
}

function taskToForm(task: ProactiveTask | null): TaskForm {
  return {
    name: task?.name || '',
    frequency: task?.frequency || 'daily',
    instruction: task?.instruction || '',
    enabled: task?.enabled ?? true,
    priority: task ? priorityLevel(task.priority) : 'medium',
    notify: task ? task.permissionTier >= 1 : true,
    time: task?.time || '',
    day: task?.day || '',
  }
}

const SCHEDULES = [
  { id: 'heartbeat', label: 'proactive.heartbeat', group: 'heartbeat' },
  { id: 'day-planner', label: 'proactive.dayPlanner', group: 'planners' },
  { id: 'week-planner', label: 'proactive.weekPlanner', group: 'planners' },
  { id: 'month-planner', label: 'proactive.monthPlanner', group: 'planners' },
] as const

export function ProactiveTab() {
  const { t, i18n } = useTranslation('settingsCore')
  const dispatch = useAppDispatch()
  const { active, width, height } = useTab()
  const form = useForm()
  const [flash, say, clearFlash] = useFlash()
  const { edit } = useExternalEditor()
  const g = glyphs()

  useResource(RESOURCES.proactiveMode)
  useResource(RESOURCES.schedulerConfig)
  useResource(RESOURCES.proactiveTasks)
  const enabled = useAppSelector(selectSchedulerEnabled)
  const schedules = useAppSelector(selectSchedules)
  const tasks = useAppSelector(selectProactiveTasks)
  const loadedMode = useAppSelector(selectProactiveHasLoadedMode)
  const loadedConfig = useAppSelector(selectProactiveHasLoadedConfig)
  const loadedTasks = useAppSelector(selectProactiveHasLoadedTasks)

  // null: the list; 'new': the add form; else the id of the task being edited.
  const [editing, setEditing] = useState<string | null>(null)
  const [snapshot, setSnapshot] = useState<ProactiveTask | null>(null)
  const [filter, setFilter] = useState<TB.Buffer>(TB.EMPTY)
  const [filtering, setFiltering] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [savingTask, setSavingTask] = useState(false)

  const liveTask = editing && editing !== 'new' ? tasks.find(x => x.id === editing) ?? snapshot : null
  const draft = useServerDraft(taskToForm(liveTask))
  const value = draft.value
  const setField = <K extends keyof TaskForm>(key: K, v: TaskForm[K]) => draft.set(prev => ({ ...prev, [key]: v }))

  useInbound(['proactive_task_add', 'proactive_task_update'], data => {
    if (!savingTask) return
    setSavingTask(false)
    const d = data as { success: boolean; error?: string }
    if (d.success) {
      form.select(editing && editing !== 'new' ? `task:${editing}` : 'task.add')
      setEditing(null)
      setSnapshot(null)
      say(t('proactive.taskSaved'), 'success')
    } else say(t('proactive.taskSaveFailed', { error: d.error ?? '' }), 'error', 8000)
  })
  useInbound('proactive_task_remove', data => {
    const d = data as { success: boolean; error?: string }
    if (!d.success) say(t('proactive.removeFailed', { error: d.error ?? '' }), 'error')
  })
  useInbound('proactive_tasks_reset', data => {
    if (!resetting) return
    setResetting(false)
    const d = data as { success?: boolean }
    say(d.success === false ? t('proactive.resetFailed') : t('proactive.resetDone'), d.success === false ? 'error' : 'success')
  })

  const scheduleOf = (id: string) => schedules.find(s => s.id === id)

  const openForm = (task: ProactiveTask | null) => {
    form.closeAll()
    setEditing(task ? task.id : 'new')
    setSnapshot(task)
    draft.acceptRemote()
    form.select('task.name')
    setFiltering(false)
  }

  const closeForm = () => {
    form.closeAll()
    form.select(editing && editing !== 'new' ? `task:${editing}` : 'task.add')
    clearFlash()
    setEditing(null)
    setSnapshot(null)
    draft.acceptRemote()
  }

  const saveTask = () => {
    if (!value.name.trim()) {
      say(t('proactive.nameRequired'), 'warn')
      form.select('task.name')
      return
    }
    if (!value.instruction.trim()) {
      say(t('proactive.instructionRequired'), 'warn')
      form.select('task.instruction')
      return
    }
    if (value.frequency === 'weekly' && !value.day) {
      say(t('proactive.dayRequired'), 'warn')
      form.select('task.day')
      return
    }
    const data = {
      name: value.name.trim(),
      frequency: value.frequency,
      instruction: value.instruction.trim(),
      enabled: value.enabled,
      priority: PRIORITY_VALUES[value.priority],
      permissionTier: value.notify ? 1 : 0,
      time: value.frequency !== 'hourly' && value.time ? value.time : undefined,
      day: value.frequency === 'weekly' && value.day ? value.day : undefined,
    }
    setSavingTask(true)
    if (editing && editing !== 'new') send('proactive_task_update', { taskId: editing, updates: data })
    else send('proactive_task_add', { task: data })
  }

  const toggleTask = (task: ProactiveTask) => {
    send('proactive_task_update', { taskId: task.id, updates: { enabled: !task.enabled } })
    dispatch(setTaskEnabled({ taskId: task.id, enabled: !task.enabled }))
  }

  const removeTask = (task: ProactiveTask) => {
    form.confirm(t('proactive.removeConfirm', { name: task.name }), () => send('proactive_task_remove', { taskId: task.id }))
  }

  const editInstruction = async () => {
    const result = await edit(value.instruction, 'instruction.md')
    if (result.error === 'busy') say(t('general.files.editorBusy'), 'warn')
    else if (result.text === null) say(t('general.files.editorFailed', { editor: result.editor, error: result.error ?? '' }), 'error', 8000)
    else {
      setField('instruction', result.text.trim())
      say(result.text.trim() === value.instruction ? t('proactive.instructionUnchanged') : t('proactive.instructionEdited'), 'muted')
    }
  }

  const fmtDate = (iso?: string) => {
    if (!iso) return '-'
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return '-'
    const sameDay = d.toDateString() === new Date().toDateString()
    try {
      return new Intl.DateTimeFormat(i18n.language, sameDay ? { hour: '2-digit', minute: '2-digit' } : { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(d)
    } catch {
      return d.toISOString().slice(0, 16).replace('T', ' ')
    }
  }

  const freqLabel = (task: ProactiveTask) => {
    const base = t(`proactive.freq.${task.frequency}`, { defaultValue: task.frequency })
    if (task.frequency === 'weekly' && task.day) return `${base} ${t(`proactive.days.${task.day}`, { defaultValue: task.day }).slice(0, 3)}`
    return task.time && task.frequency !== 'hourly' ? `${base} ${task.time}` : base
  }

  // ── Rows ──

  const rows: FormRow[] = editing ? formRows() : listRows()

  function formRows(): FormRow[] {
    const out: FormRow[] = [
      { kind: 'heading', text: editing === 'new' ? t('proactive.addTitle') : t('proactive.editTitle') },
      { kind: 'text', id: 'task.name', label: t('proactive.form.name'), value: value.name, placeholder: t('proactive.form.namePlaceholder'), onSubmit: v => setField('name', v.trim()) },
      {
        kind: 'choice',
        id: 'task.frequency',
        label: t('proactive.form.frequency'),
        value: value.frequency,
        options: FREQUENCIES.map(f => ({ value: f, label: t(`proactive.freq.${f}`) })),
        onChange: v => setField('frequency', v),
      },
    ]
    if (value.frequency !== 'hourly') {
      out.push({
        kind: 'text',
        id: 'task.time',
        label: t('proactive.form.time'),
        value: value.time,
        placeholder: t('proactive.form.timePlaceholder'),
        onSubmit: v => {
          if (!v.trim()) return setField('time', '')
          const clock = parseClock(v)
          if (clock) setField('time', clock)
          else say(t('proactive.badTime'), 'warn')
        },
      })
    }
    if (value.frequency === 'weekly') {
      out.push({
        kind: 'choice',
        id: 'task.day',
        label: t('proactive.form.day'),
        value: value.day,
        display: t('proactive.form.pickDay'),
        picker: true,
        options: WEEKDAYS.map(d => ({ value: d, label: t(`proactive.days.${d}`) })),
        onChange: v => setField('day', v),
      })
    }
    out.push(
      {
        kind: 'choice',
        id: 'task.priority',
        label: t('proactive.form.priority'),
        value: value.priority,
        options: (['high', 'medium', 'low'] as const).map(p => ({ value: p, label: t(`proactive.priority.${p}`) })),
        detail: t('proactive.form.priorityHint'),
        onChange: v => setField('priority', v as PriorityLevel),
      },
      { kind: 'toggle', id: 'task.notify', label: t('proactive.form.notify'), value: value.notify, detail: t('proactive.form.notifyHint'), onChange: v => setField('notify', v) },
      {
        kind: 'text',
        id: 'task.instruction',
        label: t('proactive.form.instruction'),
        value: value.instruction,
        placeholder: t('proactive.form.instructionPlaceholder'),
        onSubmit: v => setField('instruction', v.trim()),
        onKey: input => {
          if (input !== 'v') return false
          void editInstruction()
          return true
        },
        hints: [{ keys: 'v', label: t('hint.editor') }],
      },
    )
    if (value.instruction) out.push({ kind: 'note', text: value.instruction, maxLines: 3, indent: 4 })
    out.push(
      { kind: 'toggle', id: 'task.enabled', label: t('proactive.form.enabled'), value: value.enabled, onChange: v => setField('enabled', v) },
      {
        kind: 'action',
        id: 'task.save',
        label: savingTask ? t('proactive.saving') : editing === 'new' ? t('proactive.addTask') : t('proactive.saveChanges'),
        tone: 'brand',
        disabled: savingTask,
        onRun: saveTask,
      },
      { kind: 'action', id: 'task.cancel', label: t('proactive.cancel'), onRun: closeForm },
    )
    if (draft.remoteChanged) {
      out.push({ kind: 'action', id: 'task.loadLatest', label: t('changedElsewhereAction'), tone: 'warn', onRun: () => draft.acceptRemote() })
    }
    return out
  }

  function listRows(): FormRow[] {
    const out: FormRow[] = [
      {
        kind: 'toggle',
        id: 'mode',
        label: t('proactive.mode'),
        value: enabled,
        disabled: !loadedMode,
        detail: t('proactive.modeDetail'),
        onChange: on => send('proactive_mode_set', { enabled: on }),
      },
    ]
    for (const group of ['heartbeat', 'planners'] as const) {
      out.push({ kind: 'heading', text: group === 'heartbeat' ? t('proactive.heartbeatTitle') : t('proactive.plannersTitle') })
      for (const item of SCHEDULES.filter(s => s.group === group)) {
        const schedule = scheduleOf(item.id)
        out.push({
          kind: 'toggle',
          id: `schedule.${item.id}`,
          label: t(item.label),
          value: schedule?.enabled ?? false,
          disabled: !loadedConfig || !enabled || !schedule,
          detail: schedule ? describeCron(schedule.schedule, t, i18n.language) : loadedConfig ? t('proactive.notScheduled') : t('proactive.loading'),
          onChange: on => send('scheduler_config_update', { updates: { schedules: [{ id: item.id, enabled: on }] } }),
        })
      }
    }

    const query = filter.text.trim().toLowerCase()
    const shown = query ? tasks.filter(x => x.name.toLowerCase().includes(query) || x.instruction.toLowerCase().includes(query)) : tasks
    out.push({
      kind: 'heading',
      text: t('proactive.tasksTitle', { count: tasks.length }),
      aside: query || filtering ? `/${filter.text}${filtering ? '_' : ''}  ${t('proactive.shown', { shown: shown.length, total: tasks.length })}` : undefined,
    })
    out.push({
      kind: 'action',
      id: 'task.add',
      label: t('proactive.addTask'),
      tone: 'brand',
      disabled: !enabled,
      detail: enabled ? undefined : t('proactive.modeOff'),
      onRun: () => openForm(null),
    })
    if (!loadedTasks) out.push({ kind: 'note', text: t('proactive.loadingTasks') })
    else if (!tasks.length) out.push({ kind: 'note', text: t('proactive.noTasks') })
    else {
      const nameW = Math.max(12, Math.floor((width - 4) * 0.38))
      const freqW = Math.max(10, Math.floor((width - 4) * 0.24))
      const nextW = Math.max(10, Math.floor((width - 4) * 0.24))
      out.push({
        kind: 'note',
        indent: 2,
        tone: 'muted',
        text: `${padEnd(t('proactive.col.name'), nameW)}${padEnd(t('proactive.col.frequency'), freqW)}${padEnd(t('proactive.col.next'), nextW)}${t('proactive.col.on')}`,
        maxLines: 1,
      })
      for (const task of shown) {
        out.push({
          kind: 'item',
          id: `task:${task.id}`,
          dim: !task.enabled,
          cells: [
            { text: task.name, width: nameW },
            { text: freqLabel(task), width: freqW, tone: 'muted' },
            { text: task.enabled ? fmtDate(task.nextRun) : '-', width: nextW, tone: 'muted' },
            { text: task.enabled ? g.checked : g.unchecked, tone: task.enabled ? 'success' : 'muted' },
          ],
          onRun: () => openForm(task),
          onKey: (input, key) => {
            if (input === 'e') openForm(task)
            else if (input === ' ') toggleTask(task)
            else if (input === 'd' || key.delete) removeTask(task)
            else return false
            return true
          },
          hints: [
            { keys: 'Space', label: t('hint.onOff') },
            { keys: 'd', label: t('hint.delete') },
          ],
        })
      }
      const sel = shown.find(x => form.state.selId === `task:${x.id}`)
      if (sel) {
        out.push({
          kind: 'note',
          indent: 2,
          text: `${t(`proactive.priority.${priorityLevel(sel.priority)}`)} · ${sel.permissionTier >= 1 ? t('proactive.notifies') : t('proactive.silent')} · ${t('proactive.runs', { count: sel.runCount })}${sel.lastRun ? ` · ${t('proactive.last', { date: fmtDate(sel.lastRun) })}` : ''}`,
          maxLines: 1,
        })
        out.push({ kind: 'note', indent: 2, text: sel.instruction, maxLines: 2 })
      }
    }
    out.push(
      { kind: 'heading', text: t('proactive.resetTitle') },
      { kind: 'note', text: t('proactive.resetDesc') },
      {
        kind: 'action',
        id: 'reset',
        label: resetting ? t('proactive.resetting') : t('proactive.reset'),
        tone: 'error',
        disabled: resetting,
        onRun: () =>
          form.confirm(t('proactive.resetConfirm'), () => {
            setResetting(true)
            send('proactive_tasks_reset')
          }),
      },
    )
    return out
  }

  useTabKeys((input, key) => {
    if (filtering) {
      if (key.escape || key.return) {
        setFiltering(false)
        if (key.escape) setFilter(TB.EMPTY)
        return true
      }
      if (key.upArrow || key.downArrow) return form.handleKey(rows, '', key)
      const next = fieldKey(filter, input, key)
      if (next) setFilter(next)
      return true
    }
    if (form.handleKey(rows, input, key)) return true
    if (!editing && !form.modal) {
      if (input === 'a' && enabled) {
        openForm(null)
        return true
      }
      if (input === '/' && tasks.length) {
        setFiltering(true)
        form.select('task.add')
        return true
      }
    }
    if (editing && key.escape) {
      closeForm()
      return true
    }
    return false
  })

  const hints = editing
    ? [{ keys: 'Esc', label: t('hint.closeForm') }]
    : [
        { keys: 'a', label: t('hint.add') },
        ...(tasks.length ? [{ keys: '/', label: t('hint.filter') }] : []),
      ]

  return <FormView form={form} rows={rows} width={width} height={height} active={active} flash={flash} hints={hints} />
}
