/**
 * Lay a view block out as lines of styled segments for a given width.
 *
 * Pure: no terminal, no React. The terminal client colors the segments and
 * handles keys; `agent-app view` prints them as plain text, so the agent sees
 * exactly what the person sees. Numbers are always printed next to marks.
 */
import { formatValue, humanize, isScalar, looksLikeDate } from './format.ts'
import { get } from './pointer.ts'
import type { Block, Column, Format, Line, Segment } from './types.ts'
import { cellWidth, fit, pad, takeCells } from './width.ts'

export interface RenderOptions {
  width: number
  locale?: string
  /** Selected row of this block's rows, or -1 for none. */
  selected?: number
  /** Most data rows to show (the window follows the selection). */
  maxRows?: number
  /** Marks to draw with (a terminal whose font lacks some passes its own). */
  marks?: Partial<ViewMarks>
}

export interface ViewMarks {
  /** Before the selected row. */
  pointer: string
  bullet: string
  /** Sparkline marks, lowest first. */
  spark: string[]
  barFull: string
  barEmpty: string
}

const DEFAULT_MARKS: ViewMarks = {
  pointer: '▸',
  bullet: '•',
  spark: ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'],
  barFull: '█',
  barEmpty: '░',
}

function marksOf(opts: RenderOptions): ViewMarks {
  return { ...DEFAULT_MARKS, ...opts.marks }
}

export interface BlockOutput {
  lines: Line[]
  /** Rows a person can select (tables and lists), in display order. */
  rows: Record<string, unknown>[]
}

const HIDDEN_FIELDS = new Set(['collectionId', 'collectionName', 'expand'])
const NAME_FIELDS = ['name', 'title', 'label', 'subject', 'summary', 'description']
const TIME_FIELDS = new Set(['created', 'updated', 'created_at', 'updated_at', 'createdAt', 'updatedAt'])

const seg = (text: string, tone?: Segment['tone']): Segment => (tone ? { text, tone } : { text })

