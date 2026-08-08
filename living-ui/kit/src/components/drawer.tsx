/**
 * Drawer — slide-over side panel for detail/edit views next to a list
 * (bigger than a Dialog, keeps page context visible):
 *
 *   <Drawer open={selected !== null} onClose={() => setSelected(null)} title={selected?.title}>
 *     <EntityForm collection="cards" fields={FIELDS} initial={selected} onSaved={onSaved} />
 *   </Drawer>
 */
import { useEffect } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { cn } from '../lib/cn.ts';
import { XIcon } from './icons.tsx';

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title?: string | undefined;
  children: ReactNode;
  footer?: ReactNode | undefined;
  /** Which edge the panel slides from (default 'right'). */
  side?: 'left' | 'right' | undefined;
  /** Panel max width in px (default 420). */
  width?: number | undefined;
}

export function Drawer({
  open,
  onClose,
  title,
  children,
  footer,
  side = 'right',
  width = 420,
}: DrawerProps): React.JSX.Element | null {
  useEffect(() => {
    if (!open) return;
    document.body.style.overflow = 'hidden';
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = '';
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div
      className={cn('fixed inset-0 z-50 flex', side === 'right' ? 'justify-end' : 'justify-start')}
    >
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        style={{ maxWidth: width }}
        className={cn(
          'relative flex h-full w-full flex-col bg-[var(--lui-surface)] text-[var(--lui-text)] shadow-xl',
          side === 'right' ? 'border-l border-[var(--lui-border)]' : 'border-r border-[var(--lui-border)]',
        )}
      >
        <div className="flex items-center justify-between gap-3 border-b border-[var(--lui-border)] px-4 py-3">
          <h2 className="truncate text-base font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close panel"
            className="inline-flex shrink-0 rounded p-1 text-[var(--lui-muted)] transition-colors hover:bg-[var(--lui-border)]/40 hover:text-[var(--lui-text)]"
          >
            <XIcon size={18} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
        {footer !== undefined && footer !== null && (
          <div className="flex justify-end gap-2 border-t border-[var(--lui-border)] p-4">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
