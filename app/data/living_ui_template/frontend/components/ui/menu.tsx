/**
 * Dropdown action menu (SYSTEM-MANAGED — do not edit)
 *
 * The "⋯" row-actions pattern — one trigger, a list of actions:
 *
 *   <DropdownMenu
 *     trigger={<Button size="sm" variant="ghost" icon={<MoreHorizontal size={14} />} />}
 *     items={[
 *       { label: 'Edit', icon: <Pencil size={14} />, onSelect: () => openEdit(card) },
 *       { label: 'Duplicate', onSelect: () => duplicate(card) },
 *       { label: 'Delete', danger: true, onSelect: () => remove(card) },
 *     ]}
 *   />
 *
 * Closes on selection, outside click, and Escape.
 */

import React, { useEffect, useRef, useState } from 'react'
import { useDevSurface } from './devtour'

export interface DropdownMenuItem {
  label: string
  icon?: React.ReactNode
  onSelect: () => void
  danger?: boolean
  disabled?: boolean
}

export interface DropdownMenuProps {
  /** The element that opens the menu (a Button, an icon, …). */
  trigger: React.ReactNode
  items: DropdownMenuItem[]
  /** Which edge of the trigger the menu aligns to (default 'right'). */
  align?: 'left' | 'right'
}

export function DropdownMenu({ trigger, items, align = 'right' }: DropdownMenuProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  // Build-time tour (dev only): briefly open the menu to show its items.
  // Renders inline (inside #root), so the reveal engine captures it itself.
  useDevSurface(
    'menu',
    items[0]?.label ? `Menu (${items[0].label}…)` : 'Menu',
    () => setOpen(true),
    () => setOpen(false),
  )

  useEffect(() => {
    if (!open) return
    const onDocClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={rootRef} style={{ position: 'relative', display: 'inline-flex' }}>
      <span
        onClick={e => {
          e.stopPropagation()
          setOpen(o => !o)
        }}
        style={{ display: 'inline-flex', cursor: 'pointer' }}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {trigger}
      </span>
      {open && (
        <div
          role="menu"
          style={{
            position: 'absolute',
            top: 'calc(100% + 4px)',
            [align]: 0,
            zIndex: 'var(--z-dropdown)' as any,
            minWidth: 160,
            padding: 'var(--space-1)',
            backgroundColor: 'var(--bg-secondary)',
            backdropFilter: 'var(--surface-backdrop)',
            border: '1px solid var(--border-primary)',
            borderRadius: 'var(--radius-md)',
            boxShadow: 'var(--shadow-md)',
            animation: 'fadeIn 0.1s ease-out',
          }}
        >
          {items.map((item, i) => (
            <button
              key={i}
              role="menuitem"
              disabled={item.disabled}
              onClick={e => {
                e.stopPropagation()
                setOpen(false)
                item.onSelect()
              }}
              className={item.disabled ? '' : 'hover:bg-raised'}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--space-2)',
                width: '100%',
                padding: 'var(--space-2) var(--space-3)',
                background: 'none',
                border: 'none',
                borderRadius: 'var(--radius-sm)',
                cursor: item.disabled ? 'not-allowed' : 'pointer',
                opacity: item.disabled ? 0.5 : 1,
                textAlign: 'left',
                fontSize: 'var(--font-size-sm)',
                fontFamily: 'var(--font-sans)',
                color: item.danger ? 'var(--color-error)' : 'var(--text-primary)',
                whiteSpace: 'nowrap',
                transition: 'var(--transition-fast)',
              }}
            >
              {item.icon && (
                <span style={{ display: 'inline-flex', flexShrink: 0 }}>{item.icon}</span>
              )}
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
