import { describe, expect, it } from 'vitest'
import type { Key } from 'ink'
import type { ApprovalRequest } from '../../../browser/frontend/src/store/slices/securitySlice'
import {
  APPROVAL_CHOICES,
  approvalBody,
  approvalKey,
  approvalQueue,
  approvalReason,
  approvalSecondsLeft,
  approvalTimeLeft,
  inputLines,
} from '../../src/chat/approval'
import { isLowering, parseRetentionDays, withEffect } from '../../src/screens/settings/securityLogic'
import { width } from '../../src/text/width'

const t = (key: string, options?: Record<string, unknown>) => `${key}${options ? ' ' + JSON.stringify(options) : ''}`

const key = (over: Partial<Key> = {}): Key => ({
  upArrow: false,
  downArrow: false,
  leftArrow: false,
  rightArrow: false,
  pageDown: false,
  pageUp: false,
  home: false,
  end: false,
  return: false,
  escape: false,
  ctrl: false,
  shift: false,
  tab: false,
  backspace: false,
  delete: false,
  meta: false,
  super: false,
  hyper: false,
  capsLock: false,
  numLock: false,
  ...over,
})

const request = (over: Partial<ApprovalRequest> = {}): ApprovalRequest => ({
  id: 'r1',
  session_id: 's1',
  action_name: 'run_shell',
  action_display_name: 'Run shell command',
  effects: ['execute'],
  reason: 'high_risk',
  reason_detail: '',
  inputs: { command: 'ls -la' },
  created_at: 1000,
  expires_at: 1300,
  ...over,
})

describe('approvalQueue', () => {
  it('puts the open chat first, then oldest first, and leaves out answered ones', () => {
    const a = request({ id: 'a', session_id: 'other', created_at: 1 })
    const b = request({ id: 'b', session_id: 'here', created_at: 5 })
    const c = request({ id: 'c', session_id: 'other', created_at: 3 })
    expect(approvalQueue([a, b, c], 'here').map(r => r.id)).toEqual(['b', 'a', 'c'])
    expect(approvalQueue([a, b, c], 'here', ['b']).map(r => r.id)).toEqual(['a', 'c'])
    expect(approvalQueue([], 'here')).toEqual([])
  })
})

describe('approvalReason', () => {
  it('names what a high-risk action can do', () => {
    const text = approvalReason(request({ effects: ['execute', 'send_external'] }), t)
    expect(text).toContain('approval.reasonHighRisk')
    expect(text).toContain('approval.effects.execute and approval.effects.send_external')
  })

  it('explains an ask after outside content, with its detail', () => {
    const text = approvalReason(request({ reason: 'untrusted_content', reason_detail: 'the result of Fetch page' }), t)
    expect(text).toBe('approval.reasonUntrusted {"detail":"the result of Fetch page"}')
    const fallback = approvalReason(request({ reason: 'untrusted_content', reason_detail: '' }), t)
    expect(fallback).toContain('approval.outsideContent')
  })

  it('falls back when no effect is declared', () => {
    expect(approvalReason(request({ effects: [] }), t)).toBe('approval.reasonGeneric')
  })
})

describe('inputLines', () => {
  const more = (n: number) => `+${n}`

  it('shows one name: value per line, other values as JSON', () => {
    expect(inputLines({ command: 'ls', count: 3, opts: { a: true } }, 40, 5, more)).toEqual([
      'command: ls',
      'count: 3',
      'opts: {"a":true}',
    ])
  })

  it('continues multi-line values indented and cuts to the line budget', () => {
    const lines = inputLines({ script: 'one\ntwo\nthree\nfour', path: '/tmp' }, 40, 3, more)
    expect(lines).toEqual(['script: one', '  two', '+3'])
  })

  it('keeps every line within the width and drops control characters', () => {
    const lines = inputLines({ text: `a\tb\u0007${'x'.repeat(100)}` }, 20, 2, more)
    expect(lines).toHaveLength(1)
    expect(width(lines[0])).toBeLessThanOrEqual(20)
    expect(lines[0]).not.toMatch(/[\t\u0007]/)
  })

  it('is empty without inputs', () => {
    expect(inputLines({}, 40, 3, more)).toEqual([])
  })
})

