import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Brain, Check, ChevronDown, DatabaseZap, Gauge, Timer } from 'lucide-react'
import type { LastRequest, ReasoningChoice } from '../../types'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { usePersistedState } from '../../hooks'
import { formatNumber } from '../../i18n/format'
import { useAppSelector } from '../../store/hooks'
import { RESOURCES, useResource } from '../../store/resources'
import { selectReasoningOptions } from '../../store/selectors/reasoning'
import { selectSessionById } from '../../store/selectors/sessions'
import type { ReasoningOptions } from '../../store/slices/reasoningSlice'
import { UI_STATE } from '../../store/uiState'
import styles from './ReasoningPicker.module.css'

const CHOICE_LABEL_KEYS = {
  provider_default: 'chat:reasoning.choice.provider_default',
  off: 'chat:reasoning.choice.off',
  minimal: 'chat:reasoning.choice.minimal',
  low: 'chat:reasoning.choice.low',
  medium: 'chat:reasoning.choice.medium',
  high: 'chat:reasoning.choice.high',
  xhigh: 'chat:reasoning.choice.xhigh',
  max: 'chat:reasoning.choice.max',
} as const satisfies Record<ReasoningChoice, string>

const isReasoningChoice = (value: string): value is ReasoningChoice =>
  Object.prototype.hasOwnProperty.call(CHOICE_LABEL_KEYS, value)

/** Context fill (of the summary point) where the bar turns amber, then red. */
const CONTEXT_WARN = 0.7
const CONTEXT_HIGH = 0.9

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

interface ContextReadoutProps {
  options: ReasoningOptions
  /** The choice the next request runs at (its budget applies). */
  choice: ReasoningChoice
  lastRequest: LastRequest | null
  /** The menu is open: tick the countdown. */
  live: boolean
}

/**
 * How full the session's context is and how its prompt cache stands, as of
 * its last request. "Context" is that request's input against the budget at
 * the current choice: the event stream is summarized when the next request
 * would not fit. The cache belongs to the model that served the request, so
 * after a model switch it reads as not cached yet. The countdown runs from
 * the request's start over the provider's documented lifetime ("~" where the
 * provider only gives a typical figure); providers that document none, or
 * report no cached count, say so instead of showing a made-up number.
 */
function ContextReadout({ options, choice, lastRequest, live }: ContextReadoutProps) {
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

  const budget = options.inputBudgets[choice]
  const used = lastRequest?.inputTokens ?? null
  const fill = used === null ? 0 : used / budget
  const fillClass =
    fill >= CONTEXT_HIGH ? styles.barHigh : fill >= CONTEXT_WARN ? styles.barWarn : ''

  let cacheValue: string
  if (!cached) cacheValue = t('chat:reasoning.cache.notYet')
  else if (!options.reportsCachedTokens) cacheValue = t('chat:reasoning.cache.notReported')
  else
    cacheValue = t('chat:reasoning.cache.hit', {
      percent: percent(lastRequest.inputTokens > 0 ? lastRequest.cachedTokens / lastRequest.inputTokens : 0),
    })

  let expiryValue: string | null = null
  if (cached) {
    if (lifetime === null) expiryValue = t('chat:reasoning.cache.noExpiry')
    else {
      const remaining = lastRequest.startedAt + lifetime.seconds * 1000 - now
      if (remaining <= 0) expiryValue = t('chat:reasoning.cache.expired')
      else if (lifetime.kind === 'typical')
        expiryValue = t('chat:reasoning.cache.about', { time: formatRemaining(remaining) })
      else expiryValue = formatRemaining(remaining)
    }
  }

  return (
    <div className={styles.readout}>
      <div className={styles.row}>
        <Gauge size={13} className={styles.rowIcon} />
        <span className={styles.rowLabel}>{t('chat:reasoning.context.label')}</span>
        <span className={styles.rowValue}>
          {used === null ? '–' : compactTokens(used)} / {compactTokens(budget)}
        </span>
        {used !== null && <span className={styles.rowDetail}>{percent(fill)}</span>}
      </div>
      <div className={styles.bar}>
        <div
          className={`${styles.barFill} ${fillClass}`}
          style={{ width: `${Math.min(fill, 1) * 100}%` }}
        />
      </div>
      <div className={styles.caption}>
        {t('chat:reasoning.context.summarizesAt', { max: compactTokens(budget) })}
      </div>
      <div className={styles.row}>
        <DatabaseZap size={13} className={styles.rowIcon} />
        <span className={styles.rowLabel}>{t('chat:reasoning.cache.label')}</span>
        <span className={styles.rowValue}>{cacheValue}</span>
      </div>
      {expiryValue !== null && (
        <div className={styles.row}>
          <Timer size={13} className={styles.rowIcon} />
          <span className={styles.rowLabel}>{t('chat:reasoning.cache.timeLeft')}</span>
          <span className={styles.rowValue}>{expiryValue}</span>
        </div>
      )}
    </div>
  )
}

interface ReasoningPickerProps {
  /** The chat this composer belongs to ('new' for the draft view). */
  sessionId: string
}

