/**
 * Settings > Memory, as the browser's Memory tab: memory on or off, the
 * daily processing time and the minimum number of waiting events (both
 * saved shortly after a change), how many events wait now against that
 * minimum, processing on demand, and reset (confirmed). Items and the graph
 * live on the Memory screen.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAppSelector, send } from '../../../state/hooks'
import { RESOURCES, useResource } from '../../../../../browser/frontend/src/store/resources'
import { useServerDraft } from '../../../../../browser/frontend/src/hooks/useServerDraft'
import type { MemorySchedule } from '../../../../../browser/frontend/src/store/slices/memorySettingsSlice'
import {
  selectMemoryEnabled,
  selectMemoryHasLoadedItems,
  selectMemoryHasLoadedMode,
  selectMemoryItems,
  selectMemorySchedule,
  selectMemoryThresholdMax,
  selectMemoryUnprocessedEvents,
} from '../../../../../browser/frontend/src/store/selectors/memorySettings'
import { glyphs } from '../../../theme/theme'
import { useTab, useTabKeys } from '../tabContext'
import { FormView, useForm, type FormRow } from '../coreForm'
import { useFlash, useInbound } from '../coreHooks'
import { ASCII_METER, UNICODE_METER, localClock, meter, parseClock, runsToday } from '../coreLogic'

const DEFAULT_SCHEDULE: MemorySchedule = { time: '03:00', threshold: 25 }

export function MemoryTab() {
  const { t, i18n } = useTranslation('settingsCore')
  const { active, width, height } = useTab()
  const form = useForm()
  const [flash, say] = useFlash()
  const g = glyphs()

  useResource(RESOURCES.memoryMode)
  useResource(RESOURCES.memorySchedule)
  useResource(RESOURCES.memoryItems)
  const connected = useAppSelector(s => s.connection.connected)
  const enabled = useAppSelector(selectMemoryEnabled)
  const loadedMode = useAppSelector(selectMemoryHasLoadedMode)
  const savedSchedule = useAppSelector(selectMemorySchedule)
  const thresholdMax = useAppSelector(selectMemoryThresholdMax)
  const unprocessed = useAppSelector(selectMemoryUnprocessedEvents)
  const items = useAppSelector(selectMemoryItems)
  const loadedItems = useAppSelector(selectMemoryHasLoadedItems)

  const schedule = useServerDraft(savedSchedule ?? DEFAULT_SCHEDULE)
  const { time, threshold } = schedule.value
  const [processing, setProcessing] = useState(false)
  const [resetting, setResetting] = useState(false)
  // The schedule this tab sent, until its reply; the draft settles only if
  // it still holds that value.
  const sentSchedule = useRef<MemorySchedule | null>(null)
  const valueRef = useRef(schedule.value)
  valueRef.current = schedule.value

  useInbound('memory_mode_set', data => {
    const d = data as { success: boolean; enabled: boolean; error?: string }
    if (d.success) say(d.enabled ? t('memory.enabledToast') : t('memory.disabledToast'), 'success')
    else say(d.error || t('memory.modeFailed'), 'error')
  })
  useInbound('memory_process_trigger', data => {
    const d = data as { success: boolean; message?: string; error?: string }
    setProcessing(false)
    if (d.success) say(d.message || t('memory.processStarted'), 'success')
    else say(d.error || t('memory.processFailed'), 'error')
  })
  useInbound('memory_reset', data => {
    const d = data as { success: boolean; error?: string }
    setResetting(false)
    if (d.success) say(t('memory.resetDone'), 'success')
    else say(d.error || t('memory.resetFailed'), 'error')
  })
  useInbound('memory_schedule_set', data => {
    const sent = sentSchedule.current
    if (!sent) return
    sentSchedule.current = null
    const d = data as { success: boolean; error?: string }
    if (!d.success) {
      say(d.error || t('memory.scheduleFailed'), 'error')
      return
    }
    const now = valueRef.current
    if (now.time === sent.time && now.threshold === sent.threshold) schedule.reset()
    say(t('memory.scheduleSaved'), 'success', 2500)
  })

  // Save the schedule shortly after it is edited; a clean draft is the saved
  // value, so loads and changes made elsewhere are not echoed back.
  useEffect(() => {
    if (!schedule.isDirty) return
    const timer = setTimeout(() => {
      const [h, m] = time.split(':').map(n => parseInt(n, 10) || 0)
      sentSchedule.current = { time, threshold }
      send('memory_schedule_set', { hour: h, minute: m, threshold })
    }, 500)
    return () => clearTimeout(timer)
  }, [time, threshold, schedule.isDirty])

  // The waiting-event count grows as the agent works and nothing announces
  // it, so it is polled while the tab is open (as the browser does).
  useEffect(() => {
    if (!connected) return
    const timer = setInterval(() => send('memory_schedule_get'), 4000)
    return () => clearInterval(timer)
  }, [connected])

  const setThreshold = (value: number) => schedule.set(s => ({ ...s, threshold: Math.max(0, Math.min(thresholdMax, value)) }))

  const ready = threshold === 0 ? unprocessed > 0 : unprocessed >= threshold
  const clock = localClock(time, i18n.language)
  const when = runsToday(time, new Date()) ? t('memory.today', { time: clock }) : t('memory.tomorrow', { time: clock })
  const meterGlyphs = g.vbar === '|' ? ASCII_METER : UNICODE_METER
  const barWidth = Math.max(10, Math.min(40, width - 26))

  const rows: FormRow[] = [
    {
      kind: 'toggle',
      id: 'enabled',
      label: t('memory.enable'),
      value: enabled,
      disabled: !loadedMode,
      detail: t('memory.enableDetail'),
      onChange: on => send('memory_mode_set', { enabled: on }),
    },
    { kind: 'info', label: t('memory.items'), value: loadedItems ? t('memory.itemCount', { count: items.filter(i => !i.superseded).length }) : t('memory.loading') },

    { kind: 'heading', text: t('memory.processing') },
    ...(savedSchedule === null
      ? [{ kind: 'note', text: t('memory.loadingSchedule') } as FormRow]
      : ([
          {
            kind: 'text',
            id: 'time',
            label: t('memory.dailyTime'),
            value: time,
            disabled: !enabled,
            placeholder: '03:00',
            detail: schedule.remoteChanged ? t('changedElsewhere') : t('memory.nextRun', { when }),
            detailTone: schedule.remoteChanged ? 'warn' : 'muted',
            onSubmit: v => {
              const next = parseClock(v)
              if (next) schedule.set(s => ({ ...s, time: next }))
              else say(t('memory.badTime'), 'warn')
            },
            onKey: input => {
              if (input !== 'L' || !schedule.remoteChanged) return false
              schedule.acceptRemote()
              return true
            },
            hints: schedule.remoteChanged ? [{ keys: 'L', label: t('hint.loadLatest') }] : [],
          },
          {
            kind: 'text',
            id: 'threshold',
            label: t('memory.minEvents'),
            value: String(threshold),
            disabled: !enabled,
            detail: threshold === 0 ? t('memory.noMinimum') : undefined,
            onSubmit: v => {
              const n = Number(v.trim())
              if (Number.isInteger(n) && n >= 0) setThreshold(n)
              else say(t('memory.badNumber', { max: thresholdMax }), 'warn')
            },
            onKey: (input, key) => {
              if (key.leftArrow || input === '-') setThreshold(threshold - (key.shift ? 10 : 1))
              else if (key.rightArrow || input === '+' || input === '=') setThreshold(threshold + (key.shift ? 10 : 1))
              else return false
              return true
            },
            hints: [{ keys: '←→', label: t('hint.adjust') }],
          },
          {
            kind: 'info',
            label: t('memory.waiting'),
            value: t('memory.events', { count: unprocessed }),
            detail: threshold === 0 ? t('memory.noMinimum') : t('memory.ofMinimum', { threshold }),
          },
          {
            kind: 'note',
            text: `${meter(unprocessed / Math.max(1, thresholdMax), barWidth, threshold / Math.max(1, thresholdMax), meterGlyphs)}  ${t('memory.legend')}`,
            tone: ready ? 'success' : 'muted',
            maxLines: 1,
          },
          {
            kind: 'info',
            label: t('memory.status'),
            value: ready ? `${g.done} ${t('memory.ready', { when })}` : threshold === 0 ? t('memory.noEvents') : t('memory.needed', { count: threshold - unprocessed }),
            tone: ready ? 'success' : 'muted',
          },
          {
            kind: 'action',
            id: 'process',
            label: processing ? t('memory.processingNow') : t('memory.processNow'),
            disabled: processing || !enabled,
            detail: t('memory.processHint'),
            onRun: () =>
              form.confirm(t('memory.processConfirm'), () => {
                setProcessing(true)
                send('memory_process_trigger')
              }),
          },
        ] as FormRow[])),

    { kind: 'heading', text: t('memory.resetTitle') },
    { kind: 'note', text: t('memory.resetDesc') },
    {
      kind: 'action',
      id: 'reset',
      label: resetting ? t('memory.resetting') : t('memory.reset'),
      tone: 'error',
      disabled: resetting,
      onRun: () =>
        form.confirm(t('memory.resetConfirm'), () => {
          setResetting(true)
          send('memory_reset')
        }),
    },
  ]

  useTabKeys((input, key) => form.handleKey(rows, input, key))

  return <FormView form={form} rows={rows} width={width} height={height} active={active} flash={flash} />
}
