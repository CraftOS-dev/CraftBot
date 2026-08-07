import type { HTMLAttributes } from 'react';
import { cn } from '../lib/cn.ts';

export interface ProgressProps extends HTMLAttributes<HTMLDivElement> {
  /** 0–100. Values outside the range are clamped. */
  value?: number | undefined;
}

/** Horizontal progress bar (shadcn-conventional API: `<Progress value={60} />`). */
export function Progress({ value, className, ...props }: ProgressProps): React.JSX.Element {
  const clamped = Math.min(100, Math.max(0, value ?? 0));
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={clamped}
      className={cn(
        'h-2 w-full overflow-hidden rounded-full bg-[var(--lui-border)]/60',
        className,
      )}
      {...props}
    >
      <div
        className="h-full rounded-full bg-[var(--lui-accent)] transition-all"
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}
