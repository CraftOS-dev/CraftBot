import type { SelectHTMLAttributes } from 'react';
import { useId } from 'react';
import { cn } from '../lib/cn.ts';
import { ChevronDownIcon } from './icons.tsx';

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps
  extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'children'> {
  label?: string | undefined;
  error?: string | undefined;
  /** Rendered as a leading disabled-ish empty option (value ''). */
  placeholder?: string | undefined;
  options: ReadonlyArray<SelectOption>;
}

/**
 * Native styled select (shadcn-conventional wrapper). Dependency-free — the
 * kit avoids Radix's combobox to keep the vendored footprint small.
 */
export function Select({
  className,
  label,
  error,
  placeholder,
  options,
  id,
  ...props
}: SelectProps): React.JSX.Element {
  const autoId = useId();
  const selectId = id ?? autoId;

  return (
    <div className="flex w-full flex-col gap-1.5">
      {label !== undefined && (
        <label htmlFor={selectId} className="text-sm font-medium">
          {label}
        </label>
      )}
      <div className="relative">
        <select
          id={selectId}
          aria-invalid={error !== undefined || undefined}
          className={cn(
            'h-9 w-full appearance-none rounded-[var(--lui-radius)] border border-[var(--lui-border)] bg-[var(--lui-surface)] px-3 pr-8 text-sm focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--lui-accent)]',
            error !== undefined && 'border-red-500',
            className,
          )}
          {...props}
        >
          {placeholder !== undefined && <option value="">{placeholder}</option>}
          {options.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <ChevronDownIcon
          size={16}
          className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--lui-muted)]"
        />
      </div>
      {error !== undefined && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
    </div>
  );
}
