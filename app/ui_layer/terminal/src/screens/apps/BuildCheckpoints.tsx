/**
 * A build's two stops for the person, where it was started: the builder's
 * questions, one at a time, then the requirements it wrote (Part A) to read,
 * edit in your editor, send back with changes, or approve. Each reply goes
 * to the builder as the person's message and the build carries on. The
 * terminal version of the browser's BuildCheckpoints, over the same
 * requests (`checkpoint`, `checkpoint_reply`).
 *
 * The host screen routes keys to it through `keysRef` while it is shown.
 *
 *   Questions:  j/k move · Space pick · Enter continue · Left back
 *               Ctrl+S skip the rest (the builder decides those)
 *   Review:     j/k scroll · Tab to the changes field · e edit Part A
 *               a approve · Enter (in the field) ask for the changes
 */
import { useEffect, useRef, useState, type MutableRefObject } from 'react'
import { Box, Text, type Key } from 'ink'
import { useTranslation } from 'react-i18next'
import type { BuildCheckpoint } from '../../../../browser/frontend/src/types'
import { useAppSelector } from '../../state/hooks'
import { errorText, frameworkRequest } from '../../apps/framework'
import { glyphs, ink } from '../../theme/theme'
import { truncate } from '../../text/width'
import { renderMarkdown } from '../../render/markdown'
import * as TB from '../../input/TextBuffer'
import { TextField, fieldKey } from '../../ui/TextField'
import { editText } from '../settings/connectEditor'
import { useSuspend } from '../settings/connectKit'
import { answersPayload, composeAnswer, pickOption, readablePartA, type CheckpointAnswer, type InterviewQuestion } from './hostModel'

export type CheckpointKeys = (input: string, key: Key) => boolean

interface Detail {
  checkpoint: BuildCheckpoint & { intro?: string; questions?: InterviewQuestion[] }
  partA?: string
}
interface Reply {
  ok: boolean
  error?: string
  problems?: string[]
  reason?: string
}

/** The checkpoint the build stopped at, for the person: shown in CraftBot, not in chat. */
export function waitingForPerson(checkpoint: BuildCheckpoint | null | undefined): checkpoint is BuildCheckpoint {
  return !!checkpoint && checkpoint.status === 'pending' && checkpoint.shown === 'ui'
}

