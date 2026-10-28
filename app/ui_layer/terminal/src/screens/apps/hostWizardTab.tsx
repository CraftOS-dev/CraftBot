/**
 * The Create tab of Add Agent App: the browser's three-step wizard
 * (CreateCustomWizard) on the same backend steps (app/agent_app/wizard.py).
 *
 *   CONFIGURE  name, description, icon (a lucide name typed, or picked with
 *              Left/Right from the curated set), access, reference files by
 *              path (staged with POST /api/agent-app/stage on Continue)
 *   INTERVIEW  each {question, why, multiSelect, options} as a select or a
 *              multi-select plus free text; "Question N of M"; Ctrl+S skips
 *              the remaining questions
 *   CREATING   agent_app_wizard_finalize writes the requirements and starts
 *              the build; then the screen moves to the new app's build view
 *
 * A chat can summon the same wizard at the interview step
 * (agent_app_wizard_open, see hostJobs): `seed` carries its questions.
 */
import { useEffect, useRef, useState } from 'react'
import { Box, Text, type Key } from 'ink'
import { onInboundMessage } from '../../../../browser/frontend/src/store/socket/socketMiddleware'
import { send } from '../../state/hooks'
import { TextField, fieldKey } from '../../ui/TextField'
import { useTicker } from '../../ui/useTicker'
import * as TB from '../../input/TextBuffer'
import { glyphs, ink, spinnerFrames } from '../../theme/theme'
import { truncate, width } from '../../text/width'
import {
  answersPayload,
  composeAnswer,
  countWords,
  cycleIcon,
  humanBytes,
  MAX_WORDS,
  newWizardId,
  normalizeIconName,
  pickOption,
  validateConfig,
  type ConfigError,
  type InterviewQuestion,
} from './hostModel'
import { checkLocalFile, stageReference } from './hostUpload'
import type { WizardSeed } from './hostJobs'
import { FormRow, MultiLineField, multiLineKey, type TabController, type TabProps, wrapProse } from './hostTab'

type Step = 'configure' | 'interview' | 'creating'
type Access = 'none' | 'multi-user'
const FIELDS = ['name', 'description', 'icon', 'access', 'files', 'continue'] as const
type FieldId = (typeof FIELDS)[number]

interface StagedFile {
  path: string
  name: string
  size: number
}

