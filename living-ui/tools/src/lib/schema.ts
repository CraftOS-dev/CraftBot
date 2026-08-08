/**
 * Client-side view of an app, read through the A2APP surface (spec Phase 2 C5).
 *
 * ── Why this reads /api/_a2app/describe and not /api/collections ──
 * `/api/collections` is PocketBase's ADMIN endpoint: superuser only. Using it
 * made this CLI a privileged client that no third-party agent could imitate,
 * which is exactly the "vendor keeps the valuable half" failure the whole
 * design is meant to avoid. `describe` is the public surface, it speaks
 * protocol types rather than PocketBase's, and anything this CLI can do with
 * it, any agent can.
 *
 * ── Division of labour with the in-app guard ──
 *   CLI  — COERCES. Only side with a real clock, timezone database and `Intl`,
 *          and the only one that can look a label up. PocketBase's JS VM has
 *          none of those (spec §3.1).
 *   App  — VALIDATES. The only layer every caller passes through.
 *
 * So this file makes a well-formed request; it does not re-implement the rules.
 */
import { request, type ProjectRef } from './project.ts';

/** A field as `describe` reports it — protocol types, not PocketBase's. */
export interface Field {
  name: string;
  type: string; // string | number | boolean | datetime | enum | ref | list<…> | json | binary
  required?: boolean;
  readOnly?: boolean;
  max?: number;
  values?: string[];
  entity?: string; // target entity for ref / list<ref>
  format?: string; // e.g. YYYY-MM-DD for day-key fields
}

export interface Entity {
  name: string;
  label: string | null;
  auth?: boolean;
  fields: Field[];
  records: string;
}

export type Schema = Map<string, Entity>;

interface DescribeResponse {
  entities?: Record<
    string,
    {
      label: string | null;
      auth?: boolean;
      records: string;
      fields: Record<string, Omit<Field, 'name'>>;
    }
  >;
}

/** Read the app's data model from the A2APP surface. */
export async function fetchSchema(project: ProjectRef): Promise<Schema> {
  const out: Schema = new Map();
  const res = await request(project, 'GET', '/api/_a2app/describe');
  if (res.status >= 300) return out; // app predates the adapter — callers degrade

  const parsed = JSON.parse(res.body) as DescribeResponse;
  for (const [name, entity] of Object.entries(parsed.entities ?? {})) {
    out.set(name, {
      name,
      label: entity.label,
      auth: entity.auth === true,
      records: entity.records,
      fields: Object.entries(entity.fields ?? {}).map(([fieldName, spec]) => ({
        name: fieldName,
        ...spec,
      })),
    });
  }
  return out;
}

/** Compact, one line per entity — for error messages and `data <dir> schema`. */
export function describe(schema: Schema): string {
  const lines: string[] = [];
  for (const [name, entity] of schema) {
    const fields = entity.fields
      .filter((f) => !f.readOnly)
      .map((f) => {
        const type = f.entity !== undefined ? `->${f.entity}` : f.type;
        return `${f.name}(${type}${f.required === true ? '*' : ''})`;
      })
      .join(' ');
    lines.push(`  ${name}: ${fields}`);
  }
  return lines.join('\n');
}

/** Cheap did-you-mean (Levenshtein under a small threshold). */
export function suggest(input: string, candidates: string[]): string | null {
  const distance = (a: string, b: string): number => {
    const prev = Array.from({ length: b.length + 1 }, (_, i) => i);
    for (let i = 1; i <= a.length; i++) {
      let last = prev[0]!;
      prev[0] = i;
      for (let j = 1; j <= b.length; j++) {
        const tmp = prev[j]!;
        prev[j] = Math.min(prev[j]! + 1, prev[j - 1]! + 1, last + (a[i - 1] === b[j - 1] ? 0 : 1));
        last = tmp;
      }
    }
    return prev[b.length]!;
  };
  let best: string | null = null;
  let bestScore = Infinity;
  for (const candidate of candidates) {
    const d = distance(input.toLowerCase(), candidate.toLowerCase());
    if (d < bestScore) [best, bestScore] = [candidate, d];
  }
  return bestScore <= Math.max(2, Math.floor(input.length / 3)) ? best : null;
}

const DAYS = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];

/** Local calendar date in the host's timezone, as YYYY-MM-DD.
 *  Deliberately NOT toISOString(), which is UTC and shifts the day near
 *  midnight — the exact bug class this effort exists to remove. Node has full
 *  Intl; PocketBase's VM does not (spec §3.1), which is why this lives here. */
function localYmd(d: Date): string {
  return new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(d);
}