export function BuildCheckpoints({
  sessionId,
  columns,
  rows,
  keysRef,
  onTextFocus,
}: {
  sessionId: string
  columns: number
  rows: number
  keysRef: MutableRefObject<CheckpointKeys | null>
  onTextFocus: (focused: boolean) => void
}) {
  const { t } = useTranslation(['components', 'appsHost', 'common'])
  const build = useAppSelector(s => s.sessions.sessions.find(x => x.id === sessionId)?.agentAppBuild)
  const checkpoint = build?.checkpoint ?? null
  const waiting = waitingForPerson(checkpoint)
  const [detail, setDetail] = useState<{ id: string; data?: Detail; error?: string }>()
  // Sent replies, by checkpoint id, until the host confirms it moved on.
  const [sent, setSent] = useState<Record<string, 'answers' | 'changes' | 'approve'>>({})
  const [attempt, setAttempt] = useState(0)
  const requested = useRef<string | undefined>(undefined)

  const id = checkpoint?.id
  useEffect(() => {
    if (!waiting || !id || requested.current === id) return
    requested.current = id
    setDetail({ id })
    frameworkRequest<Detail>({ operation: 'checkpoint', sessionId })
      .then(data =>
        setDetail(value =>
          value?.id !== id ? value : data.checkpoint?.id === id && data.checkpoint.status === 'pending' ? { id, data } : { id },
        ),
      )
      .catch(err => setDetail(value => (value?.id === id ? { id, error: errorText(err) } : value)))
  }, [waiting, id, sessionId, attempt])
  const refetch = () => {
    requested.current = undefined
    setAttempt(value => value + 1)
  }

  const g = glyphs()
  if (waiting && !sent[checkpoint.id]) {
    if (detail?.id !== checkpoint.id || (!detail.data && !detail.error)) {
      keysRef.current = null
      return <Text color={ink.muted}>{t('components:createCustomWizard.loadingStep')}</Text>
    }
    if (detail.error || !detail.data) {
      keysRef.current = (input) => {
        if (input === 'r') {
          refetch()
          return true
        }
        return false
      }
      return (
        <Box flexDirection="column">
          <Text color={ink.error}>{truncate(detail.error || t('components:createCustomWizard.stepFailed'), columns)}</Text>
          <Text color={ink.muted}>{t('appsHost:checkpoint.retryHint')}</Text>
        </Box>
      )
    }
    const reply = async (body: Record<string, unknown>, kind: 'answers' | 'changes' | 'approve'): Promise<Reply> => {
      const result = await frameworkRequest<Reply>({ operation: 'checkpoint_reply', sessionId, id: checkpoint.id, ...body }).catch(
        err => ({ ok: false, error: errorText(err) }) as Reply,
      )
      if (result.ok) setSent(value => ({ ...value, [checkpoint.id]: kind }))
      else if (result.reason === 'moved') refetch()
      return result
    }
    return checkpoint.kind === 'questions' ? (
      <Questions
        key={checkpoint.id}
        detail={detail.data}
        columns={columns}
        rows={rows}
        keysRef={keysRef}
        onTextFocus={onTextFocus}
        onSend={answers => reply({ answers }, 'answers')}
      />
    ) : (
      <Review
        key={checkpoint.id}
        detail={detail.data}
        columns={columns}
        rows={rows}
        keysRef={keysRef}
        onTextFocus={onTextFocus}
        onChanges={(changes, partA) => reply({ changes, ...(partA !== undefined ? { partA } : {}) }, 'changes')}
        onApprove={partA => reply({ approve: true, ...(partA !== undefined ? { partA } : {}) }, 'approve')}
      />
    )
  }

  // Between stops: what the builder is doing, from the last reply.
  keysRef.current = null
  const last = checkpoint
    ? (sent[checkpoint.id] ??
      (checkpoint.status === 'approved' ? 'approve' : checkpoint.status === 'changes' ? 'changes' : checkpoint.status === 'answered' ? 'answers' : undefined))
    : undefined
  const [title, sub] =
    last === 'approve'
      ? [t('components:createCustomWizard.startingTitle'), '']
      : last === 'changes'
        ? [t('components:createCustomWizard.revisingTitle'), t('components:createCustomWizard.revisingSub')]
        : last === 'answers'
          ? [t('components:createCustomWizard.writingTitle'), t('components:createCustomWizard.writingSub')]
          : [t('components:createCustomWizard.preparingTitle'), t('components:createCustomWizard.preparingSub')]
  return (
    <Box flexDirection="column">
      <Text color={ink.brand}>{`${g.running} ${truncate(title, columns - 2)}`}</Text>
      {sub ? <Text color={ink.muted}>{truncate(sub, columns)}</Text> : null}
    </Box>
  )
}

