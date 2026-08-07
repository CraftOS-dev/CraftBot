/**
 * Schema-aware CRUD presets — derive a form/table from an explicit field
 * spec, save through the PB client seam, list live via useCollection.
 *
 *   const FIELDS: EntityField[] = [
 *     { name: 'title', type: 'text', required: true },
 *     { name: 'status', type: 'select', options: [{ value: 'todo', label: 'To do' }] },
 *     { name: 'columnId', type: 'ref', ref: { collection: 'columns', labelField: 'name' } },
 *   ];
 *
 *   // Create/edit form — right input per field type, required validation,
 *   // ref fields become dropdowns of the parent collection:
 *   <EntityForm collection="cards" fields={FIELDS} defaults={{ columnId: col.id }}
 *     onSaved={close} onCancel={close} />
 *   <EntityForm collection="cards" fields={FIELDS} initial={card} onSaved={close} />
 *
 *   // Live table with sortable headers, row actions and delete confirmation:
 *   <EntityTable collection="cards" columns={['title', 'status']}
 *     filter={`columnId = "${col.id}"`} onRowClick={openCard} allowDelete />
 *
 * There is no generated schema in this architecture (unlike kit ≤0.3): the
 * caller declares the fields/columns, so these presets stay decoupled from
 * any codegen step while keeping the one-component-per-CRUD-surface payoff.
 */
import { useState } from 'react';
import type { ReactNode } from 'react';
import type { RecordModel } from 'pocketbase';
import { cn } from '../lib/cn.ts';
import { getPbClient } from '../pb/client.ts';
import { useCollection } from '../pb/hooks.ts';
import type { CollectionQuery } from '../pb/hooks.ts';
import { Button } from './Button.tsx';
import { Input } from './Input.tsx';
import { Textarea } from './Textarea.tsx';
import { Select } from './Select.tsx';
import { Switch } from './Switch.tsx';
import { NumberInput, DateInput, TagInput } from './forms.tsx';
import { useConfirm } from './confirm.tsx';

export type EntityFieldType =
  | 'text'
  | 'textarea'
  | 'number'
  | 'boolean'
  | 'date'
  | 'datetime'
  | 'select'
  | 'ref'
  | 'tags';

export interface EntityField {
  /** Record key (PB field name). */
  name: string;
  /** Human label (default: derived from the name). */
  label?: string | undefined;
  type: EntityFieldType;
  required?: boolean | undefined;
  placeholder?: string | undefined;
  /** Options for type 'select'. */
  options?: ReadonlyArray<{ value: string; label: string }> | undefined;
  /** For type 'ref': the parent collection + which field labels each option. */
  ref?: { collection: string; labelField: string } | undefined;
}

