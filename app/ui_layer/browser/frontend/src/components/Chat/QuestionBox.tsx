import { useState } from 'react'
import { HelpCircle, X, Send } from 'lucide-react'
import { MarkdownContent } from '../ui'
import type { ChatMessage } from '../../types'
import styles from './QuestionBox.module.css'

interface QuestionBoxProps {
  /** The oldest unanswered question message of this session. */
  question: ChatMessage
  /** Total pending questions (this one included) — shows "1 of N" when > 1. */
  queueTotal: number
  /** Answer with a suggestion chip or typed free text. */
  onAnswer: (value: string) => void
  /** Close the question unanswered (the agent proceeds on its own judgment). */
  onDismiss: () => void
}

/**
 * Pinned agent question above the chat composer.
 *
 * Stays fixed while the timeline scrolls, so a question survives the agent
 * continuing to work in the background. Only ONE question shows at a time
 * (oldest first); the rest of the queue is communicated via the counter and
 * surfaces here as each one is resolved. Mount with key={question.messageId}
 * so the free-text draft resets when the queue advances.
 */
export function QuestionBox({ question, queueTotal, onAnswer, onDismiss }: QuestionBoxProps) {
  const [text, setText] = useState('')
  // One-shot guard against double-submit between click and the store update
  // that unmounts the box (mirrors the bubble chips' dispatch lock).
  const [submitted, setSubmitted] = useState(false)
  const allowFreeText = question.allowFreeText !== false

  const submit = (value: string) => {
    const trimmed = value.trim()
    if (!trimmed || submitted) return
    setSubmitted(true)
    onAnswer(trimmed)
  }

  return (
    <div className={styles.box} role="region" aria-label="Question from agent">
      <div className={styles.header}>
        <HelpCircle size={14} className={styles.icon} />
        <span className={styles.title}>{question.sender} is asking</span>
        {queueTotal > 1 && (
          <span className={styles.queueBadge}>1 of {queueTotal}</span>
        )}
        <button
          type="button"
          className={styles.dismiss}
          onClick={() => { if (!submitted) { setSubmitted(true); onDismiss() } }}
          title="Dismiss — the agent will proceed without an answer"
          aria-label="Dismiss question"
        >
          <X size={14} />
        </button>
      </div>

      <div className={styles.questionText}>
        <MarkdownContent content={question.content} />
      </div>

      {question.options && question.options.length > 0 && (
        <div className={styles.chips}>
          {question.options.map(opt => (
            <button
              key={opt.value}
              type="button"
              className={styles.chip}
              onClick={() => submit(opt.value)}
              disabled={submitted}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}

      {allowFreeText && (
        <div className={styles.freeTextRow}>
          <input
            type="text"
            className={styles.freeTextInput}
            placeholder="Or type your own answer..."
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                e.preventDefault()
                submit(text)
              }
            }}
            disabled={submitted}
          />
          <button
            type="button"
            className={styles.freeTextSend}
            onClick={() => submit(text)}
            disabled={submitted || !text.trim()}
            title="Send answer"
            aria-label="Send answer"
          >
            <Send size={14} />
          </button>
        </div>
      )}
    </div>
  )
}
