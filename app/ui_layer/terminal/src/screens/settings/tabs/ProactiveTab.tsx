/**
 * Settings > Proactive, as the browser's Proactive tab: proactive mode, the
 * recurring tasks grouped by frequency (filter, add, edit, on or off,
 * delete, move to the main chat when their chat is gone), the heartbeat (on
 * or off, interval, checklist), the daily, weekly and monthly planners (on
 * or off, day and time) and reset to default (confirmed).
 *
 * Edits are drafts over the saved values: the task form shows a "load
 * latest" row when the task changes elsewhere, the interval and planner
 * times save shortly after a change, and the checklist saves on Save.
 */
import { useEffect, useRef, useState } from 'react'
import type { Key } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector, send } from '../../../state/hooks'
import { RESOURCES, useResource } from '../../../../../browser/frontend/src/store/resources'
import { useServerDraft } from '../../../../../browser/frontend/src/hooks/useServerDraft'
import { setCronJobEnabled, type CronJob, type ProactiveSchedule } from '../../../../../browser/frontend/src/store/slices/proactiveSettingsSlice'
import {
  selectCronJobs,
  selectCronJobsLoaded,
  selectHeartbeatChecklist,
  selectHeartbeatOptions,
  selectProactiveHasLoadedConfig,
  selectProactiveHasLoadedMode,
  selectProactiveSchedule,
  selectSchedulerEnabled,
  selectSchedules,
} from '../../../../../browser/frontend/src/store/selectors/proactiveSettings'
import * as TB from '../../../input/TextBuffer'
import { glyphs } from '../../../theme/theme'
import { fieldKey } from '../../../ui/TextField'
import { useTab, useTabKeys } from '../tabContext'
import { FormView, useForm, type FormRow } from '../coreForm'
import { useExternalEditor, useFlash, useInbound } from '../coreHooks'
import { useTextFocus } from '../connectKit'
import {
  FREQUENCIES,
  PRIORITY_VALUES,
  WEEKDAYS,
  checklistLines,
  filterJobs,
  groupJobs,
  intervalLabel,
  jobWhen,
  parseClock,
  priorityLevel,
  scheduleUpdate,
  type PlannerTiming,
  type PriorityLevel,
} from '../coreLogic'

const DEFAULT_SCHEDULE: ProactiveSchedule = {
  heartbeatMinutes: 30,
  dayPlannerTime: '07:00',
  weekPlannerDay: 'sunday',
  weekPlannerTime: '17:00',
  monthPlannerDay: 1,
  monthPlannerTime: '08:00',
}

const MONTH_DAYS = Array.from({ length: 31 }, (_, i) => i + 1)
const CHECKLIST_PREVIEW = 6

type RemoteDraft = { remoteChanged: boolean; acceptRemote: () => void }
type RemoteProps = Partial<Pick<Extract<FormRow, { kind: 'text' }>, 'detail' | 'detailTone' | 'onKey' | 'hints'>>

interface JobForm {
  name: string
  frequency: string
  instruction: string
  enabled: boolean
  priority: PriorityLevel
  notify: boolean
  time: string
  day: string
}

