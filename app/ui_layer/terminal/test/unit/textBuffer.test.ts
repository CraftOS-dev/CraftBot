import { describe, expect, it } from 'vitest'
import * as TB from '../../src/input/TextBuffer'
import { width, wrap } from '../../src/text/width'

describe('TextBuffer', () => {
  it('steps over whole graphemes', () => {
    let buf = TB.fromText('a👨‍👩‍👧b')
    buf = TB.left(buf) // before b
    buf = TB.left(buf) // before the family emoji
    expect(buf.text.slice(buf.cursor)).toBe('👨‍👩‍👧b')
    buf = TB.backspace(TB.right(buf))
    expect(buf.text).toBe('ab')
  })

  it('treats combining marks as part of their letter', () => {
    const buf = TB.backspace(TB.fromText('café'.normalize('NFD')))
    expect(buf.text).toBe('caf')
  })

  it('moves by word in Latin and CJK text', () => {
    let buf = TB.fromText('hello world')
    buf = TB.wordLeft(buf)
    expect(buf.cursor).toBe(6)
    buf = TB.fromText('今日は良い天気です')
    const left = TB.wordLeft(buf)
    expect(left.cursor).toBeLessThan(buf.cursor)
    expect(left.cursor).toBeGreaterThan(0)
  })

  it('deletes a word back and kills to line ends', () => {
    expect(TB.deleteWordBack(TB.fromText('send the report')).text).toBe('send the ')
    const mid = { text: 'one\ntwo three', cursor: 7 }
    expect(TB.killToLineStart(mid).text).toBe('one\n three')
    expect(TB.killToLineEnd(mid).text).toBe('one\ntwo')
  })

  it('lays out wide characters by display width', () => {
    const lay = TB.layout(TB.fromText('日本語のテキスト'), 6)
    for (const row of lay.rows) expect(width(row.text)).toBeLessThanOrEqual(6)
    expect(lay.rows.map(r => r.text).join('')).toBe('日本語のテキスト')
    expect(lay.cursorRow).toBe(lay.rows.length - 1)
  })

  it('moves vertically by visual row and stops at the edges', () => {
    const buf = { text: 'first line\nsecond', cursor: 3 }
    const down = TB.verticalMove(buf, 40, 1)
    expect(down?.cursor).toBe(14)
    expect(TB.verticalMove(buf, 40, -1)).toBeNull()
  })

  it('never lays a row wider than the columns (random mixed text)', () => {
    const pool = ['a', 'Z', ' ', '日', '한', '語', 'é', '👍', '中', 'x', '\n', '٣']
    let seed = 7
    const rand = () => (seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31
    for (let run = 0; run < 200; run++) {
      const len = Math.floor(rand() * 40)
      let text = ''
      for (let i = 0; i < len; i++) text += pool[Math.floor(rand() * pool.length)]
      const cols = 2 + Math.floor(rand() * 20)
      const buf = { text, cursor: text.length }
      const lay = TB.layout(buf, cols)
      for (const row of lay.rows) expect(width(row.text)).toBeLessThanOrEqual(cols)
      expect(lay.cursorCol).toBeLessThanOrEqual(cols)
    }
  })
})

describe('wrap', () => {
  it('starts a continued piece without the space it broke at', () => {
    expect(wrap('I removed the CIMB recheck from your plan', 18)).toEqual(['I removed the CIMB', 'recheck from your', 'plan'])
  })

  it('keeps the indentation a line starts with', () => {
    expect(wrap('    indented code line here', 14)[0].startsWith('    ')).toBe(true)
  })
})
