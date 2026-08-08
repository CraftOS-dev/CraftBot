/**
 * Tooltip — explains icon-only controls on hover/focus.
 *
 *   <Tooltip content="Archive this card">
 *     <Button size="sm" variant="ghost">⌫</Button>
 *   </Tooltip>
 */
import { useState } from 'react';
import type { ReactNode } from 'react';
import { cn } from '../lib/cn.ts';

export interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  /** Placement relative to the child (default 'top'). */
  side?: 'top' | 'bottom' | undefined;
}

export function Tooltip({ content, children, side = 'top' }: TooltipProps): React.JSX.Element {
  const [visible, setVisible] = useState(false);

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onFocus={() => setVisible(true)}
      onBlur={() => setVisible(false)}
    >
      {children}
      {visible && (
        <span
          role="tooltip"
          className={cn(
            'pointer-events-none absolute left-1/2 z-50 -translate-x-1/2 whitespace-nowrap rounded-[calc(var(--lui-radius)-2px)] border border-[var(--lui-border)] bg-[var(--lui-surface)] px-2 py-1 text-xs text-[var(--lui-text)] shadow-md',
            side === 'top' ? 'bottom-[calc(100%+6px)]' : 'top-[calc(100%+6px)]',
          )}
        >
          {content}
        </span>
      )}
    </span>
  );
}