/** One question at a time; anything skipped is the builder's to decide. */
function Questions({
  detail,
  columns,
  rows,
  keysRef,
  onTextFocus,
  onSend,
}: {
  detail: Detail
  columns: number
  rows: number
  keysRef: MutableRefObject<CheckpointKeys | null>
  onTextFocus: (focused: boolean) => void
  onSend: (answers: { id: string; choices: string[]; other?: string }[]) => Promise<Reply>
}) {
  const { t } = useTranslation(['components', 'appsHost'])
  const questions = detail.checkpoint.questions ?? []
  const [index, setIndex] = useState(0)
  const [answers, setAnswers] = useState<Record<string, CheckpointAnswer>>({})
  const [selected, setSelected] = useState<string[]>([])
  const [freeText, setFreeText] = useState<TB.Buffer>(TB.EMPTY)
  // The focused row: an option, or the free answer after the last option.
  const [row, setRow] = useState(0)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const question = questions[index]
  const optionCount = question?.options.length ?? 0
  const onText = row >= optionCount

  useEffect(() => {
    onTextFocus(onText && !sending)
    return () => onTextFocus(false)
  }, [onText, sending, onTextFocus])

  const send = (final: Record<string, CheckpointAnswer>) => {
    setSending(true)
    setError('')
    void onSend(answersPayload(questions, final)).then(result => {
      if (!result.ok) {
        setSending(false)
        setError(result.error || t('components:createCustomWizard.replyFailed'))
      }
    })
  }
  const goTo = (next: number, all: Record<string, CheckpointAnswer>) => {
    const q = questions[next]
    const saved = q ? all[q.id] : undefined
    setIndex(next)
    setSelected(saved?.choices ?? [])
    setFreeText(TB.fromText(saved?.other ?? ''))
    setRow(0)
  }
  const next = (picks: string[] = selected) => {
    if (!question) return
    const answer = composeAnswer(question, picks, freeText.text)
    if (answer.choices.length === 0 && !answer.other) {
      setError(t('appsHost:wizard.pickOne'))
      return
    }
    const all = { ...answers, [question.id]: answer }
    setAnswers(all)
    setError('')
    if (index + 1 < questions.length) goTo(index + 1, all)
    else send(all)
  }

  keysRef.current = (input, key) => {
    if (sending || !question) return true
    if (key.ctrl && input === 's') {
      send(answers)
      return true
    }
    if (key.upArrow || (!onText && input === 'k')) {
      setRow(r => Math.max(0, r - 1))
      return true
    }
    if (key.downArrow || (!onText && input === 'j') || key.tab) {
      setRow(r => Math.min(optionCount, r + 1))
      return true
    }
    if (!onText && key.leftArrow) {
      if (index > 0) goTo(index - 1, answers)
      return true
    }
    if (!onText && input === ' ') {
      setSelected(pickOption(question, selected, question.options[row]))
      return true
    }
    if (key.return) {
      if (!onText) {
        // A single choice picks and moves on; a multiple one moves on with its picks.
        const picks = question.multiSelect ? selected : pickOption(question, selected, question.options[row])
        setSelected(picks)
        next(picks)
      } else next()
      return true
    }
    if (key.escape) return false
    if (onText) {
      const buf = fieldKey(freeText, input, key)
      if (buf) setFreeText(buf)
      return true
    }
    return false
  }

  const g = glyphs()
  if (!question) return null
  if (sending) return <Text color={ink.brand}>{`${g.running} ${t('components:createCustomWizard.sending')}`}</Text>
  const why = question.why ? truncate(question.why, columns) : ''
  const intro = index === 0 && detail.checkpoint.intro ? detail.checkpoint.intro : ''
  const listRows = Math.max(2, rows - 7 - (intro ? 1 : 0))
  const top = Math.max(0, Math.min(row, optionCount) - listRows + 1)
  return (
    <Box flexDirection="column">
      <Text color={ink.muted}>
        {t('components:createCustomWizard.questionProgress', { current: index + 1, total: questions.length })}
        {`  ${g.sep}  `}
        {question.multiSelect ? t('appsHost:wizard.multi') : t('appsHost:wizard.single')}
      </Text>
      {intro ? <Text color={ink.muted}>{truncate(intro, columns)}</Text> : null}
      <Text bold>{truncate(question.question, columns)}</Text>
      {why ? <Text color={ink.muted}>{why}</Text> : null}
      {question.options.slice(top, top + listRows).map((option, i) => {
        const at = top + i
        const focused = at === row
        const on = selected.includes(option)
        const mark = question.multiSelect ? (on ? g.checked : g.unchecked) : on ? g.radioOn : g.radioOff
        return (
          <Text key={option} color={focused ? ink.focus : undefined} bold={focused}>
            {focused ? `${g.pointer} ` : '  '}
            {`${mark} ${truncate(option, Math.max(4, columns - 6))}`}
          </Text>
        )
      })}
      <Box>
        <Text color={onText ? ink.focus : undefined}>{onText ? `${g.pointer} ` : '  '}</Text>
        <TextField
          label={t('appsHost:wizard.other')}
          buffer={freeText}
          focused={onText}
          width={Math.max(10, columns - 2)}
          placeholder={question.multiSelect ? t('components:createCustomWizard.freeTextMulti') : t('components:createCustomWizard.freeTextSingle')}
        />
      </Box>
      {error ? <Text color={ink.error}>{truncate(error, columns)}</Text> : null}
      <Text color={ink.dim}>{truncate(t('appsHost:checkpoint.questionKeys'), columns)}</Text>
    </Box>
  )
}