function jobToForm(job: CronJob | null): JobForm {
  return {
    name: job?.name || '',
    frequency: job?.frequency || 'daily',
    instruction: job?.instruction || '',
    enabled: job?.enabled ?? true,
    priority: job ? priorityLevel(job.priority) : 'medium',
    notify: job ? job.permissionTier >= 1 : true,
    time: job?.time || '',
    day: job?.day || '',
  }
}

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
  useResource(RESOURCES.cronJobs)
  useResource(RESOURCES.proactiveSchedule)
  useResource(RESOURCES.heartbeatChecklist)
  const enabled = useAppSelector(selectSchedulerEnabled)
  const schedules = useAppSelector(selectSchedules)
  const jobs = useAppSelector(selectCronJobs)
  const loadedMode = useAppSelector(selectProactiveHasLoadedMode)
  const loadedConfig = useAppSelector(selectProactiveHasLoadedConfig)
  const loadedJobs = useAppSelector(selectCronJobsLoaded)
  const savedTiming = useAppSelector(selectProactiveSchedule)
  const heartbeatOptions = useAppSelector(selectHeartbeatOptions)
  const savedChecklist = useAppSelector(selectHeartbeatChecklist)
  const loadingScheduler = !loadedMode || !loadedConfig

  // null: the list; 'new': the add form; else the id of the task being edited.
  const [editing, setEditing] = useState<string | null>(null)
  const [snapshot, setSnapshot] = useState<CronJob | null>(null)
  const [filter, setFilter] = useState<TB.Buffer>(TB.EMPTY)
  const [filtering, setFiltering] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [savingJob, setSavingJob] = useState(false)
  const [savingChecklist, setSavingChecklist] = useState(false)
  useTextFocus(active && filtering)

  // This tab's own requests in flight; replies to other clients' requests
  // only update data.
  const updating = useRef(new Map<string, 'toggle' | 'move'>())
  const removing = useRef<string | null>(null)
  const sentChecklist = useRef<string | null>(null)
  const sentTiming = useRef<PlannerTiming | null>(null)

  const liveJob = editing && editing !== 'new' ? jobs.find(x => x.id === editing) ?? snapshot : null
  const draft = useServerDraft(jobToForm(liveJob))
  const value = draft.value
  const setField = <K extends keyof JobForm>(key: K, v: JobForm[K]) => draft.set(prev => ({ ...prev, [key]: v }))

  const checklist = useServerDraft(savedChecklist ?? '')
  const checklistRef = useRef(checklist.value)
  checklistRef.current = checklist.value

  const saved = savedTiming ?? DEFAULT_SCHEDULE
  const heartbeatDraft = useServerDraft(saved.heartbeatMinutes)
  const dayDraft = useServerDraft(saved.dayPlannerTime)
  const weekDraft = useServerDraft({ day: saved.weekPlannerDay, time: saved.weekPlannerTime })
  const monthDraft = useServerDraft({ day: saved.monthPlannerDay, time: saved.monthPlannerTime })
  const timingRef = useRef<PlannerTiming>({})
  timingRef.current = { heartbeat: heartbeatDraft.value, day: dayDraft.value, week: weekDraft.value, month: monthDraft.value }

  // ── Replies to this tab's requests (the slice applies the data) ──

  useInbound(['cron_job_add', 'cron_job_update'], (data, type) => {
    const d = data as { jobId?: string; success: boolean; error?: string }
    const kind = type === 'cron_job_update' && d.jobId ? updating.current.get(d.jobId) : undefined
    if (kind && d.jobId) {
      updating.current.delete(d.jobId)
      if (!d.success) say(t('proactive.updateFailed', { error: d.error ?? '' }), 'error', 8000)
      else if (kind === 'move') say(t('proactive.moved'), 'success')
      return
    }
    if (!savingJob) return
    setSavingJob(false)
    if (d.success) {
      form.select(editing && editing !== 'new' ? `job:${editing}` : 'job.add')
      setEditing(null)
      setSnapshot(null)
      say(t('proactive.taskSaved'), 'success')
    } else say(t('proactive.taskSaveFailed', { error: d.error ?? '' }), 'error', 8000)
  })
  useInbound('cron_job_remove', data => {
    const d = data as { jobId?: string; success: boolean; error?: string }
    if (!d.jobId || d.jobId !== removing.current) return
    removing.current = null
    if (!d.success) say(t('proactive.removeFailed', { error: d.error ?? '' }), 'error', 8000)
  })
  useInbound('cron_jobs_reset', data => {
    if (!resetting) return
    setResetting(false)
    const d = data as { success: boolean; error?: string }
    if (d.success) say(t('proactive.resetDone'), 'success')
    else say(d.error || t('proactive.resetFailed'), 'error', 8000)
  })
  useInbound('heartbeat_checklist_set', data => {
    const sent = sentChecklist.current
    if (sent === null) return
    sentChecklist.current = null
    setSavingChecklist(false)
    const d = data as { success: boolean; error?: string }
    if (!d.success) {
      say(d.error || t('proactive.checklistFailed'), 'error', 8000)
      return
    }
    if (checklistRef.current === sent) checklist.reset()
    say(t('proactive.checklistSaved'), 'success')
  })
  useInbound('proactive_schedule_set', data => {
    const sent = sentTiming.current
    if (!sent) return
    sentTiming.current = null
    const d = data as { success: boolean; error?: string }
    if (!d.success) {
      say(d.error || t('proactive.scheduleFailed'), 'error', 8000)
      return
    }
    const now = timingRef.current
    const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
    if (sent.heartbeat !== undefined && now.heartbeat === sent.heartbeat) heartbeatDraft.reset()
    if (sent.day !== undefined && now.day === sent.day) dayDraft.reset()
    if (sent.week !== undefined && same(now.week, sent.week)) weekDraft.reset()
    if (sent.month !== undefined && same(now.month, sent.month)) monthDraft.reset()
    say(t('proactive.scheduleSaved'), 'success', 2500)
  })

  // Save the interval and planner times shortly after an edit, as the
  // browser does; a clean draft is the saved value, so only edits are sent.
  const timingDirty = heartbeatDraft.isDirty || dayDraft.isDirty || weekDraft.isDirty || monthDraft.isDirty
  useEffect(() => {
    if (!timingDirty) return
    const timer = setTimeout(() => {
      const { update, sent } = scheduleUpdate({
        heartbeat: heartbeatDraft.isDirty ? heartbeatDraft.value : undefined,
        day: dayDraft.isDirty ? dayDraft.value : undefined,
        week: weekDraft.isDirty ? weekDraft.value : undefined,
        month: monthDraft.isDirty ? monthDraft.value : undefined,
      })
      if (!Object.keys(update).length) return
      sentTiming.current = sent
      send('proactive_schedule_set', update)
    }, 500)
    return () => clearTimeout(timer)
    // The drafts are captured through their values and dirty flags.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    timingDirty,
    heartbeatDraft.isDirty, heartbeatDraft.value,
    dayDraft.isDirty, dayDraft.value,
    weekDraft.isDirty, weekDraft.value,
    monthDraft.isDirty, monthDraft.value,
  ])

  // ── Actions ──

  const scheduleOn = (id: string) => schedules.find(s => s.id === id)?.enabled ?? false
  const toggleSchedule = (id: string, on: boolean) => send('scheduler_config_update', { updates: { schedules: [{ id, enabled: on }] } })

  const openForm = (job: CronJob | null) => {
    form.closeAll()
    setEditing(job ? job.id : 'new')
    setSnapshot(job)
    draft.acceptRemote()
    form.select('form.name')
    setFiltering(false)
  }

  const closeForm = () => {
    form.closeAll()
    form.select(editing && editing !== 'new' ? `job:${editing}` : 'job.add')
    clearFlash()
    setEditing(null)
    setSnapshot(null)
    draft.acceptRemote()
  }

  const saveJob = () => {
    if (!value.name.trim()) {
      say(t('proactive.nameRequired'), 'warn')
      form.select('form.name')
      return
    }
    if (!value.instruction.trim()) {
      say(t('proactive.instructionRequired'), 'warn')
      form.select('form.instruction')
      return
    }
    const data = {
      name: value.name.trim(),
      frequency: value.frequency,
      instruction: value.instruction.trim(),
      enabled: value.enabled,
      priority: PRIORITY_VALUES[value.priority],
      permissionTier: value.notify ? 1 : 0,
      time: value.time || undefined,
      day: value.day || undefined,
    }
    setSavingJob(true)
    if (editing && editing !== 'new') send('cron_job_update', { jobId: editing, updates: data })
    else send('cron_job_add', { job: data })
  }

  const toggleJob = (job: CronJob) => {
    updating.current.set(job.id, 'toggle')
    send('cron_job_update', { jobId: job.id, updates: { enabled: !job.enabled } })
    dispatch(setCronJobEnabled({ jobId: job.id, enabled: !job.enabled }))
  }

  const moveToMain = (job: CronJob) => {
    // The action row goes away with the move; stay on the task.
    form.select(`job:${job.id}`)
    updating.current.set(job.id, 'move')
    send('cron_job_update', { jobId: job.id, updates: { sessionId: 'main' } })
  }

  const removeJob = (job: CronJob) => {
    form.confirm(t('proactive.removeConfirm', { name: job.name }), () => {
      removing.current = job.id
      send('cron_job_remove', { jobId: job.id })
    })
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

  const editChecklist = async () => {
    const result = await edit(checklist.value, 'heartbeat-checklist.md')
    if (result.error === 'busy') say(t('general.files.editorBusy'), 'warn')
    else if (result.text === null) say(t('general.files.editorFailed', { editor: result.editor, error: result.error ?? '' }), 'error', 8000)
    else {
      const next = result.text.replace(/\r\n/g, '\n').trimEnd()
      if (next === checklist.value) say(t('proactive.checklistUnchanged'), 'muted')
      else {
        checklist.set(next)
        say(t('proactive.checklistEdited'), 'muted')
      }
    }
  }

  const saveChecklist = () => {
    if (!checklist.isDirty) return
    sentChecklist.current = checklist.value
    setSavingChecklist(true)
    send('heartbeat_checklist_set', { checklist: checklist.value })
  }

  const fmtDate = (iso: string) => {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    try {
      return new Intl.DateTimeFormat(i18n.language, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(d)
    } catch {
      return d.toISOString().slice(0, 16).replace('T', ' ')
    }
  }

  const jobChat = (job: CronJob) => (job.sessionId === 'main' ? t('proactive.mainChat') : job.sessionTitle || t('proactive.untitledChat'))

  // A row's "changed elsewhere" detail and the key that loads the latest.
  const remote = (d: RemoteDraft): RemoteProps =>
    d.remoteChanged
      ? {
          detail: t('changedElsewhere'),
          detailTone: 'warn',
          onKey: (input: string, key: Key) => {
            if (input !== 'L' && !(key.ctrl && input === 'l')) return false
            d.acceptRemote()
            return true
          },
          hints: [{ keys: 'L', label: t('hint.loadLatest') }],
        }
      : {}

  const timeRow = (id: string, time: string, set: (clock: string) => void, d: RemoteDraft, off: boolean, detail?: string): FormRow => ({
    kind: 'text',
    id,
    label: `  ${t('proactive.time')}`,
    value: time,
    placeholder: 'HH:MM',
    disabled: off,
    detail,
    onSubmit: v => {
      if (!v.trim()) return
      const clock = parseClock(v)
      if (clock) set(clock)
      else say(t('proactive.badTime'), 'warn')
    },
    ...remote(d),
  })

  // ── Rows ──

  const rows: FormRow[] = editing ? formRows() : listRows()

  function formRows(): FormRow[] {
    const out: FormRow[] = [
      { kind: 'heading', text: editing === 'new' ? t('proactive.addTitle') : t('proactive.editTitle') },
      { kind: 'text', id: 'form.name', label: t('proactive.form.name'), value: value.name, placeholder: t('proactive.form.namePlaceholder'), onSubmit: v => setField('name', v.trim()) },
      {
        kind: 'choice',
        id: 'form.frequency',
        label: t('proactive.form.frequency'),
        value: value.frequency,
        options: FREQUENCIES.map(f => ({ value: f, label: t(`proactive.freq.${f}`) })),
        onChange: v => setField('frequency', v),
      },
    ]
    if (value.frequency !== 'hourly') {
      out.push({
        kind: 'text',
        id: 'form.time',
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
        id: 'form.day',
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
        id: 'form.priority',
        label: t('proactive.form.priority'),
        value: value.priority,
        options: (['high', 'medium', 'low'] as const).map(p => ({ value: p, label: t(`proactive.level.${p}`) })),
        detail: t('proactive.form.priorityHint'),
        onChange: v => setField('priority', v as PriorityLevel),
      },
      { kind: 'toggle', id: 'form.notify', label: t('proactive.form.notify'), value: value.notify, detail: t('proactive.form.notifyHint'), onChange: v => setField('notify', v) },
      {
        kind: 'text',
        id: 'form.instruction',
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
      { kind: 'toggle', id: 'form.enabled', label: t('proactive.form.enabled'), value: value.enabled, detail: t('proactive.form.enabledHint'), onChange: v => setField('enabled', v) },
      {
        kind: 'action',
        id: 'form.save',
        label: savingJob ? t('proactive.saving') : editing === 'new' ? t('proactive.addTask') : t('proactive.saveChanges'),
        tone: 'brand',
        disabled: savingJob,
        onRun: saveJob,
      },
      { kind: 'action', id: 'form.cancel', label: t('proactive.cancel'), onRun: closeForm },
    )
    if (draft.remoteChanged) {
      out.push({ kind: 'action', id: 'form.loadLatest', label: t('changedElsewhereAction'), tone: 'warn', onRun: () => draft.acceptRemote() })
    }
    return out
  }

  function listRows(): FormRow[] {
    return [
      {
        kind: 'toggle',
        id: 'mode',
        label: t('proactive.mode'),
        value: enabled,
        disabled: loadingScheduler,
        detail: t('proactive.modeDetail'),
        onChange: on => send('proactive_mode_set', { enabled: on }),
      },
      ...jobRows(),
      ...heartbeatRows(),
      ...plannerRows(),
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
            send('cron_jobs_reset')
          }),
      },
    ]
  }

  function jobRows(): FormRow[] {
    const query = filter.text.trim()
    const shown = filterJobs(jobs, query)
    const out: FormRow[] = [
      {
        kind: 'heading',
        text: t('proactive.tasksTitle'),
        aside:
          query || filtering
            ? `/${filter.text}${filtering ? '_' : ''}  ${t('proactive.shown', { shown: shown.length, total: jobs.length })}`
            : loadedJobs
              ? t('proactive.count', { count: jobs.length })
              : undefined,
      },
      { kind: 'note', text: t('proactive.tasksDesc') },
      {
        kind: 'action',
        id: 'job.add',
        label: t('proactive.addTask'),
        tone: 'brand',
        disabled: !enabled,
        detail: enabled ? undefined : t('proactive.modeOff'),
        onRun: () => openForm(null),
      },
    ]
    if (!loadedJobs) return [...out, { kind: 'note', text: t('proactive.loadingTasks') }]
    if (!jobs.length) return [...out, { kind: 'note', text: t('proactive.noTasks') }]
    const room = Math.max(20, width - 6)
    const nameW = Math.max(12, Math.floor(room * 0.42))
    const whenW = Math.max(8, Math.min(18, Math.floor(room * 0.24)))
    for (const group of groupJobs(shown)) {
      out.push({ kind: 'note', tone: 'info', text: `${t(`proactive.freq.${group.frequency}`)} · ${t('proactive.count', { count: group.jobs.length })}`, maxLines: 1 })
      for (const job of group.jobs) {
        const off = !job.enabled || !job.available
        out.push({
          kind: 'item',
          id: `job:${job.id}`,
          dim: off,
          disabled: !enabled,
          cells: [
            { text: job.enabled ? g.checked : g.unchecked, width: 2, tone: job.enabled ? 'success' : 'muted' },
            { text: job.name, width: nameW },
            { text: jobWhen(job, t), width: whenW, tone: 'muted' },
            job.available ? { text: t('proactive.runsIn', { chat: jobChat(job) }), tone: 'muted' } : { text: t('proactive.unavailableShort'), tone: 'warn' },
          ],
          onRun: () => openForm(job),
          onKey: (input, key) => {
            if (input === 'e') openForm(job)
            else if (input === ' ') toggleJob(job)
            else if (input === 'd' || key.delete) removeJob(job)
            else return false
            return true
          },
          hints: [
            { keys: 'Space', label: t('hint.onOff') },
            { keys: 'd', label: t('hint.delete') },
          ],
        })
        out.push({ kind: 'note', text: job.instruction, indent: 4, maxLines: 1 })
        const meta = [
          job.lastRun ? t('proactive.lastRun', { date: fmtDate(job.lastRun) }) : t('proactive.neverRun'),
          ...(job.runCount > 0 ? [t('proactive.runs', { count: job.runCount })] : []),
          job.permissionTier >= 1 ? t('proactive.notifies') : t('proactive.silent'),
          t(`proactive.priority.${priorityLevel(job.priority)}`),
        ]
        out.push({ kind: 'note', text: meta.join(' · '), indent: 4, maxLines: 1 })
        if (!job.available) {
          out.push(
            { kind: 'note', tone: 'warn', text: t('proactive.unavailable'), indent: 4 },
            { kind: 'action', id: `job:${job.id}:move`, label: `  ${t('proactive.moveToMain')}`, disabled: !enabled, onRun: () => moveToMain(job) },
          )
        }
      }
    }
    if (!shown.length) out.push({ kind: 'note', text: t('picker.none') })
    return out
  }

  function heartbeatRows(): FormRow[] {
    const out: FormRow[] = [
      { kind: 'heading', text: t('proactive.heartbeatTitle') },
      { kind: 'note', text: t('proactive.heartbeatDesc') },
    ]
    if (!savedTiming || savedChecklist === null) return [...out, { kind: 'note', text: t('proactive.loading') }]
    const on = scheduleOn('heartbeat')
    const empty = !checklist.value.trim()
    const lines = checklistLines(checklist.value)
    const options = heartbeatOptions.map(minutes => ({ value: String(minutes), label: intervalLabel(minutes, t) }))
    out.push(
      {
        kind: 'toggle',
        id: 'heartbeat',
        label: t('proactive.heartbeat'),
        value: on,
        disabled: loadingScheduler || !enabled,
        detail: empty ? t('proactive.heartbeatIdle') : t('proactive.heartbeatActive'),
        detailTone: empty ? 'warn' : 'muted',
        onChange: next => toggleSchedule('heartbeat', next),
      },
      {
        kind: 'choice',
        id: 'heartbeat.interval',
        label: `  ${t('proactive.interval')}`,
        value: String(heartbeatDraft.value),
        display: intervalLabel(heartbeatDraft.value, t),
        pickerTitle: t('proactive.interval'),
        options,
        disabled: !enabled || !on,
        onChange: v => heartbeatDraft.set(Number(v)),
        ...remote(heartbeatDraft),
      },
      {
        kind: 'action',
        id: 'heartbeat.checklist',
        label: t('proactive.checklist'),
        disabled: !enabled,
        detail: [lines.length ? t('proactive.checklistItems', { count: lines.length }) : t('proactive.checklistNone'), ...(checklist.isDirty ? [t('model.unsaved')] : [])].join(' · '),
        detailTone: checklist.isDirty ? 'warn' : 'muted',
        onRun: () => void editChecklist(),
      },
    )
    for (const line of lines.slice(0, CHECKLIST_PREVIEW)) out.push({ kind: 'note', text: line, indent: 4, maxLines: 1 })
    if (lines.length > CHECKLIST_PREVIEW) out.push({ kind: 'note', text: t('proactive.checklistMore', { count: lines.length - CHECKLIST_PREVIEW }), indent: 4 })
    if (empty) out.push({ kind: 'note', text: t('proactive.checklistHint'), indent: 4 })
    out.push({
      kind: 'text',
      id: 'heartbeat.add',
      label: `  ${t('proactive.addItem')}`,
      value: '',
      startEmpty: true,
      disabled: !enabled,
      placeholder: t('proactive.addItemPlaceholder'),
      onSubmit: v => {
        const line = v.trim()
        if (line) checklist.set(prev => (prev.trim() ? `${prev.trimEnd()}\n${line}` : line))
      },
    })
    if (checklist.isDirty) {
      out.push(
        {
          kind: 'action',
          id: 'heartbeat.save',
          label: savingChecklist ? t('proactive.saving') : t('proactive.saveChecklist'),
          tone: 'brand',
          disabled: savingChecklist || !enabled,
          onRun: saveChecklist,
        },
        { kind: 'action', id: 'heartbeat.discard', label: t('proactive.discardChecklist'), disabled: savingChecklist, onRun: () => checklist.acceptRemote() },
      )
    }
    if (checklist.remoteChanged) {
      out.push({ kind: 'action', id: 'heartbeat.loadLatest', label: t('changedElsewhereAction'), tone: 'warn', onRun: () => checklist.acceptRemote() })
    }
    return out
  }

  function plannerRows(): FormRow[] {
    const out: FormRow[] = [
      { kind: 'heading', text: t('proactive.plannersTitle') },
      { kind: 'note', text: t('proactive.plannersDesc') },
    ]
    if (!savedTiming) return [...out, { kind: 'note', text: t('proactive.loading') }]
    const planner = (id: string, label: string, desc: string): FormRow => ({
      kind: 'toggle',
      id,
      label,
      value: scheduleOn(id),
      disabled: loadingScheduler || !enabled,
      detail: desc,
      onChange: next => toggleSchedule(id, next),
    })
    const dayOff = !enabled || !scheduleOn('day-planner')
    const weekOff = !enabled || !scheduleOn('week-planner')
    const monthOff = !enabled || !scheduleOn('month-planner')
    out.push(
      planner('day-planner', t('proactive.dayPlanner'), t('proactive.dayPlannerDesc')),
      timeRow('planner.day.time', dayDraft.value, clock => dayDraft.set(clock), dayDraft, dayOff, t('proactive.everyDay')),
      planner('week-planner', t('proactive.weekPlanner'), t('proactive.weekPlannerDesc')),
      {
        kind: 'choice',
        id: 'planner.week.day',
        label: `  ${t('proactive.runsOn')}`,
        value: weekDraft.value.day,
        picker: true,
        pickerTitle: t('proactive.weekPlanner'),
        options: WEEKDAYS.map(d => ({ value: d, label: t(`proactive.days.${d}`) })),
        disabled: weekOff,
        onChange: v => weekDraft.set(w => ({ ...w, day: v })),
        ...remote(weekDraft),
      },
      timeRow('planner.week.time', weekDraft.value.time, clock => weekDraft.set(w => ({ ...w, time: clock })), weekDraft, weekOff),
      planner('month-planner', t('proactive.monthPlanner'), t('proactive.monthPlannerDesc')),
      {
        kind: 'choice',
        id: 'planner.month.day',
        label: `  ${t('proactive.runsOn')}`,
        value: String(monthDraft.value.day),
        picker: true,
        pickerTitle: t('proactive.monthPlanner'),
        options: MONTH_DAYS.map(d => ({ value: String(d), label: t('proactive.monthDay', { day: d }) })),
        disabled: monthOff,
        detail: monthDraft.value.day > 28 ? t('proactive.monthDayHint') : undefined,
        onChange: v => monthDraft.set(m => ({ ...m, day: Number(v) })),
        ...remote(monthDraft),
      },
      timeRow('planner.month.time', monthDraft.value.time, clock => monthDraft.set(m => ({ ...m, time: clock })), monthDraft, monthOff),
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
      if (input === '/' && jobs.length) {
        setFiltering(true)
        form.select('job.add')
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
    : [...(enabled ? [{ keys: 'a', label: t('hint.add') }] : []), ...(jobs.length ? [{ keys: '/', label: t('hint.filter') }] : [])]

  return <FormView form={form} rows={rows} width={width} height={height} active={active} flash={flash} hints={hints} />
}
