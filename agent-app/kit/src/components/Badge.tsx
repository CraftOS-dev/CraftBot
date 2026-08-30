import { cva, type VariantProps } from 'class-variance-authority';
import type { HTMLAttributes } from 'react';
import { cn } from '../lib/cn.ts';

const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-[var(--lui-accent)] text-[var(--lui-accent-contrast)]',
        secondary: 'border-transparent bg-[var(--lui-border)]/60 text-[var(--lui-text)]',
        destructive: 'border-transparent bg-red-600 text-white',
        outline: 'border-[var(--lui-border)] text-[var(--lui-text)]',
      },
    },
    defaultVariants: { variant: 'default' },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

/** Small status pill (shadcn-conventional API). */
export function Badge({ className, variant, ...props }: BadgeProps): React.JSX.Element {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
