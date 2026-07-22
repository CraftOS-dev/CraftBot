import React, { memo, useState, useRef, useEffect } from 'react'
import { Copy, Check } from 'lucide-react'
import { MarkdownContent, AttachmentDisplay, AttachmentPreviewModal, IconButton } from '../../components/ui'
import type { Attachment, ChatMessage as ChatMessageType } from '../../types'
import { useWebSocket } from '../../contexts/WebSocketContext'
import styles from './ChatPage.module.css'

interface ChatMessageProps {
  message: ChatMessageType
  onOpenFile: (path: string) => void
  onOpenFolder: (path: string) => void
  onOptionClick?: (value: string, messageId: string) => void
}

export const ChatMessageItem = memo(function ChatMessageItem({
  message,
  onOpenFile,
  onOpenFolder,
  onOptionClick,
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

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation()
    navigator.clipboard.writeText(message.content).catch(() => {})
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
        <div className={styles.messageContent}>
          <MarkdownContent content={message.content} />
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
          left for user). */}
      {isHovered && canCopy && (
        <div className={styles.messageActionsOutside}>
          <IconButton
            icon={copied ? <Check size={14} /> : <Copy size={14} />}
            variant="ghost"
            size="sm"
            onClick={handleCopy}
            tooltip={copied ? 'Copied!' : 'Copy message'}
          />
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
