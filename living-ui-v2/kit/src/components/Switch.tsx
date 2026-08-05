import { cn } from '../lib/cn.ts';

export interface SwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label?: string | undefined;
  disabled?: boolean | undefined;
  id?: string | undefined;
  className?: string | undefined;
}

/** Boolean toggle (shadcn-conventional `checked`/`onCheckedChange` API). */
export function Switch({
  checked,
  onCheckedChange,
  label,
  disabled = false,
  id,
  className,
}: SwitchProps): React.JSX.Element {
  const toggle = (
    <button
      type="button"
      role="switch"
      id={id}
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--lui-accent)]',
        checked ? 'bg-[var(--lui-accent)]' : 'bg-[var(--lui-border)]',
        className,
      )}
    >
      <span
        className={cn(
          'inline-block h-4 w-4 rounded-full bg-white shadow transition-transform',
          checked ? 'translate-x-4' : 'translate-x-0.5',
        )}
      />
    </button>
  );

  if (label === undefined) return toggle;

  return (
    <div className="flex items-center gap-2">
      {toggle}
      <span
        className="cursor-pointer select-none text-sm font-medium"
        onClick={() => {
          if (!disabled) onCheckedChange(!checked);
        }}
      >
        {label}
      </span>
    </div>
  );
}
