import { useState, type KeyboardEvent } from 'react'
import type { ChatMessageQuestion } from '../../types'
import styles from './QuestionStepper.module.css'

export interface QuestionStepperProps {
  messageId: string
  sessionId?: string
  questions: ChatMessageQuestion[]
  answers?: Record<string, string>
  declined?: boolean
  onSubmit: (messageId: string, sessionId: string | undefined, answers: Record<string, string> | undefined, declined: boolean) => void
}

// Per-question draft kept structured (which boxes are checked vs. what was
// free-typed) so navigating between questions never has to reverse-engineer
// state from the joined answer string — choice values containing ", " would
// mis-parse, and a free-typed value equal to a choice would be reclassified.
interface QuestionDraft {
  checked: string[]
  other: string
}

const draftText = (d: QuestionDraft) =>
  [...d.checked, ...(d.other ? [d.other] : [])].join(', ')

export function QuestionStepper({ messageId, sessionId, questions, answers, declined, onSubmit }: QuestionStepperProps) {
  const resolved = !!answers || !!declined
  const [step, setStep] = useState(0)
  const [drafts, setDrafts] = useState<Record<string, QuestionDraft>>({})
  const [otherText, setOtherText] = useState('')
  const [checked, setChecked] = useState<Set<string>>(new Set())

  // Esc abandons the whole batch — scoped to this stepper via bubbling from
  // its own focused controls, not a window-wide listener (which would decline
  // whichever batch happened to be mounted regardless of what's focused).
  // The free-text inputs intercept Esc to clear themselves instead, and the
  // Dismiss button covers the case where nothing in the stepper has focus.
  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') onSubmit(messageId, sessionId, undefined, true)
  }

  if (resolved) {
    return (
      <div className={styles.resolved}>
        {declined ? (
          <span className={styles.declinedNote}>Declined to answer.</span>
        ) : (
          questions.map(q => (
            <div key={q.id} className={styles.resolvedRow}>
              <span className={styles.resolvedQuestion}>{q.text}</span>
              <span className={styles.resolvedAnswer}>{answers?.[q.id]}</span>
            </div>
          ))
        )}
      </div>
    )
  }

  const single = questions.length === 1
  const isReview = !single && step === questions.length
  const current = questions[step]

  const answerTextFor = (qid: string): string | undefined => {
    const d = drafts[qid]
    return d === undefined ? undefined : draftText(d)
  }

  // Navigating to a question rehydrates its saved draft (if any) so a
  // previously-given answer shows exactly as it was entered.
  // `source` lets callers that just updated the drafts pass the fresh map,
  // since the `drafts` in this closure is one render behind.
  const goToStep = (i: number, source: Record<string, QuestionDraft> = drafts) => {
    setStep(i)
    const q = questions[i]
    if (!q) return // i === questions.length: moving into the review step
    const d = source[q.id]
    setChecked(new Set(d?.checked ?? []))
    setOtherText(d?.other ?? '')
  }

  const saveCurrent = (d: QuestionDraft) => {
    const next = { ...drafts, [current.id]: d }
    setDrafts(next)
    if (single) {
      onSubmit(messageId, sessionId, { [current.id]: draftText(d) }, false)
    } else {
      goToStep(step + 1, next)
    }
  }

  const toggleChecked = (value: string) => {
    const next = new Set(checked)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    setChecked(next)
  }

  const confirmMultiSelect = () => {
    const other = otherText.trim()
    if (checked.size === 0 && !other) return
    saveCurrent({ checked: [...checked], other })
  }

  const submitOther = () => {
    const other = otherText.trim()
    if (!other) return
    saveCurrent({ checked: [], other })
  }

  const submitAll = () => {
    const all: Record<string, string> = {}
    for (const q of questions) {
      const text = answerTextFor(q.id)
      if (text !== undefined) all[q.id] = text
    }
    onSubmit(messageId, sessionId, all, false)
  }

  const clearOnEscape = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      e.stopPropagation() // clear the field, don't decline the batch
      setOtherText('')
    }
  }

  return (
    <div className={styles.stepper} onKeyDown={handleKeyDown}>
      <div className={styles.nav}>
        {!single && step > 0 && (
          <button type="button" className={styles.backButton} onClick={() => goToStep(step - 1)}>
            ‹ Back
          </button>
        )}
        {!single && questions.map((q, i) => (
          <button
            key={q.id}
            type="button"
            className={`${styles.navDot} ${i === step ? styles.navDotActive : ''} ${drafts[q.id] ? styles.navDotDone : ''}`}
            onClick={() => goToStep(i)}
            disabled={i > step && drafts[q.id] === undefined}
            aria-label={`Question ${i + 1} of ${questions.length}`}
          >
            {i + 1}
          </button>
        ))}
        {!single && (
          <span className={styles.navReview}>{isReview ? 'Review' : `${step + 1} of ${questions.length}`}</span>
        )}
        <button
          type="button"
          className={styles.dismissButton}
          onClick={() => onSubmit(messageId, sessionId, undefined, true)}
        >
          Dismiss
        </button>
      </div>

      {isReview ? (
        <div className={styles.review}>
          {questions.map(q => (
            <button
              key={q.id}
              type="button"
              className={styles.reviewRow}
              onClick={() => goToStep(questions.indexOf(q))}
            >
              <span className={styles.resolvedQuestion}>{q.text}</span>
              <span className={styles.resolvedAnswer}>{answerTextFor(q.id)}</span>
            </button>
          ))}
          <button type="button" className={styles.submitButton} onClick={submitAll}>
            Submit answers
          </button>
        </div>
      ) : (
        <div className={styles.question} role={current.multiSelect ? 'group' : 'radiogroup'}>
          {!single && <span className={styles.questionText}>{current.text}</span>}

          {current.multiSelect ? (
            <>
              {current.choices.map(c => (
                <label key={c.value} className={styles.checkboxRow}>
                  <input
                    type="checkbox"
                    className={styles.checkbox}
                    checked={checked.has(c.value)}
                    onChange={() => toggleChecked(c.value)}
                  />
                  {c.label}
                </label>
              ))}
              <div className={styles.otherRow}>
                <input
                  type="text"
                  className={styles.otherInput}
                  value={otherText}
                  onChange={e => setOtherText(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') confirmMultiSelect(); clearOnEscape(e) }}
                  placeholder="Other (optional)..."
                />
              </div>
              <button
                type="button"
                className={styles.submitButton}
                onClick={confirmMultiSelect}
                disabled={checked.size === 0 && !otherText.trim()}
              >
                Continue
              </button>
            </>
          ) : (
            <>
              {current.choices.map((c, i) => {
                const selected = checked.has(c.value)
                return (
                  <button
                    key={c.value}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    className={`${styles.choiceButton} ${selected ? styles.choiceButtonSelected : ''}`}
                    onClick={() => saveCurrent({ checked: [c.value], other: '' })}
                  >
                    <span className={styles.choiceIndex}>{i + 1}</span>
                    {c.label}
                  </button>
                )
              })}
              <div className={styles.otherRow}>
                <input
                  type="text"
                  className={styles.otherInput}
                  value={otherText}
                  onChange={e => setOtherText(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') submitOther(); clearOnEscape(e) }}
                  placeholder={current.choices.length > 0 ? 'Or type your own answer...' : 'Type your answer...'}
                />
                <button type="button" className={styles.otherSend} onClick={submitOther} disabled={!otherText.trim()}>
                  Send
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
