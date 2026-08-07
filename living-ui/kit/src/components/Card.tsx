import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '../lib/cn.ts';

/**
 * Card family — shadcn-conventional composition (kit 0.4.0):
 *
 *   <Card>
 *     <CardHeader>
 *       <CardTitle>…</CardTitle>
 *       <CardDescription>…</CardDescription>
 *     </CardHeader>
 *     <CardContent>…</CardContent>
 *     <CardFooter>…</CardFooter>
 *   </Card>
 *
 * Models write this shape from training-data memory, so the kit accepts it
 * verbatim. Back-compat (kit ≤0.3): `<CardHeader title="…" actions={…} />`
 * still renders, and `CardBody` remains as an alias of `CardContent`.
 */

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

export interface CardHeaderProps
  extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  /** Legacy prop API (kit ≤0.3). When set, renders the title/actions bar. */
  title?: ReactNode;
  actions?: ReactNode | undefined;
}

export function CardHeader({
  title,
  actions,
  className,
  children,
  ...props
}: CardHeaderProps): React.JSX.Element {
  if (title !== undefined || actions !== undefined) {
    return (
      <div
        className={cn(
          'flex items-center justify-between border-b border-[var(--lui-border)] px-5 py-4',
          className,
        )}
        {...props}
      >
        <h2 className="text-base font-semibold">{title}</h2>
        {actions !== undefined && <div className="flex items-center gap-2">{actions}</div>}
        {children}
      </div>
    );
  }
  return (
    <div className={cn('flex flex-col gap-1 px-5 py-4', className)} {...props}>
      {children}
    </div>
  );
}

export function CardTitle({
  className,
  ...props
}: HTMLAttributes<HTMLHeadingElement>): React.JSX.Element {
  return <h2 className={cn('text-base font-semibold leading-tight', className)} {...props} />;
}

export function CardDescription({
  className,
  ...props
}: HTMLAttributes<HTMLParagraphElement>): React.JSX.Element {
  return <p className={cn('text-sm text-[var(--lui-muted)]', className)} {...props} />;
}

export function CardContent({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>): React.JSX.Element {
  return <div className={cn('px-5 py-4', className)} {...props} />;
}

export function CardFooter({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>): React.JSX.Element {
  return (
    <div
      className={cn(
        'flex items-center gap-2 border-t border-[var(--lui-border)] px-5 py-4',
        className,
      )}
      {...props}
    />
  );
}

/** Alias for kit ≤0.3 code — same element as CardContent. */
export const CardBody = CardContent;
