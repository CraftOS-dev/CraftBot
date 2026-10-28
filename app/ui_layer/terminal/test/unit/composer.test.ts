import { describe, expect, it } from 'vitest'
import type { Key } from 'ink'
import { applyKey, applyPaste, EMPTY_MODEL, modelFromText, stripInvisible, submittedText } from '../../src/input/composer'

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
const ctx = { columns: 40, history: ['first', 'second'] }

describe('composer keys', () => {
  it('types and submits', () => {
    let m = applyKey(EMPTY_MODEL, 'hi', key(), ctx).model
    const r = applyKey(m, '', key({ return: true }), ctx)
    expect(r.effect).toEqual({ kind: 'submit', text: 'hi' })
    m = r.model
  })

  it('does not submit blank input', () => {
    const r = applyKey(modelFromText('   '), '', key({ return: true }), ctx)
    expect(r.effect).toBeNull()
    expect(r.handled).toBe(true)
  })

  it('inserts newlines with Shift+Enter, Alt+Enter, Ctrl+J and a trailing backslash', () => {
    expect(applyKey(modelFromText('a'), '', key({ return: true, shift: true }), ctx).model.buffer.text).toBe('a\n')
    expect(applyKey(modelFromText('a'), '', key({ return: true, meta: true }), ctx).model.buffer.text).toBe('a\n')
    expect(applyKey(modelFromText('a'), '\n', key(), ctx).model.buffer.text).toBe('a\n')
    const bs = applyKey(modelFromText('a\\'), '', key({ return: true }), ctx)
    expect(bs.effect).toBeNull()
    expect(bs.model.buffer.text).toBe('a\n')
  })

  it('walks history at the edges and restores the draft', () => {
    let m = modelFromText('draft')
    m = applyKey(m, '', key({ upArrow: true }), ctx).model
    expect(m.buffer.text).toBe('second')
    m = applyKey(m, '', key({ upArrow: true }), ctx).model
    expect(m.buffer.text).toBe('first')
    m = applyKey(m, '', key({ downArrow: true }), ctx).model
    m = applyKey(m, '', key({ downArrow: true }), ctx).model
    expect(m.buffer.text).toBe('draft')
    expect(m.historyIndex).toBeNull()
  })

  it('leaves shortcuts to the chat', () => {
    for (const k of [key({ escape: true }), key({ tab: true }), key({ ctrl: true })]) {
      expect(applyKey(EMPTY_MODEL, k.ctrl ? 'p' : '', k, ctx).handled).toBe(false)
    }
  })

  it('drops control characters from typed input', () => {
    expect(applyKey(EMPTY_MODEL, 'a\u0007b', key(), ctx).model.buffer.text).toBe('ab')
  })
})

describe('paste', () => {
  it('keeps short pastes inline', () => {
    expect(applyPaste(EMPTY_MODEL, 'one\r\ntwo').buffer.text).toBe('one\ntwo')
  })

  it('collapses long pastes into a chip and expands it on submit', () => {
    const big = Array.from({ length: 10 }, (_, i) => `line ${i}`).join('\n')
    const m = applyPaste(modelFromText('see: '), big)
    expect(m.buffer.text).toBe('see: [Pasted text #1 · 10 lines]')
    expect(submittedText(m).text).toBe(`see: ${big}`)
  })
})

describe('invisible characters', () => {
  it('strips tag characters, bidi controls and zero-width spaces', () => {
    const r = stripInvisible('ok‮done​\u{E0041}')
    expect(r.text).toBe('okdone')
    expect(r.removed).toBe(3)
  })

  it('keeps emoji joiners', () => {
    expect(stripInvisible('👨‍👩‍👧').text).toBe('👨‍👩‍👧')
  })
})
