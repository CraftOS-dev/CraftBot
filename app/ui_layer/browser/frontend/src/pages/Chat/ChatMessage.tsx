import React, { memo, useState, useRef, useEffect, useMemo } from 'react'
import { Copy, Check, Reply } from 'lucide-react'
import { MarkdownContent, AttachmentDisplay, AttachmentPreviewModal, IconButton } from '../../components/ui'
import type { Attachment, ChatMessage as ChatMessageType } from '../../types'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { getErrorCategoryStyle } from '../../constants/errorCategories'
import styles from './ChatPage.module.css'

interface ChatMessageProps {
  message: ChatMessageType
  onOpenFile: (path: string) => void
  onOpenFolder: (path: string) => void
  onOptionClick?: (value: string, messageId: string) => void
  /** Hover action on agent bubbles: quote this message in the next send. */
  onReply?: (displayName: string, originalContent: string) => void
}

// Reply context marker appended by the backend to a replying user
// message. The user bubble strips it and renders the quoted agent
// message as a callout instead.
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
  onOptionClick,
  onReply,
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

  const canCopy = message.style === 'user' || message.style === 'agent'

  // Reply is offered on agent bubbles, except ones presenting options
  // that require an explicit choice via the option buttons.
  const hasPendingOptions = !!(message.options && message.options.length > 0)
  const canReply = message.style === 'agent' && !!onReply && !hasPendingOptions

  // User messages that replied to an agent bubble carry the quoted
  // original after REPLY_MARKER — split it out for the callout.
  const { userMessage, replyContext } = useMemo(() => {
    if (message.style === 'user') {
      return parseReplyContext(message.content)
    }
    return { userMessage: message.content, replyContext: null }
  }, [message.content, message.style])

  const handleReply = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!canReply) return
    const displayName = message.content.length > 50
      ? message.content.slice(0, 50) + '...'
      : message.content
    onReply?.(displayName, message.content)
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
  const errorStyle = message.style === 'error' ? getErrorCategoryStyle(message.errorCategory) : null
  const ErrorIcon = errorStyle?.icon

  const bubbleContainer = (
    <div className={styles.messageBubbleContainer}>
      <div className={`${styles.message} ${styles[message.style]} ${message.pending ? styles.pending : ''}`}>
        <div className={styles.messageHeader}>
          <span className={styles.sender}>
            {ErrorIcon && (
              <ErrorIcon
                size={14}
                className={styles.errorCategoryIcon}
                style={{ color: `var(${errorStyle.colorVar})` }}
              />
            )}
            {message.sender}
          </span>
          <span className={styles.timestamp}>
            {new Date(message.timestamp * 1000).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}
          </span>
        </div>
        {/* Reply context callout — the quoted agent message, shown above
            the user's text when this message replied to a bubble. */}
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
                  if (opt.url) {
                    window.open(opt.url, '_blank', 'noopener')
                  }
                  onOptionClick?.(opt.value, message.messageId)
                }}
                disabled={!!selected}
              >
                <span className={styles.optionIndex}>{index + 1}</span>
                {opt.label}
              </button>
            ))}
          </div>
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
  && prev.message.content === next.message.content
)
