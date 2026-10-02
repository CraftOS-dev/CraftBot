import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Brain, Check, ChevronDown } from 'lucide-react'
import type { ReasoningChoice } from '../../types'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { usePersistedState } from '../../hooks'
import { useAppSelector } from '../../store/hooks'
import { RESOURCES, useResource } from '../../store/resources'
import { selectReasoningOptions } from '../../store/selectors/reasoning'
import { selectSessionById } from '../../store/selectors/sessions'
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

  if (!options || !options.configurable) {
    return (
      <div className={styles.wrap}>
        <button
          type="button"
          className={styles.button}
          disabled
          title={options ? t('chat:reasoning.notConfigurable', { model: options.model }) : undefined}
          aria-label={t('chat:reasoning.picker')}
        >
          <Brain size={14} />
          <span>{t('chat:reasoning.title')}</span>
        </button>
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
        </div>
      )}
    </div>
  )
}
