import { describe, expect, it } from 'vitest'
import stringWidth from 'string-width'
import stripAnsi from 'strip-ansi'
import { blankEmoji, isEmoji, stripEmoji } from '../../src/text/emoji'
import { renderMarkdown } from '../../src/render/markdown'

describe('emoji', () => {
  it('removes the backend notices emoji with their space', () => {
    expect(stripEmoji('⚙️ Memory processing workflow: Daily Memory Processing')).toBe(
      'Memory processing workflow: Daily Memory Processing',
    )
    expect(stripEmoji('📩 Incoming message')).toBe('Incoming message')
    expect(stripEmoji('Done 🎉 now')).toBe('Done now')
  })

  it('removes sequences, flags and skin tones whole', () => {
    expect(stripEmoji('a 👨‍👩‍👧 b 🇯🇵 c 👍🏽 d')).toBe('a b c d')
  })

  it('keeps keycap digits and text symbols', () => {
    expect(stripEmoji('Step 1️⃣ of 3')).toBe('Step 1 of 3')
    expect(stripEmoji('© 2026 ™ ↔ ✓ ✔ ★☆ ▶')).toBe('© 2026 ™ ↔ ✓ ✔ ★☆ ▶')
  })

  it('removes pictographic symbols drawn without the emoji selector', () => {
    expect(stripEmoji('⚙ Settings saved')).toBe('Settings saved')
    expect(stripEmoji('⚠ Low disk ☀ sunny ✈ flight')).toBe('Low disk sunny flight')
  })

  it("never touches the client's own glyphs or CJK text", () => {
    const glyphs = '✓ ✗ ● ○ ◐ ▸ › • ─ │ ▣ ■ □ ┌ █ ░ ▁ ⠋ 日本語 한국어'
    expect(stripEmoji(glyphs)).toBe(glyphs)
    for (const g of ['✓', '◐', '▣', '■', '⠋']) expect(isEmoji(g)).toBe(false)
  })

  it('blanks laid-out text without changing its width', () => {
    const line = '\u001B[90m│ ⚙️ Gear 🎉 │\u001B[39m'
    const blanked = blankEmoji(line)
    expect(stringWidth(stripAnsi(blanked))).toBe(stringWidth(stripAnsi(line)))
    expect(blanked).not.toMatch(/\p{Emoji_Presentation}|️/u)
    expect(blanked).toContain('\u001B[90m')
  })

  it('cleans message text before Markdown layout', () => {
    expect(renderMarkdown('⚙️ Proactive planning: Daily Planning', 80).map(l => stripAnsi(l))).toEqual([
      'Proactive planning: Daily Planning',
    ])
  })
})
