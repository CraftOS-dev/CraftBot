/**
 * First-run setup, driven step by step by the backend's onboarding flow
 * (the same steps and submissions as the browser wizard): a welcome, the
 * model provider (a list), its API key (masked) or the Ollama address, the
 * user's profile (a form) and the agent's name. Optional steps are skipped
 * with Ctrl+S, as in the browser; Esc goes back a step.
 *
 * A provider with a subscription sign-in offers it above the key, with the
 * Settings > Model messages: sign in (the system browser, or a code pasted
 * back), install or update Claude Code first when needed, disconnect. Tab
 * and the arrows move between it and the key.
 */
import { useEffect, useState, type ReactNode } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector, send } from '../state/hooks'
import { setLoading, markComplete } from '../../../browser/frontend/src/store/slices/onboardingSlice'
import { clearSubscriptionPasteback, setSubscriptionPending } from '../../../browser/frontend/src/store/slices/modelSettingsSlice'
import {
  selectSubscriptionOauth,
  selectSubscriptionPasteback,
  selectSubscriptionPending,
} from '../../../browser/frontend/src/store/selectors/modelSettings'
import type { OnboardingFormField, OnboardingStep } from '../../../browser/frontend/src/types'
import { Frame } from '../ui/Frame'
import { useScreen, useScreenKeys } from './context'
import { TextField, fieldKey } from '../ui/TextField'
import * as TB from '../input/TextBuffer'
import { glyphs, ink } from '../theme/theme'
import { truncate, wrap, wrapLines } from '../text/width'
import { renderMarkdown } from '../render/markdown'
import { closeAllScreens } from '../state/tuiSlice'
import { useInbound } from './settings/coreHooks'
import { openInBrowser } from './settings/coreEditor'

const PROXIED = ['moonshot', 'minimax']

type FormValue = string | string[]

// Text fields start empty with their default shown as the placeholder, so
// typing replaces it; an empty field submits the default.
function initialForm(step: OnboardingStep): Record<string, FormValue> {
  const values: Record<string, FormValue> = {}
  for (const field of step.form_fields ?? []) {
    if (field.field_type === 'text') values[field.name] = ''
    else values[field.name] = field.default ?? (field.field_type === 'multi_checkbox' ? [] : '')
  }
  return values
}

function withDefaults(step: OnboardingStep, values: Record<string, FormValue>): Record<string, FormValue> {
  const out = { ...values }
  for (const field of step.form_fields ?? []) {
    if (field.field_type === 'text' && !String(out[field.name] ?? '').trim()) out[field.name] = field.default ?? ''
  }
  return out
}

