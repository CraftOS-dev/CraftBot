import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, Check, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../components/ui/Button'
import { MarkdownContent } from '../../components/ui/MarkdownContent'
import { formatNumber } from '../../i18n/format'
import { useAppSelector } from '../../store/hooks'
import type { BuildCheckpoint } from '../../types'
import { frameworkRequest } from './frameworkApi'
import styles from '../../components/ui/CreateCustomWizard.module.css'

interface Question { id: string; question: string; why?: string; options: string[]; multiSelect: boolean }
interface Detail { checkpoint: BuildCheckpoint & { intro?: string; questions?: Question[] }; partA?: string }
interface Reply { ok: boolean; error?: string; problems?: string[]; reason?: string }
type Answer = { choices: string[]; other: string }

/** The checkpoint the build stopped at, for the person: shown in CraftBot, not in chat. */
export function waitingForPerson(checkpoint: BuildCheckpoint | null | undefined): checkpoint is BuildCheckpoint {
  return !!checkpoint && checkpoint.status === 'pending' && checkpoint.shown === 'ui'
}

/**
 * A build's two stops for the person, where it was started: the builder's
 * questions, one at a time, then the requirements it wrote (Part A) to read,
 * edit, send back with changes, or approve. Each reply goes to the builder as
 * the person's message and the build carries on; between stops this shows
 * what the builder is doing. `onApproved` runs once the requirements are
 * approved, or when the build no longer waits on this view.
 */
export function BuildCheckpoints({ sessionId, onApproved, onOpenBuild }: {
  sessionId: string
  onApproved?: () => void
  /** Leave this view for the build session (the dialog offers it while waiting). */
  onOpenBuild?: () => void
}) {
  const { t } = useTranslation(['components', 'common'])
  const build = useAppSelector(state => state.sessions.sessions.find(item => item.id === sessionId)?.agentAppBuild)
  const checkpoint = build?.checkpoint ?? null
  const waiting = waitingForPerson(checkpoint)
  const [detail, setDetail] = useState<{ id: string; data?: Detail; error?: string }>()
  // Sent replies, by checkpoint id, until the host confirms it moved on.
  const [sent, setSent] = useState<Record<string, 'answers' | 'changes' | 'approve'>>({})
  const [attempt, setAttempt] = useState(0)
  const requested = useRef<string>()
  const approvedRef = useRef(false)

  const id = checkpoint?.id
  useEffect(() => {
    if (!waiting || !id || requested.current === id) return
    requested.current = id
    setDetail({ id })
    // A late answer for a step the build has since left is dropped; so is a
    // step it left between the session update and this read (the next update
    // brings what is waiting now).
    frameworkRequest<Detail>({ operation: 'checkpoint', sessionId })
      .then(data => setDetail(value => (value?.id !== id ? value
        : data.checkpoint?.id === id && data.checkpoint.status === 'pending' ? { id, data } : { id })))
      .catch(error => setDetail(value => (value?.id === id ? { id, error: error instanceof Error ? error.message : String(error) } : value)))
  }, [waiting, id, sessionId, attempt])
  const refetch = () => { requested.current = undefined; setAttempt(value => value + 1) }

  // Approved, or the build is no longer waiting on anyone: hand over to the build.
  const done = checkpoint?.status === 'approved' || (build === null && Object.keys(sent).length > 0)
  useEffect(() => {
    if (done && !approvedRef.current) {
      approvedRef.current = true
      onApproved?.()
    }
  }, [done, onApproved])

  if (waiting && !sent[checkpoint.id]) {
    if (detail?.id !== checkpoint.id || (!detail.data && !detail.error)) return <Waiting title={t('components:createCustomWizard.loadingStep')} />
    if (detail.error || !detail.data) {
      return <div className={styles.stateScreen}>
        <p className={styles.stateError}>{detail.error || t('components:createCustomWizard.stepFailed')}</p>
        <div className={styles.stateActions}>
          <Button variant="secondary" onClick={refetch}>{t('common:actions.retry')}</Button>
        </div>
      </div>
    }
    const reply = async (body: Record<string, unknown>, kind: 'answers' | 'changes' | 'approve'): Promise<Reply> => {
      const result = await frameworkRequest<Reply>({ operation: 'checkpoint_reply', sessionId, id: checkpoint.id, ...body })
        .catch(error => ({ ok: false, error: error instanceof Error ? error.message : String(error) }) as Reply)
      if (result.ok) setSent(value => ({ ...value, [checkpoint.id]: kind }))
      else if (result.reason === 'moved') refetch()
      return result
    }
    return checkpoint.kind === 'questions'
      ? <Questions key={checkpoint.id} detail={detail.data} onSend={answers => reply({ answers }, 'answers')} />
      : <Review key={checkpoint.id} detail={detail.data}
        onChanges={(changes, partA) => reply({ changes, ...(partA !== undefined ? { partA } : {}) }, 'changes')}
        onApprove={partA => reply({ approve: true, ...(partA !== undefined ? { partA } : {}) }, 'approve')} />
  }

  // Between stops: what the builder is doing, from the last reply.
  const last = checkpoint ? (sent[checkpoint.id] ?? (checkpoint.status === 'approved' ? 'approve' : checkpoint.status === 'changes' ? 'changes' : checkpoint.status === 'answered' ? 'answers' : undefined)) : undefined
  const [title, sub] = last === 'approve'
    ? [t('components:createCustomWizard.startingTitle'), '']
    : last === 'changes'
      ? [t('components:createCustomWizard.revisingTitle'), t('components:createCustomWizard.revisingSub')]
      : last === 'answers'
        ? [t('components:createCustomWizard.writingTitle'), t('components:createCustomWizard.writingSub')]
        : [t('components:createCustomWizard.preparingTitle'), t('components:createCustomWizard.preparingSub')]
  return <Waiting title={title} sub={sub} onOpenBuild={last === 'approve' ? undefined : onOpenBuild} />
}