export function useWizardTab({ t, columns, height, active, onOpenProject, seed }: TabProps & { seed: WizardSeed | null }): TabController {
  const g = glyphs()
  const wizardId = useRef(seed?.wizardId ?? newWizardId())
  const seedConfig = (seed?.config ?? {}) as Record<string, unknown>

  const [step, setStep] = useState<Step>(seed ? 'interview' : 'configure')
  // configure
  const [field, setField] = useState(0)
  const [name, setName] = useState<TB.Buffer>(TB.fromText(String(seedConfig.name ?? '')))
  const [description, setDescription] = useState<TB.Buffer>(TB.fromText(String(seedConfig.description ?? '')))
  const [icon, setIcon] = useState<TB.Buffer>(TB.EMPTY)
  const [access, setAccess] = useState<Access>(seedConfig.authMode === 'multi-user' ? 'multi-user' : 'none')
  const [files, setFiles] = useState<StagedFile[]>([])
  const [filePath, setFilePath] = useState<TB.Buffer>(TB.EMPTY)
  const [errors, setErrors] = useState<{ name?: ConfigError; description?: ConfigError; icon?: boolean; file?: string }>({})
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  // interview
  const [loading, setLoading] = useState(false)
  const [interviewError, setInterviewError] = useState<string | null>(null)
  const [questions, setQuestions] = useState<InterviewQuestion[]>(seed?.questions ?? [])
  const [qIndex, setQIndex] = useState(0)
  const [answers, setAnswers] = useState<Record<string, string[]>>({})
  const [freeText, setFreeText] = useState<TB.Buffer>(TB.EMPTY)
  const [cursor, setCursor] = useState(0)
  const [followupDone, setFollowupDone] = useState(false)
  const [nudge, setNudge] = useState(false)
  // creating
  const [createError, setCreateError] = useState<string | null>(null)

  const tick = useTicker(120, uploading || loading || (step === 'creating' && !createError))
  const spin = spinnerFrames()[tick % spinnerFrames().length]

  const iconName = normalizeIconName(icon.text)
  const buildConfig = () => ({
    name: name.text.trim(),
    description: description.text.trim(),
    layout: typeof seedConfig.layout === 'string' && seedConfig.layout ? seedConfig.layout : 'free',
    uiTheme: 'craftbot',
    stylePack: 'craftbot',
    authMode: access,
    icon: iconName ? `lucide:${iconName}` : null,
    attachments: files.map(f => ({ name: f.name, kind: 'reference' })),
    ...(seedConfig.context ? { context: seedConfig.context } : {}),
  })
  const configRef = useRef(buildConfig)
  configRef.current = buildConfig

  // Replies are broadcast to every client: keep only this wizard's.
  useEffect(
    () =>
      onInboundMessage(msg => {
        const data = (msg.data ?? {}) as Record<string, unknown>
        if (data.wizardId !== wizardId.current) return
        if (msg.type === 'agent_app_wizard_interview') {
          setLoading(false)
          const qs = data.questions as InterviewQuestion[] | undefined
          if (data.success && Array.isArray(qs) && qs.length > 0) {
            setQuestions(qs)
            setQIndex(0)
            setCursor(0)
            setInterviewError(null)
          } else setInterviewError(String(data.error || t('appsHost:wizard.interviewFailed')))
        } else if (msg.type === 'agent_app_wizard_finalize') {
          const followups = data.followupQuestions as InterviewQuestion[] | undefined
          if (data.success && Array.isArray(followups) && followups.length > 0) {
            // A second round: the backend wants to know what to adapt.
            setFollowupDone(true)
            setQuestions(prev => [...prev, ...followups])
            setQIndex(i => i + 1)
            setCursor(0)
            setStep('interview')
          } else if (data.success && typeof data.projectId === 'string') {
            onOpenProject(data.projectId)
          } else setCreateError(String(data.error || t('appsHost:wizard.createFailed')))
        }
      }),
    [onOpenProject, t],
  )

  const fieldId: FieldId = FIELDS[field]
  const fieldLabels = ['name', 'description', 'icon', 'access', 'files'].map(id => t(`appsHost:wizard.${id}`))
  const labelWidth = Math.min(22, Math.max(...fieldLabels.map(l => width(l))) + 2)
  const inputWidth = Math.max(10, columns - labelWidth - 2)

  // ── configure ──

  const addFile = () => {
    const raw = filePath.text.trim()
    if (!raw) return false
    const check = checkLocalFile(raw)
    if (!check.ok) {
      setErrors(e => ({ ...e, file: t(check.reason === 'missing' ? 'appsHost:files.missing' : 'appsHost:files.notFile', { path: raw }) }))
      return true
    }
    setFiles(prev => (prev.some(f => f.name === check.name) ? prev : [...prev, { path: check.path, name: check.name, size: check.size }]))
    setFilePath(TB.EMPTY)
    setErrors(e => ({ ...e, file: undefined }))
    return true
  }

  const askInterview = () => {
    setStep('interview')
    setLoading(true)
    setInterviewError(null)
    send('agent_app_wizard_interview', { wizardId: wizardId.current, config: configRef.current() })
  }

  const submitConfigure = async () => {
    const found = validateConfig(name.text, description.text)
    const iconBad = !!icon.text.trim() && !iconName
    setErrors(e => ({ ...e, name: found.name, description: found.description, icon: iconBad }))
    if (found.name) return setField(0)
    if (found.description) return setField(1)
    if (iconBad) return setField(2)
    setUploading(true)
    setUploadError(null)
    try {
      for (const f of files) await stageReference(wizardId.current, f.path)
    } catch (err) {
      setUploadError(t('appsHost:wizard.uploadFailed', { message: err instanceof Error ? err.message : String(err) }))
      setUploading(false)
      return
    }
    setUploading(false)
    askInterview()
  }

  // Editing a field clears its error (and a failed upload's).
  const clearError = (id: 'name' | 'description' | 'icon' | 'file') => {
    setErrors(e => (e[id] ? { ...e, [id]: undefined } : e))
    setUploadError(null)
  }

  const configureKey = (input: string, key: Key): boolean => {
    if (uploading) return true
    if (key.escape) return false
    const next = (delta: 1 | -1) => setField(f => Math.max(0, Math.min(FIELDS.length - 1, f + delta)))
    if (key.tab) {
      next(key.shift ? -1 : 1)
      return true
    }
    if (fieldId === 'description') {
      if (key.return && !key.shift && !key.meta) {
        next(1)
        return true
      }
      const edited = multiLineKey(description, input, key, inputWidth)
      if (edited) {
        setDescription(edited)
        clearError('description')
      }
      else if (key.upArrow) next(-1)
      else if (key.downArrow) next(1)
      return true
    }
    if (key.upArrow) {
      next(-1)
      return true
    }
    if (key.downArrow) {
      next(1)
      return true
    }
    switch (fieldId) {
      case 'name': {
        if (key.return) next(1)
        else {
          const edited = fieldKey(name, input, key)
          if (edited) {
            setName(edited)
            clearError('name')
          }
        }
        return true
      }
      case 'icon': {
        if (key.return) next(1)
        else if (key.leftArrow || key.rightArrow) {
          setIcon(TB.fromText(cycleIcon(iconName, key.leftArrow ? -1 : 1) ?? ''))
          clearError('icon')
        }
        else {
          const edited = fieldKey(icon, input, key)
          if (edited) {
            setIcon(edited)
            clearError('icon')
          }
        }
        return true
      }
      case 'access': {
        if (key.return) next(1)
        else if (key.leftArrow || key.rightArrow || input === ' ') setAccess(a => (a === 'none' ? 'multi-user' : 'none'))
        return true
      }
      case 'files': {
        if (key.return) {
          if (!addFile()) next(1)
        } else if (key.backspace && !filePath.text && files.length > 0) setFiles(prev => prev.slice(0, -1))
        else {
          const edited = fieldKey(filePath, input, key)
          if (edited) {
            setFilePath(edited)
            clearError('file')
          }
        }
        return true
      }
      case 'continue': {
        if (key.return || input === ' ') void submitConfigure()
        return true
      }
    }
    return true
  }

  // ── interview ──

  const question = questions[qIndex]
  const optionCount = question?.options.length ?? 0
  const onFreeText = !!question && cursor === optionCount

  const finalize = (finalAnswers: Record<string, string[]>) => {
    setStep('creating')
    setCreateError(null)
    send('agent_app_wizard_finalize', {
      wizardId: wizardId.current,
      config: configRef.current(),
      answers: answersPayload(questions, finalAnswers),
      followupDone,
      ...(seed?.originSessionId ? { originSessionId: seed.originSessionId } : {}),
    })
  }

  const advance = (next: Record<string, string[]>) => {
    setAnswers(next)
    setFreeText(TB.EMPTY)
    setNudge(false)
    if (qIndex + 1 < questions.length) {
      setQIndex(qIndex + 1)
      setCursor(0)
    } else finalize(next)
  }

  const interviewKey = (input: string, key: Key): boolean => {
    if (loading) {
      if (key.escape) {
        setLoading(false)
        setStep('configure')
      }
      return true
    }
    if (interviewError || !question) {
      if (key.escape) setStep('configure')
      else if (input === 'r') askInterview()
      else if (key.ctrl && input === 's') finalize({})
      return true
    }
    if (key.ctrl && input === 's') {
      finalize(answers)
      return true
    }
    if (key.escape) {
      if (qIndex > 0) {
        setQIndex(qIndex - 1)
        setCursor(0)
        setFreeText(TB.EMPTY)
      } else if (seed) return false
      else setStep('configure')
      return true
    }
    const selected = answers[question.id] ?? []
    const choose = (option: string) => setAnswers({ ...answers, [question.id]: pickOption(question, selected, option) })
    if (key.upArrow || (!onFreeText && input === 'k')) {
      setCursor(c => Math.max(0, c - 1))
      return true
    }
    if (key.downArrow || key.tab || (!onFreeText && input === 'j')) {
      setCursor(c => Math.min(optionCount, c + 1))
      return true
    }
    if (!onFreeText && /^[1-9]$/.test(input)) {
      const option = question.options[Number(input) - 1]
      if (option) {
        setCursor(Number(input) - 1)
        choose(option)
      }
      return true
    }
    if (key.return) {
      let final: string[]
      if (onFreeText) final = composeAnswer(question, selected, freeText.text)
      // On an option: a single-select takes that option; a multi-select
      // keeps its checked options (or takes this one) plus any typed answer.
      else if (!question.multiSelect) final = [question.options[cursor]]
      else final = composeAnswer(question, selected.length > 0 ? selected : [question.options[cursor]], freeText.text)
      if (final.length === 0) {
        setNudge(true)
        return true
      }
      advance({ ...answers, [question.id]: final })
      return true
    }
    if (!onFreeText && input === ' ') {
      choose(question.options[cursor])
      return true
    }
    if (onFreeText) {
      const edited = fieldKey(freeText, input, key)
      if (edited) setFreeText(edited)
      return true
    }
    return false
  }

  // ── creating ──

  const creatingKey = (input: string, key: Key): boolean => {
    if (!createError) return true
    if (input === 'r') finalize(answers)
    else if (key.escape) setStep(questions.length > 0 ? 'interview' : 'configure')
    return true
  }

  const handleKey = (input: string, key: Key): boolean => {
    if (step === 'configure') return configureKey(input, key)
    if (step === 'interview') return interviewKey(input, key)
    return creatingKey(input, key)
  }

  // ── render ──

  const textFocus =
    active &&
    ((step === 'configure' && ['name', 'description', 'icon', 'files'].includes(fieldId)) || (step === 'interview' && onFreeText && !loading))

  const errorText = (e: ConfigError | undefined) => (e ? t(`appsHost:wizard.errors.${e}`, { max: MAX_WORDS }) : '')

  const renderConfigure = () => {
    const words = countWords(description.text)
    const descRows = Math.max(1, Math.min(6, height - 9 - Math.min(files.length, 3)))
    const fileRows = Math.max(0, Math.min(files.length, height - 9 - descRows))
    const error =
      uploadError ||
      errorText(errors.name) ||
      errorText(errors.description) ||
      (errors.icon ? t('appsHost:wizard.errors.icon') : '') ||
      errors.file ||
      ''
    const focused = (id: FieldId) => active && fieldId === id
    return (
      <Box flexDirection="column">
        <FormRow label={t('appsHost:wizard.name')} labelWidth={labelWidth} focused={focused('name')} error={!!errors.name}>
          <TextField buffer={name} focused={focused('name')} width={inputWidth} placeholder={t('appsHost:wizard.namePlaceholder')} />
        </FormRow>
        <FormRow label={t('appsHost:wizard.description')} labelWidth={labelWidth} focused={focused('description')} error={!!errors.description}>
          <MultiLineField buffer={description} focused={focused('description')} width={inputWidth} maxRows={descRows} placeholder={t('appsHost:wizard.descPlaceholder')} />
        </FormRow>
        <Text color={words > MAX_WORDS ? ink.error : ink.muted}>
          {' '.repeat(labelWidth + 2) + truncate(t('appsHost:wizard.words', { words, max: MAX_WORDS }) + (focused('description') ? '  ' + t('appsHost:wizard.newlineHint') : ''), inputWidth)}
        </Text>
        <FormRow label={t('appsHost:wizard.icon')} labelWidth={labelWidth} focused={focused('icon')} error={errors.icon}>
          <TextField buffer={icon} focused={focused('icon')} width={Math.min(inputWidth, 24)} placeholder={t('appsHost:wizard.iconPlaceholder')} />
          <Text color={ink.muted}>{truncate('  ' + (iconName && iconName !== icon.text ? iconName + '  ' : '') + t('appsHost:wizard.iconHint'), Math.max(0, inputWidth - 24))}</Text>
        </FormRow>
        <FormRow label={t('appsHost:wizard.access')} labelWidth={labelWidth} focused={focused('access')}>
          <Text>{focused('access') ? `< ${t(`appsHost:wizard.accessOptions.${access}`)} >` : t(`appsHost:wizard.accessOptions.${access}`)}</Text>
        </FormRow>
        <FormRow label={t('appsHost:wizard.files')} labelWidth={labelWidth} focused={focused('files')}>
          <TextField buffer={filePath} focused={focused('files')} width={inputWidth} placeholder={t('appsHost:wizard.filesPlaceholder')} />
        </FormRow>
        {files.slice(-fileRows).map(f => (
          <Text key={f.path} color={ink.muted}>
            {' '.repeat(labelWidth + 2) + truncate(`${g.bullet} ${f.name}  ${humanBytes(f.size)}`, inputWidth)}
          </Text>
        ))}
        {files.length > fileRows ? (
          <Text color={ink.muted}>{' '.repeat(labelWidth + 2) + t('appsHost:wizard.moreFiles', { count: files.length - fileRows })}</Text>
        ) : null}
        <Text> </Text>
        <Box>
          <Text color={focused('continue') ? ink.focus : undefined}>{focused('continue') ? `${g.pointer} ` : '  '}</Text>
          <Text inverse={focused('continue')} bold>{` ${uploading ? `${spin} ${t('appsHost:wizard.uploading')}` : t('appsHost:wizard.continue')} `}</Text>
        </Box>
        {error ? <Text color={ink.error}>{truncate(error, columns)}</Text> : null}
      </Box>
    )
  }

  const renderInterview = () => {
    if (loading) {
      return (
        <Box flexDirection="column">
          <Text bold>{`${spin} ${t('appsHost:wizard.preparing')}`}</Text>
          {wrapProse(t('appsHost:wizard.preparingSub'), columns).map((line, i) => (
            <Text key={i} color={ink.muted}>{line}</Text>
          ))}
        </Box>
      )
    }
    if (interviewError || !question) {
      return (
        <Box flexDirection="column">
          <Text color={ink.error}>{truncate(interviewError || t('appsHost:wizard.interviewFailed'), columns)}</Text>
          <Text color={ink.muted}>{t('appsHost:wizard.interviewErrorKeys')}</Text>
        </Box>
      )
    }
    const selected = answers[question.id] ?? []
    const qLines = wrapProse(question.question, columns).slice(0, 3)
    const whyLines = question.why ? wrapProse(question.why, columns).slice(0, 2) : []
    const mark = (on: boolean) => (question.multiSelect ? (on ? g.checked : g.unchecked) : on ? '(•)' : '( )')
    return (
      <Box flexDirection="column">
        <Text color={ink.muted}>
          {truncate(`${t('appsHost:wizard.progress', { current: qIndex + 1, total: questions.length })} · ${question.multiSelect ? t('appsHost:wizard.multi') : t('appsHost:wizard.single')}`, columns)}
        </Text>
        {qLines.map((line, i) => (
          <Text key={`q${i}`} bold>{line}</Text>
        ))}
        {whyLines.map((line, i) => (
          <Text key={`w${i}`} color={ink.muted}>{line}</Text>
        ))}
        <Text> </Text>
        {question.options.map((option, i) => {
          const on = selected.includes(option)
          const here = active && cursor === i
          return (
            <Box key={i}>
              <Text color={here ? ink.focus : undefined}>{here ? `${g.pointer} ` : '  '}</Text>
              <Text color={on ? ink.brand : ink.muted}>{`${i + 1} ${mark(on)} `}</Text>
              <Text bold={here || on}>{truncate(option, Math.max(4, columns - 8 - width(mark(on))))}</Text>
            </Box>
          )
        })}
        <Box>
          <Text color={onFreeText ? ink.focus : undefined}>{onFreeText && active ? `${g.pointer} ` : '  '}</Text>
          <TextField
            label={t('appsHost:wizard.other')}
            buffer={freeText}
            focused={onFreeText && active}
            width={Math.max(10, columns - 2)}
            placeholder={question.multiSelect ? t('appsHost:wizard.freeTextMulti') : t('appsHost:wizard.freeTextSingle')}
          />
        </Box>
        {nudge ? <Text color={ink.warn}>{t('appsHost:wizard.pickOne')}</Text> : null}
      </Box>
    )
  }

  const renderCreating = () =>
    createError ? (
      <Box flexDirection="column">
        <Text color={ink.error}>{truncate(createError, columns)}</Text>
        <Text color={ink.muted}>{t('appsHost:wizard.createErrorKeys')}</Text>
      </Box>
    ) : (
      <Box flexDirection="column">
        <Text bold>{`${spin} ${t('appsHost:wizard.creating')}`}</Text>
        {wrapProse(t('appsHost:wizard.creatingSub'), columns).map((line, i) => (
          <Text key={i} color={ink.muted}>{line}</Text>
        ))}
      </Box>
    )

  let hints: TabController['hints']
  if (step === 'configure') {
    hints = [
      { keys: 'Tab', label: t('appsHost:hint.nextField') },
      ...(fieldId === 'icon' ? [{ keys: 'Left/Right', label: t('appsHost:hint.browseIcons') }] : []),
      ...(fieldId === 'access' ? [{ keys: 'Left/Right', label: t('appsHost:hint.change') }] : []),
      ...(fieldId === 'files' ? [{ keys: 'Enter', label: t('appsHost:hint.addFile') }] : []),
      ...(fieldId === 'continue' ? [{ keys: 'Enter', label: t('appsHost:hint.continue') }] : []),
      { keys: 'Esc', label: t('appsHost:hint.tabBar') },
    ]
  } else if (step === 'interview' && question && !loading && !interviewError) {
    hints = [
      { keys: '1-9', label: t('appsHost:hint.pick') },
      ...(question.multiSelect ? [{ keys: 'Space', label: t('appsHost:hint.toggle') }] : []),
      { keys: 'Enter', label: t('appsHost:hint.continue') },
      { keys: 'Ctrl+S', label: t('appsHost:hint.skipRest') },
      { keys: 'Esc', label: t('appsHost:hint.back') },
    ]
  } else hints = [{ keys: 'Esc', label: t('appsHost:hint.back') }]

  const body = step === 'configure' ? renderConfigure() : step === 'interview' ? renderInterview() : renderCreating()
  const dirty = step !== 'creating' && (!!name.text.trim() || !!description.text.trim() || files.length > 0 || questions.length > 0)
  return { handleKey, textFocus, hints, body, dirty }
}