/** Natural or absolute date → a PocketBase datetime, or null if unparseable. */
export function parseDate(value: string, now: Date = new Date()): string | null {
  const s = value.trim().toLowerCase();
  if (s === '') return '';
  if (/^\d{4}-\d{2}-\d{2}/.test(value.trim())) return value.trim();

  const shift = (days: number): string => {
    const d = new Date(now);
    d.setDate(d.getDate() + days);
    return `${localYmd(d)} 00:00:00.000Z`;
  };

  if (s === 'today' || s === 'now') return shift(0);
  if (s === 'tomorrow') return shift(1);
  if (s === 'yesterday') return shift(-1);

  let m = /^(?:in )?([+-]?\d+) ?(d|day|days|w|week|weeks|m|month|months)$/.exec(s);
  if (m) {
    const n = Number(m[1]);
    const unit = m[2]!;
    return shift(unit.startsWith('w') ? n * 7 : unit.startsWith('m') ? n * 30 : n);
  }

  m = /^(?:next |this |on )?([a-z]+)$/.exec(s);
  if (m) {
    const word = m[1]!;
    if (word === 'week') return shift(7);
    if (word === 'month') return shift(30);
    const target = DAYS.indexOf(word);
    if (target >= 0) return shift(((target - now.getDay() + 7) % 7) || 7);
  }
  return null;
}

/** Day-key fields are plain text with a declared YYYY-MM-DD format. */
function isDayKey(field: Field): boolean {
  return field.type === 'string' && field.format === 'YYYY-MM-DD';
}

export interface RefResolution {
  id?: string;
  error?: string;
}

/** "To Do" → a record id. Ambiguity is an error listing the candidates, never
 *  a guess: across the shipped apps NO relation field has a unique index on its
 *  label, so a multi-match is the normal case, not an edge one (spec §3.6). */
export async function resolveRef(
  project: ProjectRef,
  schema: Schema,
  targetName: string,
  value: string
): Promise<RefResolution> {
  if (/^[a-z0-9]{15}$/.test(value)) return { id: value };
  const target = schema.get(targetName);
  if (target === undefined || target.label === null) return { id: value };
  const label = target.label;

  const filter = encodeURIComponent(`${label}="${value.replace(/"/g, '\\"')}"`);
  const res = await request(project, 'GET', `${target.records}?perPage=10&filter=${filter}`);
  if (res.status >= 300) return { id: value };
  const items = (JSON.parse(res.body) as { items?: Record<string, unknown>[] }).items ?? [];

  if (items.length === 1) return { id: String(items[0]!['id']) };
  if (items.length === 0) {
    const all = await request(project, 'GET', `${target.records}?perPage=25`);
    const names = ((JSON.parse(all.body) as { items?: Record<string, unknown>[] }).items ?? [])
      .map((r) => String(r[label] ?? ''))
      .filter(Boolean);
    return {
      error: `no ${targetName} with ${label}="${value}"${names.length ? ` — existing: ${names.join(', ')}` : ''}`,
    };
  }
  return {
    error: `"${value}" matches ${items.length} ${targetName} records — pass an id instead: ${items
      .map((r) => String(r['id']))
      .join(', ')}`,
  };
}

/** Coerce a write body: human dates → ISO, relation labels → ids.
 *  Unknown fields and bad values are left alone — the app rejects those, and it
 *  must, because it is the only layer every caller goes through. */
export async function coerceBody(
  project: ProjectRef,
  schema: Schema,
  entityName: string,
  body: Record<string, unknown>
): Promise<{ body: Record<string, unknown>; errors: string[] }> {
  const entity = schema.get(entityName);
  if (entity === undefined) return { body, errors: [] };
  const byName = new Map(entity.fields.map((f) => [f.name, f]));
  const out: Record<string, unknown> = { ...body };
  const errors: string[] = [];

  for (const [key, value] of Object.entries(body)) {
    const field = byName.get(key);
    if (field === undefined || typeof value !== 'string' || value === '') continue;

    if (field.type === 'datetime' || isDayKey(field)) {
      const parsed = parseDate(value);
      if (parsed === null) {
        errors.push(`--${key} "${value}" is not a date. Try an ISO date, or today/tomorrow/in 3 days/next monday.`);
      } else {
        out[key] = isDayKey(field) ? parsed.slice(0, 10) : parsed;
      }
      continue;
    }

    if (field.type === 'ref' && field.entity !== undefined) {
      const resolved = await resolveRef(project, schema, field.entity, value);
      if (resolved.error !== undefined) errors.push(`--${key}: ${resolved.error}`);
      else if (resolved.id !== undefined) out[key] = resolved.id;
    }
  }
  return { body: out, errors };
}

/** Fallback for apps whose adapter predates the write guard: which non-blank
 *  requested values are missing or empty in what came back? */
export function droppedFields(sent: Record<string, unknown>, saved: Record<string, unknown>): string[] {
  const out: string[] = [];
  for (const [key, value] of Object.entries(sent)) {
    if (value === '' || value === null || value === undefined) continue;
    const stored = saved[key];
    if (stored === undefined || stored === '' || stored === null) out.push(key);
  }
  return out;
}
