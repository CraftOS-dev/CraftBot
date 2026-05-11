import React, { memo, useState, useMemo, useRef, useEffect } from 'react'
import { Reply } from 'lucide-react'
import { MarkdownContent, AttachmentDisplay, IconButton } from '../../components/ui'
import type { ChatMessage as ChatMessageType } from '../../types'
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
}: ChatMessageProps) {
  const [isHovered, setIsHovered] = useState(false)
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

  // Show reply for agent messages, except those presenting options that
  // require the user to make an explicit choice via the option buttons.
  const hasPendingOptions = !!(message.options && message.options.length > 0)
  const canReply = message.style === 'agent' && onReply && !hasPendingOptions

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

  const isAgent = message.style === 'agent'

  const bubbleContainer = (
    <div className={styles.messageBubbleContainer}>
      <div className={`${styles.message} ${styles[message.style]} ${message.pending ? styles.pending : ''}`}>
        <div className={styles.messageHeader}>
          <span className={styles.sender}>{message.sender}</span>
          <span className={styles.timestamp}>
            {new Date(message.timestamp * 1000).toLocaleTimeString()}
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
      </div>
      {message.attachments && message.attachments.length > 0 && (
        <div className={styles.messageAttachments}>
          <AttachmentDisplay
            attachments={message.attachments}
            onOpenFile={onOpenFile}
            onOpenFolder={onOpenFolder}
          />
        </div>
      )}
      {/* Reply button - positioned outside the bubble at top-right */}
      {canReply && isHovered && (
        <IconButton
          icon={<Reply size={14} />}
          variant="ghost"
          size="sm"
          onClick={handleReply}
          tooltip="Reply to this message"
          className={styles.replyButtonOutside}
        />
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
    </div>
  )
}, (prev, next) =>
  prev.message.messageId === next.message.messageId
  && prev.message.optionSelected === next.message.optionSelected
  && prev.message.content === next.message.content
)
