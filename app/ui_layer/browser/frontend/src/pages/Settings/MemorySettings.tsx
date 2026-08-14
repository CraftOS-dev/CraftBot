import { useState, useEffect, useRef } from 'react'
import type { PointerEvent as RPointerEvent, KeyboardEvent as RKeyboardEvent } from 'react'
import {
  Brain,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  RotateCcw,
} from 'lucide-react'
import { Button, ConfirmModal } from '../../components/ui'
import { useToast } from '../../contexts/ToastContext'
import { useConfirmModal } from '../../hooks'
import styles from './SettingsPage.module.css'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import { useAppSelector } from '../../store/hooks'
import {
  selectMemoryEnabled,
  selectMemoryHasLoadedMode,
} from '../../store/selectors/memorySettings'

export function MemorySettings() {
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const { showToast } = useToast()

  // Slice-backed: cached across remounts.
  const memoryEnabled = useAppSelector(selectMemoryEnabled)
  const hasLoadedMode = useAppSelector(selectMemoryHasLoadedMode)
  const isLoadingMode = !hasLoadedMode

  // UI state (transient)
  const [isResetting, setIsResetting] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)

  // Daily auto-processing time + threshold (loaded from the scheduler).
  const [autoTime, setAutoTime] = useState('03:00')
  const [threshold, setThreshold] = useState(25)
  const [thresholdMax, setThresholdMax] = useState(100)
  const [unprocessed, setUnprocessed] = useState(0)
  const [hasLoadedSchedule, setHasLoadedSchedule] = useState(false)
  // Auto-save: remember the last-applied values so the initial load isn't
  // echoed straight back, and debounce rapid edits.
  const lastSavedRef = useRef<{ time: string; threshold: number } | null>(null)
  const saveTimerRef = useRef<number | undefined>(undefined)
  // Custom threshold slider (drag the picker along the track).
  const gateBarRef = useRef<HTMLDivElement>(null)
  const gateDraggingRef = useRef(false)

  // Confirm modal
  const { modalProps: confirmModalProps, confirm } = useConfirmModal()

  // Side-effect handlers (toasts). Enabled state itself is owned by
  // memorySettingsSlice via the registry. Memory items are managed in the
  // dedicated Memory panel, not here.
  useEffect(() => {
    if (!isConnected) return

    const cleanups = [
      onMessage('memory_mode_set', (data: unknown) => {
        const d = data as { success: boolean; enabled: boolean; error?: string }
        if (d.success) showToast('success', `Memory ${d.enabled ? 'enabled' : 'disabled'}`)
        else showToast('error', d.error || 'Failed to update memory mode')
      }),
      onMessage('memory_reset', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        setIsResetting(false)
        if (d.success) showToast('success', 'Memory reset to default')
        else showToast('error', d.error || 'Failed to reset memory')
      }),
      onMessage('memory_process_trigger', (data: unknown) => {
        const d = data as { success: boolean; message?: string; error?: string }
        setIsProcessing(false)
        if (d.success) showToast('success', d.message || 'Memory processing started')
        else showToast('error', d.error || 'Failed to start memory processing')
      }),
      onMessage('memory_schedule_get', (data: unknown) => {
        const d = data as {
          success: boolean
          schedule?: { hour: number; minute: number }
          threshold?: number
          threshold_max?: number
          unprocessed?: number
        }
        if (!d.success || !d.schedule) return
        if (typeof d.threshold_max === 'number') setThresholdMax(d.threshold_max)
        if (typeof d.unprocessed === 'number') setUnprocessed(d.unprocessed)
        // Adopt the saved time/threshold only on the FIRST load; later polls
        // (for the live event count) must not clobber an in-progress edit.
        if (!hasLoadedSchedule) {
          const time = `${String(d.schedule.hour).padStart(2, '0')}:${String(d.schedule.minute).padStart(2, '0')}`
          const thr = d.threshold ?? 25
          setAutoTime(time)
          setThreshold(thr)
          lastSavedRef.current = { time, threshold: thr }
          setHasLoadedSchedule(true)
        }
      }),
      onMessage('memory_schedule_set', (data: unknown) => {
        const d = data as { success: boolean; error?: string }
        if (!d.success) showToast('error', d.error || 'Failed to update schedule')
      }),
    ]

    if (!hasLoadedMode) send('memory_mode_get')
    if (!hasLoadedSchedule) send('memory_schedule_get')

    return () => cleanups.forEach(c => c())
  }, [isConnected, send, onMessage, hasLoadedMode, hasLoadedSchedule, showToast])

  const handleToggleMemory = (enabled: boolean) => {
    send('memory_mode_set', { enabled })
  }

  const handleProcessMemory = () => {
    confirm({
      title: 'Process Memory',
      message: 'This will process all unprocessed events into long-term memory. Continue?',
      confirmText: 'Process',
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

  // Auto-save the daily time / threshold whenever they change (debounced),
  // skipping the values just loaded from the scheduler.
  useEffect(() => {
    if (!hasLoadedSchedule) return
    const last = lastSavedRef.current
    if (last && last.time === autoTime && last.threshold === threshold) return
    window.clearTimeout(saveTimerRef.current)
    saveTimerRef.current = window.setTimeout(() => {
      const [h, m] = autoTime.split(':').map(n => parseInt(n, 10) || 0)
      send('memory_schedule_set', { hour: h, minute: m, threshold })
      lastSavedRef.current = { time: autoTime, threshold }
    }, 500)
    return () => window.clearTimeout(saveTimerRef.current)
  }, [autoTime, threshold, hasLoadedSchedule, send])

  // Keep the live "events waiting" count current while the panel is open,
  // without needing a manual refresh.
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
    const suffix = h < 12 ? 'AM' : 'PM'
    const clock = `${h % 12 || 12}:${String(m).padStart(2, '0')} ${suffix}`
    const now = new Date()
    const beforeToday = now.getHours() < h || (now.getHours() === h && now.getMinutes() < m)
    return `${beforeToday ? 'today' : 'tomorrow'} at ${clock}`
  })()

  const handleResetMemory = () => {
    confirm({
      title: 'Reset Memory',
      message: 'Are you sure you want to reset all memory? This will clear all memory items and unprocessed events. This action cannot be undone.',
      confirmText: 'Reset',
      variant: 'danger',
    }, () => {
      setIsResetting(true)
      send('memory_reset')
    })
  }

  return (
    <div className={styles.settingsSection}>
      <div className={styles.sectionHeader}>
        <h3>Memory Settings</h3>
        <p>Manage agent memory and event processing</p>
      </div>

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

      {/* Toggleable Content */}
      <div className={`${styles.toggleableContent} ${!memoryEnabled ? styles.disabledContent : ''}`}>
        {/* Memory Processing: daily schedule, run condition, manual trigger */}
        <div className={styles.subsection}>
          <h4 className={styles.subsectionTitle}>Memory Processing</h4>
          <p className={styles.subsectionDesc}>
            Once a day, CraftBot distills recent events into long-term memory.
            Choose when it runs and how many new events must be waiting; if
            fewer have accumulated by then, the run is skipped, so quiet days
            do nothing. You can also process everything waiting right now.
          </p>

          {!hasLoadedSchedule ? (
            <div className={styles.loadingState}>
              <Loader2 size={18} className={styles.spinning} />
              <span>Loading schedule…</span>
            </div>
          ) : (
            <>
              <div className={`${styles.formGroup} ${styles.inlineRow}`}>
                <label>Daily time</label>
                <input
                  type="time"
                  value={autoTime}
                  onChange={e => setAutoTime(e.target.value)}
                  disabled={!memoryEnabled}
                />
              </div>

              <div className={styles.formGroup}>
                <div className={styles.gateHeader}>
                  <label>Minimum events to run</label>
                  <span className={styles.gateReadout}>
                    {threshold === 0
                      ? `${unprocessed} unprocessed ${unprocessed === 1 ? 'event' : 'events'} / no minimum`
                      : `${unprocessed} unprocessed ${unprocessed === 1 ? 'event' : 'events'} / ${threshold} minimum to run`}
                  </span>
                </div>
                <div
                  ref={gateBarRef}
                  className={`${styles.gateTrack} ${!memoryEnabled ? styles.gateDisabled : ''}`}
                  role="slider"
                  aria-label="Minimum events to run"
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
                    unprocessed events
                  </span>
                  <span className={styles.gateLegendItem}>
                    <span className={styles.gateSwatchThumb} />
                    minimum to run
                  </span>
                </div>
              </div>

              <div className={`${styles.gateStatus} ${gateReached ? styles.gateStatusReady : ''}`}>
                {gateReached ? (
                  <>
                    <CheckCircle2 size={15} />
                    <span>
                      Enough events have accumulated: memory will be processed{' '}
                      {nextRunPhrase}.
                    </span>
                  </>
                ) : (
                  <span>
                    {threshold === 0
                      ? 'No events waiting. The next scheduled run will be skipped.'
                      : `${threshold - unprocessed} more ${threshold - unprocessed === 1 ? 'event' : 'events'} needed. Scheduled runs are skipped until then.`}
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
                  {isProcessing ? 'Processing...' : 'Process Memory Now'}
                </Button>
                <span className={styles.hint}>
                  Processes all waiting events immediately, ignoring the
                  schedule and minimum.
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

      {/* Confirm Modal */}
      <ConfirmModal {...confirmModalProps} />
    </div>
  )
}
