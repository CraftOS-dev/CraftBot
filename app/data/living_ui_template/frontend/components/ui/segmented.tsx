/**
 * SegmentedControl (SYSTEM-MANAGED — do not edit)
 *
 * Compact exclusive choice — THE filter control for enum fields:
 *
 *   <SegmentedControl
 *     options={[{ value: 'all', label: 'All' }, { value: 'todo', label: 'To do' },
 *               { value: 'done', label: 'Done' }]}
 *     value={status}
 *     onChange={setStatus}
 *   />
 */

export interface SegmentedOption {
  value: string
  label: string
}

export interface SegmentedControlProps {
  options: SegmentedOption[]
  value: string
  onChange: (value: string) => void
  size?: 'sm' | 'md'
}

export function SegmentedControl({ options, value, onChange, size = 'md' }: SegmentedControlProps) {
  return (
    <div
      role="radiogroup"
      style={{
        display: 'inline-flex',
        padding: 2,
        gap: 2,
        backgroundColor: 'var(--bg-tertiary)',
        border: '1px solid var(--border-primary)',
        borderRadius: 'var(--radius-md)',
      }}
    >
      {options.map(opt => {
        const active = opt.value === value
        return (
          <button
            key={opt.value}
            role="radio"
            aria-checked={active}
            onClick={() => onChange(opt.value)}
            className={active ? '' : 'hover:text-ink'}
            style={{
              padding:
                size === 'sm' ? '2px var(--space-2)' : 'var(--space-1) var(--space-3)',
              fontSize: size === 'sm' ? 'var(--font-size-xs)' : 'var(--font-size-sm)',
              fontFamily: 'var(--font-sans)',
              fontWeight: 'var(--font-weight-medium)' as any,
              color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
              backgroundColor: active ? 'var(--bg-secondary)' : 'transparent',
              border: '1px solid',
              borderColor: active ? 'var(--border-primary)' : 'transparent',
              borderRadius: 'var(--radius-sm)',
              boxShadow: active ? 'var(--shadow-sm)' : 'none',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              transition: 'var(--transition-fast)',
            }}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}
