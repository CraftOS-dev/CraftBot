import { cva, type VariantProps } from 'class-variance-authority';
import type { ButtonHTMLAttributes } from 'react';
import { cn } from '../lib/cn.ts';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 rounded-[var(--agent-app-radius)] text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--agent-app-ring)]',
  {
    variants: {
      // Both vocabularies are accepted: the kit's original names and the
      // shadcn names models write from training-data memory (kit 0.4.0).
      variant: {
        primary: 'bg-[var(--agent-app-accent)] text-[var(--agent-app-accent-contrast)] hover:opacity-90',
        default: 'bg-[var(--agent-app-accent)] text-[var(--agent-app-accent-contrast)] hover:opacity-90',
        secondary:
          'border border-[var(--agent-app-border)] bg-[var(--agent-app-surface)] hover:bg-[var(--agent-app-hover)]',
        outline:
          'border border-[var(--agent-app-border)] bg-transparent hover:bg-[var(--agent-app-hover)]',
        danger: 'bg-red-600 text-white hover:bg-red-700',
        destructive: 'bg-red-600 text-white hover:bg-red-700',
        ghost: 'hover:bg-[var(--agent-app-hover)]',
        link: 'text-[var(--agent-app-accent)] underline-offset-4 hover:underline',
      },
      size: {
        sm: 'h-8 px-3',
        md: 'h-9 px-4',
        default: 'h-9 px-4',
        lg: 'h-10 px-6',
        icon: 'size-9 p-0',
      },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  loading?: boolean | undefined;
}

export function Button({
  className,
  variant,
  size,
  loading = false,
  disabled,
  children,
  type,
  ...props
}: ButtonProps): React.JSX.Element {
  return (
    <button
      type={type ?? 'button'}
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled === true || loading}
      {...props}
    >
      {loading && (
        <span
          aria-hidden
          className="size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
        />
      )}
      {children}
    </button>
  );
}
