import { forwardRef, useCallback, useEffect, useId, useImperativeHandle, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Bot, Hand, Keyboard, Loader2, Plus, RotateCw } from 'lucide-react'
import { Button } from '../../../components/ui'
import { useToast } from '../../../contexts/ToastContext'
import type { MiniBrowserTab } from '../../../types'
import { useLatest } from '../useLatest'
import { useAgentCursor } from './useAgentCursor'
import { useFramePainter } from './useFramePainter'
import { useKeyboardSink } from './useKeyboardSink'
import { useLiveInput } from './useLiveInput'
import { usePointerInput } from './usePointerInput'
import styles from './LiveView.module.css'

export interface LiveViewHandle {
  /** Give the page the keyboard. */
  focus(): void
}

interface LiveViewProps {
  /** The browser is ready and the page is on screen. While false (starting,
   *  stopped, error…) the view stays mounted, so frames that arrive early are
   *  kept, but it takes no input. */
  active: boolean
  /** The tab on screen (null: none open). */
  tab: MiniBrowserTab | null
  /** Ids of every open tab, joined; frames of closed tabs are dropped. */
  tabIdsKey: string
  connected: boolean
  showCursor: boolean
  /** Who owns `tab`, for the "… is browsing" pill. */
  ownerName: string
  onFocusAddress(): void
  onHistory(action: 'back' | 'forward' | 'reload'): void
  onControl(take: boolean): void
  onNewTab(): void
  /** The user just interacted with the page (throttled). */
  onUserInput(): void
}

/**
 * The live page: paints the screencast and forwards the user's mouse, wheel,
 * touch and keyboard (including IME and paste) to the viewed tab, with the
 * agent's cursor and the take-over controls on top.
 *
 * Frames and the agent's pointer never go through React state: neither this
 * component nor the chat beside it re-renders per frame.
 */
