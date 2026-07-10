/**
 * Schema-aware presets (SYSTEM-MANAGED — do not edit)
 *
 * These derive the UI from config/schema.json (via the generated
 * schema.gen.ts), so the most common components cost ONE line:
 *
 *   // Create/edit form — right input per field type, required validation,
 *   // ref fields become dropdowns of the parent entity, saves via the
 *   // generated API:
 *   <EntityForm entity="Card" defaults={{ columnId: col.id }} onSaved={...} onCancel={...} />
 *   <EntityForm entity="Card" initial={card} onSaved={...} />   // edit mode
 *
 *   // Sortable data table with row actions and delete confirmation:
 *   <EntityTable<Card> entity="Card" filters={{ columnId: col.id }}
 *     columns={['title', 'dueDate']} onRowClick={openCard} allowDelete />
 *
 * `entity` is the SCHEMA name (PascalCase, e.g. "Card"), not the route
 * plural. Hide fields with `exclude`; add custom inputs by building your
 * own form instead — these presets cover the standard case.
 */

import React, { useEffect, useMemo, useState } from 'react'
import { Button, Input, Select, Textarea, Toggle, EmptyState, Pagination } from './index'
import { NumberInput, DateInput, TagInput, SearchInput } from './forms'
import { useConfirm } from './confirm'
import { data, useEntities } from '../../services/data'
import { ENTITIES } from '../../schema.gen'
import type { EntityName } from '../../schema.gen'

interface FieldMeta {
  type: string
  required?: boolean
  values?: readonly string[]
  entity?: string
}

interface EntityMeta {
  plural: string
  fields: Record<string, FieldMeta>
}

const ENTITY_META = ENTITIES as unknown as Record<string, EntityMeta>

function metaFor(entity: string): EntityMeta {
  const meta = ENTITY_META[entity]
  if (!meta) {
    // The #1 mixup: passing the ROUTE PLURAL (useEntities' identifier)
    // where the SCHEMA NAME belongs. Name the correct value in the error.
    const byPlural = Object.entries(ENTITY_META).find(
      ([, m]) => m.plural === entity,
    )
    const hint = byPlural
      ? ` — "${entity}" is the route plural (used by useEntities); the ` +
        `entity prop takes the SCHEMA name: use entity="${byPlural[0]}"`
      : ' — declare it in config/schema.json. Valid names: ' +
        (Object.keys(ENTITY_META).join(', ') || '(none)')
    throw new Error(`EntityForm/EntityTable: unknown entity "${entity}"${hint}`)
  }
  return meta
}

