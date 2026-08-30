import { cn } from '../lib/cn.ts';

export interface SpinnerProps {
  /** Diameter in px (default 16). */
  size?: number | undefined;
  className?: string | undefined;
}

/** Inline loading spinner (matches Button's loading glyph). */
export function Spinner({ size = 16, className }: SpinnerProps): React.JSX.Element {
  return (
    <span
      aria-hidden
      className={cn(
        'inline-block animate-spin rounded-full border-2 border-current border-t-transparent',
        className,
      )}
      style={{ width: size, height: size }}
    />
  );
}
