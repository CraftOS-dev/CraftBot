/**
 * Form input presets (SYSTEM-MANAGED — do not edit)
 *
 *   <NumberInput label="Position" value={n} onValue={setN} />
 *   <DateInput label="Due" value={iso} onValue={setIso} />
 *   <SearchInput placeholder="Search cards…" onSearch={setQuery} />
 *   <TagInput label="Labels" value={tags} onChange={setTags} />
 *
 * All values are wire-format: NumberInput emits number|null, DateInput
 * emits an ISO-8601-compatible string|null (what the backend's datetime
 * fields accept), TagInput emits string[] (for json array fields).
 */

import { useEffect, useState } from 'react'
import { Input } from './index'
import { useDebounce } from './hooks'
import { Search, X } from 'lucide-react'

export interface NumberInputProps {
  label?: string
  error?: string
  hint?: string
  placeholder?: string
  value: number | null
  onValue: (value: number | null) => void
  min?: number
  max?: number
  step?: number
}

export function NumberInput({ value, onValue, ...rest }: NumberInputProps) {
  return (
    <Input
      type="number"
      value={value ?? ''}
      onChange={e => {
        const raw = e.target.value
        onValue(raw === '' ? null : Number(raw))
      }}
      {...rest}
    />
  )
}

export interface DateInputProps {
  label?: string
  error?: string
  hint?: string
  /** ISO-8601 string (backend wire format) or null */
  value: string | null
  onValue: (iso: string | null) => void
  /** Date without time (uses the native date picker only). */
  dateOnly?: boolean
}

export function DateInput({ value, onValue, dateOnly = false, ...rest }: DateInputProps) {
  // datetime-local wants "YYYY-MM-DDTHH:mm"; date wants "YYYY-MM-DD"
  const local = value ? value.slice(0, dateOnly ? 10 : 16) : ''
  return (
    <Input
      type={dateOnly ? 'date' : 'datetime-local'}
      value={local}
      onChange={e => onValue(e.target.value ? e.target.value : null)}
      {...rest}
    />
  )
}

export interface SearchInputProps {
  placeholder?: string
  /** Called with the debounced query ('' when cleared). */
  onSearch: (query: string) => void
  delayMs?: number
  label?: string
}

export function SearchInput({
  placeholder = 'Search…',
  onSearch,
  delayMs = 300,
  label,
}: SearchInputProps) {
  const [raw, setRaw] = useState('')
  const debounced = useDebounce(raw, delayMs)
  useEffect(() => {
    onSearch(debounced.trim())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced])
  // The label renders OUTSIDE the relative wrapper so the icon centers on
  // the input itself, not on the label+input stack.
  return (
    <div className="flex flex-col gap-1">
      {label && (
        <span className="text-ink text-sm font-medium">{label}</span>
      )}
      <div className="relative">
        <Search
          size={14}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted pointer-events-none z-10"
        />
        <Input
          placeholder={placeholder}
          value={raw}
          onChange={e => setRaw(e.target.value)}
          style={{ paddingLeft: 32 }}
          aria-label={label ?? 'Search'}
        />
      </div>
    </div>
  )
}

export interface TagInputProps {
  label?: string
  hint?: string
  value: string[]
  onChange: (tags: string[]) => void
  placeholder?: string
}

export function TagInput({
  label,
  hint,
  value,
  onChange,
  placeholder = 'Type and press Enter',
}: TagInputProps) {
  const [draft, setDraft] = useState('')

  const add = () => {
    const tag = draft.trim().replace(/,+$/, '')
    if (tag && !value.includes(tag)) onChange([...value, tag])
    setDraft('')
  }

  return (
    <div className="flex flex-col gap-1">
      {label && <span className="text-ink-secondary text-xs font-semibold">{label}</span>}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {value.map(tag => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 bg-raised border border-line rounded-full px-2 py-0.5 text-xs text-ink"
            >
              {tag}
              <button
                type="button"
                className="bg-transparent border-0 p-0 cursor-pointer text-ink-muted hover:text-ink flex items-center"
                onClick={() => onChange(value.filter(t => t !== tag))}
                aria-label={`Remove ${tag}`}
              >
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
      )}
      <Input
        placeholder={placeholder}
        value={draft}
        onChange={e => setDraft(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault()
            add()
          } else if (e.key === 'Backspace' && !draft && value.length) {
            onChange(value.slice(0, -1))
          }
        }}
        onBlur={add}
        hint={hint}
      />
    </div>
  )
}
