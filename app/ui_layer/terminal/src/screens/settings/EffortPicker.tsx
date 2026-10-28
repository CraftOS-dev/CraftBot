/**
 * The open chat's reasoning effort, as the browser's ReasoningPicker: the
 * choices the model in use accepts (its default marked), what a stored
 * choice the model lacks resolves to, and the chat's context and cache
 * readout: context used against the budget at the chat's current choice
 * (amber from 70%, red from 90%), cache hit rate and the cache's time left.
 * Choosing sends session_reasoning_set for the active chat and closes.
 */
import { useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector, send } from '../../state/hooks'
import { closeScreen } from '../../state/tuiSlice'
import { RESOURCES, useResource } from '../../../../browser/frontend/src/store/resources'
import { selectReasoningOptions } from '../../../../browser/frontend/src/store/selectors/reasoning'
import { selectSessionById } from '../../../../browser/frontend/src/store/selectors/sessions'
import { selectUiState } from '../../../../browser/frontend/src/store/selectors/ui'
import { upsertSession } from '../../../../browser/frontend/src/store/slices/sessionsSlice'
import { setUiState } from '../../../../browser/frontend/src/store/slices/uiSlice'
import { UI_STATE } from '../../../../browser/frontend/src/store/uiState'
import type { LastRequest, ReasoningChoice } from '../../../../browser/frontend/src/types'
import type { ReasoningOptions } from '../../../../browser/frontend/src/store/slices/reasoningSlice'
import { Frame } from '../../ui/Frame'
import { useScreen, useScreenKeys } from '../context'
import { useTicker } from '../../ui/useTicker'
import { glyphs, ink } from '../../theme/theme'
import { padEnd, truncate, width as cells } from '../../text/width'
import { ASCII_METER, UNICODE_METER, contextLevel, formatRemaining, meter } from './coreLogic'

const CHOICES: ReasoningChoice[] = ['provider_default', 'off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']
const isChoice = (value: string): value is ReasoningChoice => (CHOICES as string[]).includes(value)

export function EffortPicker() {
  const { t, i18n } = useTranslation('settingsCore')
  const dispatch = useAppDispatch()
  const { columns, rows } = useScreen()
  useResource(RESOURCES.reasoningOptions)
  const options = useAppSelector(selectReasoningOptions)
  const sessionId = useAppSelector(s => s.tui.activeSessionId)
  const session = useAppSelector(s => selectSessionById(s, sessionId))
  const draftChoice = useAppSelector(s => selectUiState(s, UI_STATE.chat.draftReasoningEffort)) as ReasoningChoice | null
  const g = glyphs()

  const stored: ReasoningChoice | null = sessionId === 'new' ? draftChoice : (session?.reasoningEffort ?? null)
  const lastRequest = session?.lastRequest ?? null
  const configurable = !!options?.configurable
  const choices = options?.configurable ? options.choices : []
  const requested: ReasoningChoice = options?.configurable ? stored ?? options.defaultLevel : 'provider_default'
  const effective: ReasoningChoice = options?.configurable ? options.resolution[requested] ?? requested : requested
  const marked = choices.includes(requested) ? requested : effective
  const clamped = configurable && !choices.includes(requested) && requested !== 'provider_default'

  // Follows the current choice (the options may arrive after the first
  // render) until the user moves.
  const [index, setIndex] = useState<number | null>(null)
  const cursor = Math.min(index ?? Math.max(0, choices.indexOf(marked)), Math.max(0, choices.length - 1))

  const choiceLabel = (value: ReasoningChoice) => t(`effort.choice.${value}`)
  const levelLabel = (value: string) => (isChoice(value) ? choiceLabel(value) : t('effort.dynamic'))
  const summary = (value: ReasoningChoice) =>
    value === 'provider_default' && options?.configurable
      ? t('effort.withLevel', { choice: choiceLabel('provider_default'), level: levelLabel(options.providerDefault) })
      : choiceLabel(value)

  const choose = (value: ReasoningChoice) => {
    if (sessionId === 'new') dispatch(setUiState(UI_STATE.chat.draftReasoningEffort, value))
    else {
      // Optimistic, as the browser: the server's session_updated is authoritative.
      if (session) dispatch(upsertSession({ ...session, reasoningEffort: value }))
      send('session_reasoning_set', { sessionId, reasoningEffort: value })
    }
    dispatch(closeScreen())
  }

  useScreenKeys((input, key) => {
    if (!configurable) return false
    if (key.upArrow || input === 'k') setIndex(Math.max(0, cursor - 1))
    else if (key.downArrow || input === 'j') setIndex(Math.min(choices.length - 1, cursor + 1))
    else if (key.home || input === 'g') setIndex(0)
    else if (key.end || input === 'G') setIndex(choices.length - 1)
    else if (/^[1-9]$/.test(input) && Number(input) <= choices.length) choose(choices[Number(input) - 1])
    else if (key.return && choices[cursor]) choose(choices[cursor])
    else return false
    return true
  })

  const sessionTitle = sessionId === 'main' ? t('effort.main') : sessionId === 'new' ? t('effort.newChat') : session?.title || t('effort.untitled')
  const inner = columns - 2
  return (
    <Frame
      title={t('effort.title')}
      aside={options ? `${sessionTitle} · ${options.model}` : sessionTitle}
      hints={
        configurable
          ? [
              { keys: '↑↓', label: t('hint.move') },
              { keys: 'Enter', label: t('hint.choose') },
              { keys: '1-9', label: t('hint.pick') },
              { keys: 'Esc', label: t('hint.back') },
            ]
          : [{ keys: 'Esc', label: t('hint.back') }]
      }
      columns={columns}
      rows={rows}
    >
      <Box flexDirection="column" paddingX={1}>
        {!options ? (
          <Text color={ink.muted}>{t('effort.loading')}</Text>
        ) : (
          <>
            <Text bold>{truncate(t('effort.header', { model: options.model }), inner)}</Text>
            {!configurable ? (
              <Text color={ink.muted}>{truncate(t('effort.notConfigurable', { model: options.model }), inner)}</Text>
            ) : (
              choices.map((value, i) => {
                const sel = i === cursor
                const tag =
                  value === options.defaultLevel
                    ? t('effort.defaultTag')
                    : value === 'provider_default' && options.configurable
                      ? levelLabel(options.providerDefault)
                      : ''
                const label = padEnd(`${i + 1}  ${choiceLabel(value)}`, Math.max(12, Math.min(28, inner - 18)))
                return (
                  <Text key={value}>
                    <Text color={sel ? ink.focus : undefined}>{sel ? `${g.pointer} ` : '  '}</Text>
                    <Text color={ink.success}>{value === marked ? `${g.done} ` : '  '}</Text>
                    <Text color={sel ? ink.focus : undefined} bold={sel}>{label}</Text>
                    <Text color={ink.muted}>{truncate(tag, Math.max(0, inner - 4 - cells(label)))}</Text>
                  </Text>
                )
              })
            )}
            {clamped ? (
              <Text color={ink.warn}>{truncate(t('effort.clamped', { requested: choiceLabel(requested), effective: summary(effective) }), inner)}</Text>
            ) : null}
            <Text> </Text>
            <ContextReadout
              options={options}
              choice={configurable ? requested : 'provider_default'}
              lastRequest={lastRequest}
              width={inner}
              locale={i18n.language}
            />
          </>
        )}
      </Box>
    </Frame>
  )
}

