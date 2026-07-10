import React, { memo, useState, useMemo, useRef, useEffect } from 'react'
import { Reply, Copy, Check } from 'lucide-react'
import { MarkdownContent, AttachmentDisplay, AttachmentPreviewModal, IconButton, QuestionStepper } from '../../components/ui'
import type { Attachment, ChatMessage as ChatMessageType } from '../../types'
import { useWebSocket } from '../../contexts/WebSocketContext'
import styles from './ChatPage.module.css'

interface ChatMessageProps {
  message: ChatMessageType
  onOpenFile: (path: string) => void
  onOpenFolder: (path: string) => void
  onReply?: (
    sessionId: string | undefined,
    displayName: string,
    fullContent: string
  ) => void
  onOptionClick?: (value: string, sessionId?: string, messageId?: string) => void
  onQuestionAnswers?: (
    messageId: string,
    sessionId: string | undefined,
    answers: Record<string, string> | undefined,
    declined: boolean
  ) => void
}

// Parse reply context from message content
const REPLY_MARKER = '[REPLYING TO PREVIOUS AGENT MESSAGE]:'

function parseReplyContext(content: string): { userMessage: string; replyContext: string | null } {
  const markerIndex = content.indexOf(REPLY_MARKER)
  if (markerIndex === -1) {
    return { userMessage: content, replyContext: null }
  }
  const userMessage = content.slice(0, markerIndex).trim()
  const replyContext = content.slice(markerIndex + REPLY_MARKER.length).trim()
  return { userMessage, replyContext }
}

export const ChatMessageItem = memo(function ChatMessageItem({
  message,
  onOpenFile,
  onOpenFolder,
  onReply,
  onOptionClick,
  onQuestionAnswers,
}: ChatMessageProps) {
  const [isHovered, setIsHovered] = useState(false)
  const [copied, setCopied] = useState(false)
  const [previewAttachment, setPreviewAttachment] = useState<Attachment | null>(null)
  // The selection is owned by the message prop (the single source of truth).
  // The ref is a one-shot guard to suppress double-dispatch between the click
  // and the next render cycle, and is re-synced whenever the prop changes so
  // it can't be out of step after virtualizer remounts or WS state replays.
  const selected = message.optionSelected ?? null
  const dispatchLockRef = useRef(!!selected)
  useEffect(() => {
    dispatchLockRef.current = !!selected
  }, [selected])
  const { agentProfilePictureUrl } = useWebSocket()

  // Show reply for agent messages, except those presenting options/questions
  // that require the user to make an explicit choice via the buttons.
  const hasPendingOptions = !!(message.options && message.options.length > 0)
  const hasPendingQuestions = !!(
    message.questions && message.questions.length > 0
    && !message.questionAnswers && !message.questionsDeclined
  )
  const canReply = message.style === 'agent' && onReply && !hasPendingOptions && !hasPendingQuestions
  const canCopy = message.style === 'user' || message.style === 'agent'

  // Parse reply context for user messages
  const { userMessage, replyContext } = useMemo(() => {
    if (message.style === 'user') {
      return parseReplyContext(message.content)
    }
    return { userMessage: message.content, replyContext: null }
  }, [message.content, message.style])

  const handleReply = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (canReply) {
      // Truncate content for display preview
      const displayName = message.content.length > 50
        ? message.content.slice(0, 50) + '...'
        : message.content
      onReply(message.taskSessionId, displayName, message.content)
    }
  }

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation()
    // For user messages strip the [REPLYING TO ...] marker so the
    // clipboard only contains what the user actually typed.
    const text = message.style === 'user' ? userMessage : message.content
    navigator.clipboard.writeText(text).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const isAgent = message.style === 'agent'

  const bubbleContainer = (
    <div className={styles.messageBubbleContainer}>
      <div className={`${styles.message} ${styles[message.style]} ${message.pending ? styles.pending : ''}`}>
        <div className={styles.messageHeader}>
          <span className={styles.sender}>{message.sender}</span>
          <span className={styles.timestamp}>
            {new Date(message.timestamp * 1000).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}
          </span>
        </div>
        {/* Reply context callout - shown above user message when replying */}
        {replyContext && (
          <div className={styles.replyContextCallout}>
            <MarkdownContent content={replyContext} />
          </div>
        )}
        <div className={styles.messageContent}>
          <MarkdownContent content={userMessage} />
        </div>
        {message.options && message.options.length > 0 && (
          <div className={styles.messageOptions}>
            <span className={styles.optionsPrompt}>Please select a response to continue:</span>
            {message.options.map((opt, index) => (
              <button
                key={opt.value}
                className={`${styles.optionButton} ${selected === opt.value ? styles['optionButton--selected'] : ''} ${selected && selected !== opt.value ? styles['optionButton--disabled'] : ''}`}
                onClick={() => {
                  if (dispatchLockRef.current) return
                  dispatchLockRef.current = true
                  onOptionClick?.(opt.value, message.taskSessionId, message.messageId)
                }}
                disabled={!!selected}
              >
                <span className={styles.optionIndex}>{index + 1}</span>
                {opt.label}
              </button>
            ))}
          </div>
        )}
        {message.questions && message.questions.length > 0 && (
          <QuestionStepper
            messageId={message.messageId}
            sessionId={message.taskSessionId}
            questions={message.questions}
            answers={message.questionAnswers}
            declined={message.questionsDeclined}
            onSubmit={(msgId, sid, ans, dec) => onQuestionAnswers?.(msgId, sid, ans, dec)}
          />
        )}
      </div>
      {message.attachments && message.attachments.length > 0 && (
        <div className={styles.messageAttachments}>
          <AttachmentDisplay
            attachments={message.attachments}
            onOpenFile={onOpenFile}
            onOpenFolder={onOpenFolder}
            onPreview={setPreviewAttachment}
          />
        </div>
      )}
      {/* Action buttons - positioned outside the bubble (right for agent,
          left for user). Stacked vertically when both reply + copy show. */}
      {isHovered && (canReply || canCopy) && (
        <div className={styles.messageActionsOutside}>
          {canReply && (
            <IconButton
              icon={<Reply size={14} />}
              variant="ghost"
              size="sm"
              onClick={handleReply}
              tooltip="Reply to this message"
            />
          )}
          {canCopy && (
            <IconButton
              icon={copied ? <Check size={14} /> : <Copy size={14} />}
              variant="ghost"
              size="sm"
              onClick={handleCopy}
              tooltip={copied ? 'Copied!' : 'Copy message'}
            />
          )}
        </div>
      )}
    </div>
  )

  return (
    <div
      className={`${styles.messageWrapper} ${styles[message.style + 'Wrapper']}`}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {isAgent ? (
        <div className={styles.agentContentRow}>
          <img
            className={styles.agentAvatar}
            src={agentProfilePictureUrl}
            alt=""
          />
          {bubbleContainer}
        </div>
      ) : (
        bubbleContainer
      )}
      <AttachmentPreviewModal
        isOpen={previewAttachment !== null}
        attachment={previewAttachment}
        onClose={() => setPreviewAttachment(null)}
      />
    </div>
  )
}, (prev, next) =>
  prev.message.messageId === next.message.messageId
  && prev.message.optionSelected === next.message.optionSelected
  && prev.message.questionAnswers === next.message.questionAnswers
  && prev.message.questionsDeclined === next.message.questionsDeclined
  && prev.message.content === next.message.content
)
