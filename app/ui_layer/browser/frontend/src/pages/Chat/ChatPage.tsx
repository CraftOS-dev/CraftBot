import React, { useState, useRef, useEffect, KeyboardEvent, useCallback } from 'react'
import { Send, Paperclip, X, Loader2 } from 'lucide-react'
import { useWebSocket } from '../../contexts/WebSocketContext'
import { Button, IconButton, StatusIndicator, MarkdownContent } from '../../components/ui'
import styles from './ChatPage.module.css'

// Panel width limits
const DEFAULT_PANEL_WIDTH = 380
const MIN_PANEL_WIDTH = 200
const MAX_PANEL_WIDTH = 800

export function ChatPage() {
  const { messages, actions, status, connected, sendMessage, cancelTask, cancellingTaskId } = useWebSocket()
  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Resizable panel state
  const [panelWidth, setPanelWidth] = useState(DEFAULT_PANEL_WIDTH)
  const [isResizing, setIsResizing] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

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
    if (input.trim()) {
      sendMessage(input.trim())
      setInput('')
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
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
                className={`${styles.message} ${styles[msg.style]}`}
              >
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
          <IconButton
            icon={<Paperclip size={18} />}
            variant="ghost"
            tooltip="Attach file"
          />
          <textarea
            ref={inputRef}
            className={styles.input}
            placeholder="Type a message..."
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
          />
          <Button
            icon={<Send size={16} />}
            onClick={handleSend}
            disabled={!input.trim()}
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
