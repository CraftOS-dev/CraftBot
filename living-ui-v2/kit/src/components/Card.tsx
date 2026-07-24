import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '../lib/cn.ts';

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>): React.JSX.Element {
  return (
    <div
      className={cn(
        'rounded-xl border border-[var(--lui-border)] bg-[var(--lui-surface)] shadow-sm',
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({
  title,
  actions,
}: {
  title: ReactNode;
  actions?: ReactNode;
}): React.JSX.Element {
  return (
    <div className="flex items-center justify-between border-b border-[var(--lui-border)] px-5 py-4">
      <h2 className="text-base font-semibold">{title}</h2>
      {actions !== undefined && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>): React.JSX.Element {
  return <div className={cn('px-5 py-4', className)} {...props} />;
}
