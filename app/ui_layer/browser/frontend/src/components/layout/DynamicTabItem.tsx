import React, { useState, useRef, useEffect } from 'react'
import { X } from 'lucide-react'
import { DynamicTab } from '../../types/dynamicTabs'
import { getTabIcon } from './tabIcons'
import styles from './NavBar.module.css'

interface DynamicTabItemProps {
  tab: DynamicTab
  isActive: boolean
  index: number
  dragIndex: number | null
  dragOverIndex: number | null
  onClose: (e: React.MouseEvent, tabId: string) => void
  onClick: (tab: DynamicTab) => void
  onRename: (tabId: string, newLabel: string) => void
  onDragStart: (e: React.DragEvent, index: number) => void
  onDragOver: (e: React.DragEvent, index: number) => void
  onDragEnd: () => void
  onDrop: (e: React.DragEvent, index: number) => void
}

export const DynamicTabItem = React.memo(function DynamicTabItem({
  tab,
  isActive,
  index,
  dragIndex,
  dragOverIndex,
  onClose,
  onClick,
  onRename,
  onDragStart,
  onDragOver,
  onDragEnd,
  onDrop,
}: DynamicTabItemProps) {
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [editing])

  const handleDoubleClick = () => {
    setEditing(true)
    setEditValue(tab.label)
  }

  const commitRename = () => {
    if (editValue.trim()) {
      onRename(tab.id, editValue.trim())
    }
    setEditing(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') commitRename()
    else if (e.key === 'Escape') setEditing(false)
  }

  const className = [
    styles.navItem,
    styles.dynamicTab,
    isActive ? styles.active : '',
    dragIndex === index ? styles.dragging : '',
    dragOverIndex === index ? styles.dragOver : '',
  ].filter(Boolean).join(' ')

  return (
    <button
      className={className}
      onClick={() => !editing && onClick(tab)}
      onDoubleClick={handleDoubleClick}
      title={editing ? undefined : tab.label}
      draggable={!editing}
      onDragStart={(e) => onDragStart(e, index)}
      onDragOver={(e) => onDragOver(e, index)}
      onDragEnd={onDragEnd}
      onDrop={(e) => onDrop(e, index)}
    >
      <span className={styles.icon}>{getTabIcon(tab.iconName)}</span>
      {editing ? (
        <input
          ref={inputRef}
          className={styles.renameInput}
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          onBlur={commitRename}
          onKeyDown={handleKeyDown}
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <span className={styles.label}>{tab.label}</span>
      )}
      <span
        className={styles.closeBtn}
        onClick={(e) => onClose(e, tab.id)}
        role="button"
        tabIndex={-1}
        aria-label={`Close ${tab.label}`}
      >
        <X size={12} />
      </span>
    </button>
  )
})
