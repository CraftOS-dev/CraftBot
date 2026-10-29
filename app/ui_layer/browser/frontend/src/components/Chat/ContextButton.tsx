import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { DatabaseZap, FoldVertical, Gauge, Loader2, Timer } from 'lucide-react'
import type { LastFold, LastRequest, ReasoningChoice } from '../../types'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { usePersistedState } from '../../hooks'
import { formatNumber } from '../../i18n/format'
import { useAppSelector } from '../../store/hooks'
import { RESOURCES, useResource } from '../../store/resources'
import { selectReasoningOptions } from '../../store/selectors/reasoning'
import { selectSessionById } from '../../store/selectors/sessions'
import type { ReasoningOptions } from '../../store/slices/reasoningSlice'
import { UI_STATE } from '../../store/uiState'
import styles from './ContextButton.module.css'

/** Context fill (of the summary point) where the ring and bar turn amber, then red. */
const CONTEXT_WARN = 0.7
const CONTEXT_HIGH = 0.9

/** The ring's radius in its 18px box. */
const RING_RADIUS = 7
const RING_LENGTH = 2 * Math.PI * RING_RADIUS
/** The arc that spins while a fold runs. */
const FOLDING_ARC = 0.25

const compactTokens = (n: number): string =>
  formatNumber(n, { notation: 'compact', maximumFractionDigits: 1 })

const percent = (ratio: number): string =>
  formatNumber(ratio, { style: 'percent', maximumFractionDigits: 0 })

