/**
 * The app screen's view engine (src/apps/view): screens generated from an
 * app's operations.json, action keys, layout; and the op form's typing.
 */
import { describe, expect, it } from 'vitest'
import { assignKeys, cellWidth, fitColumns, generateViews, inferColumns, isReadOp, recordActions, RESERVED_KEYS, renderBlock, toText, wrapText, type Operation } from '../../src/apps/view'
import { coerceParam, prefillFromRow, unwrapResult } from '../../src/apps/engine'
import { formParams, initForm, validateForm } from '../../src/apps/opForm'

const op = (name: string, extra: Partial<Operation> = {}): Operation => ({ name, description: name, destructive: false, params: {}, ...extra })

const OPS: Operation[] = [
  op('health', { system: true, readOnly: true }),
  op('home.summary', { readOnly: true, module: 'home' }),
  op('expenses.list', { readOnly: true, module: 'expenses' }),
  op('expenses.get', { readOnly: true, module: 'expenses', params: { id: { type: 'string', required: true } } }),
  op('expenses.add', { module: 'expenses', params: { title: { type: 'string', required: true }, amount: { type: 'number', required: true } } }),
  op('expenses.add-many', { module: 'expenses', params: { items: { type: 'json', required: true } } }),
  op('expenses.delete', { module: 'expenses', destructive: true, params: { id: { type: 'string', required: true } } }),
  op('budget.set', { module: 'budgets', params: { month: { type: 'string' } } }),
]

describe('generated screens', () => {
  it('reads only what is declared read-only and not destructive', () => {
    expect(isReadOp(op('a.b', { readOnly: true }))).toBe(true)
    expect(isReadOp(op('a.b'))).toBe(false)
    expect(isReadOp(op('a.b', { readOnly: true, destructive: true }))).toBe(false)
  })

  it('puts Home first, then one screen per module in the manifest order, system ops hidden', () => {
    const views = generateViews(OPS, ['budgets', 'expenses'])
    expect(views.home).toBe('home')
    expect(views.screens.map(s => s.id)).toEqual(['home', 'area:budgets', 'area:expenses'])
    const expenses = views.screens[2]
    expect(expenses.blocks.map(b => b.source?.op)).toEqual(['expenses.list'])
    const keys = Object.fromEntries((expenses.actions ?? []).map(a => [a.op, a.key]))
    expect(keys['expenses.add']).toBe('a')
    expect(keys['expenses.delete']).toBe('d')
    expect(keys['expenses.add-many']).not.toBe('d')
  })

  it('offers a record the ops on its entity, the record bound to the param that names it', () => {
    const ops = [
      op('tasks.complete', { entity: 'tasks', params: { task: { type: 'ref', entity: 'tasks', required: true } } }),
      op('tasks.rename', { entity: 'tasks', params: { id: { type: 'string', required: true }, title: { type: 'string' } } }),
      op('notes.pin', { entity: 'notes', params: { note: { type: 'ref', entity: 'notes' } } }),
    ]
    const actions = recordActions(ops, 'tasks')
    expect(actions.map(a => a.op)).toEqual(['tasks.complete', 'tasks.rename'])
    expect(actions[0].params).toEqual({ task: '$row.id' })
    expect(actions[1].params).toEqual({ id: '$row.id' })
  })

  it('never takes navigation keys for actions', () => {
    const actions = assignKeys([op('x.get'), op('x.go'), op('x.quit')], RESERVED_KEYS)
    for (const a of actions) expect(RESERVED_KEYS.has(a.key)).toBe(false)
  })
})

describe('layout', () => {
  it('drops low-priority columns to fit and keeps names first', () => {
    const rows = [{ id: 'r1', amount: 12.5, title: 'Lunch', created: '2026-10-01 10:00:00.000Z', category_id: 'c1' }]
    const columns = inferColumns(rows)
    expect(columns[0]?.field).toBe('title')
    expect(columns.some(c => c.field === 'id')).toBe(false)
    const fitted = fitColumns(columns, [['Lunch', '12.5', 'Oct 1, 2026', 'c1']], 20)
    expect(fitted[0]?.column.field).toBe('title')
    expect(fitted.reduce((s, f) => s + f.width, 0) + (fitted.length - 1) * 2).toBeLessThanOrEqual(20)
  })

  it('never draws a line wider than asked, CJK included', () => {
    const data = { items: [{ name: '東京の会議室を予約する', note: 'x'.repeat(80) }, { name: 'Lunch', note: '弁当' }] }
    for (const width of [30, 50, 80]) {
      const out = renderBlock({ type: 'auto', value: '/items' }, data, { width, selected: 0 })
      for (const line of toText(out.lines).split('\n')) expect(cellWidth(line)).toBeLessThanOrEqual(width)
      expect(out.rows).toHaveLength(2)
    }
    for (const line of wrapText('一二三四五六七八九十'.repeat(3), 7)) expect(cellWidth(line)).toBeLessThanOrEqual(7)
  })
})

describe('op results', () => {
  it('shows the result without the protocol envelope', () => {
    expect(unwrapResult({ a2app: true, ok: true, operation: 'count-tasks', result: { count: 1 } })).toEqual({ count: 1 })
    expect(unwrapResult({ items: [1] })).toEqual({ items: [1] })
    expect(unwrapResult({ a2app: true, ok: false, code: 'x' })).toEqual({ a2app: true, ok: false, code: 'x' })
    expect(unwrapResult([1, 2])).toEqual([1, 2])
  })
})

describe('op forms', () => {
  it('sends values typed as the app declares them', () => {
    expect(coerceParam({ type: 'number' }, ' 12.5 ')).toBe(12.5)
    expect(coerceParam({ type: 'boolean' }, 'true')).toBe(true)
    expect(coerceParam({ type: 'list<enum>' }, 'a, b ,,c')).toEqual(['a', 'b', 'c'])
    expect(coerceParam({ type: 'json' }, '{"a":1}')).toEqual({ a: 1 })
    expect(coerceParam({ type: 'datetime' }, '2026-11-18')).toBe('2026-11-18')
    expect(() => coerceParam({ type: 'number' }, 'many')).toThrow()
  })

  it('checks required, numbers and JSON before running, and leaves empty optional fields out', () => {
    const add = OPS.find(o => o.name === 'expenses.add')!
    const empty = initForm(add)
    expect(validateForm(empty)).toEqual({ title: 'required', amount: 'required' })
    const filled = initForm(add, { title: 'Lunch', amount: '9.5' })
    expect(validateForm(filled)).toEqual({})
    expect(formParams(filled)).toEqual({ title: 'Lunch', amount: 9.5 })
    const many = initForm(OPS.find(o => o.name === 'expenses.add-many')!, { items: '[1,' })
    expect(validateForm(many)).toEqual({ items: 'json' })
    expect(formParams(initForm(OPS.find(o => o.name === 'budget.set')!))).toEqual({})
  })

  it('starts an enum on its first value and fills ids from the selected row', () => {
    const pick = op('mode.set', { params: { mode: { type: 'enum', values: ['fast', 'slow'], required: true } } })
    expect(initForm(pick).fields[0].value.text).toBe('fast')
    const del = OPS.find(o => o.name === 'expenses.delete')!
    expect(prefillFromRow(del, { id: 'r9', title: 'Lunch' })).toEqual({ id: 'r9' })
    expect(prefillFromRow(op('t.tag', { params: { tags: { type: 'list<enum>' } } }), { tags: ['a', 'b'] })).toEqual({ tags: 'a, b' })
  })
})
