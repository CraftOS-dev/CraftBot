/**
 * Tooltip (SYSTEM-MANAGED — do not edit)
 *
 * Explains icon-only controls on hover/focus:
 *
 *   <Tooltip content="Archive this card">
 *     <Button size="sm" variant="ghost" icon={<Archive size={14} />} />
 *   </Tooltip>
 */

import { ReactNode, useState } from 'react'

export interface TooltipProps {
  content: ReactNode
  children: ReactNode
  /** Placement relative to the child (default 'top'). */
  side?: 'top' | 'bottom'
}

export function Tooltip({ content, children, side = 'top' }: TooltipProps) {
  const [visible, setVisible] = useState(false)

  return (
    <span
      style={{ position: 'relative', display: 'inline-flex' }}
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onFocus={() => setVisible(true)}
      onBlur={() => setVisible(false)}
    >
      {children}
      {visible && (
        <span
          role="tooltip"
          style={{
            position: 'absolute',
            left: '50%',
            transform: 'translateX(-50%)',
            ...(side === 'top' ? { bottom: 'calc(100% + 6px)' } : { top: 'calc(100% + 6px)' }),
            zIndex: 'var(--z-tooltip)' as any,
            padding: 'var(--space-1) var(--space-2)',
            backgroundColor: 'var(--bg-tertiary)',
            border: '1px solid var(--border-primary)',
            borderRadius: 'var(--radius-sm)',
            boxShadow: 'var(--shadow-md)',
            color: 'var(--text-primary)',
            fontSize: 'var(--font-size-xs)',
            whiteSpace: 'nowrap',
            pointerEvents: 'none',
            animation: 'fadeIn 0.1s ease-out',
          }}
        >
          {content}
        </span>
      )}
    </span>
  )
}
