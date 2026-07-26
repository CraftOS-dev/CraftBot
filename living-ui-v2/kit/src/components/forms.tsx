/**
 * Form input presets.
 *
 *   <NumberInput label="Position" value={n} onValue={setN} />
 *   <DateInput label="Due" value={iso} onValue={setIso} />
 *   <SearchInput placeholder="Search cards…" onSearch={setQuery} />
 *   <TagInput label="Labels" value={tags} onChange={setTags} />
 *
 * All values are wire-format: NumberInput emits number|null, DateInput emits
 * an ISO-8601-compatible string|null (what PocketBase date fields accept),
 * TagInput emits string[] (for json array fields).
 */
import { useEffect, useRef, useState } from 'react';
import { cn } from '../lib/cn.ts';
import { useDebounce } from '../lib/hooks.ts';
import { Input } from './Input.tsx';
import { SearchIcon, XIcon } from './icons.tsx';

export interface NumberInputProps {
  label?: string | undefined;
  error?: string | undefined;
  placeholder?: string | undefined;
  value: number | null;
  onValue: (value: number | null) => void;
  min?: number | undefined;
  max?: number | undefined;
  step?: number | undefined;
}

export function NumberInput({ value, onValue, ...rest }: NumberInputProps): React.JSX.Element {
  return (
    <Input
      type="number"
      value={value ?? ''}
      onChange={(e) => {
        const raw = e.target.value;
        onValue(raw === '' ? null : Number(raw));
      }}
      {...rest}
    />
  );
}

export interface DateInputProps {
  label?: string | undefined;
  error?: string | undefined;
  /** ISO-8601 string (backend wire format) or null. */
  value: string | null;
  onValue: (iso: string | null) => void;
  /** Date without time (uses the native date picker only). */
  dateOnly?: boolean | undefined;
}

export function DateInput({
  value,
  onValue,
  dateOnly = false,
  ...rest
}: DateInputProps): React.JSX.Element {
  // datetime-local wants "YYYY-MM-DDTHH:mm"; date wants "YYYY-MM-DD".
  const local = value !== null ? value.slice(0, dateOnly ? 10 : 16) : '';
  return (
    <Input
      type={dateOnly ? 'date' : 'datetime-local'}
      value={local}
      onChange={(e) => onValue(e.target.value !== '' ? e.target.value : null)}
      {...rest}
    />
  );
}

export interface SearchInputProps {
  placeholder?: string | undefined;
  /** Called with the debounced query ('' when cleared). */
  onSearch: (query: string) => void;
  delayMs?: number | undefined;
  label?: string | undefined;
  className?: string | undefined;
}

export function SearchInput({
  placeholder = 'Search…',
  onSearch,
  delayMs = 300,
  label,
  className,
}: SearchInputProps): React.JSX.Element {
  const [raw, setRaw] = useState('');
  const debounced = useDebounce(raw, delayMs);
  const onSearchRef = useRef(onSearch);
  onSearchRef.current = onSearch;

  useEffect(() => {
    onSearchRef.current(debounced.trim());
  }, [debounced]);

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      {label !== undefined && <span className="text-sm font-medium">{label}</span>}
      <div className="relative">
        <SearchIcon
          size={14}
          className="pointer-events-none absolute left-3 top-1/2 z-10 -translate-y-1/2 text-[var(--lui-muted)]"
        />
        <Input
          placeholder={placeholder}
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          className="pl-8"
          aria-label={label ?? 'Search'}
        />
      </div>
    </div>
  );
}

export interface TagInputProps {
  label?: string | undefined;
  value: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string | undefined;
}

export function TagInput({
  label,
  value,
  onChange,
  placeholder = 'Type and press Enter',
}: TagInputProps): React.JSX.Element {
  const [draft, setDraft] = useState('');

  const add = (): void => {
    const tag = draft.trim().replace(/,+$/, '');
    if (tag !== '' && !value.includes(tag)) onChange([...value, tag]);
    setDraft('');
  };

  return (
    <div className="flex flex-col gap-1.5">
      {label !== undefined && <span className="text-sm font-medium">{label}</span>}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {value.map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 rounded-full border border-[var(--lui-border)] bg-[var(--lui-border)]/40 px-2 py-0.5 text-xs text-[var(--lui-text)]"
            >
              {tag}
              <button
                type="button"
                className="inline-flex items-center text-[var(--lui-muted)] hover:text-[var(--lui-text)]"
                onClick={() => onChange(value.filter((t) => t !== tag))}
                aria-label={`Remove ${tag}`}
              >
                <XIcon size={11} />
              </button>
            </span>
          ))}
        </div>
      )}
      <Input
        placeholder={placeholder}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            add();
          } else if (e.key === 'Backspace' && draft === '' && value.length > 0) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={add}
      />
    </div>
  );
}
