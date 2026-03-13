import React, { useState, useRef, useEffect, useLayoutEffect, KeyboardEvent, useCallback, ChangeEvent, useMemo } from 'react'
import { Send, Paperclip, X, Loader2, File, AlertCircle } from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { Button, IconButton, StatusIndicator, MarkdownContent, AttachmentDisplay } from '../../components/ui'
import styles from './ChatPage.module.css'

// Pending attachment type
interface PendingAttachment {
  name: string
  type: string
  size: number
  content: string  // base64
}

// Panel width limits
const DEFAULT_PANEL_WIDTH = 380
const MIN_PANEL_WIDTH = 200
const MAX_PANEL_WIDTH = 800

// Attachment limits
const MAX_ATTACHMENT_COUNT = 10
const MAX_TOTAL_SIZE_BYTES = 50 * 1024 * 1024 * 1024  // 50GB

// Format file size for display
const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

export function ChatPage() {
  const { messages, actions, status, connected, sendMessage, cancelTask, cancellingTaskId, openFile, openFolder } = useWebSocket()
  const [input, setInput] = useState('')
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([])
  const [attachmentError, setAttachmentError] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Resizable panel state
  const [panelWidth, setPanelWidth] = useState(DEFAULT_PANEL_WIDTH)
  const [isResizing, setIsResizing] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  // Compute attachment validation status
  const attachmentValidation = useMemo(() => {
    const totalSize = pendingAttachments.reduce((sum, att) => sum + att.size, 0)
    const count = pendingAttachments.length

    if (count > MAX_ATTACHMENT_COUNT) {
      return {
        valid: false,
        error: `Maximum ${MAX_ATTACHMENT_COUNT} files allowed. You have ${count} files.`
      }
    }
    if (totalSize > MAX_TOTAL_SIZE_BYTES) {
      return {
        valid: false,
        error: `Total size (${formatFileSize(totalSize)}) exceeds 50GB limit. Please remove some files or copy large files directly to the agent workspace.`
      }
    }
    return { valid: true, error: null }
  }, [pendingAttachments])

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Auto-resize textarea based on content
  const adjustTextareaHeight = useCallback(() => {
    const textarea = inputRef.current
    if (textarea) {
      // Reset height to auto to get accurate scrollHeight
      textarea.style.height = 'auto'
      // Set height to scrollHeight (CSS max-height will clamp it)
      textarea.style.height = `${textarea.scrollHeight}px`
    }
  }, [])

  // Adjust textarea height when input changes (useLayoutEffect for synchronous DOM updates)
  useLayoutEffect(() => {
    adjustTextareaHeight()
  }, [input, adjustTextareaHeight])

  // Handle resize drag
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsResizing(true)
  }, [])

  useEffect(() => {
    if (!isResizing) return

    const handleMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return
      const containerRect = containerRef.current.getBoundingClientRect()
      // Calculate width from right edge (since panel is on the right)
      const newWidth = containerRect.right - e.clientX
      // Clamp to min/max limits
      const clampedWidth = Math.min(Math.max(newWidth, MIN_PANEL_WIDTH), MAX_PANEL_WIDTH)
      setPanelWidth(clampedWidth)
    }

    const handleMouseUp = () => {
      setIsResizing(false)
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isResizing])

  const handleSend = () => {
    // Don't send if there are validation errors
    if (!attachmentValidation.valid) return

    if (input.trim() || pendingAttachments.length > 0) {
      sendMessage(input.trim(), pendingAttachments.length > 0 ? pendingAttachments : undefined)
      setInput('')
      setPendingAttachments([])
      setAttachmentError(null)
      // Reset textarea height after clearing input
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
    }
  }

  const handleAttachClick = () => {
    fileInputRef.current?.click()
  }

  const handleFileSelect = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    // Check if adding these files would exceed the count limit
    const totalFileCount = pendingAttachments.length + files.length
    if (totalFileCount > MAX_ATTACHMENT_COUNT) {
      setAttachmentError(`Maximum ${MAX_ATTACHMENT_COUNT} files allowed. You have ${pendingAttachments.length} file(s) and are trying to add ${files.length} more.`)
      e.target.value = ''
      return
    }

    const newAttachments: PendingAttachment[] = []
    let newTotalSize = pendingAttachments.reduce((sum, att) => sum + att.size, 0)

    for (let i = 0; i < files.length; i++) {
      const file = files[i]

      // Check individual file size (for very large files, recommend manual copy)
      if (file.size > MAX_TOTAL_SIZE_BYTES) {
        setAttachmentError(`File "${file.name}" (${formatFileSize(file.size)}) exceeds the 50GB limit. For very large files, please copy them directly to the agent workspace folder.`)
        e.target.value = ''
        return
      }

      // Check if adding this file would exceed total size limit
      if (newTotalSize + file.size > MAX_TOTAL_SIZE_BYTES) {
        setAttachmentError(`Adding "${file.name}" would exceed the 50GB total size limit. Current total: ${formatFileSize(newTotalSize)}. For large files, please copy them directly to the agent workspace folder.`)
        e.target.value = ''
        return
      }

      try {
        // Read file as base64
        const content = await readFileAsBase64(file)
        newAttachments.push({
          name: file.name,
          type: file.type || 'application/octet-stream',
          size: file.size,
          content,
        })
        newTotalSize += file.size
      } catch (error) {
        console.error('Failed to read file:', error)
        setAttachmentError(`Failed to read file "${file.name}". The file may be too large or inaccessible.`)
        e.target.value = ''
        return
      }
    }

    // Clear any previous error and add the attachments
    setAttachmentError(null)
    setPendingAttachments(prev => [...prev, ...newAttachments])

    // Reset file input so the same file can be selected again
    e.target.value = ''
  }

  const removeAttachment = (index: number) => {
    setPendingAttachments(prev => prev.filter((_, i) => i !== index))
    // Clear any error when removing files
    setAttachmentError(null)
  }

  // Helper to read file as base64
  const readFileAsBase64 = (file: globalThis.File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => {
        const result = reader.result as string
        // Remove data URL prefix (e.g., "data:image/png;base64,")
        const base64 = result.split(',')[1]
        resolve(base64)
      }
      reader.onerror = reject
      reader.readAsDataURL(file)
    })
  }

  // Group actions by task
  const tasks = actions.filter(a => a.itemType === 'task')
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)

  const getActionsForTask = (taskId: string) =>
    actions.filter(a => a.itemType === 'action' && a.parentId === taskId)

  return (
    <div className={`${styles.chatPage} ${isResizing ? styles.resizing : ''}`} ref={containerRef}>
      {/* Chat Panel - flexible width */}
      <div className={styles.chatPanel}>
        <div className={styles.messagesContainer}>
          {messages.length === 0 ? (
            <div className={styles.emptyState}>
              <div className={styles.emptyIcon}>
                <svg width="48" height="48" viewBox="0 0 32 32" fill="none">
                  <rect width="32" height="32" rx="6" fill="var(--color-primary-light)"/>
                  <path d="M8 12h16M8 16h12M8 20h8" stroke="var(--color-primary)" strokeWidth="2" strokeLinecap="round"/>
                </svg>
              </div>
              <h3>Start a conversation</h3>
              <p>Send a message to begin interacting with CraftBot</p>
            </div>
          ) : (
            messages.map((msg, idx) => (
              <div
                key={msg.messageId || idx}
                className={`${styles.messageWrapper} ${styles[msg.style + 'Wrapper']}`}
              >
                <div className={`${styles.message} ${styles[msg.style]}`}>
                  <div className={styles.messageHeader}>
                    <span className={styles.sender}>{msg.sender}</span>
                    <span className={styles.timestamp}>
                      {new Date(msg.timestamp * 1000).toLocaleTimeString()}
                    </span>
                  </div>
                  <div className={styles.messageContent}>
                    <MarkdownContent content={msg.content} />
                  </div>
                </div>
                {msg.attachments && msg.attachments.length > 0 && (
                  <div className={styles.messageAttachments}>
                    <AttachmentDisplay
                      attachments={msg.attachments}
                      onOpenFile={openFile}
                      onOpenFolder={openFolder}
                    />
                  </div>
                )}
              </div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Status bar */}
        <div className={styles.statusBar}>
          <StatusIndicator status={connected ? status.state : 'error'} size="sm" variant="dot" />
          <span>{connected ? status.message : 'Disconnected'}</span>
        </div>

        {/* Input area */}
        <div className={styles.inputArea}>
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className={styles.hiddenFileInput}
            onChange={handleFileSelect}
          />

          <IconButton
            icon={<Paperclip size={18} />}
            variant="ghost"
            tooltip="Attach file"
            onClick={handleAttachClick}
          />

          <div className={styles.inputWrapper}>
            {/* Attachment error message */}
            {(attachmentError || !attachmentValidation.valid) && (
              <div className={styles.attachmentError}>
                <AlertCircle size={14} />
                <span>{attachmentError || attachmentValidation.error}</span>
                <button
                  className={styles.dismissError}
                  onClick={() => setAttachmentError(null)}
                  title="Dismiss"
                >
                  <X size={12} />
                </button>
              </div>
            )}

            {/* Pending attachments preview */}
            {pendingAttachments.length > 0 && (
              <div className={styles.pendingAttachments}>
                {pendingAttachments.map((att, idx) => (
                  <div key={idx} className={styles.pendingAttachment}>
                    <File size={12} />
                    <span className={styles.pendingFileName} title={att.name}>
                      {att.name}
                    </span>
                    <span className={styles.pendingFileSize}>
                      ({formatFileSize(att.size)})
                    </span>
                    <button
                      className={styles.removeAttachment}
                      onClick={() => removeAttachment(idx)}
                      title="Remove"
                    >
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <textarea
              ref={inputRef}
              className={styles.input}
              placeholder="Type a message..."
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
            />
          </div>

          <Button
            icon={<Send size={16} />}
            onClick={handleSend}
            disabled={(!input.trim() && pendingAttachments.length === 0) || !attachmentValidation.valid}
          />
        </div>
      </div>

      {/* Resize Handle */}
      <div
        className={styles.resizeHandle}
        onMouseDown={handleMouseDown}
      />

      {/* Task/Action Panel - resizable width */}
      <div className={styles.actionPanel} style={{ width: panelWidth, flexShrink: 0 }}>
        <div className={styles.panelHeader}>
          <h3>Tasks & Actions</h3>
        </div>
        <div className={styles.actionList}>
          {tasks.length === 0 ? (
            <div className={styles.emptyActions}>
              <p>No active tasks</p>
            </div>
          ) : (
            tasks.map(task => (
              <div key={task.id} className={styles.taskGroup}>
                <div
                  className={`${styles.taskItem} ${selectedTaskId === task.id ? styles.selected : ''}`}
                  onClick={() => setSelectedTaskId(
                    selectedTaskId === task.id ? null : task.id
                  )}
                >
                  <StatusIndicator status={task.status} size="sm" />
                  <span className={styles.taskName}>{task.name}</span>
                  {task.status === 'running' && (
                    <IconButton
                      size="sm"
                      variant="ghost"
                      className={styles.taskCancelBtn}
                      onClick={(e) => {
                        e.stopPropagation()
                        cancelTask(task.id)
                      }}
                      disabled={cancellingTaskId === task.id}
                      title="Cancel Task"
                      icon={
                        cancellingTaskId === task.id ? (
                          <Loader2 size={12} className={styles.spinning} />
                        ) : (
                          <X size={12} />
                        )
                      }
                    />
                  )}
                </div>
                {selectedTaskId === task.id && (
                  <div className={styles.actionsList}>
                    {getActionsForTask(task.id).map(action => (
                      <div key={action.id} className={styles.actionItem}>
                        <StatusIndicator status={action.status} size="sm" />
                        <span className={styles.actionName}>{action.name}</span>
                      </div>
                    ))}
                    {getActionsForTask(task.id).length === 0 && (
                      <div className={styles.noActions}>No actions yet</div>
                    )}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