export function OnboardingScreen() {
  const { t } = useTranslation('tui')
  const { t: ts } = useTranslation('settingsCore')
  const dispatch = useAppDispatch()
  const { columns, rows, setTextFocus } = useScreen()
  const step = useAppSelector(s => s.onboarding.step)
  const error = useAppSelector(s => s.onboarding.error)
  const loading = useAppSelector(s => s.onboarding.loading)
  const finishing = useAppSelector(s => s.onboarding.finishing)
  const subscriptionOauth = useAppSelector(selectSubscriptionOauth)
  const subscriptionPending = useAppSelector(selectSubscriptionPending)
  const subscriptionPasteback = useAppSelector(selectSubscriptionPasteback)

  const [optionIndex, setOptionIndex] = useState(0)
  const [text, setText] = useState<TB.Buffer>(TB.EMPTY)
  const [via, setVia] = useState<'direct' | 'openrouter'>('direct')
  const [form, setForm] = useState<Record<string, FormValue>>({})
  const [fieldIndex, setFieldIndex] = useState(0)
  const [checkIndex, setCheckIndex] = useState(0)
  const [subFocus, setSubFocus] = useState('')
  const [code, setCode] = useState<TB.Buffer>(TB.EMPTY)
  const [subNotice, setSubNotice] = useState<{ text: string; tone: 'success' | 'error' } | null>(null)

  useEffect(() => {
    if (!step) send('onboarding_step_get')
  }, [step])

  // ── Subscription sign-in (api_key step of a provider that offers one) ──
  const subProvider = step?.name === 'api_key' && step.supports_subscription_oauth && step.provider ? step.provider : ''
  const subStatus = subProvider ? subscriptionOauth[subProvider] : undefined
  const subConnected = !!subStatus?.connected
  const subPending = subProvider ? !!subscriptionPending[subProvider] : false
  const pasteback = subProvider ? subscriptionPasteback[subProvider] : undefined
  const subTargets: string[] = !subProvider
    ? []
    : [
        ...(subConnected
          ? ['disconnect']
          : pasteback?.awaiting
            ? ['code', ...(pasteback.authUrl ? ['reopen'] : []), 'cancel']
            : subStatus?.setup
              ? ['setup']
              : ['signIn']),
        ...(!subConnected && subStatus?.configured ? ['recover'] : []),
        'key',
      ]
  // A target that went away hands focus on: to the key once signed in.
  const focus = subTargets.includes(subFocus) ? subFocus : subConnected ? 'key' : subTargets[0] ?? 'key'

  // Refresh the live status on landing on the step, as the browser does.
  useEffect(() => {
    if (!subProvider) return
    send('model_subscription_status', { provider: subProvider })
    setSubFocus('')
    setCode(TB.EMPTY)
    setSubNotice(null)
  }, [subProvider, step?.index])

  useInbound(['model_subscription_connect', 'model_subscription_disconnect', 'model_subscription_setup'], (data, type) => {
    const d = data as { provider?: string; success: boolean; message?: string; error?: string }
    if (!subProvider || d.provider !== subProvider) return
    if (type === 'model_subscription_setup') {
      setSubNotice({ text: d.message || d.error || (d.success ? ts('model.sub.setupDone') : ts('model.sub.setupFailed')), tone: d.success ? 'success' : 'error' })
    } else if (!d.success) {
      const fallback = type === 'model_subscription_connect' ? ts('model.sub.connectFailed') : ts('model.sub.disconnectFailed')
      setSubNotice({ text: d.message || d.error || fallback, tone: 'error' })
    } else setSubNotice(null)
  })

  const runSub = (target: string) => {
    if (!subProvider || (subPending && target !== 'reopen')) return
    const pending = () => dispatch(setSubscriptionPending({ provider: subProvider, pending: true }))
    setSubNotice(null)
    if (target === 'signIn') {
      pending()
      // OpenAI and Claude finish through a local callback; the others end on
      // a page with a code to paste back.
      const loopback = subProvider === 'openai' || subProvider === 'anthropic'
      send(loopback ? 'model_subscription_connect' : 'model_subscription_prepare', { provider: subProvider })
    } else if (target === 'setup') {
      pending()
      send('model_subscription_setup', { provider: subProvider })
    } else if (target === 'disconnect' || target === 'recover') {
      pending()
      send('model_subscription_disconnect', { provider: subProvider })
    } else if (target === 'code') {
      const value = code.text.trim()
      if (!value) return
      pending()
      send('model_subscription_complete', { provider: subProvider, code: value, attemptId: pasteback?.attemptId })
    } else if (target === 'cancel') {
      dispatch(clearSubscriptionPasteback(subProvider))
      setCode(TB.EMPTY)
    } else if (target === 'reopen' && pasteback?.authUrl) {
      void openInBrowser(pasteback.authUrl).then(ok => {
        if (!ok) setSubNotice({ text: ts('model.sub.openFailed'), tone: 'error' })
      })
    }
  }

  // A new step resets the inputs to its defaults.
  useEffect(() => {
    if (!step) return
    const def = typeof step.default === 'string' ? step.default : ''
    const defIndex = step.options.findIndex(o => o.default || o.value === def)
    setOptionIndex(Math.max(0, defIndex))
    const isOllama = step.name === 'api_key' && step.provider === 'remote'
    setText(TB.fromText(isOllama ? def || 'http://localhost:11434' : step.name === 'api_key' ? '' : def))
    setVia('direct')
    setForm(initialForm(step))
    setFieldIndex(0)
    setCheckIndex(0)
  }, [step?.name, step?.index])

  // Finishing: the browser plays an outro; the terminal goes straight to the chat.
  useEffect(() => {
    if (finishing) {
      dispatch(markComplete())
      dispatch(closeAllScreens())
    }
  }, [finishing, dispatch])

  const isForm = !!step?.form_fields?.length
  const isText = !!step && !isForm && step.options.length === 0 && step.name !== 'intro'
  useEffect(() => {
    setTextFocus(isText || isForm)
    return () => setTextFocus(false)
  }, [isText, isForm, setTextFocus])

  const submit = () => {
    if (!step) return
    let value: unknown
    if (step.name === 'api_key' && step.provider === 'remote') value = text.text.trim()
    else if (step.name === 'api_key' && step.provider && PROXIED.includes(step.provider)) value = { api_key: text.text.trim(), via, or_model: '' }
    else if (isForm) value = withDefaults(step, form)
    else if (step.options.length > 0) value = step.options[optionIndex]?.value
    else value = text.text.trim()
    dispatch(setLoading(true))
    send('onboarding_step_submit', { value })
  }

  const fields: OnboardingFormField[] = step?.form_fields ?? []
  const field = fields[fieldIndex]

  useScreenKeys((input, key) => {
    if (!step || loading) return true
    if (key.ctrl && input === 's' && !step.required) {
      dispatch(setLoading(true))
      send('onboarding_skip')
      return true
    }
    if (key.escape) {
      if (step.index > 0) {
        dispatch(setLoading(true))
        send('onboarding_back')
      }
      return true
    }
    if (isForm && field) {
      if (key.tab || (key.downArrow && field.field_type !== 'multi_checkbox')) {
        setFieldIndex(i => (key.shift ? (i - 1 + fields.length) % fields.length : (i + 1) % fields.length))
        setCheckIndex(0)
        return true
      }
      if (key.upArrow && field.field_type !== 'multi_checkbox') {
        setFieldIndex(i => (i - 1 + fields.length) % fields.length)
        return true
      }
      if (key.return && (key.ctrl || fieldIndex === fields.length - 1)) {
        submit()
        return true
      }
      if (key.return) {
        setFieldIndex(i => Math.min(fields.length - 1, i + 1))
        return true
      }
      if (field.field_type === 'select') {
        const opts = field.options
        const current = Math.max(0, opts.findIndex(o => o.value === form[field.name]))
        if (key.leftArrow || key.rightArrow || input === ' ') {
          const next = opts[(current + (key.leftArrow ? -1 : 1) + opts.length) % opts.length]
          setForm({ ...form, [field.name]: next.value })
        }
        return true
      }
      if (field.field_type === 'multi_checkbox') {
        const opts = field.options
        if (key.upArrow) setCheckIndex(i => Math.max(0, i - 1))
        else if (key.downArrow) {
          if (checkIndex >= opts.length - 1) setFieldIndex(i => Math.min(fields.length - 1, i + 1))
          else setCheckIndex(i => i + 1)
        } else if (input === ' ') {
          const chosen = new Set(Array.isArray(form[field.name]) ? (form[field.name] as string[]) : [])
          const value = opts[checkIndex]?.value
          if (value) {
            if (chosen.has(value)) chosen.delete(value)
            else chosen.add(value)
            setForm({ ...form, [field.name]: Array.from(chosen) })
          }
        }
        return true
      }
      const buf = TB.fromText(String(form[field.name] ?? ''))
      const next = fieldKey(buf, input, key)
      if (next) setForm({ ...form, [field.name]: next.text })
      return true
    }
    if (subProvider) {
      const at = subTargets.indexOf(focus)
      if (key.tab || key.upArrow || key.downArrow) {
        const delta = key.upArrow || (key.tab && key.shift) ? -1 : 1
        setSubFocus(subTargets[(at + delta + subTargets.length) % subTargets.length])
        return true
      }
      if (focus !== 'key') {
        if (key.return) runSub(focus)
        else if (focus === 'code' && !subPending) {
          const next = fieldKey(code, input, key)
          if (next) setCode(next)
        }
        return true
      }
    }
    if (step.options.length > 0) {
      if (key.upArrow || input === 'k') setOptionIndex(i => Math.max(0, i - 1))
      else if (key.downArrow || input === 'j') setOptionIndex(i => Math.min(step.options.length - 1, i + 1))
      else if (key.return) submit()
      return true
    }
    if (key.return) {
      submit()
      return true
    }
    if (step.name === 'api_key' && step.provider && PROXIED.includes(step.provider) && key.tab) {
      setVia(v => (v === 'direct' ? 'openrouter' : 'direct'))
      return true
    }
    if (isText) {
      const next = fieldKey(text, input, key)
      if (next) setText(next)
    }
    return true
  })

  const g = glyphs()
  if (!step) {
    return (
      <Frame title={t('onboarding.title')} hints={[]} columns={columns} rows={rows}>
        <Text color={ink.muted}>{error ?? t('onboarding.loading')}</Text>
      </Frame>
    )
  }
  const progress = `${step.index + 1}/${step.total}`
  const width = columns - 4

  // The subscription block above the key field.
  const subLines: ReactNode[] = []
  if (subProvider) {
    const action = (id: string, label: string) => (
      <Text key={id} color={focus === id ? ink.focus : undefined} bold={focus === id}>
        {focus === id ? `${g.pointer} ` : '  '}
        {truncate(label, width - 2)}
      </Text>
    )
    const note = (id: string, value: string, color: string | undefined = ink.muted, max = 2) =>
      wrap(value, width - 2)
        .slice(0, max)
        .map((line, i) => <Text key={`${id}${i}`} color={color}>{'  ' + line.trimStart()}</Text>)
    subLines.push(<Text key="label" bold>{ts('model.sub.label')}</Text>)
    if (subConnected) {
      const who = [subStatus?.email, subStatus?.plan].filter(Boolean).join(' · ')
      subLines.push(
        <Text key="connected" color={ink.success}>{'  ' + truncate(`${g.done} ${ts('model.sub.connected')}${who ? ` · ${who}` : ''}`, width - 2)}</Text>,
        action('disconnect', subPending ? ts('model.sub.disconnecting') : ts('model.sub.disconnect')),
      )
    } else if (pasteback?.awaiting) {
      subLines.push(
        <Box key="code">
          <Text color={focus === 'code' ? ink.focus : undefined}>{focus === 'code' ? `${g.pointer} ` : '  '}</Text>
          <TextField label={`${ts('model.sub.code')}:`} buffer={code} focused={focus === 'code'} width={width - 2} placeholder={ts('model.sub.pastePlaceholder')} />
        </Box>,
      )
      if (subPending) subLines.push(...note('checking', ts('model.sub.checking')))
      if (pasteback.authUrl) subLines.push(action('reopen', ts('model.sub.reopen')))
      subLines.push(action('cancel', ts('model.sub.cancel')))
      if (pasteback.authUrl) subLines.push(...note('url', `${ts('model.sub.urlNote')} ${pasteback.authUrl}`, ink.muted, 3))
      if (pasteback.errorMessage) subLines.push(...note('codeError', pasteback.errorMessage, ink.error))
    } else if (subStatus?.setup) {
      // Claude Code is missing or too old to sign in: set it up first.
      const install = subStatus.setup.action === 'install'
      const hint = install
        ? ts('model.sub.claudeCodeMissing')
        : subStatus.setup.version
          ? ts('model.sub.claudeCodeOutdated', { version: subStatus.setup.version })
          : ts('model.sub.claudeCodeOutdatedUnknown')
      subLines.push(
        ...note('setupHint', hint, ink.warn),
        action(
          'setup',
          install
            ? subPending ? ts('model.sub.installingClaudeCode') : ts('model.sub.installClaudeCode')
            : subPending ? ts('model.sub.updatingClaudeCode') : ts('model.sub.updateClaudeCode'),
        ),
      )
    } else {
      subLines.push(action('signIn', subPending ? ts('model.sub.waiting') : step.subscription_label || ts('model.sub.signInWith', { provider: subProvider })))
      if (pasteback?.errorMessage) subLines.push(...note('signInError', pasteback.errorMessage, ink.error))
    }
    if (!subConnected && subStatus?.configured) subLines.push(...note('recovery', ts('model.sub.recovery')), action('recover', ts('model.sub.disconnect')))
    if (subStatus?.error && !subStatus.setup) subLines.push(...note('error', subStatus.error, ink.error))
    if (subProvider === 'anthropic') subLines.push(...note('claude', ts('model.sub.claudeNote')))
    if (subNotice) subLines.push(...note('notice', subNotice.text, subNotice.tone === 'error' ? ink.error : ink.success))
    subLines.push(<Text key="gap"> </Text>, <Text key="or" color={ink.muted}>{truncate(ts('model.sub.orKey'), width)}</Text>)
  }

  const description = wrapLines(renderMarkdown(step.description ?? '', width), width).slice(0, Math.max(subProvider ? 2 : 3, rows - 16 - subLines.length))
  const onSubAction = !!subProvider && focus !== 'key'
  const hints = [
    {
      keys: 'Enter',
      label: onSubAction ? ts('hint.run') : isForm && fieldIndex < fields.length - 1 ? t('onboarding.next') : t('onboarding.continue'),
    },
    ...(step.index > 0 ? [{ keys: 'Esc', label: t('hint.back') }] : []),
    ...(!step.required ? [{ keys: 'Ctrl+S', label: t('onboarding.skip') }] : []),
    ...((isForm && fields.length > 1) || subProvider ? [{ keys: 'Tab', label: t('onboarding.nextField') }] : []),
  ]

  return (
    <Frame title={t('onboarding.title')} aside={progress} hints={hints} columns={columns} rows={rows}>
      <Box flexDirection="column" paddingX={1}>
        <Text bold color={ink.brand}>{truncate(step.title, columns - 4)}</Text>
        {description.map((line, i) => (
          <Text key={i}>{line}</Text>
        ))}
        <Text> </Text>
        {step.options.length > 0 && !isForm
          ? step.options.map((option, i) => {
              const active = i === optionIndex
              return (
                <Box key={option.value} flexDirection="column">
                  <Text color={active ? ink.focus : undefined} bold={active}>
                    {active ? `${g.pointer} ` : '  '}
                    {option.label}
                  </Text>
                  {active && option.description ? (
                    <Text color={ink.muted}>{'    ' + truncate(option.description, columns - 8)}</Text>
                  ) : null}
                </Box>
              )
            })
          : null}
        {isText ? (
          <Box flexDirection="column">
            {subLines}
            <Box>
              {subProvider ? <Text color={focus === 'key' ? ink.focus : undefined}>{focus === 'key' ? `${g.pointer} ` : '  '}</Text> : null}
              <TextField
                label={step.name === 'api_key' ? (step.provider === 'remote' ? t('onboarding.ollamaUrl') : t('onboarding.apiKey')) : ''}
                buffer={text}
                focused={!subProvider || focus === 'key'}
                width={subProvider ? width - 2 : width}
                masked={step.name === 'api_key' && step.provider !== 'remote'}
                placeholder={step.name === 'agent_name' ? t('onboarding.agentNamePlaceholder') : subConnected ? ts('model.key.optional') : ''}
              />
            </Box>
            {step.name === 'api_key' && step.provider && PROXIED.includes(step.provider) ? (
              <Text color={ink.muted}>{t('onboarding.via', { via: via === 'direct' ? t('onboarding.viaDirect') : 'OpenRouter' })}</Text>
            ) : null}
          </Box>
        ) : null}
        {isForm
          ? fields.map((f, i) => {
              const focused = i === fieldIndex
              const value = form[f.name]
              if (f.field_type === 'select') {
                const label = f.options.find(o => o.value === value)?.label ?? String(value ?? '')
                return (
                  <Text key={f.name} color={focused ? ink.focus : undefined}>
                    {focused ? `${g.pointer} ` : '  '}
                    {f.label}: {focused ? `< ${label} >` : label}
                  </Text>
                )
              }
              if (f.field_type === 'multi_checkbox') {
                const chosen = new Set(Array.isArray(value) ? value : [])
                return (
                  <Box key={f.name} flexDirection="column">
                    <Text color={focused ? ink.focus : undefined}>{focused ? `${g.pointer} ` : '  '}{f.label}</Text>
                    {f.options.map((o, j) => (
                      <Text key={o.value} color={focused && j === checkIndex ? ink.focus : undefined}>
                        {'    '}{chosen.has(o.value) ? g.checked : g.unchecked} {o.label}
                      </Text>
                    ))}
                  </Box>
                )
              }
              if (f.field_type === 'image_upload') {
                return <Text key={f.name} color={ink.muted}>{'  '}{f.label}: {t('onboarding.imageLater')}</Text>
              }
              return (
                <Box key={f.name}>
                  <Text color={focused ? ink.focus : undefined}>{focused ? `${g.pointer} ` : '  '}</Text>
                  <TextField
                    label={`${f.label}:`}
                    buffer={TB.fromText(String(value ?? ''))}
                    focused={focused}
                    width={columns - 6}
                    placeholder={typeof f.default === 'string' && f.default ? f.default : f.placeholder}
                  />
                </Box>
              )
            })
          : null}
        <Text> </Text>
        {loading ? <Text color={ink.muted}>{t('onboarding.working')}</Text> : null}
        {error ? <Text color={ink.error}>{truncate(error, columns - 4)}</Text> : null}
      </Box>
    </Frame>
  )
}