/**
 * How full the chat's context is (its last request's input against the
 * budget at `choice`) and how its prompt cache stands. The cache belongs to
 * the model that served the request, so after a model switch it reads as not
 * cached yet; providers that document no lifetime or report no cached count
 * say so instead of a made-up number.
 */
function ContextReadout({
  options,
  choice,
  lastRequest,
  width: inner,
  locale,
}: {
  options: ReasoningOptions
  choice: ReasoningChoice
  lastRequest: LastRequest | null
  width: number
  locale: string
}) {
  const { t } = useTranslation('settingsCore')
  const g = glyphs()
  const lifetime = options.cacheLifetime
  const cached = lastRequest !== null && lastRequest.surface === options.surface && lastRequest.model === options.model
  useTicker(1000, cached && lifetime !== null)

  const compact = (n: number) => {
    try {
      return new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(n)
    } catch {
      return String(n)
    }
  }
  const percent = (ratio: number) => {
    try {
      return new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 }).format(ratio)
    } catch {
      return `${Math.round(ratio * 100)}%`
    }
  }

  const budget = options.inputBudgets[choice] ?? options.inputBudgets.provider_default ?? 0
  const used = lastRequest?.inputTokens ?? null
  const fill = used === null || !budget ? 0 : used / budget
  const level = contextLevel(fill)
  const barColor = level === 'high' ? ink.error : level === 'warn' ? ink.warn : ink.success

  let cacheValue: string
  let cacheColor: string | undefined
  if (!cached) cacheValue = t('effort.cache.notYet')
  else if (!options.reportsCachedTokens) cacheValue = t('effort.cache.notReported')
  else {
    const ratio = lastRequest.inputTokens > 0 ? lastRequest.cachedTokens / lastRequest.inputTokens : 0
    cacheValue = t('effort.cache.hit', { percent: percent(ratio) })
    cacheColor = ratio >= 0.5 ? ink.success : undefined
  }

  let expiry: string | null = null
  let expired = false
  if (cached) {
    if (lifetime === null) expiry = t('effort.cache.noExpiry')
    else {
      const remaining = lastRequest.startedAt + lifetime.seconds * 1000 - Date.now()
      if (remaining <= 0) {
        expiry = t('effort.cache.expired')
        expired = true
      } else expiry = lifetime.kind === 'typical' ? t('effort.cache.about', { time: formatRemaining(remaining) }) : formatRemaining(remaining)
    }
  }

  const lw = 12
  const barWidth = Math.max(10, Math.min(48, inner - 2))
  const levelWord = level === 'high' ? ` ${t('effort.context.high')}` : level === 'warn' ? ` ${t('effort.context.warn')}` : ''
  return (
    <Box flexDirection="column">
      <Text>
        <Text color={ink.muted}>{padEnd(t('effort.context.label'), lw)}</Text>
        <Text>{`${used === null ? '-' : compact(used)} / ${compact(budget)}`}</Text>
        {used !== null ? <Text color={barColor}>{`   ${percent(fill)}${levelWord}`}</Text> : null}
      </Text>
      <Text color={barColor}>{meter(fill, barWidth, null, g.vbar === '|' ? ASCII_METER : UNICODE_METER)}</Text>
      <Text color={ink.muted}>{truncate(t('effort.context.summarizesAt', { max: compact(budget) }), inner)}</Text>
      <Text>
        <Text color={ink.muted}>{padEnd(t('effort.cache.label'), lw)}</Text>
        <Text color={cacheColor}>{truncate(cacheValue, inner - lw)}</Text>
      </Text>
      {expiry !== null ? (
        <Text>
          <Text color={ink.muted}>{padEnd(t('effort.cache.timeLeft'), lw)}</Text>
          <Text color={expired ? ink.warn : undefined}>{truncate(expiry, inner - lw)}</Text>
        </Text>
      ) : null}
    </Box>
  )
}
