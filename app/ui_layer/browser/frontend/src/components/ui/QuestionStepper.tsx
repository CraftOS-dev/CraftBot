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

export function QuestionStepper({ messageId, sessionId, questions, answers, declined, onSubmit }: QuestionStepperProps) {
  const resolved = !!answers || !!declined
  const [step, setStep] = useState(0)
  const [localAnswers, setLocalAnswers] = useState<Record<string, string>>({})
  const [otherText, setOtherText] = useState('')
  const [checked, setChecked] = useState<Set<string>>(new Set())

  // Esc abandons the whole batch — scoped to this stepper via bubbling from
  // its own focused controls, not a window-wide listener (which would decline
  // whichever batch happened to be mounted regardless of what's focused).
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

  // Navigating to a question rehydrates its previous answer (if any) instead
  // of blindly clearing it — otherwise revisiting an already-answered
  // question shows it as unanswered, and re-confirming would silently
  // overwrite the earlier answer with an empty/partial one.
  const goToStep = (i: number) => {
    setStep(i)
    const q = questions[i]
    if (!q) return // i === questions.length: moving into the review step, nothing to rehydrate
    const existing = localAnswers[q.id]
    if (existing === undefined) {
      setOtherText('')
      setChecked(new Set())
      return
    }
    if (q.multiSelect) {
      const knownValues = new Set(q.choices.map(c => c.value))
      const parts = existing.split(', ')
      setChecked(new Set(parts.filter(p => knownValues.has(p))))
      setOtherText(parts.filter(p => !knownValues.has(p)).join(', '))
    } else {
      const isKnownChoice = q.choices.some(c => c.value === existing)
      setChecked(new Set())
      setOtherText(isKnownChoice ? '' : existing)
    }
  }

  const answerCurrent = (value: string) => {
    const next = { ...localAnswers, [current.id]: value }
    setLocalAnswers(next)
    if (single) {
      onSubmit(messageId, sessionId, next, false)
    } else {
      goToStep(step + 1)
    }
  }

  const toggleChecked = (value: string) => {
    const next = new Set(checked)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    setChecked(next)
  }

  const confirmMultiSelect = () => {
    const values = [...checked, ...(otherText.trim() ? [otherText.trim()] : [])]
    if (values.length === 0) return
    answerCurrent(values.join(', '))
  }

  const submitOther = () => {
    if (!otherText.trim()) return
    answerCurrent(otherText.trim())
  }

  return (
    <div className={styles.stepper} onKeyDown={handleKeyDown}>
      {!single && (
        <div className={styles.nav}>
          {step > 0 && (
            <button type="button" className={styles.backButton} onClick={() => goToStep(step - 1)}>
              ‹ Back
            </button>
          )}
          {questions.map((q, i) => (
            <button
              key={q.id}
              type="button"
              className={`${styles.navDot} ${i === step ? styles.navDotActive : ''} ${localAnswers[q.id] ? styles.navDotDone : ''}`}
              onClick={() => goToStep(i)}
              disabled={i > step && localAnswers[q.id] === undefined}
              aria-label={`Question ${i + 1} of ${questions.length}`}
            >
              {i + 1}
            </button>
          ))}
          <span className={styles.navReview}>{isReview ? 'Review' : `${step + 1} of ${questions.length}`}</span>
        </div>
      )}

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
              <span className={styles.resolvedAnswer}>{localAnswers[q.id]}</span>
            </button>
          ))}
          <button
            type="button"
            className={styles.submitButton}
            onClick={() => onSubmit(messageId, sessionId, localAnswers, false)}
          >
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
                  onKeyDown={e => { if (e.key === 'Enter') confirmMultiSelect() }}
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
              {current.choices.map((c, i) => (
                <button
                  key={c.value}
                  type="button"
                  role="radio"
                  aria-checked="false"
                  className={styles.choiceButton}
                  onClick={() => answerCurrent(c.value)}
                >
                  <span className={styles.choiceIndex}>{i + 1}</span>
                  {c.label}
                </button>
              ))}
              <div className={styles.otherRow}>
                <input
                  type="text"
                  className={styles.otherInput}
                  value={otherText}
                  onChange={e => setOtherText(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') submitOther() }}
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