function Waiting({ title, sub, onOpenBuild }: { title: string; sub?: string; onOpenBuild?: () => void }) {
  const { t } = useTranslation('components')
  return <div className={styles.stateScreen} role="status">
    <Loader2 size={28} className={styles.spinner} />
    <p className={styles.stateTitle}>{title}</p>
    {sub && <p className={styles.stateSub}>{sub}</p>}
    {onOpenBuild && <>
      <p className={styles.stateSub}>{t('createCustomWizard.closeHint')}</p>
      <div className={styles.stateActions}>
        <Button variant="secondary" onClick={onOpenBuild}>{t('createCustomWizard.openBuild')}</Button>
      </div>
    </>}
  </div>
}

/** One question at a time, as the Build tab always asked them; anything skipped is the builder's to decide. */
function Questions({ detail, onSend }: { detail: Detail; onSend: (answers: { id: string; choices: string[]; other?: string }[]) => Promise<Reply> }) {
  const { t } = useTranslation(['components', 'common'])
  const questions = detail.checkpoint.questions ?? []
  const [index, setIndex] = useState(0)
  const [answers, setAnswers] = useState<Record<string, Answer>>({})
  const [freeText, setFreeText] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const question = questions[index]
  if (!question) return null
  const current = answers[question.id] ?? { choices: [], other: '' }

  const send = async (final: Record<string, Answer>) => {
    setSending(true); setError('')
    const result = await onSend(questions.map(q => {
      const a = final[q.id]
      return { id: q.id, choices: a?.choices ?? [], ...(a?.other ? { other: a.other } : {}) }
    }))
    if (!result.ok) { setSending(false); setError(result.error || t('components:createCustomWizard.replyFailed')) }
  }
  const pick = (option: string) => {
    const on = current.choices.includes(option)
    const choices = question.multiSelect
      ? (on ? current.choices.filter(c => c !== option) : [...current.choices, option])
      : [option]
    setAnswers({ ...answers, [question.id]: { ...current, choices } })
  }
  // Continue: typed words join the picks (multi) or stand instead of them (single).
  const next = () => {
    const text = freeText.trim()
    const answer = text ? { choices: question.multiSelect ? current.choices : [], other: text } : current
    const final = { ...answers, [question.id]: answer }
    setAnswers(final)
    setFreeText(final[questions[index + 1]?.id]?.other ?? '')
    if (index + 1 < questions.length) setIndex(index + 1)
    else void send(final)
  }
  const canContinue = current.choices.length > 0 || freeText.trim().length > 0

  if (sending) return <Waiting title={t('components:createCustomWizard.sending')} />
  return <div className={styles.wizardBody}>
    <div className={styles.interview}>
      <div className={styles.interviewHeader}>
        <button type="button" className={styles.backLink} disabled={index === 0}
          onClick={() => { setIndex(index - 1); setFreeText(answers[questions[index - 1].id]?.other ?? '') }}>
          <ArrowLeft size={13} /> {t('common:actions.back')}
        </button>
        <span className={styles.interviewProgress}>
          {t('components:createCustomWizard.questionProgress', { current: formatNumber(index + 1), total: formatNumber(questions.length) })}
        </span>
        <button type="button" className={styles.skipLink} onClick={() => void send(answers)}>
          {t('components:createCustomWizard.skipRemaining')}
        </button>
      </div>
      {index === 0 && detail.checkpoint.intro && <p className={styles.questionWhy}>{detail.checkpoint.intro}</p>}
      <h3 className={styles.questionText}>{question.question}</h3>
      {question.why && <p className={styles.questionWhy}>{question.why}</p>}
      {question.options.length > 0 && <div className={styles.optionList}>
        {question.options.map(option => {
          const selected = current.choices.includes(option)
          return <label key={option} className={`${styles.optionRow} ${selected ? styles.optionRowActive : ''}`}>
            <input type={question.multiSelect ? 'checkbox' : 'radio'} name={`cp-q-${question.id}`} className={styles.optionInput}
              checked={selected} onChange={() => pick(option)} />
            <span>{option}</span>
          </label>
        })}
      </div>}
      <div className={styles.freeAnswerRow}>
        <input className={styles.input}
          placeholder={question.multiSelect ? t('components:createCustomWizard.freeTextMulti') : t('components:createCustomWizard.freeTextSingle')}
          value={freeText} onChange={e => setFreeText(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && canContinue) next() }} />
        <Button variant="primary" icon={<ArrowRight size={14} />} onClick={next} disabled={!canContinue}>
          {t('common:actions.continue')}
        </Button>
      </div>
      {error && <p className={styles.stateError} role="alert">{error}</p>}
    </div>
  </div>
}

