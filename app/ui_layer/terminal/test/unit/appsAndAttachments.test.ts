import { describe, expect, it } from 'vitest'
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { Key } from 'ink'
import { formKey, formParams, initForm } from '../../src/apps/opForm'
import { mentionAt, mentionedFiles, pathSuggestions } from '../../src/input/attachments'
import type { Operation } from '../../../../../agent-app/view/src/index.ts'

const key = (over: Partial<Key> = {}): Key => ({
  upArrow: false, downArrow: false, leftArrow: false, rightArrow: false, pageDown: false, pageUp: false,
  home: false, end: false, return: false, escape: false, ctrl: false, shift: false, tab: false,
  backspace: false, delete: false, meta: false, super: false, hyper: false, capsLock: false, numLock: false,
  ...over,
})

const op: Operation = {
  name: 'expenses.add',
  description: 'Add an expense',
  params: {
    title: { type: 'string', required: true },
    amount: { type: 'number', required: true },
    paid: { type: 'boolean' },
    kind: { type: 'string', enum: ['food', 'travel'] },
  },
  executor: { type: 'http', method: 'POST', path: '/api/ops/expenses-add' },
}

describe('op form', () => {
  it('starts on the first empty required field and keeps prefills', () => {
    const form = initForm(op, { title: 'Lunch' })
    expect(form.fields[form.index]?.name).toBe('amount')
    expect(form.fields[0]?.value.text).toBe('Lunch')
  })

  it('refuses to submit until required fields are valid', () => {
    let state = initForm(op)
    state = formKey(state, 'Taxi', key()).state
    for (let i = 0; i < 3; i++) state = formKey(state, '', key({ downArrow: true })).state
    let result = formKey(state, '', key({ return: true }))
    expect(result.submit).toBeUndefined()
    expect(result.state.errors.amount).toBe('required')
    state = formKey(result.state, 'abc', key()).state
    result = formKey({ ...state, index: 3 }, '', key({ return: true }))
    expect(result.state.errors.amount).toBe('number')
  })

  it('toggles booleans, cycles enums and sends only filled params', () => {
    let state = initForm(op, { title: 'Bus', amount: '3' })
    state = { ...state, index: 2 }
    state = formKey(state, ' ', key()).state
    state = { ...state, index: 3 }
    state = formKey(state, '', key({ rightArrow: true })).state
    const result = formKey(state, '', key({ return: true }))
    expect(result.submit).toBe(true)
    expect(formParams(result.state)).toEqual({ title: 'Bus', amount: '3', paid: 'true', kind: 'food' })
  })

  it('cancels on Esc', () => {
    expect(formKey(initForm(op), '', key({ escape: true })).cancel).toBe(true)
  })
})

describe('@ attachments', () => {
  const dir = mkdtempSync(join(tmpdir(), 'cb-attach-'))
  writeFileSync(join(dir, 'report.pdf'), 'x')
  writeFileSync(join(dir, 'my notes.txt'), 'x')
  mkdirSync(join(dir, 'docs'))

  it('finds mentioned files that exist, quoted or not', () => {
    const files = mentionedFiles('see @report.pdf and @"my notes.txt" but not @nobody', dir)
    expect(files).toEqual([join(dir, 'report.pdf'), join(dir, 'my notes.txt')])
  })

  it('knows the mention under the caret', () => {
    expect(mentionAt('look at @rep', 12)).toEqual({ start: 8, path: 'rep' })
    expect(mentionAt('mail me@example', 15)).toBeNull()
  })

  it('suggests directory entries, folders keep completing', () => {
    const items = pathSuggestions('', dir)
    expect(items.map(i => i.label)).toEqual(['docs' + (process.platform === 'win32' ? '\\' : '/'), 'my notes.txt', 'report.pdf'])
    expect(items.find(i => i.label === 'report.pdf')?.value).toBe('@report.pdf ')
    expect(items.find(i => i.label === 'my notes.txt')?.value).toBe('@"my notes.txt" ')
  })
})
