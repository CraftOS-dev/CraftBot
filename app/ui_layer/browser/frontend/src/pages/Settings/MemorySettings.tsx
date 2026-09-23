import { useState, useEffect, useRef } from 'react'
import type { PointerEvent as RPointerEvent, KeyboardEvent as RKeyboardEvent } from 'react'
import {
  Brain,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  RotateCcw,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button, ConfirmModal } from '../../components/ui'
import { useToast } from '../../contexts/ToastContext'
import { useConfirmModal, useServerDraft } from '../../hooks'
import { formatNumber, formatTime } from '../../i18n/format'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import { RemoteChangeHint } from './RemoteChangeHint'
import { useAppSelector } from '../../store/hooks'
import {
  selectMemoryEnabled,
  selectMemoryHasLoadedMode,
  selectMemorySchedule,
  selectMemoryThresholdMax,
  selectMemoryUnprocessedEvents,
} from '../../store/selectors/memorySettings'
import type { MemorySchedule } from '../../store/slices/memorySettingsSlice'
import { RESOURCES, useResource } from '../../store/resources'

const DEFAULT_SCHEDULE: MemorySchedule = { time: '03:00', threshold: 25 }

export function MemorySettings() {
  const { t } = useTranslation(['settings', 'common'])
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const { showToast } = useToast()

  // Slice-backed: cached across remounts, refreshed by ResourceSync.
  const memoryEnabled = useAppSelector(selectMemoryEnabled)
  const hasLoadedMode = useAppSelector(selectMemoryHasLoadedMode)
  const isLoadingMode = !hasLoadedMode
  const savedSchedule = useAppSelector(selectMemorySchedule)
  const thresholdMax = useAppSelector(selectMemoryThresholdMax)
  const unprocessed = useAppSelector(selectMemoryUnprocessedEvents)
  const hasLoadedSchedule = savedSchedule !== null
  useResource(RESOURCES.memoryMode)
  useResource(RESOURCES.memorySchedule)

  // UI state (transient)
  const [isResetting, setIsResetting] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)

  // Daily auto-processing time + threshold: a draft over the saved schedule,
  // so a change made elsewhere shows up here unless this form is mid-edit.
  const schedule = useServerDraft(savedSchedule ?? DEFAULT_SCHEDULE)
  const { time: autoTime, threshold } = schedule.value
  const setAutoTime = (time: string) => schedule.set(s => ({ ...s, time }))
  const setThreshold = (value: number) => schedule.set(s => ({ ...s, threshold: value }))
  const resetSchedule = schedule.reset
  // The value this tab's auto-save sent, until its reply arrives. The draft
  // settles only if it still holds that value (the user may have kept editing).
  const savingScheduleRef = useRef<MemorySchedule | null>(null)
  const scheduleValueRef = useRef(schedule.value)
  scheduleValueRef.current = schedule.value
  const saveTimerRef = useRef<number | undefined>(undefined)
  // Custom threshold slider (drag the picker along the track).
  const gateBarRef = useRef<HTMLDivElement>(null)
  const gateDraggingRef = useRef(false)

  // Confirm modal
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  // Side-effect handlers (toasts, this tab's save result). Enabled state and
  // the schedule are owned by memorySettingsSlice via the registry. Memory
  // items are managed in the dedicated Memory panel, not here.
  useEffect(() => {
    const cleanups = [
      onMessage('memory_mode_set', (data: unknown) => {
        const d = data as { success: boolean; enabled: boolean; error?: string }
        if (d.success) showToast('success', d.enabled ? t('settings:memory.toast.enabled') : t('settings:memory.toast.disabled'))
        else showToast('error', d.error || t('settings:memory.toast.modeFailed'))
      }),
      onMessage('memory_reset', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        setIsResetting(false)
        if (d.success) showToast('success', t('settings:memory.toast.resetDone'))
        else showToast('error', d.error || t('settings:memory.toast.resetFailed'))
      }),
      onMessage('memory_process_trigger', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        setIsProcessing(false)
        if (d.success) showToast('success', d.message || t('settings:memory.toast.processStarted'))
        else showToast('error', d.error || t('settings:memory.toast.processFailed'))
      }),
      onMessage('memory_schedule_set', (data: unknown) => {
        const sent = savingScheduleRef.current
        if (!sent) return
        savingScheduleRef.current = null
        const d = data as { success: boolean; error?: string }
        if (!d.success) {
          showToast('error', d.error || t('settings:memory.toast.scheduleFailed'))
          return
        }
        const current = scheduleValueRef.current
        if (current.time === sent.time && current.threshold === sent.threshold) resetSchedule()
      }),
    ]
    return () => cleanups.forEach(c => c())
  }, [onMessage, showToast, resetSchedule])

  const handleToggleMemory = (enabled: boolean) => {
    send('memory_mode_set', { enabled })
  }

  const handleProcessMemory = () => {
    confirm({
      title: t('settings:memory.processConfirmTitle'),
      message: t('settings:memory.processConfirmMessage'),
      confirmText: t('settings:memory.processConfirmButton'),
      variant: 'default',
    }, () => {
      setIsProcessing(true)
      send('memory_process_trigger')
    })
  }

  // ── Threshold slider: drag the picker to set the minimum-events gate ──
  const setThresholdFromPointer = (clientX: number) => {
    const el = gateBarRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const pct = rect.width > 0 ? (clientX - rect.left) / rect.width : 0
    setThreshold(Math.round(Math.min(1, Math.max(0, pct)) * thresholdMax))
  }
  const onGatePointerDown = (e: RPointerEvent<HTMLDivElement>) => {
    if (!memoryEnabled) return
    gateDraggingRef.current = true
    e.currentTarget.setPointerCapture(e.pointerId)
    setThresholdFromPointer(e.clientX)
  }
  const onGatePointerMove = (e: RPointerEvent<HTMLDivElement>) => {
    if (!gateDraggingRef.current) return
    setThresholdFromPointer(e.clientX)
  }
  const onGatePointerUp = (e: RPointerEvent<HTMLDivElement>) => {
    gateDraggingRef.current = false
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId)
    }
  }
  const onGateKeyDown = (e: RKeyboardEvent<HTMLDivElement>) => {
    if (!memoryEnabled) return
    if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
      e.preventDefault()
      setThreshold(Math.max(0, threshold - 1))
    } else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
      e.preventDefault()
      setThreshold(Math.min(thresholdMax, threshold + 1))
    }
  }

  // Auto-save the daily time / threshold while they're edited (debounced).
  // A clean draft is the saved value, so loads and remote changes aren't
  // echoed back.
  useEffect(() => {
    if (!schedule.isDirty) return
    window.clearTimeout(saveTimerRef.current)
    saveTimerRef.current = window.setTimeout(() => {
      const [h, m] = autoTime.split(':').map(n => parseInt(n, 10) || 0)
      savingScheduleRef.current = { time: autoTime, threshold }
      send('memory_schedule_set', { hour: h, minute: m, threshold })
    }, 500)
    return () => window.clearTimeout(saveTimerRef.current)
  }, [autoTime, threshold, schedule.isDirty, send])

  // Keep the live "events waiting" count current while the panel is open.
  // The count grows as the agent works and nothing announces it, so this
  // stays a poll (the schedule itself is refreshed by resource changes).
  useEffect(() => {
    if (!isConnected) return
    const id = window.setInterval(() => send('memory_schedule_get'), 4000)
    return () => window.clearInterval(id)
  }, [isConnected, send])

  // ── Gate status: is the next scheduled run going to fire? ──
  // Threshold 0 means "no minimum": the run fires whenever anything is
  // pending. Otherwise the daily run is skipped until the waiting-event
  // count reaches the threshold.
  const gateReached = threshold === 0 ? unprocessed > 0 : unprocessed >= threshold
  const nextRunPhrase = (() => {
    const [h, m] = autoTime.split(':').map(n => parseInt(n, 10) || 0)
    const clockDate = new Date()
    clockDate.setHours(h, m, 0, 0)
    const clock = formatTime(clockDate)
    const now = new Date()
    const beforeToday = now.getHours() < h || (now.getHours() === h && now.getMinutes() < m)
    return beforeToday
      ? t('settings:memory.nextRunToday', { time: clock })
      : t('settings:memory.nextRunTomorrow', { time: clock })
  })()

  const handleResetMemory = () => {
    confirm({
      title: t('settings:memory.resetConfirmTitle'),
      message: t('settings:memory.resetConfirmMessage'),
      confirmText: t('common:actions.reset'),
      variant: 'danger',
    }, () => {
      setIsResetting(true)
      send('memory_reset')
    })
  }

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>{t('settings:memory.title')}</h3>
        <p>{t('settings:memory.subtitle')}</p>
      </div>

      {/* Master Toggle */}
      <div className={styles.settingsForm}>
        <div className={styles.toggleGroup}>
          <div className={styles.toggleInfo}>
            <span className={styles.toggleLabel}>{t('settings:memory.enableLabel')}</span>
            <span className={styles.toggleDesc}>
              {t('settings:memory.enableDesc')}
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

      {/* Toggleable Content */}
      <div className={`${styles.toggleableContent} ${!memoryEnabled ? styles.disabledContent : ''}`}>
        {/* Memory Processing: daily schedule, run condition, manual trigger */}
        <div className={styles.subsection}>
          <h4 className={styles.subsectionTitle}>{t('settings:memory.processingTitle')}</h4>
          <p className={styles.subsectionDesc}>
            {t('settings:memory.processingDesc')}
          </p>

          {!hasLoadedSchedule ? (
            <div className={styles.loadingState}>
              <Loader2 size={18} className={styles.spinning} />
              <span>{t('settings:memory.loadingSchedule')}</span>
            </div>
          ) : (
            <>
              <div className={`${styles.formGroup} ${styles.inlineRow}`}>
                <label>{t('settings:memory.dailyTime')}</label>
                <input
                  type="time"
                  value={autoTime}
                  onChange={e => setAutoTime(e.target.value)}
                  disabled={!memoryEnabled}
                />
                {schedule.remoteChanged && <RemoteChangeHint onLoadLatest={schedule.acceptRemote} />}
              </div>

              <div className={styles.formGroup}>
                <div className={styles.gateHeader}>
                  <label>{t('settings:memory.minEvents')}</label>
                  <span className={styles.gateReadout}>
                    {threshold === 0
                      ? t('settings:memory.readoutNoMin', { events: t('settings:memory.unprocessedEvents', { count: unprocessed }) })
                      : t('settings:memory.readoutWithMin', { events: t('settings:memory.unprocessedEvents', { count: unprocessed }), threshold: formatNumber(threshold) })}
                  </span>
                </div>
                <div
                  ref={gateBarRef}
                  className={`${styles.gateTrack} ${!memoryEnabled ? styles.gateDisabled : ''}`}
                  role="slider"
                  aria-label={t('settings:memory.minEvents')}
                  aria-valuemin={0}
                  aria-valuemax={thresholdMax}
                  aria-valuenow={threshold}
                  tabIndex={memoryEnabled ? 0 : -1}
                  onPointerDown={onGatePointerDown}
                  onPointerMove={onGatePointerMove}
                  onPointerUp={onGatePointerUp}
                  onKeyDown={onGateKeyDown}
                >
                  <div
                    className={styles.gateEventFill}
                    style={{ width: `${Math.min(100, (unprocessed / thresholdMax) * 100)}%` }}
                  />
                  <div
                    className={styles.gateThumb}
                    style={{ left: `${(threshold / thresholdMax) * 100}%` }}
                  />
                </div>
                <div className={styles.gateLegend}>
                  <span className={styles.gateLegendItem}>
                    <span className={styles.gateSwatchFill} />
                    {t('settings:memory.legendUnprocessed')}
                  </span>
                  <span className={styles.gateLegendItem}>
                    <span className={styles.gateSwatchThumb} />
                    {t('settings:memory.legendMinimum')}
                  </span>
                </div>
              </div>

              <div className={`${styles.gateStatus} ${gateReached ? styles.gateStatusReady : ''}`}>
                {gateReached ? (
                  <>
                    <CheckCircle2 size={15} />
                    <span>
                      {t('settings:memory.gateReady', { when: nextRunPhrase })}
                    </span>
                  </>
                ) : (
                  <span>
                    {threshold === 0
                      ? t('settings:memory.gateNoEvents')
                      : t('settings:memory.eventsNeeded', { count: threshold - unprocessed })}
                  </span>
                )}
              </div>

              <div className={styles.processRow}>
                <Button
                  variant="secondary"
                  onClick={handleProcessMemory}
                  disabled={isProcessing || !memoryEnabled}
                  icon={isProcessing ? <Loader2 size={14} className={styles.spinning} /> : <Brain size={14} />}
                >
                  {isProcessing ? t('common:status.processing') : t('settings:memory.processNow')}
                </Button>
                <span className={styles.hint}>
                  {t('settings:memory.processHint')}
                </span>
              </div>
            </>
          )}
        </div>

      </div>

      {/* Reset Memory */}
      <div className={styles.dangerZone}>
        <div className={styles.dangerHeader}>
          <AlertTriangle size={18} className={styles.dangerIcon} />
          <h4>{t('settings:memory.resetTitle')}</h4>
        </div>
        <p className={styles.dangerDescription}>
          {t('settings:memory.resetDesc')}
        </p>
        <Button
          variant="danger"
          onClick={handleResetMemory}
          disabled={isResetting}
          icon={isResetting ? <Loader2 size={14} className={styles.spinning} /> : <RotateCcw size={14} />}
        >
          {isResetting ? t('settings:memory.resetting') : t('settings:memory.resetButton')}
        </Button>
      </div>

      {/* Confirm Modal */}
      <ConfirmModal {...confirmModalProps} />
    </div>
  )
}
