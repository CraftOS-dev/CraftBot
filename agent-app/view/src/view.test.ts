/**
 * The view engine: generated screens, action keys, layout and validation.
 * Run: node --test view/src/view.test.ts
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { assignKeys, generateViews, isReadOp, RESERVED_KEYS } from './generate.ts';
import { fitColumns, inferColumns, renderBlock, toText, wrapText } from './render.ts';
import { validateViews } from './validate.ts';
import { cellWidth } from './width.ts';
import type { Operation } from './types.ts';

const op = (name: string, method: string, params: Operation['params'] = {}, extra: Partial<Operation> = {}): Operation => ({
  name,
  description: name,
  params,
  executor: { type: 'http', method, path: `/api/ops/${name}` },
  ...extra,
});

const OPS: Operation[] = [
  op('health', 'GET', {}, { system: true }),
  op('home.summary', 'GET'),
  op('expenses.list', 'GET'),
  op('expenses.get', 'GET', { id: { type: 'string', required: true } }),
  op('expenses.add', 'POST', { title: { type: 'string', required: true }, amount: { type: 'number', required: true } }),
  op('expenses.add-many', 'POST', { items: { type: 'string', required: true } }),
  op('expenses.delete', 'POST', { id: { type: 'string', required: true } }, { destructive: true }),
];

test('read ops are GETs unless declared otherwise', () => {
  assert.equal(isReadOp(op('a.b', 'GET')), true);
  assert.equal(isReadOp(op('a.b', 'POST')), false);
  assert.equal(isReadOp(op('a.b', 'POST', {}, { readOnly: true })), true);
});

test('generated views: home first, one screen per area, system ops hidden', () => {
  const views = generateViews(OPS);
  assert.equal(views.home, 'home');
  assert.deepEqual(views.screens.map((s) => s.id), ['home', 'area:expenses']);
  const expenses = views.screens[1];
  assert.ok(expenses);
  assert.deepEqual(expenses.blocks.map((b) => b.source?.op), ['expenses.list']);
  const keys = Object.fromEntries((expenses.actions ?? []).map((a) => [a.op, a.key]));
  assert.equal(keys['expenses.add'], 'a');
  assert.equal(keys['expenses.delete'], 'd');
  assert.notEqual(keys['expenses.add-many'], 'd', 'd always means delete');
});

test('action keys never take navigation keys', () => {
  const actions = assignKeys([op('x.get', 'POST'), op('x.go', 'POST'), op('x.quit', 'POST')], RESERVED_KEYS);
  for (const a of actions) assert.ok(!RESERVED_KEYS.has(a.key), a.key);
});

test('tables drop low-priority columns to fit and keep names first', () => {
  const rows = [{ id: 'r1', amount: 12.5, title: 'Lunch', created: '2026-10-01 10:00:00.000Z', category_id: 'c1' }];
  const columns = inferColumns(rows);
  assert.equal(columns[0]?.field, 'title');
  assert.ok(!columns.some((c) => c.field === 'id'));
  const fitted = fitColumns(columns, [['Lunch', '12.5', 'Oct 1, 2026', 'c1']], 20);
  assert.equal(fitted[0]?.column.field, 'title');
  assert.ok(fitted.reduce((s, f) => s + f.width, 0) + (fitted.length - 1) * 2 <= 20);
});

test('rendered lines never exceed the width, CJK included', () => {
  const data = { items: [{ name: '東京の会議室を予約する', note: 'x'.repeat(80) }, { name: 'Lunch', note: '弁当' }] };
  for (const width of [30, 50, 80]) {
    const out = renderBlock({ type: 'auto', value: '/items' }, data, { width, selected: 0 });
    for (const line of toText(out.lines).split('\n')) assert.ok(cellWidth(line) <= width, `${width}: ${line}`);
    assert.equal(out.rows.length, 2);
  }
  for (const line of wrapText('一二三四五六七八九十'.repeat(3), 7)) assert.ok(cellWidth(line) <= 7);
});

test('validation: sources must read, actions must exist, keys are free', () => {
  const problems = validateViews(
    {
      viewsVersion: 1,
      home: 'main',
      screens: [
        {
          id: 'main',
          title: 'Main',
          source: { op: 'expenses.add' },
          blocks: [{ type: 'table', rows: '/items', columns: [], rowActions: [{ key: 'z', op: 'nope' }] }],
          actions: [{ key: 'j', op: 'expenses.delete' }],
        },
      ],
    },
    OPS,
  );
  const text = problems.map((p) => p.message).join('\n');
  assert.match(text, /source op "expenses.add" changes data/);
  assert.match(text, /op "nope" is not declared/);
  assert.match(text, /key "j" is kept for navigation/);
  assert.deepEqual(validateViews({ viewsVersion: 1, screens: [{ id: 'm', title: 'M', blocks: [{ type: 'auto', source: { op: 'expenses.list' } }] }] }, OPS), []);
});
