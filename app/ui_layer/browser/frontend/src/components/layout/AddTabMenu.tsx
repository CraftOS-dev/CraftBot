import React, { useState, useRef, useEffect } from 'react'
import { Plus, Code2, TrendingUp, CalendarRange, LayoutPanelLeft } from 'lucide-react'
import { DynamicTabType } from '../../types/dynamicTabs'
import styles from './NavBar.module.css'

const ADD_TAB_OPTIONS: { type: DynamicTabType; label: string; icon: React.ReactNode }[] = [
  { type: 'code', label: 'Code Viewer', icon: <Code2 size={14} /> },
  { type: 'stock', label: 'Stock Charts', icon: <TrendingUp size={14} /> },
  { type: 'planner', label: 'Planner Board', icon: <CalendarRange size={14} /> },
  { type: 'custom', label: 'Custom Tab', icon: <LayoutPanelLeft size={14} /> },
]

interface AddTabMenuProps {
  onAddTab: (type: DynamicTabType) => void
}

export function AddTabMenu({ onAddTab }: AddTabMenuProps) {
  const [open, setOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const btnRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const handleClick = (e: MouseEvent) => {
      if (
        menuRef.current && !menuRef.current.contains(e.target as Node) &&
        btnRef.current && !btnRef.current.contains(e.target as Node)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  const handleSelect = (type: DynamicTabType) => {
    onAddTab(type)
    setOpen(false)
  }

  return (
    <div className={styles.addTabWrapper}>
      <button
        ref={btnRef}
        className={`${styles.navItem} ${styles.addTabBtn}`}
        onClick={() => setOpen(prev => !prev)}
        title="Add new tab"
      >
        <Plus size={16} />
      </button>

      {open && (
        <div ref={menuRef} className={styles.addMenu}>
          {ADD_TAB_OPTIONS.map(opt => (
            <button
              key={opt.type}
              className={styles.addMenuItem}
              onClick={() => handleSelect(opt.type)}
            >
              <span className={styles.addMenuIcon}>{opt.icon}</span>
              <span>{opt.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
