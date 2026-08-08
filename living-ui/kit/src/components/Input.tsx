import type { InputHTMLAttributes } from 'react';
import { useId } from 'react';
import { cn } from '../lib/cn.ts';

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string | undefined;
  error?: string | undefined;
}

export function Input({ className, label, error, id, ...props }: InputProps): React.JSX.Element {
  const autoId = useId();
  const inputId = id ?? autoId;

  return (
    <div className="flex w-full flex-col gap-1.5">
      {label !== undefined && (
        <label htmlFor={inputId} className="text-sm font-medium">
          {label}
        </label>
      )}
      <input
        id={inputId}
        aria-invalid={error !== undefined || undefined}
        className={cn(
          'h-9 w-full rounded-[var(--lui-radius)] border border-[var(--lui-border)] bg-[var(--lui-surface)] px-3 text-sm placeholder:text-[var(--lui-muted)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--lui-accent)]',
          error !== undefined && 'border-red-500',
          className,
        )}
        {...props}
      />
      {error !== undefined && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
    </div>
  );
}