export const LiveView = forwardRef<LiveViewHandle, LiveViewProps>(function LiveView(props, ref) {
  const { active, tab, tabIdsKey, connected, showCursor, ownerName, onControl, onHistory, onNewTab } = props
  const { t } = useTranslation(['minibrowser', 'common'])
  const { showToast } = useToast()
  const hintId = useId()

  const stageRef = useRef<HTMLDivElement>(null)
  const imgRef = useRef<HTMLImageElement>(null)
  const sinkRef = useRef<HTMLTextAreaElement>(null)
  const cursorRef = useRef<HTMLDivElement>(null)
  const rippleRef = useRef<HTMLSpanElement>(null)
  const [coarsePointer] = useState(
    () => typeof window !== 'undefined' && !!window.matchMedia?.('(pointer: coarse)').matches,
  )

  // Handlers bound once read the current props from here.
  const latest = useLatest(props)
  const tabId = tab?.id ?? null

  const input = useLiveInput(latest)
  const { hasFrame, shownFrameRef, onFrameLoad } = useFramePainter(imgRef, tabId, tabIdsKey)
  useAgentCursor({ stage: stageRef, img: imgRef, cursor: cursorRef, ripple: rippleRef }, tabId, showCursor, styles.cursorVisible)

  const focusSink = useCallback(() => {
    if (!latest.current.active || !latest.current.tab) return
    sinkRef.current?.focus({ preventScroll: true })
  }, [latest])

  // Focus the sink where the user clicked, so an IME's candidate window
  // opens next to the page's field rather than in a corner.
  const focusAt = useCallback((clientX: number, clientY: number) => {
    const stage = stageRef.current
    const sink = sinkRef.current
    if (stage && sink) {
      const box = stage.getBoundingClientRect()
      sink.style.left = `${Math.round(Math.max(0, Math.min(clientX - box.left, box.width - 24)))}px`
      sink.style.top = `${Math.round(Math.max(0, Math.min(clientY - box.top, box.height - 32)))}px`
    }
    focusSink()
  }, [focusSink])

  useImperativeHandle(ref, () => ({ focus: focusSink }), [focusSink])

  usePointerInput({ stage: stageRef, img: imgRef, input, shownFrame: shownFrameRef, target: latest, focusAt })

  const onPasteTruncated = useCallback((max: number) => {
    showToast('warning', t('minibrowser:live.pasteTruncated', { max: max.toLocaleString() }))
  }, [showToast, t])
  const onCopyFailed = useCallback(() => {
    showToast('error', t('minibrowser:live.copyFailed'))
  }, [showToast, t])
  const keyboard = useKeyboardSink({
    sink: sinkRef,
    input,
    target: latest,
    composingClass: styles.sinkComposing,
    onPasteTruncated,
    onCopyFailed,
  })

  // Keystrokes must never follow the view to another tab, nor vanish while
  // they can't be delivered: switching tabs (e.g. following an agent),
  // disconnecting, or leaving the ready state releases the keyboard.
  useEffect(() => {
    const sink = sinkRef.current
    if (sink && document.activeElement === sink) sink.blur()
  }, [tabId, connected, active])

  const agentWorking = !!tab && tab.busy && tab.ownerKind !== 'user' && !tab.userControl
  const inControl = !!tab && tab.userControl
  const stageClass = [
    styles.stage,
    hasFrame ? styles.stageLive : '',
    agentWorking ? styles.stageAgent : '',
    inControl ? styles.stageControl : '',
  ].filter(Boolean).join(' ')

  return (
    <div className={styles.root}>
      <div
        ref={stageRef}
        className={stageClass}
        role="application"
        aria-label={t('minibrowser:live.label')}
        aria-describedby={hintId}
        aria-busy={tab?.loading || undefined}
      >
        <img
          ref={imgRef}
          className={`${styles.frame} ${hasFrame ? styles.frameVisible : ''}`}
          alt=""
          draggable={false}
          onLoad={onFrameLoad}
        />
        <textarea
          ref={sinkRef}
          className={styles.sink}
          tabIndex={active && tab ? 0 : -1}
          aria-label={t('minibrowser:live.label')}
          aria-describedby={hintId}
          autoCapitalize="off"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          data-gramm="false"
          data-1p-ignore=""
          data-lpignore="true"
          rows={1}
          {...keyboard}
        />
        <span id={hintId} className="sr-only">{t('minibrowser:live.keyboardHint')}</span>
        <div ref={cursorRef} className={styles.cursor} aria-hidden="true">
          <svg viewBox="0 0 24 24" width="22" height="22" focusable="false">
            <path d="M4 2.5 19.5 13l-6.6 1.3 3.9 7.2-2.7 1.4-3.9-7.2L5.6 20z" />
          </svg>
        </div>
        <span ref={rippleRef} className={styles.ripple} aria-hidden="true" />
      </div>

      {/* Overlays sit above the stage but outside it, so clicks on their
          controls never reach the page. */}
      {active && (
        <div className={styles.overlays}>
          {!tab && (
            <div className={styles.placeholder}>
              <p>{t('minibrowser:live.noTab')}</p>
              <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={onNewTab}>
                {t('minibrowser:tabs.newTab')}
              </Button>
            </div>
          )}
          {tab?.crashed && (
            <div className={styles.placeholder} role="alert">
              <AlertTriangle size={28} className={styles.crashIcon} />
              <p className={styles.placeholderTitle}>{t('minibrowser:live.crashedTitle')}</p>
              <p>{t('minibrowser:live.crashedBody')}</p>
              <Button variant="secondary" size="sm" icon={<RotateCw size={14} />} onClick={() => onHistory('reload')}>
                {t('minibrowser:live.reloadTab')}
              </Button>
            </div>
          )}
          {tab && !tab.crashed && !hasFrame && (
            <div className={styles.placeholder} role="status">
              <Loader2 size={22} className={styles.spin} />
              <p>{t('minibrowser:live.loading')}</p>
            </div>
          )}

          {agentWorking && (
            <div className={styles.pill} role="status">
              <Bot size={14} className={styles.pillIcon} />
              <span className={styles.pillText}>{t('minibrowser:live.agentBrowsing', { owner: ownerName })}</span>
              <button
                type="button"
                className={styles.pillButton}
                onClick={() => {
                  onControl(true)
                  // Ready to type right away (the pill itself goes away).
                  focusSink()
                }}
                title={t('minibrowser:live.takeControlHint')}
              >
                <Hand size={13} /> {t('minibrowser:live.takeControl')}
              </button>
            </div>
          )}
          {inControl && (
            <div className={`${styles.pill} ${styles.pillControl}`} role="status">
              <Hand size={14} className={styles.pillIcon} />
              <span className={styles.pillText}>{t('minibrowser:live.inControl')}</span>
              <button
                type="button"
                className={styles.pillButton}
                onClick={() => onControl(false)}
                title={t('minibrowser:live.handBackHint')}
              >
                {t('minibrowser:live.handBack')}
              </button>
            </div>
          )}

          {coarsePointer && tab && !tab.crashed && (
            <button
              type="button"
              className={styles.keyboardButton}
              onClick={focusSink}
              aria-label={t('minibrowser:live.showKeyboard')}
              title={t('minibrowser:live.showKeyboard')}
            >
              <Keyboard size={18} />
            </button>
          )}
        </div>
      )}
    </div>
  )
})
