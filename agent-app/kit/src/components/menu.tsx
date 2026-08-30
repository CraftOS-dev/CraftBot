/**
 * Dropdown action menu — the "⋯" row-actions pattern:
 *
 *   <DropdownMenu
 *     trigger={<Button size="sm" variant="ghost">⋯</Button>}
 *     items={[
 *       { label: 'Edit', onSelect: () => openEdit(card) },
 *       { label: 'Duplicate', onSelect: () => duplicate(card) },
 *       { label: 'Delete', danger: true, onSelect: () => remove(card) },
 *     ]}
 *   />
 *
 * Closes on selection, outside click, and Escape.
 */
import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { cn } from '../lib/cn.ts';

export interface DropdownMenuItem {
  label: string;
  icon?: ReactNode | undefined;
  onSelect: () => void;
  danger?: boolean | undefined;
  disabled?: boolean | undefined;
}

export interface DropdownMenuProps {
  /** The element that opens the menu (a Button, an icon, …). */
  trigger: ReactNode;
  items: ReadonlyArray<DropdownMenuItem>;
  /** Which edge of the trigger the menu aligns to (default 'right'). */
  align?: 'left' | 'right' | undefined;
}

export function DropdownMenu({
  trigger,
  items,
  align = 'right',
}: DropdownMenuProps): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent): void => {
      if (rootRef.current !== null && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative inline-flex">
      <span
        className="inline-flex cursor-pointer"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      >
        {trigger}
      </span>
      {open && (
        <div
          role="menu"
          className={cn(
            'absolute top-full z-50 mt-1 min-w-[10rem] rounded-[var(--lui-radius)] border border-[var(--lui-border)] bg-[var(--lui-surface)] p-1 shadow-md',
            align === 'left' ? 'left-0' : 'right-0',
          )}
        >
          {items.map((item, i) => (
            <button
              key={i}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
                item.onSelect();
              }}
              className={cn(
                'flex w-full items-center gap-2 whitespace-nowrap rounded-[calc(var(--lui-radius)-2px)] px-3 py-2 text-left text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                item.danger === true ? 'text-red-600' : 'text-[var(--lui-text)]',
                'hover:bg-[var(--lui-border)]/40',
              )}
            >
              {item.icon !== undefined && item.icon !== null && (
                <span className="inline-flex shrink-0">{item.icon}</span>
              )}
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
