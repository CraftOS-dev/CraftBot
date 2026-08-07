import type { TextareaHTMLAttributes } from 'react';
import { useId } from 'react';
import { cn } from '../lib/cn.ts';

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string | undefined;
  error?: string | undefined;
}

/** Multi-line text input (shadcn-conventional API, mirrors Input). */
export function Textarea({
  className,
  label,
  error,
  id,
  ...props
}: TextareaProps): React.JSX.Element {
  const autoId = useId();
  const textareaId = id ?? autoId;

  return (
    <div className="flex w-full flex-col gap-1.5">
      {label !== undefined && (
        <label htmlFor={textareaId} className="text-sm font-medium">
          {label}
        </label>
      )}
      <textarea
        id={textareaId}
        aria-invalid={error !== undefined || undefined}
        className={cn(
          'min-h-[80px] w-full rounded-[var(--lui-radius)] border border-[var(--lui-border)] bg-[var(--lui-surface)] px-3 py-2 text-sm placeholder:text-[var(--lui-muted)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--lui-accent)]',
          error !== undefined && 'border-red-500',
          className,
        )}
        {...props}
      />
      {error !== undefined && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
    </div>
  );
}