/** camelCase / snake_case -> Title Case ("dueDate" -> "Due Date"). */
function labelOf(name: string): string {
  const spaced = name.replace(/[_-]+/g, ' ').replace(/([a-z0-9])([A-Z])/g, '$1 $2');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function emptyValue(type: EntityFieldType): unknown {
  if (type === 'tags') return [];
  if (type === 'boolean') return false;
  return null;
}

/** Dropdown of a ref field's parent collection, live via useCollection. */
function RefSelect({
  field,
  value,
  onValue,
  error,
}: {
  field: EntityField;
  value: string | null;
  onValue: (id: string | null) => void;
  error?: string | undefined;
}): React.JSX.Element {
  const ref = field.ref;
  const { records } = useCollection<RecordModel>(ref?.collection ?? '');
  const options =
    ref === undefined
      ? []
      : records.map((r) => ({
          value: r.id,
          label: String((r as Record<string, unknown>)[ref.labelField] ?? `#${r.id}`),
        }));
  return (
    <Select
      label={field.label ?? labelOf(field.name)}
      placeholder={`Select ${ref?.collection ?? 'item'}…`}
      options={options}
      value={value ?? ''}
      onChange={(e) => onValue(e.target.value !== '' ? e.target.value : null)}
      error={error}
    />
  );
}

export interface EntityFormProps {
  /** PocketBase collection name (e.g. "cards"). */
  collection: string;
  fields: ReadonlyArray<EntityField>;
  /** Edit mode when it has an id; values prefill the form. */
  initial?: (Record<string, unknown> & { id?: string | undefined }) | undefined;
  /** Prefilled values for create mode (e.g. the parent ref id). */
  defaults?: Record<string, unknown> | undefined;
  submitLabel?: string | undefined;
  /** Fires AFTER the record has been saved. Close/toast/navigate here only —
   * calling create/update in here would save AGAIN. */
  onSaved?: ((record: RecordModel) => void) | undefined;
  onCancel?: (() => void) | undefined;
}

export function EntityForm({
  collection,
  fields,
  initial,
  defaults,
  submitLabel,
  onSaved,
  onCancel,
}: EntityFormProps): React.JSX.Element {
  const editing = typeof initial?.id === 'string';

  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const v: Record<string, unknown> = {};
    for (const field of fields) {
      const preset = initial?.[field.name] ?? defaults?.[field.name];
      v[field.name] = preset !== undefined ? preset : emptyValue(field.type);
    }
    return v;
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (name: string, value: unknown): void =>
    setValues((prev) => ({ ...prev, [name]: value }));

  const submit = async (): Promise<void> => {
    const nextErrors: Record<string, string> = {};
    for (const field of fields) {
      if (field.required !== true) continue;
      const v = values[field.name];
      if (v === null || v === undefined || v === '') {
        nextErrors[field.name] = `${field.label ?? labelOf(field.name)} is required`;
      }
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    setBusy(true);
    setServerError(null);
    try {
      const client = getPbClient();
      const saved =
        editing && typeof initial?.id === 'string'
          ? await client.call((pb) => pb.collection(collection).update(initial.id as string, values))
          : await client.call((pb) => pb.collection(collection).create(values));
      onSaved?.(saved);
    } catch (e) {
      setServerError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const renderField = (field: EntityField): ReactNode => {
    const err = errors[field.name];
    const v = values[field.name];
    const label = field.label ?? labelOf(field.name);
    switch (field.type) {
      case 'select':
        return (
          <Select
            label={label}
            options={field.options ?? []}
            placeholder={field.required === true ? undefined : '—'}
            value={(v as string | null) ?? ''}
            onChange={(e) => set(field.name, e.target.value !== '' ? e.target.value : null)}
            error={err}
          />
        );
      case 'boolean':
        return <Switch label={label} checked={Boolean(v)} onCheckedChange={(c) => set(field.name, c)} />;
      case 'number':
        return (
          <NumberInput
            label={label}
            value={(v as number | null) ?? null}
            onValue={(n) => set(field.name, n)}
            error={err}
          />
        );
      case 'date':
      case 'datetime':
        return (
          <DateInput
            label={label}
            value={(v as string | null) ?? null}
            onValue={(iso) => set(field.name, iso)}
            dateOnly={field.type === 'date'}
            error={err}
          />
        );
      case 'tags':
        return (
          <TagInput
            label={label}
            value={Array.isArray(v) ? (v as string[]) : []}
            onChange={(tags) => set(field.name, tags)}
          />
        );
      case 'ref':
        return (
          <RefSelect
            field={field}
            value={(v as string | null) ?? null}
            onValue={(id) => set(field.name, id)}
            error={err}
          />
        );
      case 'textarea':
        return (
          <Textarea
            label={label}
            value={(v as string | null) ?? ''}
            onChange={(e) => set(field.name, e.target.value)}
            error={err}
            rows={3}
          />
        );
      default:
        return (
          <Input
            label={label}
            placeholder={field.placeholder}
            value={(v as string | null) ?? ''}
            onChange={(e) => set(field.name, e.target.value)}
            error={err}
          />
        );
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {fields.map((field) => (
        <div key={field.name}>{renderField(field)}</div>
      ))}
      {serverError !== null && <p className="text-xs text-red-500">{serverError}</p>}
      <div className="mt-1 flex justify-end gap-2">
        {onCancel !== undefined && (
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        )}
        <Button variant="primary" onClick={() => void submit()} loading={busy}>
          {submitLabel ?? (editing ? 'Save' : 'Create')}
        </Button>
      </div>
    </div>
  );
}

export interface EntityColumn {
  field: string;
  label?: string | undefined;
  /** Custom cell renderer; receives the raw value and the whole record. */
  render?: ((value: unknown, record: RecordModel) => ReactNode) | undefined;
}

export interface EntityTableProps {
  /** PocketBase collection name. */
  collection: string;
  /** Columns to show — a field name string, or an EntityColumn for control. */
  columns: ReadonlyArray<EntityColumn | string>;
  /** PB filter expression, e.g. `columnId = "abc"`. */
  filter?: string | undefined;
  /** PB sort expression used until a header is clicked, e.g. `-created`. */
  sort?: string | undefined;
  expand?: string | undefined;
  onRowClick?: ((record: RecordModel) => void) | undefined;
  /** Extra cell(s) rendered at the end of each row. */
  rowActions?: ((record: RecordModel) => ReactNode) | undefined;
  /** Adds a Delete action with a confirmation dialog. */
  allowDelete?: boolean | undefined;
  emptyMessage?: string | undefined;
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? '✓' : '—';
  if (Array.isArray(value)) return value.join(', ');
  return String(value);
}

export function EntityTable({
  collection,
  columns,
  filter,
  sort,
  expand,
  onRowClick,
  rowActions,
  allowDelete = false,
  emptyMessage,
}: EntityTableProps): React.JSX.Element {
  const cols: EntityColumn[] = columns.map((c) => (typeof c === 'string' ? { field: c } : c));
  const [sortField, setSortField] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [confirmEl, confirm] = useConfirm();

  const effectiveSort =
    sortField !== null ? `${sortDir === 'desc' ? '-' : ''}${sortField}` : sort;

  const query: CollectionQuery = {};
  if (filter !== undefined) query.filter = filter;
  if (effectiveSort !== undefined) query.sort = effectiveSort;
  if (expand !== undefined) query.expand = expand;
  const { records, loading, error, refresh } = useCollection<RecordModel>(collection, query);

  const toggleSort = (field: string): void => {
    if (sortField === field) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortField(field);
      setSortDir('asc');
    }
  };

  const handleDelete = async (record: RecordModel): Promise<void> => {
    if (!(await confirm('Delete this item?'))) return;
    try {
      await getPbClient().call((pb) => pb.collection(collection).delete(record.id));
      refresh();
    } catch {
      /* surfaced by the shell's PB error handler */
    }
  };

  const hasActions = rowActions !== undefined || allowDelete;

  return (
    <div className="flex flex-col gap-3">
      {error !== null && <p className="text-xs text-red-500">{error}</p>}
      {loading ? (
        <p className="px-6 py-10 text-center text-sm text-[var(--lui-muted)]">Loading…</p>
      ) : records.length === 0 ? (
        <div className="flex flex-col items-center gap-1 px-6 py-10 text-center">
          <p className="text-sm text-[var(--lui-muted)]">{emptyMessage ?? 'Nothing here yet.'}</p>
        </div>
      ) : (
        <div className="w-full overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-[var(--lui-border)] text-left">
                {cols.map((col) => (
                  <th
                    key={col.field}
                    onClick={() => toggleSort(col.field)}
                    className="cursor-pointer select-none whitespace-nowrap px-4 py-2.5 font-medium text-[var(--lui-muted)] hover:text-[var(--lui-text)]"
                  >
                    {col.label ?? labelOf(col.field)}
                    {sortField === col.field ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}
                  </th>
                ))}
                {hasActions && <th className="px-4 py-2.5" />}
              </tr>
            </thead>
            <tbody>
              {records.map((row) => (
                <tr
                  key={row.id}
                  onClick={onRowClick !== undefined ? () => onRowClick(row) : undefined}
                  className={cn(
                    'border-b border-[var(--lui-border)] last:border-0',
                    onRowClick !== undefined && 'cursor-pointer hover:bg-[var(--lui-border)]/20',
                  )}
                >
                  {cols.map((col) => {
                    const raw = (row as Record<string, unknown>)[col.field];
                    return (
                      <td key={col.field} className="px-4 py-2.5">
                        {col.render !== undefined ? col.render(raw, row) : formatCell(raw)}
                      </td>
                    );
                  })}
                  {hasActions && (
                    <td className="px-4 py-2.5 text-right">
                      <span
                        className="inline-flex justify-end gap-1"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {rowActions?.(row)}
                        {allowDelete && (
                          <Button size="sm" variant="ghost" onClick={() => void handleDelete(row)}>
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
      )}
      {confirmEl}
    </div>
  );
}