/** Word-wrap to `width` cells; a word longer than a line is split by grapheme. */
export function wrapText(text: string, width: number): string[] {
  const out: string[] = []
  const cols = Math.max(1, width)
  for (const paragraph of text.split('\n')) {
    let line = ''
    for (const token of paragraph.split(/(\s+)/)) {
      if (!token) continue
      if (cellWidth(line + token) <= cols) {
        line += token
        continue
      }
      if (line.trim()) out.push(line.trimEnd())
      let piece = token.trimStart()
      while (cellWidth(piece) > cols) {
        const head = takeCells(piece, cols)
        out.push(head)
        piece = piece.slice(head.length)
      }
      line = piece
    }
    out.push(line.trimEnd())
  }
  return out
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isSeries(value: unknown): value is Record<string, unknown>[] {
  if (!Array.isArray(value) || value.length < 3 || !value.every(isRecord)) return false
  const first = value[0] as Record<string, unknown>
  const keys = Object.keys(first)
  const numeric = keys.filter(k => typeof first[k] === 'number')
  const label = keys.filter(k => typeof first[k] === 'string')
  return keys.length <= 3 && numeric.length === 1 && label.length >= 1
}

/** Columns for rows nobody declared: names first, ids hidden, timestamps last. */
export function inferColumns(rows: Record<string, unknown>[]): Column[] {
  const seen: string[] = []
  for (const row of rows.slice(0, 25)) {
    for (const [key, value] of Object.entries(row)) {
      if (HIDDEN_FIELDS.has(key) || key === 'id' || seen.includes(key)) continue
      if (!isScalar(value) && !(Array.isArray(value) && value.every(isScalar))) continue
      seen.push(key)
    }
  }
  const columns = seen.map((field, index): Column => {
    let priority = 2 + index
    if (NAME_FIELDS.includes(field)) priority = NAME_FIELDS.indexOf(field) === 0 ? 0 : 1
    else if (field.endsWith('_id') || field.endsWith('Id')) priority = 90
    else if (TIME_FIELDS.has(field)) priority = 80
    const sample = rows.find(r => r[field] !== undefined && r[field] !== null && r[field] !== '')?.[field]
    const format: Format | undefined = looksLikeDate(sample) ? 'date' : typeof sample === 'number' ? 'number' : undefined
    return { field, label: humanize(field), priority, ...(format ? { format } : {}) }
  })
  // The identifying column first; the rest keep the order the app gave them.
  const lead = columns.filter(c => (c.priority ?? 2) <= 1).sort((a, b) => (a.priority ?? 0) - (b.priority ?? 0))
  return [...lead, ...columns.filter(c => !lead.includes(c))]
}

interface Fitted {
  column: Column
  width: number
  numeric: boolean
}

/** Drop the lowest-priority columns until the rest fit; shrink the widest if still needed. */
export function fitColumns(columns: Column[], cells: string[][], width: number): Fitted[] {
  const natural = columns.map((c, i) =>
    Math.min(40, Math.max(cellWidth(c.label ?? humanize(c.field)), ...cells.map(r => cellWidth(r[i] ?? '')), 1)),
  )
  const numeric = columns.map((_, i) => cells.length > 0 && cells.every(r => (r[i] ?? '') === '' || /^[-+]?[\d.,%\s¥$€£]+$/.test(r[i] ?? '')))
  let keep = columns.map((_, i) => i)
  const total = (idx: number[]) => idx.reduce((sum, i) => sum + Math.min(natural[i] ?? 1, 24), 0) + Math.max(0, idx.length - 1) * 2
  while (keep.length > 1 && total(keep) > width) {
    let drop = keep[0] as number
    for (const i of keep) if ((columns[i]?.priority ?? 1) > (columns[drop]?.priority ?? 1)) drop = i
    if ((columns[drop]?.priority ?? 1) === 0 && keep.every(i => (columns[i]?.priority ?? 1) === 0)) break
    keep = keep.filter(i => i !== drop)
  }
  const widths = keep.map(i => natural[i] ?? 1)
  const gaps = Math.max(0, keep.length - 1) * 2
  while (widths.reduce((a, b) => a + b, 0) + gaps > width) {
    const widest = widths.indexOf(Math.max(...widths))
    if ((widths[widest] ?? 0) <= 4) break
    widths[widest] = (widths[widest] ?? 4) - 1
  }
  return keep.map((i, j) => ({ column: columns[i] as Column, width: widths[j] ?? 4, numeric: numeric[i] ?? false }))
}

function renderTable(
  rows: Record<string, unknown>[],
  columns: Column[],
  source: unknown,
  opts: RenderOptions,
  empty: string,
): BlockOutput {
  const locale = opts.locale ?? 'en'
  if (rows.length === 0) return { lines: [[seg(empty, 'muted')]], rows: [] }
  const cells = rows.map(row => columns.map(c => formatValue(row[c.field], c.format, source, locale)))
  const fitted = fitColumns(columns, cells, opts.width - 2)
  const header: Line = [seg('  ')]
  fitted.forEach((f, j) => {
    header.push(seg(pad(f.column.label ?? humanize(f.column.field), f.width, f.numeric ? 'right' : 'left'), 'muted'))
    if (j < fitted.length - 1) header.push(seg('  '))
  })
  const lines: Line[] = [header]
  const selected = opts.selected ?? -1
  const max = opts.maxRows ?? rows.length
  const start = selected >= max ? selected - max + 1 : 0
  const shown = rows.slice(start, start + max)
  shown.forEach((row, k) => {
    const index = start + k
    const isSel = index === selected
    const line: Line = [seg(isSel ? `${marksOf(opts).pointer} ` : '  ', isSel ? 'accent' : undefined)]
    fitted.forEach((f, j) => {
      const text = formatValue(row[f.column.field], f.column.format, source, locale)
      line.push(seg(pad(text, f.width, f.numeric ? 'right' : 'left'), isSel ? 'selected' : j === 0 ? 'bold' : undefined))
      if (j < fitted.length - 1) line.push(seg('  '))
    })
    lines.push(line)
  })
  if (rows.length > shown.length) {
    lines.push([seg(`  ${start + 1}-${start + shown.length} of ${rows.length}`, 'muted')])
  }
  return { lines, rows }
}

function sparkline(values: number[], spark: string[]): string {
  if (values.length === 0) return ''
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  return values.map(v => spark[Math.min(spark.length - 1, Math.floor(((v - min) / span) * (spark.length - 1)))]).join('')
}

function renderSeries(points: Record<string, unknown>[], y: string, x: string | undefined, format: Format | undefined, source: unknown, opts: RenderOptions): Line[] {
  const locale = opts.locale ?? 'en'
  const values = points.map(p => Number(p[y])).filter(Number.isFinite)
  if (values.length === 0) return [[seg('No data yet', 'muted')]]
  const room = Math.max(4, opts.width - 30)
  const step = Math.max(1, Math.ceil(values.length / room))
  const sampled = values.filter((_, i) => i % step === 0)
  const last = values[values.length - 1] ?? 0
  const lines: Line[] = [[seg(sparkline(sampled, marksOf(opts).spark), 'accent'), seg(`  last ${formatValue(last, format, source, locale)}`, 'muted')]]
  const first = x ? points[0]?.[x] : undefined
  const end = x ? points[points.length - 1]?.[x] : undefined
  lines.push([
    seg(`min ${formatValue(Math.min(...values), format, source, locale)}  max ${formatValue(Math.max(...values), format, source, locale)}` +
      (first !== undefined ? `  ${formatValue(first, undefined, source, locale)} to ${formatValue(end, undefined, source, locale)}` : ''), 'muted'),
  ])
  return lines
}

function renderBars(points: Record<string, unknown>[], xField: string, yField: string, format: Format | undefined, source: unknown, opts: RenderOptions): Line[] {
  const locale = opts.locale ?? 'en'
  if (points.length > 14) return renderSeries(points, yField, xField, format, source, opts)
  const values = points.map(p => Number(p[yField]) || 0)
  const labels = points.map(p => formatValue(p[xField], undefined, source, locale))
  const numbers = values.map(v => formatValue(v, format, source, locale))
  const labelW = Math.min(16, Math.max(...labels.map(cellWidth), 1))
  const numW = Math.max(...numbers.map(cellWidth), 1)
  const barW = Math.max(4, opts.width - labelW - numW - 4)
  const max = Math.max(...values, 0) || 1
  return points.map((_, i) => {
    const filled = Math.round(((values[i] ?? 0) / max) * barW)
    return [
      seg(pad(labels[i] ?? '', labelW)),
      seg(' '),
      seg(marksOf(opts).barFull.repeat(Math.max(0, filled)), 'accent'),
      seg(marksOf(opts).barEmpty.repeat(Math.max(0, barW - filled)), 'muted'),
      seg(' ' + pad(numbers[i] ?? '', numW, 'right')),
    ]
  })
}

function renderKeyValue(obj: Record<string, unknown>, fields: { field: string; label?: string; format?: Format }[] | undefined, source: unknown, opts: RenderOptions): Line[] {
  const locale = opts.locale ?? 'en'
  const chosen: { field: string; label?: string; format?: Format }[] =
    fields ?? Object.keys(obj).filter(k => isScalar(obj[k]) && !HIDDEN_FIELDS.has(k)).map(field => ({ field }))
  const entries = chosen
    .map(f => ({ label: f.label ?? humanize(f.field), text: formatValue(obj[f.field], f.format, source, locale) }))
    .filter(e => e.text !== '')
  if (entries.length === 0) return []
  const labelW = Math.min(22, Math.max(...entries.map(e => cellWidth(e.label))))
  const colW = labelW + 2 + 24
  const perLine = opts.width >= colW * 2 + 4 ? Math.floor(opts.width / (colW + 4)) : 1
  const lines: Line[] = []
  for (let i = 0; i < entries.length; i += perLine) {
    const line: Line = []
    entries.slice(i, i + perLine).forEach((e, j) => {
      if (j > 0) line.push(seg('    '))
      line.push(seg(pad(e.label, labelW), 'muted'), seg('  '))
      const valueW = perLine === 1 ? opts.width - labelW - 2 : 24
      line.push(seg(perLine === 1 ? fit(e.text, valueW) : pad(e.text, valueW), 'bold'))
    })
    lines.push(line)
  }
  return lines
}

function renderAuto(value: unknown, source: unknown, opts: RenderOptions): BlockOutput {
  if (value === undefined || value === null) return { lines: [[seg('Nothing to show', 'muted')]], rows: [] }
  if (typeof value === 'string') return { lines: wrapText(value, opts.width).map(l => [seg(l)]), rows: [] }
  if (isScalar(value)) return { lines: [[seg(formatValue(value, undefined, source, opts.locale), 'bold')]], rows: [] }
  if (Array.isArray(value)) {
    if (value.length === 0) return { lines: [[seg('Nothing here yet', 'muted')]], rows: [] }
    if (isSeries(value)) {
      const first = value[0] as Record<string, unknown>
      const y = Object.keys(first).find(k => typeof first[k] === 'number') ?? ''
      const x = Object.keys(first).find(k => typeof first[k] === 'string')
      return { lines: renderSeries(value as Record<string, unknown>[], y, x, undefined, source, opts), rows: [] }
    }
    if (value.every(isRecord)) {
      const rows = value as Record<string, unknown>[]
      return renderTable(rows, inferColumns(rows), source, opts, 'Nothing here yet')
    }
    return { lines: value.map(v => [seg(`${marksOf(opts).bullet} ` + formatValue(v, undefined, source, opts.locale))]), rows: [] }
  }
  // An object: its scalars as a key-value grid, then each nested list or object.
  const obj = value as Record<string, unknown>
  const lines: Line[] = renderKeyValue(obj, undefined, source, opts)
  let rows: Record<string, unknown>[] = []
  for (const [key, nested] of Object.entries(obj)) {
    if (isScalar(nested) || HIDDEN_FIELDS.has(key)) continue
    if (Array.isArray(nested) && nested.every(isScalar)) {
      if (nested.length) lines.push([seg(humanize(key), 'muted'), seg('  ' + fit(nested.join(', '), opts.width - cellWidth(humanize(key)) - 2))])
      continue
    }
    if (lines.length) lines.push([])
    lines.push([seg(humanize(key), 'heading')])
    const sub = renderAuto(nested, source, rows.length === 0 ? opts : { ...opts, selected: -1 })
    lines.push(...sub.lines)
    if (rows.length === 0 && sub.rows.length) rows = sub.rows
  }
  return { lines, rows }
}

/** Lay out one block of a screen; `data` is the result of its source op. */
export function renderBlock(block: Block, data: unknown, opts: RenderOptions): BlockOutput {
  const locale = opts.locale ?? 'en'
  const titled = (out: BlockOutput): BlockOutput =>
    block.title ? { lines: [[seg(block.title, 'heading')], ...out.lines], rows: out.rows } : out
  switch (block.type) {
    case 'metrics': {
      const line: Line = []
      for (const item of block.items) {
        if (line.length) line.push(seg('    '))
        line.push(seg(item.label + ' ', 'muted'), seg(formatValue(get(data, item.value), item.format, data, locale), 'bold'))
      }
      return titled({ lines: [line], rows: [] })
    }
    case 'keyvalue': {
      const obj = get(data, block.value)
      return titled({ lines: isRecord(obj) ? renderKeyValue(obj, block.fields, data, opts) : [[seg('Nothing to show', 'muted')]], rows: [] })
    }
    case 'table': {
      const rows = get(data, block.rows)
      const list = Array.isArray(rows) ? rows.filter(isRecord) : []
      return titled(renderTable(list, block.columns.length ? block.columns : inferColumns(list), data, opts, block.empty ?? 'Nothing here yet'))
    }
    case 'list': {
      const items = get(data, block.items)
      const list = Array.isArray(items) ? items.filter(isRecord) : []
      if (list.length === 0) return titled({ lines: [[seg(block.empty ?? 'Nothing here yet', 'muted')]], rows: [] })
      const selected = opts.selected ?? -1
      const lines = list.slice(0, opts.maxRows ?? list.length).map((item, i): Line => [
        seg(i === selected ? `${marksOf(opts).pointer} ` : '  ', i === selected ? 'accent' : undefined),
        seg(fit(formatValue(item[block.primary], undefined, data, locale), opts.width - 4), i === selected ? 'selected' : 'bold'),
        ...(block.secondary ? [seg('  ' + fit(formatValue(item[block.secondary], undefined, data, locale), Math.max(0, opts.width / 2)), 'muted')] : []),
      ])
      return titled({ lines, rows: list })
    }
    case 'bars': {
      const series = get(data, block.series)
      return titled({ lines: Array.isArray(series) ? renderBars(series.filter(isRecord), block.x, block.y, block.format, data, opts) : [], rows: [] })
    }
    case 'sparkline': {
      const series = get(data, block.series)
      return titled({ lines: Array.isArray(series) ? renderSeries(series.filter(isRecord), block.y, block.x, block.format, data, opts) : [], rows: [] })
    }
    case 'text': {
      const value = block.text ?? get(data, block.value)
      return titled({ lines: wrapText(typeof value === 'string' ? value : formatValue(value, undefined, data, locale), opts.width).map(l => [seg(l)]), rows: [] })
    }
    case 'auto':
      return titled(renderAuto(get(data, block.value), data, opts))
  }
}

/** Plain text of rendered lines (agent-app view). */
export function toText(lines: Line[]): string {
  return lines.map(line => line.map(s => s.text).join('').trimEnd()).join('\n')
}