/** Part A as the builder wrote it: read it, edit it, send it back with changes, or approve it. */
function Review({
  detail,
  columns,
  rows,
  keysRef,
  onTextFocus,
  onChanges,
  onApprove,
}: {
  detail: Detail
  columns: number
  rows: number
  keysRef: MutableRefObject<CheckpointKeys | null>
  onTextFocus: (focused: boolean) => void
  onChanges: (changes: string, partA?: string) => Promise<Reply>
  onApprove: (partA?: string) => Promise<Reply>
}) {
  const { t } = useTranslation(['components', 'appsHost'])
  const suspend = useSuspend()
  const original = detail.partA ?? ''
  const [draft, setDraft] = useState(original)
  const [changes, setChanges] = useState<TB.Buffer>(TB.EMPTY)
  const [inField, setInField] = useState(false)
  const [scroll, setScroll] = useState(0)
  const [sending, setSending] = useState<'changes' | 'approve' | null>(null)
  const [error, setError] = useState('')
  const [problems, setProblems] = useState<string[]>([])
  const edit = draft !== original ? draft : undefined

  useEffect(() => {
    onTextFocus(inField && sending === null)
    return () => onTextFocus(false)
  }, [inField, sending, onTextFocus])

  const lines = renderMarkdown(readablePartA(draft), Math.max(20, columns - 2))
  const docRows = Math.max(3, rows - 8 - Math.min(3, problems.length))
  const maxScroll = Math.max(0, lines.length - docRows)
  const top = Math.min(scroll, maxScroll)

  const run = (kind: 'changes' | 'approve') => {
    if (kind === 'changes' && !changes.text.trim()) return
    setSending(kind)
    setError('')
    setProblems([])
    const request = kind === 'approve' ? onApprove(edit) : onChanges(changes.text.trim(), edit)
    void request.then(result => {
      if (result.ok) return
      setSending(null)
      setError(result.error || t('components:createCustomWizard.replyFailed'))
      setProblems(result.problems ?? [])
    })
  }

  keysRef.current = (input, key) => {
    if (sending) return true
    if (key.tab) {
      setInField(f => !f)
      return true
    }
    if (inField) {
      if (key.escape) {
        setInField(false)
        return true
      }
      if (key.return) {
        run('changes')
        return true
      }
      const buf = fieldKey(changes, input, key)
      if (buf) setChanges(buf)
      return true
    }
    const page = Math.max(1, docRows - 1)
    if (key.downArrow || input === 'j') setScroll(Math.min(maxScroll, top + 1))
    else if (key.upArrow || input === 'k') setScroll(Math.max(0, top - 1))
    else if (key.pageDown || input === ' ') setScroll(Math.min(maxScroll, top + page))
    else if (key.pageUp) setScroll(Math.max(0, top - page))
    else if (input === 'a') run('approve')
    else if (input === 'e') {
      void editText(suspend, draft, 'requirements').then(result => {
        if (result.text !== null && result.changed) {
          setDraft(result.text)
          setProblems([])
          setError('')
        }
      })
    } else return false
    return true
  }

  const g = glyphs()
  return (
    <Box flexDirection="column">
      <Text bold>
        {truncate(detail.checkpoint.round > 1 ? t('components:createCustomWizard.reviewRevisedTitle') : t('components:createCustomWizard.reviewTitle'), columns)}
      </Text>
      <Text color={ink.muted}>{truncate(t('components:createCustomWizard.reviewSub'), columns)}</Text>
      <Text color={ink.dim}>
        {truncate(`${edit !== undefined ? t('appsHost:checkpoint.edited') : t('components:createCustomWizard.partALabel')}  ${g.sep}  ${top + 1}-${Math.min(lines.length, top + docRows)} / ${lines.length}`, columns)}
      </Text>
      <Box flexDirection="column" height={docRows} overflow="hidden">
        {lines.slice(top, top + docRows).map((line, i) => (
          <Text key={i} wrap="truncate-end">{`  ${line || ' '}`}</Text>
        ))}
      </Box>
      {problems.slice(0, 3).map(problem => (
        <Text key={problem} color={ink.error}>{truncate(`${g.failed} ${problem}`, columns)}</Text>
      ))}
      <Box>
        <Text color={inField ? ink.focus : undefined}>{inField ? `${g.pointer} ` : '  '}</Text>
        <TextField
          label={t('components:createCustomWizard.changesLabel')}
          buffer={changes}
          focused={inField}
          width={Math.max(10, columns - 2)}
          placeholder={t('appsHost:checkpoint.changesPlaceholder')}
        />
      </Box>
      {sending ? (
        <Text color={ink.brand}>{`${g.running} ${t(sending === 'approve' ? 'appsHost:checkpoint.approving' : 'appsHost:checkpoint.sendingChanges')}`}</Text>
      ) : error ? (
        <Text color={ink.error}>{truncate(error, columns)}</Text>
      ) : null}
      <Text color={ink.dim}>{truncate(t(inField ? 'appsHost:checkpoint.fieldKeys' : 'appsHost:checkpoint.reviewKeys'), columns)}</Text>
    </Box>
  )
}