/**
 * How hard the model reasons for this chat (chat input, beside "+").
 *
 * Follows the pi agent harness: each chat holds a concrete choice, and the
 * menu lists only what the model in use accepts, with the model's default
 * level marked "Default" (where every new chat starts). A real session's
 * choice is saved server-side; the draft view keeps it in UI state until its
 * first message creates the session (untouched: the default level). A stored
 * choice the model lacks shows the level actually used instead (the backend
 * clamps it the way pi does and keeps the stored choice for other models).
 *
 * Below the choices, the chat's context and cache readout (ContextReadout).
 * A model whose reasoning is not adjustable still opens the menu for it.
 */
export function ReasoningPicker({ sessionId }: ReasoningPickerProps) {
  const { t } = useTranslation(['chat', 'common'])
  const { setSessionReasoning } = useWebSocket()
  useResource(RESOURCES.reasoningOptions)
  const options = useAppSelector(selectReasoningOptions)
  const session = useAppSelector(state => selectSessionById(state, sessionId))
  const [draftChoice] = usePersistedState(UI_STATE.chat.draftReasoningEffort)
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  // The chat's own choice; null while it has none yet (an untouched draft,
  // or the main session before the backend has sent it).
  const stored: ReasoningChoice | null =
    sessionId === 'new' ? draftChoice : (session?.reasoningEffort ?? null)
  const lastRequest = session?.lastRequest ?? null

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const choiceLabel = (value: ReasoningChoice): string => t(CHOICE_LABEL_KEYS[value])

  // What a level-like value from the backend reads as: a choice, or the
  // provider deciding the amount itself.
  const levelLabel = (value: string): string =>
    isReasoningChoice(value) ? choiceLabel(value) : t('chat:reasoning.dynamic')

  if (!options) {
    return (
      <div className={styles.wrap}>
        <button type="button" className={styles.button} disabled aria-label={t('chat:reasoning.picker')}>
          <Brain size={14} />
          <span>{t('chat:reasoning.title')}</span>
        </button>
      </div>
    )
  }

  if (!options.configurable) {
    return (
      <div className={styles.wrap} ref={wrapRef}>
        <button
          type="button"
          className={styles.button}
          onClick={() => setOpen(o => !o)}
          title={t('chat:reasoning.notConfigurable', { model: options.model })}
          aria-label={t('chat:reasoning.picker')}
          aria-haspopup="menu"
          aria-expanded={open}
        >
          <Brain size={14} />
          <span>{t('chat:reasoning.title')}</span>
          <ChevronDown size={12} />
        </button>
        {open && (
          <div className={styles.menu} role="menu">
            <div className={styles.header}>{t('chat:reasoning.header', { model: options.model })}</div>
            <div className={styles.notice}>{t('chat:reasoning.notConfigurable', { model: options.model })}</div>
            <ContextReadout
              options={options}
              choice="provider_default"
              lastRequest={lastRequest}
              live={open}
            />
          </div>
        )}
      </div>
    )
  }

  const { defaultLevel, providerDefault } = options
  const requested: ReasoningChoice = stored ?? defaultLevel
  const effective = options.resolution[requested]
  // A choice as it takes effect on this model.
  const summary = (value: ReasoningChoice): string =>
    value === 'provider_default'
      ? t('chat:reasoning.withLevel', {
        choice: choiceLabel('provider_default'),
        level: levelLabel(providerDefault),
      })
      : choiceLabel(value)
  // The row marked as current: the requested choice, or what it resolves to
  // when the model does not offer it.
  const marked = options.choices.includes(requested) ? requested : effective
  // Only a level the model lacks is clamped; provider_default on a model
  // whose default is no reasoning simply IS off.
  const clamped = !options.choices.includes(requested) && requested !== 'provider_default'

  return (
    <div className={styles.wrap} ref={wrapRef}>
      <button
        type="button"
        className={styles.button}
        onClick={() => setOpen(o => !o)}
        title={t('chat:reasoning.picker')}
        aria-label={t('chat:reasoning.picker')}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <Brain size={14} />
        <span>{summary(effective)}</span>
        <ChevronDown size={12} />
      </button>
      {open && (
        <div className={styles.menu} role="menu">
          <div className={styles.header}>{t('chat:reasoning.header', { model: options.model })}</div>
          {options.choices.map(value => (
            <button
              key={value}
              type="button"
              role="menuitemradio"
              aria-checked={value === marked}
              className={`${styles.item}${value === marked ? ` ${styles.itemActive}` : ''}`}
              onClick={() => {
                setSessionReasoning(sessionId, value)
                setOpen(false)
              }}
            >
              <span className={styles.check}>{value === marked && <Check size={13} />}</span>
              <span className={styles.itemLabel}>{choiceLabel(value)}</span>
              {value === defaultLevel && (
                <span className={styles.itemDetail}>{t('chat:reasoning.defaultTag')}</span>
              )}
              {value === 'provider_default' && (
                <span className={styles.itemDetail}>{levelLabel(providerDefault)}</span>
              )}
            </button>
          ))}
          {clamped && (
            <div className={styles.note}>
              {t('chat:reasoning.clamped', { requested: choiceLabel(requested), effective: summary(effective) })}
            </div>
          )}
          <ContextReadout options={options} choice={requested} lastRequest={lastRequest} live={open} />
        </div>
      )}
    </div>
  )
}
