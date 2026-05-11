import React, { useState, useRef, useEffect, useLayoutEffect, KeyboardEvent, useCallback, ChangeEvent, useMemo } from 'react'
import ReactDOM from 'react-dom'
import { Send, Paperclip, X, Loader2, File, AlertCircle, Reply, Mic, MicOff } from 'lucide-react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { useToast } from '../../contexts/ToastContext'
import { Button, IconButton, StatusIndicator } from '../ui'
import { useDerivedAgentStatus } from '../../hooks'
import { ChatMessageItem } from '../../pages/Chat/ChatMessage'
import styles from './Chat.module.css'

// Pending attachment type
interface PendingAttachment {
  name: string
  type: string
  size: number
  content: string  // base64
}

interface ChatProps {
  /** Optional Living UI project ID — auto-included in messages sent from this chat */
  livingUIId?: string
  /** Optional placeholder text for the input */
  placeholder?: string
  /** Optional empty state message */
  emptyMessage?: string
}

const MIC_LANGUAGES = [
  { code: 'en-US', label: 'EN', full: 'English' },
  { code: 'ja-JP', label: 'JA', full: '日本語' },
  { code: 'zh-CN', label: 'ZH', full: '中文 (简体)' },
  { code: 'zh-TW', label: 'ZH-TW', full: '中文 (繁體)' },
  { code: 'ko-KR', label: 'KO', full: '한국어' },
  { code: 'ar-SA', label: 'AR', full: 'العربية' },
  { code: 'es-ES', label: 'ES', full: 'Español' },
  { code: 'fr-FR', label: 'FR', full: 'Français' },
  { code: 'de-DE', label: 'DE', full: 'Deutsch' },
  { code: 'pt-BR', label: 'PT', full: 'Português' },
  { code: 'hi-IN', label: 'HI', full: 'हिन्दी' },
  { code: 'ru-RU', label: 'RU', full: 'Русский' },
  { code: 'it-IT', label: 'IT', full: 'Italiano' },
]

// Attachment limits
const MAX_ATTACHMENT_COUNT = 10
const MAX_TOTAL_SIZE_BYTES = 70 * 1024 * 1024  // 70MB

const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

