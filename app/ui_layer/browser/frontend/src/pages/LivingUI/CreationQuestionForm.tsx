import { useMemo, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { ArrowRight, MessagesSquare } from 'lucide-react'
import styles from './CreationQuestionForm.module.css'

interface Props {
  projectName: string
  message: string
  onAnswer?: (text: string) => void
}

interface ParsedQuestions {
  preamble: string
  items: { label: string; text: string }[]
  trailer: string
}

/**
 * Split an agent question message into its parts. A numbered list ("1. … 2. …")
 * becomes one field per question; preamble/trailer are the framing text around
 * it. A message with no numbered list parses to zero items (single-box mode).
 */
function parseQuestions(message: string): ParsedQuestions {
  const preamble: string[] = []
  const items: { label: string; text: string }[] = []
  const trailer: string[] = []
  let current: { label: string; text: string } | null = null
  let seen = false
  for (const raw of message.split('\n')) {
    const m = raw.match(/^\s*(\d+)[.)]\s+(.*)$/)
    if (m) {
      seen = true
      current = { label: m[1], text: m[2].trim() }
      items.push(current)
    } else if (!seen) {
      if (raw.trim()) preamble.push(raw.trim())
    } else if (raw.trim() === '') {
      current = null // a blank line ends the current question; rest is trailer
    } else if (current) {
      current.text += ' ' + raw.trim() // wrapped continuation of a question
    } else {
      trailer.push(raw.trim())
    }
  }
  return { preamble: preamble.join(' '), items, trailer: trailer.join(' ') }
}

/**
 * Form shown on the Living UI creation screen when the agent asks a question
 * (a send_message with wait_for_user_reply). Mirrors the chat question so the
 * user can answer with the chat panel closed. The answer is sent back through
 * the normal reply path, resuming the task — so answering here or in chat are
 * equivalent (whichever lands first wins).
 */
export function CreationQuestionForm({ projectName, message, onAnswer }: Props) {
  const parsed = useMemo(() => parseQuestions(message), [message])
  const multi = parsed.items.length > 0
  const [single, setSingle] = useState('')
  const [answers, setAnswers] = useState<string[]>(() => parsed.items.map(() => ''))

  const canSend = multi ? answers.some(a => a.trim()) : single.trim().length > 0

  const submit = () => {
    if (multi) {
      // Recombine into the numbered reply the agent expects (e.g. "1. …\n2. …").
      const parts = parsed.items
        .map((q, i) => ({ label: q.label, a: answers[i].trim() }))
        .filter(x => x.a)
      if (!parts.length) return
      onAnswer?.(parts.map(x => `${x.label}. ${x.a}`).join('\n'))
    } else {
      const t = single.trim()
      if (!t) return
      onAnswer?.(t)
    }
  }

  const onKey = (e: ReactKeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className={styles.surface}>
      <div className={styles.questionWrap}>
        <div className={styles.questionCard}>
          <div className={styles.brandRow}>
            <MessagesSquare size={18} className={styles.brandIcon} />
            <span className={styles.buildingTitle}>Building {projectName}</span>
          </div>

          {multi ? (
            <>
              {parsed.preamble && <p className={styles.questionPrompt}>{parsed.preamble}</p>}
              <div className={styles.questionList}>
                {parsed.items.map((q, i) => (
                  <div key={i} className={styles.questionField}>
                    <label className={styles.questionLabel}>
                      <span className={styles.questionNum}>{q.label}</span>
                      <span>{q.text}</span>
                    </label>
                    <textarea
                      className={styles.questionInput}
                      value={answers[i]}
                      onChange={e =>
                        setAnswers(prev => prev.map((a, j) => (j === i ? e.target.value : a)))
                      }
                      onKeyDown={onKey}
                      placeholder="Your answer…"
                      rows={2}
                      autoFocus={i === 0}
                    />
                  </div>
                ))}
              </div>
              {parsed.trailer && <p className={styles.questionTrailer}>{parsed.trailer}</p>}
            </>
          ) : (
            <>
              <p className={styles.questionPrompt}>{message}</p>
              <textarea
                className={styles.questionInput}
                value={single}
                onChange={e => setSingle(e.target.value)}
                onKeyDown={onKey}
                placeholder="Type your answer…"
                rows={4}
                autoFocus
              />
            </>
          )}

          <div className={styles.questionActions}>
            <span className={styles.questionHint}>Answer here or in chat · ⌘/Ctrl + Enter</span>
            <button className={styles.questionSubmit} onClick={submit} disabled={!canSend}>
              Send <ArrowRight size={14} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