/** camelCase -> Title Case ("dueDate" -> "Due Date") */
function labelOf(field: string): string {
  const spaced = field.replace(/([a-z0-9])([A-Z])/g, '$1 $2')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

function emptyValue(f: FieldMeta): unknown {
  if (f.type === 'json') return []
  if (f.type === 'boolean') return false
  if (f.type === 'enum') return f.required ? f.values?.[0] ?? null : null
  return null
}

/** Dropdown of a ref field's parent entity (label = first stringish field). */
function RefSelect({
  field,
  meta,
  value,
  onValue,
  error,
}: {
  field: string
  meta: FieldMeta
  value: number | null
  onValue: (id: number | null) => void
  error?: string
}) {
  const parent = meta.entity ? ENTITY_META[meta.entity] : undefined
  const [options, setOptions] = useState<{ value: string; label: string }[]>([])
  useEffect(() => {
    if (!parent) return
    let alive = true
    data
      .list<Record<string, unknown> & { id: number }>(parent.plural)
      .then(rows => {
        if (!alive) return
        const labelField = Object.entries(parent.fields).find(
          ([, f]) => f.type === 'string' || f.type === 'text',
        )?.[0]
        setOptions(
          rows.map(r => ({
            value: String(r.id),
            label: labelField ? String(r[labelField] ?? `#${r.id}`) : `#${r.id}`,
          })),
        )
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [meta.entity])
  return (
    <Select
      label={labelOf(field)}
      options={options}
      placeholder={`Select ${meta.entity ?? 'item'}…`}
      value={value === null ? '' : String(value)}
      onChange={e => onValue(e.target.value === '' ? null : Number(e.target.value))}
      error={error}
    />
  )
}

/** Keeps T inferable only from typed usage (e.g. onSaved), so plain
 * object literals in `defaults`/`initial` never pin T to the constraint. */
type NoInferT<T> = [T][T extends unknown ? 0 : never]

export interface EntityFormProps<T> {
  /** Schema entity NAME, e.g. "Card" (NOT the route plural — that is
   * useEntities' identifier). Typed against the schema: a wrong value is
   * a compile error. */
  entity: EntityName
  /** Edit mode when it has an id; values prefill the form. */
  initial?: Partial<NoInferT<T>> & { id?: number }
  /** Prefilled values for create mode (e.g. the parent ref id). */
  defaults?: Partial<NoInferT<T>>
  /** Field names to hide (they submit from defaults/initial unchanged). */
  exclude?: string[]
  submitLabel?: string
  /** Fires AFTER EntityForm has ALREADY saved, with the saved item (id set).
   * Use it to close the modal / toast / navigate ONLY — calling
   * create/update in here saves AGAIN and duplicates the record. */
  onSaved?: (item: T) => void
  onCancel?: () => void
}

export function EntityForm<T extends { id: number } = any>({
  entity,
  initial,
  defaults,
  exclude = [],
  submitLabel,
  onSaved,
  onCancel,
}: EntityFormProps<T>) {
  const meta = metaFor(entity)
  const editing = initial?.id !== undefined

  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const v: Record<string, unknown> = {}
    for (const [field, f] of Object.entries(meta.fields)) {
      const preset =
        (initial as Record<string, unknown> | undefined)?.[field] ??
        (defaults as Record<string, unknown> | undefined)?.[field]
      v[field] = preset !== undefined ? preset : emptyValue(f)
    }
    return v
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [serverError, setServerError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const set = (field: string, value: unknown) =>
    setValues(prev => ({ ...prev, [field]: value }))

  const submit = async () => {
    const nextErrors: Record<string, string> = {}
    for (const [field, f] of Object.entries(meta.fields)) {
      if (!f.required || exclude.includes(field)) continue
      const v = values[field]
      if (v === null || v === undefined || v === '') {
        nextErrors[field] = `${labelOf(field)} is required`
      }
    }
    setErrors(nextErrors)
    if (Object.keys(nextErrors).length > 0) return
    setBusy(true)
    setServerError(null)
    try {
      const saved = editing
        ? await data.update<T>(meta.plural, initial!.id!, values as Partial<T>)
        : await data.create<T>(meta.plural, values as Partial<T>)
      onSaved?.(saved)
    } catch (e) {
      setServerError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const renderField = (field: string, f: FieldMeta) => {
    const err = errors[field]
    const v = values[field]
    switch (f.type) {
      case 'enum':
        return (
          <Select
            label={labelOf(field)}
            options={(f.values ?? []).map(x => ({ value: x, label: x }))}
            placeholder={f.required ? undefined : '—'}
            value={(v as string) ?? ''}
            onChange={e => set(field, e.target.value === '' ? null : e.target.value)}
            error={err}
          />
        )
      case 'boolean':
        return (
          <Toggle
            label={labelOf(field)}
            checked={Boolean(v)}
            onChange={checked => set(field, checked)}
          />
        )
      case 'integer':
      case 'float':
        return (
          <NumberInput
            label={labelOf(field)}
            value={(v as number) ?? null}
            onValue={n => set(field, n)}
            error={err}
          />
        )
      case 'datetime':
        return (
          <DateInput
            label={labelOf(field)}
            value={(v as string) ?? null}
            onValue={iso => set(field, iso)}
            error={err}
          />
        )
      case 'json':
        return (
          <TagInput
            label={labelOf(field)}
            value={Array.isArray(v) ? (v as string[]) : []}
            onChange={tags => set(field, tags)}
          />
        )
      case 'ref':
        return (
          <RefSelect
            field={field}
            meta={f}
            value={(v as number) ?? null}
            onValue={id => set(field, id)}
            error={err}
          />
        )
      case 'text':
        return (
          <Textarea
            label={labelOf(field)}
            value={(v as string) ?? ''}
            onChange={e => set(field, e.target.value)}
            error={err}
            rows={3}
          />
        )
      default:
        return (
          <Input
            label={labelOf(field)}
            value={(v as string) ?? ''}
            onChange={e => set(field, e.target.value)}
            error={err}
          />
        )
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {Object.entries(meta.fields)
        .filter(([field]) => !exclude.includes(field))
        .map(([field, f]) => (
          <div key={field}>{renderField(field, f)}</div>
        ))}
      {serverError && <p className="text-error text-xs m-0">{serverError}</p>}
      <div className="flex justify-end gap-2 mt-1">
        {onCancel && (
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        )}
        <Button variant="primary" onClick={submit} loading={busy}>
          {submitLabel ?? (editing ? 'Save' : 'Create')}
        </Button>
      </div>
    </div>
  )
}

export interface EntityTableProps<T> {
  /** Schema entity NAME, e.g. "Card" (NOT the route plural — that is
   * useEntities' identifier). Typed against the schema: a wrong value is
   * a compile error. */
  entity: EntityName
  /** Equality filters passed to the generated list endpoint. */
  filters?: Record<string, string | number | boolean>
  /** Which fields to show (default: all schema fields). */
  columns?: string[]
  onRowClick?: (item: T) => void
  /** Extra cell rendered at the end of each row. */
  actions?: (item: T, refresh: () => Promise<void>) => React.ReactNode
  /** Adds a Delete action with a confirmation dialog. */
  allowDelete?: boolean
  emptyMessage?: string
  /** Adds a search box wired to the list endpoint's ?q= param. */
  searchable?: boolean
  /** Enables server-side paging (limit/offset) with this page size. */
  pageSize?: number
}

function cell(value: unknown, type: string): string {
  if (value === null || value === undefined) return '—'
  if (type === 'boolean') return value ? '✓' : '—'
  if (type === 'datetime') return new Date(String(value)).toLocaleString()
  if (type === 'json')
    return Array.isArray(value) ? value.join(', ') : JSON.stringify(value)
  return String(value)
}

export function EntityTable<T extends { id: number } = any>({
  entity,
  filters,
  columns,
  onRowClick,
  actions,
  allowDelete = false,
  emptyMessage,
  searchable = false,
  pageSize,
}: EntityTableProps<T>) {
  const meta = metaFor(entity)
  const cols = columns ?? Object.keys(meta.fields)
  const [orderBy, setOrderBy] = useState<string | null>(null)
  const [order, setOrder] = useState<'asc' | 'desc'>('asc')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(0)
  const [confirmEl, confirm] = useConfirm()

  const params = useMemo(
    () => ({
      ...(filters ?? {}),
      ...(orderBy ? { orderBy, order } : {}),
      ...(query ? { q: query } : {}),
      ...(pageSize ? { limit: pageSize, offset: page * pageSize } : {}),
    }),
    [JSON.stringify(filters ?? {}), orderBy, order, query, page, pageSize],
  )
  const store = useEntities<T>(meta.plural, params)

  const sort = (field: string) => {
    if (orderBy === field) setOrder(o => (o === 'asc' ? 'desc' : 'asc'))
    else {
      setOrderBy(field)
      setOrder('asc')
    }
  }

  const search = searchable ? (
    <SearchInput
      placeholder={`Search ${meta.plural.replace(/_/g, ' ')}…`}
      onSearch={q => {
        setQuery(q)
        setPage(0)
      }}
    />
  ) : null

  if (!store.loading && store.items.length === 0 && page === 0) {
    return (
      <div className="flex flex-col gap-3">
        {search}
        <EmptyState
          message={
            query
              ? `No ${meta.plural.replace(/_/g, ' ')} match "${query}".`
              : emptyMessage ?? `No ${meta.plural.replace(/_/g, ' ')} yet.`
          }
        />
        {confirmEl}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {search}
      <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            {cols.map(field => (
              <th
                key={field}
                onClick={() => sort(field)}
                className="text-left text-ink-secondary font-semibold text-xs uppercase tracking-wide px-3 py-2 border-b border-line cursor-pointer select-none whitespace-nowrap"
              >
                {labelOf(field)}
                {orderBy === field ? (order === 'asc' ? ' ↑' : ' ↓') : ''}
              </th>
            ))}
            {(actions || allowDelete) && (
              <th className="px-3 py-2 border-b border-line" />
            )}
          </tr>
        </thead>
        <tbody>
          {store.items.map(item => (
            <tr
              key={item.id}
              onClick={onRowClick ? () => onRowClick(item) : undefined}
              className={
                'border-b border-line ' +
                (onRowClick ? 'cursor-pointer hover:bg-raised ' : '')
              }
            >
              {cols.map(field => {
                const text = cell(
                  (item as Record<string, unknown>)[field],
                  meta.fields[field]?.type ?? 'string',
                )
                return (
                  <td key={field} className="px-3 py-2 text-ink">
                    <div className="max-w-xs truncate" title={text}>
                      {text}
                    </div>
                  </td>
                )
              })}
              {(actions || allowDelete) && (
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <span onClick={e => e.stopPropagation()} className="inline-flex gap-1">
                    {actions?.(item, store.refresh)}
                    {allowDelete && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={async () => {
                          if (await confirm('Delete this item?')) {
                            await store.remove(item.id)
                          }
                        }}
                      >
                        Delete
                      </Button>
                    )}
                  </span>
                </td>
              )}
            </tr>
          ))}
        </tbody>
        </table>
      </div>
      {pageSize !== undefined && (
        <Pagination
          page={page}
          onPage={setPage}
          hasNext={store.items.length === pageSize}
          pageSize={pageSize}
        />
      )}
      {store.error && <p className="text-error text-xs">{store.error}</p>}
      {confirmEl}
    </div>
  )
}