describe('approvalBody', () => {
  it('names another chat, then the reason, then the inputs', () => {
    const body = approvalBody(request(), 60, 3, t, { sessionLabel: 'Research' })
    expect(body[0]).toEqual({ text: 'approval.inSession {"session":"Research"}', tone: 'muted' })
    expect(body[1].tone).toBe('reason')
    expect(body[body.length - 1]).toEqual({ text: 'command: ls -la', tone: 'input' })
  })

  it('says when there are no inputs and keeps the reason to two rows', () => {
    const body = approvalBody(request({ inputs: {}, effects: ['execute', 'write_files', 'send_external', 'change_agent'] }), 20, 3, t)
    expect(body.filter(l => l.tone === 'reason').length).toBeLessThanOrEqual(2)
    expect(body[body.length - 1]).toEqual({ text: 'approval.noInputs', tone: 'muted' })
  })
})

describe('approval time left', () => {
  it('counts down to 0:00 and never below', () => {
    expect(approvalTimeLeft(1300, 1000_000)).toBe('5:00')
    expect(approvalTimeLeft(1300, 1299_500)).toBe('0:01')
    expect(approvalTimeLeft(1300, 2000_000)).toBe('0:00')
    expect(approvalSecondsLeft(1300, 1270_000)).toBe(30)
    expect(approvalSecondsLeft(1300, 2000_000)).toBe(0)
  })
})

describe('approvalKey', () => {
  it('picks with digits and arrows, answers with Enter', () => {
    expect(approvalKey(0, '2', key())).toEqual({ kind: 'move', index: 1 })
    expect(approvalKey(0, '4', key())).toEqual({ kind: 'none' })
    expect(approvalKey(0, '', key({ downArrow: true }))).toEqual({ kind: 'move', index: 1 })
    expect(approvalKey(2, '', key({ downArrow: true }))).toEqual({ kind: 'move', index: 2 })
    expect(approvalKey(0, '', key({ upArrow: true }))).toEqual({ kind: 'move', index: 0 })
    expect(approvalKey(2, '', key({ return: true }))).toEqual({ kind: 'answer', decision: 'deny' })
    expect(approvalKey(1, '', key({ return: true }))).toEqual({ kind: 'answer', decision: 'allow_session' })
  })

  it('answers at once with a / s / d and gives focus back with Esc or Tab', () => {
    expect(APPROVAL_CHOICES.map(c => approvalKey(0, c.letter, key()))).toEqual([
      { kind: 'answer', decision: 'allow_once' },
      { kind: 'answer', decision: 'allow_session' },
      { kind: 'answer', decision: 'deny' },
    ])
    expect(approvalKey(0, 'd', key({ ctrl: true }))).toEqual({ kind: 'none' })
    expect(approvalKey(0, '', key({ escape: true }))).toEqual({ kind: 'blur' })
    expect(approvalKey(0, '', key({ tab: true }))).toEqual({ kind: 'blur' })
    expect(approvalKey(0, 'x', key())).toEqual({ kind: 'none' })
  })
})

describe('security settings helpers', () => {
  it('knows which level changes lower security', () => {
    expect(isLowering('strict', 'enhanced')).toBe(true)
    expect(isLowering('enhanced', 'standard')).toBe(true)
    expect(isLowering('standard', 'strict')).toBe(false)
    expect(isLowering('enhanced', 'enhanced')).toBe(false)
  })

  it('turns an effect on or off in the page order', () => {
    expect(withEffect(['send_external', 'execute'], 'write_files', true)).toEqual(['execute', 'write_files', 'send_external'])
    expect(withEffect(['execute', 'write_files'], 'execute', false)).toEqual(['write_files'])
    expect(withEffect(['execute'], 'execute', true)).toEqual(['execute'])
  })

  it('reads retention as whole days', () => {
    expect(parseRetentionDays(' 30 ')).toBe(30)
    expect(parseRetentionDays('0')).toBe(0)
    expect(parseRetentionDays('-1')).toBeNull()
    expect(parseRetentionDays('1.5')).toBeNull()
    expect(parseRetentionDays('')).toBeNull()
  })
})