export function Chat({ livingUIId, placeholder, emptyMessage }: ChatProps) {
  const {
    messages,
    actions,
    connected,
    sendMessage,
    sendCommand,
    sendOptionClick,
    openFile,
    openFolder,
    lastSeenMessageId,
    markMessagesAsSeen,
    replyTarget,
    setReplyTarget,
    clearReplyTarget,
    loadOlderMessages,
    hasMoreMessages,
    loadingOlderMessages,
  } = useWebSocket()

  const status = useDerivedAgentStatus({ actions, messages, connected })
  const { showToast } = useToast()

  // Render messages in server-canonical timestamp order so that the order
  // users see live matches the order they see after a refresh (where history
  // is loaded sorted by timestamp). Pending bubbles use client time, so they
  // land at the end; when the server echo arrives with its real timestamp,
  // the item may shift a position or two — a CSS transform transition on the
  // virtualized row animates that shift as a smooth slide.
  const orderedMessages = useMemo(() => {
    return messages.slice().sort((a, b) => a.timestamp - b.timestamp)
  }, [messages])

  const [input, setInput] = useState('')
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([])
  const [attachmentError, setAttachmentError] = useState<string | null>(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const [previewAttachment, setPreviewAttachment] = useState<PendingAttachment | null>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Voice input state
  const [isListening, setIsListening] = useState(false)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null)
  const [micLang, setMicLang] = useState(() => {
    const browserLang = navigator.language || 'en-US'
    return MIC_LANGUAGES.some(l => l.code === browserLang) ? browserLang : 'en-US'
  })
  const [langOpen, setLangOpen] = useState(false)
  const langDropdownRef = useRef<HTMLDivElement>(null)

  // Input history (terminal-style up/down arrow navigation)
  const inputHistoryRef = useRef<string[]>([])
  const historyIndexRef = useRef(-1)
  const parentRef = useRef<HTMLDivElement>(null)
  const wasNearBottomRef = useRef(true)
  const prevMessageCountRef = useRef(0)
  const hasInitialScrolled = useRef(false)

  const attachmentValidation = useMemo(() => {
    const totalSize = pendingAttachments.reduce((sum, att) => sum + att.size, 0)
    const count = pendingAttachments.length
    if (count > MAX_ATTACHMENT_COUNT) {
      return { valid: false, error: `Maximum ${MAX_ATTACHMENT_COUNT} files allowed. You have ${count} files.` }
    }
    if (totalSize > MAX_TOTAL_SIZE_BYTES) {
      return { valid: false, error: `Total size (${formatFileSize(totalSize)}) exceeds 70MB limit.` }
    }
    return { valid: true, error: null }
  }, [pendingAttachments])

  const virtualizer = useVirtualizer({
    count: orderedMessages.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 100,
    overscan: 5,
  })

  const getFirstUnreadIndex = useCallback(() => {
    if (!lastSeenMessageId) return -1
    const lastSeenIdx = orderedMessages.findIndex(m => m.messageId === lastSeenMessageId)
    if (lastSeenIdx === -1) return 0
    if (lastSeenIdx === orderedMessages.length - 1) return -1
    return lastSeenIdx + 1
  }, [orderedMessages, lastSeenMessageId])

  const isNearBottom = useCallback(() => {
    const container = parentRef.current
    if (!container) return true
    return container.scrollHeight - container.scrollTop - container.clientHeight < 100
  }, [])

  // Close language dropdown when clicking outside
  useEffect(() => {
    if (!langOpen) return
    const handler = (e: MouseEvent) => {
      if (langDropdownRef.current && !langDropdownRef.current.contains(e.target as Node)) {
        setLangOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [langOpen])

  // Close preview on Escape
  useEffect(() => {
    if (!previewAttachment) return
    const handler = (e: globalThis.KeyboardEvent) => { if (e.key === 'Escape') setPreviewAttachment(null) }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [previewAttachment])

  // Track scroll position + load older messages on scroll-to-top
  useEffect(() => {
    const container = parentRef.current
    if (!container) return
    const handleScroll = () => {
      wasNearBottomRef.current = isNearBottom()
      if (container.scrollTop < 100 && hasMoreMessages && !loadingOlderMessages) {
        loadOlderMessages()
      }
    }
    container.addEventListener('scroll', handleScroll)
    return () => container.removeEventListener('scroll', handleScroll)
  }, [isNearBottom, hasMoreMessages, loadingOlderMessages, loadOlderMessages])

  // Scroll to unread on mount, auto-scroll on new messages if near bottom
  useEffect(() => {
    if (orderedMessages.length === 0) return

    const isNewMessage = orderedMessages.length > prevMessageCountRef.current
    prevMessageCountRef.current = orderedMessages.length

    if (!hasInitialScrolled.current) {
      hasInitialScrolled.current = true
      const firstUnreadIdx = getFirstUnreadIndex()
      setTimeout(() => {
        if (firstUnreadIdx !== -1) {
          virtualizer.scrollToIndex(firstUnreadIdx, { align: 'start', behavior: 'auto' })
        } else {
          virtualizer.scrollToIndex(orderedMessages.length - 1, { align: 'end', behavior: 'auto' })
        }
        markMessagesAsSeen()
      }, 50)
    } else if (isNewMessage && wasNearBottomRef.current) {
      virtualizer.scrollToIndex(orderedMessages.length - 1, { align: 'end', behavior: 'smooth' })
      markMessagesAsSeen()
    }
  }, [orderedMessages.length, virtualizer, getFirstUnreadIndex, markMessagesAsSeen])

  const adjustTextareaHeight = useCallback(() => {
    const textarea = inputRef.current
    if (!textarea) return
    // When the textarea is empty, let CSS min-height control the height.
    // Reading scrollHeight on an empty textarea in a narrow container can
    // include wrapped placeholder text, which would balloon the input to
    // multiple visual rows.
    if (!textarea.value) {
      textarea.style.height = ''
      return
    }
    textarea.style.height = 'auto'
    textarea.style.height = `${textarea.scrollHeight}px`
  }, [])

  useLayoutEffect(() => {
    adjustTextareaHeight()
  }, [input, adjustTextareaHeight])

  const handleChatReply = useCallback((
    sessionId: string | undefined,
    displayName: string,
    fullContent: string
  ) => {
    setReplyTarget({
      type: 'chat',
      sessionId,
      displayName,
      originalContent: fullContent,
    })
    inputRef.current?.focus()
  }, [setReplyTarget])

  const toggleListening = useCallback(() => {
    if (isListening) {
      recognitionRef.current?.stop()
      setIsListening(false)
      return
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const w = window as any
    const SpeechRecognitionAPI = w.SpeechRecognition || w.webkitSpeechRecognition

    if (!SpeechRecognitionAPI) {
      alert('Speech recognition is not supported in this browser.')
      return
    }

    const recognition = new SpeechRecognitionAPI()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = micLang

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let finalTranscript = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) {
          finalTranscript += event.results[i][0].transcript
        }
      }
      if (finalTranscript) {
        setInput(prev => prev + (prev.endsWith(' ') || prev === '' ? '' : ' ') + finalTranscript)
        if (inputRef.current) {
          inputRef.current.style.height = 'auto'
          inputRef.current.style.height = inputRef.current.scrollHeight + 'px'
        }
      }
    }

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      setIsListening(false)
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
        alert('Microphone access denied. Please allow microphone permission in your browser settings.')
      }
    }
    recognition.onend = () => setIsListening(false)

    recognitionRef.current = recognition
    recognition.start()
    setIsListening(true)
    inputRef.current?.focus()
  }, [isListening, micLang])

  // Stop mic if component unmounts while listening
  useEffect(() => {
    return () => { recognitionRef.current?.abort() }
  }, [])

  const handleSend = () => {
    if (!attachmentValidation.valid) return
    if (input.trim() || pendingAttachments.length > 0) {
      // Save to input history
      if (input.trim()) {
        inputHistoryRef.current.push(input.trim())
      }
      historyIndexRef.current = -1

      const replyContext = replyTarget ? {
        sessionId: replyTarget.sessionId,
        originalMessage: replyTarget.originalContent,
      } : undefined

      // Stop mic if still listening when message is sent
      if (isListening) {
        recognitionRef.current?.stop()
        setIsListening(false)
      }

      const trimmed = input.trim()
      // Slash commands route through the dedicated command channel so no
      // optimistic user bubble is inserted — the backend's CommandExecutor
      // responds with system/error messages rather than echoing user input.
      // Attachments + slash command falls through to chat (commands don't
      // accept attachments), which preserves the existing behavior for that
      // edge case.
      const isSlashCommand = trimmed.startsWith('/') && pendingAttachments.length === 0
      if (isSlashCommand) {
        sendCommand(trimmed)
      } else {
        sendMessage(
          trimmed,
          pendingAttachments.length > 0 ? pendingAttachments : undefined,
          replyContext,
          livingUIId
        )
      }
      if (!connected) {
        showToast('info', 'Reconnecting — your message will send when the connection is restored.')
      }
      setInput('')
      setPendingAttachments([])
      setAttachmentError(null)
      clearReplyTarget()
      if (inputRef.current) {
        inputRef.current.style.height = 'auto'
      }
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      const history = inputHistoryRef.current
      if (history.length === 0) return
      if (historyIndexRef.current === -1 && input.trim() !== '') return

      if (e.key === 'ArrowUp') {
        e.preventDefault()
        if (historyIndexRef.current === -1) {
          historyIndexRef.current = history.length - 1
        } else if (historyIndexRef.current > 0) {
          historyIndexRef.current--
        }
        setInput(history[historyIndexRef.current])
      } else if (e.key === 'ArrowDown') {
        e.preventDefault()
        if (historyIndexRef.current === -1) return
        if (historyIndexRef.current < history.length - 1) {
          historyIndexRef.current++
          setInput(history[historyIndexRef.current])
        } else {
          historyIndexRef.current = -1
          setInput('')
        }
      }
    }
  }

  const handleAttachClick = () => {
    fileInputRef.current?.click()
  }

  const processFiles = async (files: globalThis.File[]) => {
    if (files.length === 0) return

    const totalFileCount = pendingAttachments.length + files.length
    if (totalFileCount > MAX_ATTACHMENT_COUNT) {
      setAttachmentError(`Maximum ${MAX_ATTACHMENT_COUNT} files allowed.`)
      return
    }

    const newAttachments: PendingAttachment[] = []
    let newTotalSize = pendingAttachments.reduce((sum, att) => sum + att.size, 0)

    for (const file of files) {
      if (file.size > MAX_TOTAL_SIZE_BYTES) {
        setAttachmentError(`File "${file.name}" (${formatFileSize(file.size)}) exceeds the 70MB limit.`)
        return
      }
      if (newTotalSize + file.size > MAX_TOTAL_SIZE_BYTES) {
        setAttachmentError(`Adding "${file.name}" would exceed the 70MB total size limit.`)
        return
      }
      try {
        const content = await readFileAsBase64(file)
        newAttachments.push({ name: file.name, type: file.type || 'application/octet-stream', size: file.size, content })
        newTotalSize += file.size
      } catch {
        setAttachmentError(`Failed to read file "${file.name}".`)
        return
      }
    }

    setAttachmentError(null)
    setPendingAttachments(prev => [...prev, ...newAttachments])
  }

  const handleFileSelect = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return
    await processFiles(Array.from(files))
    e.target.value = ''
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
      setIsDragOver(false)
    }
  }

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const files = Array.from(e.dataTransfer.files)
    await processFiles(files)
  }

  const handlePaste = async (e: React.ClipboardEvent) => {
    const files = Array.from(e.clipboardData.files)
    if (files.length === 0) return
    e.preventDefault()
    await processFiles(files)
  }

  const removeAttachment = (index: number) => {
    setPendingAttachments(prev => prev.filter((_, i) => i !== index))
    setAttachmentError(null)
  }

  const openPreview = (att: PendingAttachment) => {
    setPreviewAttachment(att)
  }

  const readFileAsBase64 = (file: globalThis.File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => {
        const result = reader.result as string
        resolve(result.split(',')[1])
      }
      reader.onerror = reject
      reader.readAsDataURL(file)
    })
  }

  const pdfBlobUrl = useMemo(() => {
    if (!previewAttachment) return null
    const isPdf = previewAttachment.type === 'application/pdf' || previewAttachment.name.toLowerCase().endsWith('.pdf')
    if (!isPdf) return null
    try {
      const bytes = Uint8Array.from(atob(previewAttachment.content), c => c.charCodeAt(0))
      const blob = new Blob([bytes], { type: 'application/pdf' })
      return URL.createObjectURL(blob)
    } catch { return null }
  }, [previewAttachment])

  useEffect(() => {
    return () => { if (pdfBlobUrl) URL.revokeObjectURL(pdfBlobUrl) }
  }, [pdfBlobUrl])

  return (
    <div className={styles.chat}>
      <div className={styles.messagesContainer} ref={parentRef}>
        {orderedMessages.length === 0 ? (
          <div className={styles.emptyState}>
            <div className={styles.emptyIcon}>
              <svg width="48" height="48" viewBox="0 0 32 32" fill="none">
                <rect width="32" height="32" rx="6" fill="var(--color-primary-light)"/>
                <path d="M8 12h16M8 16h12M8 20h8" stroke="var(--color-primary)" strokeWidth="2" strokeLinecap="round"/>
              </svg>
            </div>
            <h3>{emptyMessage || 'Start a conversation'}</h3>
            <p>{livingUIId ? 'Ask the agent about this UI' : 'Send a message to begin interacting with CraftBot'}</p>
          </div>
        ) : (
          <div
            style={{
              height: `${virtualizer.getTotalSize()}px`,
              width: '100%',
              position: 'relative',
            }}
          >
            {loadingOlderMessages && (
              <div style={{ textAlign: 'center', padding: '8px 0', color: 'var(--text-tertiary)', fontSize: 'var(--text-xs)' }}>
                <Loader2 size={14} style={{ display: 'inline', animation: 'spin 1s linear infinite' }} /> Loading older messages...
              </div>
            )}
            {virtualizer.getVirtualItems().map((virtualItem) => {
              const message = orderedMessages[virtualItem.index]
              // Prefer clientId as the React key so that when a pending optimistic
              // message is reconciled with the server echo (messageId changes from
              // `pending:<cid>` to the real id), React reuses the same DOM node —
              // letting the CSS transform transition animate the slide into
              // its server-canonical sorted position.
              const rowKey = message.clientId || message.messageId || virtualItem.index
              return (
                <div
                  key={rowKey}
                  data-index={virtualItem.index}
                  ref={virtualizer.measureElement}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    transform: `translateY(${virtualItem.start}px)`,
                    transition: 'transform 250ms ease',
                  }}
                >
                  <ChatMessageItem
                    message={message}
                    onOpenFile={openFile}
                    onOpenFolder={openFolder}
                    onReply={handleChatReply}
                    onOptionClick={sendOptionClick}
                  />
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Status bar */}
      <div className={styles.statusBar}>
        <StatusIndicator status={status.state} size="sm" variant="dot" />
        <span>{status.message}</span>
      </div>

      {/* Input area */}
      <div className={styles.inputArea}>
        <input ref={fileInputRef} type="file" multiple className={styles.hiddenFileInput} onChange={handleFileSelect} />
        <IconButton icon={<Paperclip size={18} />} variant="ghost" tooltip="Attach file" onClick={handleAttachClick} />

        <div className={styles.micGroup} ref={langDropdownRef}>
          <IconButton
            icon={isListening ? <MicOff size={18} /> : <Mic size={18} />}
            variant="ghost"
            active={isListening}
            tooltip={isListening ? 'Stop listening' : 'Voice input'}
            onClick={toggleListening}
            className={isListening ? styles.micListening : undefined}
          />
          <button
            className={styles.langBtn}
            onClick={() => !isListening && setLangOpen(o => !o)}
            title="Speech language"
            disabled={isListening}
          >
            {MIC_LANGUAGES.find(l => l.code === micLang)?.label ?? 'EN'}
          </button>
          {langOpen && (
            <div className={styles.langDropdown}>
              {MIC_LANGUAGES.map(lang => (
                <button
                  key={lang.code}
                  className={`${styles.langOption}${micLang === lang.code ? ` ${styles.langOptionActive}` : ''}`}
                  onClick={() => { setMicLang(lang.code); setLangOpen(false) }}
                >
                  <span className={styles.langCode}>{lang.label}</span>
                  <span className={styles.langFull}>{lang.full}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div
          className={`${styles.inputWrapper}${isDragOver ? ` ${styles.inputWrapperDragOver}` : ''}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          {(attachmentError || !attachmentValidation.valid) && (
            <div className={styles.attachmentError}>
              <AlertCircle size={14} />
              <span>{attachmentError || attachmentValidation.error}</span>
              <button className={styles.dismissError} onClick={() => setAttachmentError(null)} title="Dismiss">
                <X size={12} />
              </button>
            </div>
          )}

          {replyTarget && (
            <div className={styles.replyBar}>
              <Reply size={14} />
              <span className={styles.replyText}>Replying to: <em>{replyTarget.displayName}</em></span>
              <button className={styles.replyCancel} onClick={clearReplyTarget} title="Cancel reply">
                <X size={14} />
              </button>
            </div>
          )}

          {pendingAttachments.length > 0 && (
            <div className={styles.pendingAttachments}>
              {pendingAttachments.map((att, idx) => (
                <div key={idx} className={styles.pendingAttachment}>
                  <button
                    className={styles.pendingAttachmentBody}
                    onClick={() => openPreview(att)}
                    title="Click to preview"
                  >
                    {att.type.startsWith('image/') ? (
                      <img
                        src={`data:${att.type};base64,${att.content}`}
                        alt={att.name}
                        className={styles.pendingImageThumb}
                      />
                    ) : (
                      <File size={12} />
                    )}
                    <span className={styles.pendingFileName} title={att.name}>{att.name}</span>
                    <span className={styles.pendingFileSize}>({formatFileSize(att.size)})</span>
                  </button>
                  <button className={styles.removeAttachment} onClick={() => removeAttachment(idx)} title="Remove">
                    <X size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}

          {isListening && (
            <div className={styles.listeningDots}>
              <span /><span /><span />
            </div>
          )}

          <textarea
            ref={inputRef}
            className={`${styles.input}${isListening ? ` ${styles.inputListening}` : ''}`}
            placeholder={isListening ? 'Listening... speak now' : (placeholder || 'Type a message...')}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            rows={1}
            lang={micLang}
            inputMode="text"
          />
        </div>

        <Button
          icon={<Send size={16} />}
          onClick={handleSend}
          disabled={(!input.trim() && pendingAttachments.length === 0) || !attachmentValidation.valid}
        />
      </div>

      {previewAttachment && ReactDOM.createPortal(
        (() => {
          const isImage = previewAttachment.type.startsWith('image/')
          const isPdf = previewAttachment.type === 'application/pdf' || previewAttachment.name.toLowerCase().endsWith('.pdf')
          const isText = !isPdf && (previewAttachment.type.startsWith('text/') ||
            ['application/json', 'application/xml', 'application/javascript',
             'application/typescript', 'application/yaml', 'application/toml',
             'application/csv', 'application/x-sh'].includes(previewAttachment.type) ||
            /\.(txt|md|csv|json|xml|yaml|yml|toml|sh|py|js|ts|jsx|tsx|css|html|htm|env|log|ini|cfg|conf)$/i.test(previewAttachment.name))

          let textContent = ''
          let lineCount = 0
          if (isText) {
            try {
              const bytes = Uint8Array.from(atob(previewAttachment.content), c => c.charCodeAt(0))
              textContent = new TextDecoder('utf-8').decode(bytes)
              lineCount = textContent.split('\n').length
            } catch { textContent = '' }
          }

          return (
            <div className={styles.previewOverlay} onClick={() => setPreviewAttachment(null)}>
              <div className={styles.previewModal} onClick={e => e.stopPropagation()}>
                <div className={styles.previewHeader}>
                  <div className={styles.previewHeaderLeft}>
                    <span className={styles.previewFileName} title={previewAttachment.name}>
                      {previewAttachment.name}
                    </span>
                    <span className={styles.previewMeta}>
                      {formatFileSize(previewAttachment.size)}
                      {isText && lineCount > 0 && <> · {lineCount} line{lineCount !== 1 ? 's' : ''}</>}
                      {isText && <> · Formatting may be inconsistent from source</>}
                    </span>
                  </div>
                  <button className={styles.previewClose} onClick={() => setPreviewAttachment(null)} title="Close (Esc)">
                    <X size={18} />
                  </button>
                </div>

                {isImage ? (
                  <img
                    src={`data:${previewAttachment.type};base64,${previewAttachment.content}`}
                    alt={previewAttachment.name}
                    className={styles.previewImage}
                  />
                ) : isPdf && pdfBlobUrl ? (
                  <iframe
                    src={pdfBlobUrl}
                    className={styles.previewPdf}
                    title={previewAttachment.name}
                  />
                ) : isText && textContent ? (
                  <pre className={styles.previewTextContent}>{textContent}</pre>
                ) : (
                  <div className={styles.previewFileInfo}>
                    <p className={styles.previewUnavailableText}>
                      Preview isn't available for {previewAttachment.name} ({formatFileSize(previewAttachment.size)}).
                    </p>
                  </div>
                )}
              </div>
            </div>
          )
        })(),
        document.body
      )}
    </div>
  )
}
