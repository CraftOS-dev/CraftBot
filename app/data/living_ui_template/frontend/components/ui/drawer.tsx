/**
 * Drawer — slide-over side panel (SYSTEM-MANAGED — do not edit)
 *
 * For detail/edit views next to a list (bigger than a Modal, keeps page
 * context visible):
 *
 *   <Drawer open={!!selected} onClose={() => setSelected(null)} title={selected?.title}>
 *     <EntityForm entity="Card" initial={selected} onSaved={onSaved} />
 *   </Drawer>
 */

import { ReactNode, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

export interface DrawerProps {
  open: boolean
  onClose: () => void
  title?: string
  children: ReactNode
  footer?: ReactNode
  /** Which edge the panel slides from (default 'right'). */
  side?: 'left' | 'right'
  /** Panel width in px (default 420). */
  width?: number
}

export function Drawer({
  open,
  onClose,
  title,
  children,
  footer,
  side = 'right',
  width = 420,
}: DrawerProps) {
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.body.style.overflow = ''
    }
  }, [open])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 'var(--z-modal)' as any,
        display: 'flex',
        justifyContent: side === 'right' ? 'flex-end' : 'flex-start',
      }}
    >
      <div
        onClick={onClose}
        style={{
          position: 'absolute',
          inset: 0,
          backgroundColor: 'var(--overlay-color)',
          animation: 'fadeIn 0.15s ease-out',
        }}
      />
      <div
        role="dialog"
        aria-modal="true"
        style={{
          position: 'relative',
          width: '100%',
          maxWidth: width,
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          backgroundColor: 'var(--bg-secondary)',
          backdropFilter: 'var(--surface-backdrop)',
          borderLeft: side === 'right' ? '1px solid var(--border-primary)' : 'none',
          borderRight: side === 'left' ? '1px solid var(--border-primary)' : 'none',
          boxShadow: 'var(--shadow-lg)',
          animation: `${side === 'right' ? 'slideInRight' : 'slideInLeft'} 0.15s ease-out`,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 'var(--space-3)',
            padding: 'var(--space-4)',
            borderBottom: '1px solid var(--border-primary)',
          }}
        >
          <h2
            style={{
              margin: 0,
              fontSize: 'var(--font-size-lg)',
              fontWeight: 'var(--font-weight-semibold)' as any,
              color: 'var(--text-primary)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {title}
          </h2>
          <button
            onClick={onClose}
            className="hover:bg-raised hover:text-ink rounded-token"
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--text-secondary)',
              padding: 'var(--space-2)',
              margin: 'calc(var(--space-2) * -1)',
              display: 'inline-flex',
              flexShrink: 0,
              transition: 'var(--transition-fast)',
            }}
            aria-label="Close panel"
          >
            <X size={18} />
          </button>
        </div>
        <div style={{ flex: 1, padding: 'var(--space-4)', overflowY: 'auto' }}>{children}</div>
        {footer && (
          <div
            style={{
              display: 'flex',
              justifyContent: 'flex-end',
              gap: 'var(--space-2)',
              padding: 'var(--space-4)',
              borderTop: '1px solid var(--border-primary)',
            }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}
