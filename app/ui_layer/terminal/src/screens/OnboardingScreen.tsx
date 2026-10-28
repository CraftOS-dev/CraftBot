/**
 * First-run setup, driven step by step by the backend's onboarding flow
 * (the same steps and submissions as the browser wizard): a welcome, the
 * model provider (a list), its API key (masked) or the Ollama address, the
 * user's profile (a form) and the agent's name. Optional steps are skipped
 * with Ctrl+S, as in the browser; Esc goes back a step.
 */
import { useEffect, useState } from 'react'
import { Box, Text } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector, send } from '../state/hooks'
import { setLoading, markComplete } from '../../../browser/frontend/src/store/slices/onboardingSlice'
import type { OnboardingFormField, OnboardingStep } from '../../../browser/frontend/src/types'
import { Frame } from '../ui/Frame'
import { useScreen, useScreenKeys } from './context'
import { TextField, fieldKey } from '../ui/TextField'
import * as TB from '../input/TextBuffer'
import { glyphs, ink } from '../theme/theme'
import { truncate, wrapLines } from '../text/width'
import { renderMarkdown } from '../render/markdown'
import { closeAllScreens } from '../state/tuiSlice'

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
  const dispatch = useAppDispatch()
  const { columns, rows, setTextFocus } = useScreen()
  const step = useAppSelector(s => s.onboarding.step)
  const error = useAppSelector(s => s.onboarding.error)
  const loading = useAppSelector(s => s.onboarding.loading)
  const finishing = useAppSelector(s => s.onboarding.finishing)

  const [optionIndex, setOptionIndex] = useState(0)
  const [text, setText] = useState<TB.Buffer>(TB.EMPTY)
  const [via, setVia] = useState<'direct' | 'openrouter'>('direct')
  const [form, setForm] = useState<Record<string, FormValue>>({})
  const [fieldIndex, setFieldIndex] = useState(0)
  const [checkIndex, setCheckIndex] = useState(0)

  useEffect(() => {
    if (!step) send('onboarding_step_get')
  }, [step])

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
  const description = wrapLines(renderMarkdown(step.description ?? '', columns - 4), columns - 4).slice(0, Math.max(3, rows - 16))
  const hints = [
    { keys: 'Enter', label: isForm && fieldIndex < fields.length - 1 ? t('onboarding.next') : t('onboarding.continue') },
    ...(step.index > 0 ? [{ keys: 'Esc', label: t('hint.back') }] : []),
    ...(!step.required ? [{ keys: 'Ctrl+S', label: t('onboarding.skip') }] : []),
    ...(isForm && fields.length > 1 ? [{ keys: 'Tab', label: t('onboarding.nextField') }] : []),
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
            <TextField
              label={step.name === 'api_key' ? (step.provider === 'remote' ? t('onboarding.ollamaUrl') : t('onboarding.apiKey')) : ''}
              buffer={text}
              focused
              width={columns - 4}
              masked={step.name === 'api_key' && step.provider !== 'remote'}
              placeholder={step.name === 'agent_name' ? t('onboarding.agentNamePlaceholder') : ''}
            />
            {step.name === 'api_key' && step.provider && PROXIED.includes(step.provider) ? (
              <Text color={ink.muted}>{t('onboarding.via', { via: via === 'direct' ? t('onboarding.viaDirect') : 'OpenRouter' })}</Text>
            ) : null}
            {step.supports_subscription_oauth ? (
              <Text color={ink.muted}>{t('onboarding.subscriptionHint', { label: step.subscription_label ?? '' })}</Text>
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