/**
 * Part A as the person reads it. Left out: the template's marker line and the
 * Approval section, which approving writes. Hard-wrapped lines are joined,
 * since the chat renderer breaks the line wherever the text does.
 */
function readable(partA: string): string {
  const out: string[] = []
  let approval = false
  for (const line of partA.split('\n')) {
    if (/^PART A\b/.test(line)) continue
    const heading = /^#{1,6}\s/.test(line)
    if (heading) approval = /^#{1,6}\s+Approval\b/i.test(line)
    if (approval) continue
    const previous = out[out.length - 1] ?? ''
    const continues = !heading && line.trim() !== '' && previous.trim() !== ''
      && !/^#{1,6}\s/.test(previous) && !/^\s*([-*+]|\d+\.)\s/.test(line) && !/^\s*\|/.test(line)
    if (continues) out[out.length - 1] = `${previous.trimEnd()} ${line.trim()}`
    else out.push(line)
  }
  return out.join('\n')
}

/** Part A as the builder wrote it: read it, edit it, send it back with changes, or approve it. */
function Review({ detail, onChanges, onApprove }: {
  detail: Detail
  onChanges: (changes: string, partA?: string) => Promise<Reply>
  onApprove: (partA?: string) => Promise<Reply>
}) {
  const { t } = useTranslation('components')
  const original = detail.partA ?? ''
  const [draft, setDraft] = useState(original)
  const [editing, setEditing] = useState(false)
  const [changes, setChanges] = useState('')
  const [sending, setSending] = useState<'changes' | 'approve' | null>(null)
  const [error, setError] = useState('')
  const [problems, setProblems] = useState<string[]>([])
  const edit = draft !== original ? draft : undefined

  const run = async (kind: 'changes' | 'approve') => {
    setSending(kind); setError(''); setProblems([])
    const result = kind === 'approve' ? await onApprove(edit) : await onChanges(changes.trim(), edit)
    if (result.ok) return
    setSending(null)
    setError(result.error || t('createCustomWizard.replyFailed'))
    setProblems(result.problems ?? [])
    if (result.problems?.length) setEditing(true)
  }

  return <div className={styles.wizardBody}>
    <div className={styles.review}>
      <div>
        <h3 className={styles.questionText}>
          {detail.checkpoint.round > 1 ? t('createCustomWizard.reviewRevisedTitle') : t('createCustomWizard.reviewTitle')}
        </h3>
        <p className={styles.questionWhy}>{t('createCustomWizard.reviewSub')}</p>
      </div>
      <div className={styles.reviewHead}>
        <span>{editing ? t('createCustomWizard.editingLabel') : t('createCustomWizard.partALabel')}</span>
        <Button variant="secondary" size="sm" onClick={() => setEditing(value => !value)}>
          {editing ? t('createCustomWizard.preview') : t('createCustomWizard.edit')}
        </Button>
      </div>
      {editing
        ? <textarea className={`${styles.textarea} ${styles.reviewEditor}`} value={draft} spellCheck={false}
          aria-label={t('createCustomWizard.editingLabel')}
          // What was wrong with the last attempt no longer describes the text.
          onChange={e => { setDraft(e.target.value); setProblems([]); setError('') }} />
        : <div className={styles.reviewDoc}><MarkdownContent content={readable(draft)} /></div>}
      {problems.length > 0 && <ul className={styles.reviewProblems}>{problems.map(problem => <li key={problem}>{problem}</li>)}</ul>}
      <div className={styles.formGroup}>
        <label htmlFor="cp-changes" className={styles.label}>{t('createCustomWizard.changesLabel')}</label>
        <textarea id="cp-changes" className={styles.textarea} rows={3} value={changes}
          placeholder={t('createCustomWizard.changesPlaceholder')} onChange={e => setChanges(e.target.value)} />
      </div>
      {error && <p className={styles.stateError} role="alert">{error}</p>}
      <div className={styles.reviewActions}>
        <Button variant="secondary" onClick={() => void run('changes')} disabled={sending !== null || !changes.trim()}
          loading={sending === 'changes'}>
          {t('createCustomWizard.askChanges')}
        </Button>
        <Button variant="primary" icon={<Check size={14} />} onClick={() => void run('approve')} disabled={sending !== null}
          loading={sending === 'approve'}>
          {t('createCustomWizard.approve')}
        </Button>
      </div>
    </div>
  </div>
}