/** Remaining time as m:ss, or h:mm:ss from an hour up. */
function formatRemaining(ms: number): string {
  const total = Math.ceil(ms / 1000)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = String(total % 60).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

interface ContextUse {
  tokens: number
  /** A fold since the last request: its size less what the fold freed,
   *  until the next request reports the real one. */
  estimated: boolean
}

function contextUse(lastRequest: LastRequest | null, lastFold: LastFold | null): ContextUse | null {
  if (lastRequest === null) return null
  if (lastFold !== null && lastFold.at > lastRequest.startedAt)
    return { tokens: Math.max(lastRequest.inputTokens - lastFold.freedTokens, 0), estimated: true }
  return { tokens: lastRequest.inputTokens, estimated: false }
}

const fillClassFor = (fill: number): string =>
  fill >= CONTEXT_HIGH ? styles.high : fill >= CONTEXT_WARN ? styles.warn : ''

interface ContextReadoutProps {
  options: ReasoningOptions
  budget: number
  used: ContextUse | null
  lastRequest: LastRequest | null
  /** The menu is open: tick the countdown. */
  live: boolean
}

/**
 * How full the session's context is and how its prompt cache stands, as of
 * its last request. "Context" is that request's input against the budget at
 * the session's reasoning choice: the event stream is summarized when the
 * next request would not fit. The cache belongs to the model that served the
 * request, so after a model switch it reads as not cached yet. The countdown
 * runs from the request's start over the provider's documented lifetime ("~"
 * where the provider only gives a typical figure); providers that document
 * none, or report no cached count, say so instead of showing a made-up number.
 */
function ContextReadout({ options, budget, used, lastRequest, live }: ContextReadoutProps) {
  const { t } = useTranslation(['chat', 'common'])
  const [now, setNow] = useState(() => Date.now())
  const lifetime = options.cacheLifetime
  const cached =
    lastRequest !== null &&
    lastRequest.surface === options.surface &&
    lastRequest.model === options.model

  useEffect(() => {
    if (!live || !cached || lifetime === null) return
    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [live, cached, lifetime])

  const fill = used === null ? 0 : used.tokens / budget

  let usedValue = '–'
  if (used !== null)
    usedValue = used.estimated
      ? t('chat:contextWindow.context.estimate', { value: compactTokens(used.tokens) })
      : compactTokens(used.tokens)

  let cacheValue: string
  if (!cached) cacheValue = t('chat:contextWindow.cache.notYet')
  else if (!options.reportsCachedTokens) cacheValue = t('chat:contextWindow.cache.notReported')
  else
    cacheValue = t('chat:contextWindow.cache.hit', {
      percent: percent(lastRequest.inputTokens > 0 ? lastRequest.cachedTokens / lastRequest.inputTokens : 0),
    })

  let expiryValue: string | null = null
  if (cached) {
    if (lifetime === null) expiryValue = t('chat:contextWindow.cache.noExpiry')
    else {
      const remaining = lastRequest.startedAt + lifetime.seconds * 1000 - now
      if (remaining <= 0) expiryValue = t('chat:contextWindow.cache.expired')
      else if (lifetime.kind === 'typical')
        expiryValue = t('chat:contextWindow.cache.about', { time: formatRemaining(remaining) })
      else expiryValue = formatRemaining(remaining)
    }
  }

  return (
    <div className={styles.readout}>
      <div className={styles.row}>
        <Gauge size={13} className={styles.rowIcon} />
        <span className={styles.rowLabel}>{t('chat:contextWindow.context.label')}</span>
        <span className={styles.rowValue}>
          {usedValue} / {compactTokens(budget)}
        </span>
        {used !== null && <span className={styles.rowDetail}>{percent(fill)}</span>}
      </div>
      <div className={styles.bar}>
        <div
          className={`${styles.barFill} ${fillClassFor(fill)}`}
          style={{ width: `${Math.min(fill, 1) * 100}%` }}
        />
      </div>
      <div className={styles.caption}>
        {t('chat:contextWindow.context.summarizesAt', { max: compactTokens(budget) })}
      </div>
      <div className={styles.row}>
        <DatabaseZap size={13} className={styles.rowIcon} />
        <span className={styles.rowLabel}>{t('chat:contextWindow.cache.label')}</span>
        <span className={styles.rowValue}>{cacheValue}</span>
      </div>
      {expiryValue !== null && (
        <div className={styles.row}>
          <Timer size={13} className={styles.rowIcon} />
          <span className={styles.rowLabel}>{t('chat:contextWindow.cache.timeLeft')}</span>
          <span className={styles.rowValue}>{expiryValue}</span>
        </div>
      )}
    </div>
  )
}

/** The button's ring: how full the context is, or a spinning arc while a fold runs. */
function ContextRing({ fill, folding }: { fill: number; folding: boolean }) {
  const shown = folding ? FOLDING_ARC : Math.min(fill, 1)
  return (
    <svg
      className={`${styles.ring}${folding ? ` ${styles.ringFolding}` : ''}`}
      width={18}
      height={18}
      viewBox="0 0 18 18"
      aria-hidden="true"
    >
      <circle className={styles.ringTrack} cx={9} cy={9} r={RING_RADIUS} />
      {shown > 0 && (
        <circle
          className={`${styles.ringFill} ${folding ? '' : fillClassFor(fill)}`}
          cx={9}
          cy={9}
          r={RING_RADIUS}
          strokeDasharray={RING_LENGTH}
          strokeDashoffset={RING_LENGTH * (1 - shown)}
          transform="rotate(-90 9 9)"
        />
      )}
    </svg>
  )
}

interface ContextButtonProps {
  /** The chat this composer belongs to ('new' for the draft view). */
  sessionId: string
}

/**
 * The chat's context window (chat input, left of the mic): a ring that fills
 * as the session's context does. Its menu holds the context and cache readout
 * (ContextReadout) and folds the event stream on demand, the same /fold a
 * typed command runs. The budget follows the chat's reasoning choice, as the
 * reasoning picker shows it.
 */
export function ContextButton({ sessionId }: ContextButtonProps) {
  const { t } = useTranslation(['chat', 'common'])
  const { foldSession } = useWebSocket()
  useResource(RESOURCES.reasoningOptions)
  const options = useAppSelector(selectReasoningOptions)
  const session = useAppSelector(state => selectSessionById(state, sessionId))
  const [draftChoice] = usePersistedState(UI_STATE.chat.draftReasoningEffort)
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  if (!options) {
    return (
      <div className={styles.wrap}>
        <button type="button" className={styles.button} disabled aria-label={t('chat:contextWindow.title')}>
          <ContextRing fill={0} folding={false} />
        </button>
      </div>
    )
  }

  const lastRequest = session?.lastRequest ?? null
  const folding = session?.folding ?? false
  const stored: ReasoningChoice | null =
    sessionId === 'new' ? draftChoice : (session?.reasoningEffort ?? null)
  const choice: ReasoningChoice = options.configurable
    ? (stored ?? options.defaultLevel)
    : 'provider_default'
  const budget = options.inputBudgets[choice]
  const used = contextUse(lastRequest, session?.lastFold ?? null)
  const fill = used === null ? 0 : used.tokens / budget

  return (
    <div className={styles.wrap} ref={wrapRef}>
      <button
        type="button"
        className={styles.button}
        onClick={() => setOpen(o => !o)}
        title={
          used === null
            ? t('chat:contextWindow.title')
            : t('chat:contextWindow.tooltip', {
              used: compactTokens(used.tokens),
              max: compactTokens(budget),
              percent: percent(fill),
            })
        }
        aria-label={t('chat:contextWindow.title')}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <ContextRing fill={fill} folding={folding} />
      </button>
      {open && (
        <div className={styles.menu} role="menu">
          <div className={styles.header}>{t('chat:contextWindow.header', { model: options.model })}</div>
          <ContextReadout options={options} budget={budget} used={used} lastRequest={lastRequest} live={open} />
          <div className={styles.actions}>
            <button
              type="button"
              role="menuitem"
              className={`${styles.item}${folding ? ` ${styles.busy}` : ''}`}
              onClick={() => foldSession(sessionId)}
              disabled={folding || sessionId === 'new'}
              title={t('chat:contextWindow.foldHint')}
            >
              {folding
                ? <Loader2 size={14} className={styles.spin} />
                : <FoldVertical size={14} />}
              <span className={styles.itemLabel}>
                {folding ? t('chat:contextWindow.folding') : t('chat:contextWindow.fold')}
              </span>
              <span className={styles.itemDetail}>/fold</span>
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
