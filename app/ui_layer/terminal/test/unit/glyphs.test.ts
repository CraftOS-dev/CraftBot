import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import stringWidth from 'string-width'
import stripAnsi from 'strip-ansi'
import { consoleDrawable, consoleSafe } from '../../src/text/glyphSafe'
import { glyphSetFor, setGlyphMode, spinnerFrames } from '../../src/theme/theme'
import { renderChunk, renderUnit, renderWelcome } from '../../src/render/transcript'

// The real catalog loads through the bundler; keys stand in for most labels.
vi.mock('../../src/platform/i18n', () => {
  const words: Record<string, (n: number) => string> = {
    'tui:transcript.actions': n => `${n} actions`,
    'tui:transcript.failed': n => `${n} failed`,
  }
  return {
    default: { t: (key: string, opts?: { count?: number }) => words[key]?.(opts?.count ?? 0) ?? key, language: 'en' },
  }
})

const chars = (value: unknown): string[] => {
  if (typeof value === 'string') return [...value]
  if (Array.isArray(value)) return value.flatMap(chars)
  if (value && typeof value === 'object') return Object.values(value).flatMap(chars)
  return []
}

describe('console glyph set', () => {
  it('only uses characters the classic console fonts draw', () => {
    const undrawable = chars(glyphSetFor('console')).filter(ch => !consoleDrawable(ch))
    expect(undrawable).toEqual([])
    setGlyphMode('console')
    try {
      expect(spinnerFrames().flatMap(f => [...f]).filter(ch => !consoleDrawable(ch))).toEqual([])
    } finally {
      setGlyphMode('modern')
    }
  })

  it('keeps every glyph one cell wide in every set, so layouts line up', () => {
    for (const mode of ['modern', 'console'] as const) {
      const set = glyphSetFor(mode)
      for (const [name, value] of Object.entries(set)) {
        for (const glyph of Array.isArray(value) ? value : [value]) {
          if (glyph === '') continue
          expect(stringWidth(glyph), `${mode}.${name}`).toBe(1)
        }
      }
    }
  })

  it('draws the welcome card with console-safe characters only', () => {
    setGlyphMode('console')
    try {
      const card = stripAnsi(renderWelcome({ version: '1.4.5', agentName: 'Aria', model: 'claude-sonnet-5' }, 80))
      expect([...card].filter(ch => !consoleDrawable(ch))).toEqual([])
      const rows = card.split('\n').filter(Boolean)
      expect(new Set(rows.map(r => stringWidth(r))).size).toBe(1)
    } finally {
      setGlyphMode('modern')
    }
  })
})

describe('locale strings', () => {
  it('need no character the classic console cannot draw', () => {
    const root = join(__dirname, '..', '..', 'locales')
    const problems: string[] = []
    for (const lang of readdirSync(root)) {
      for (const file of readdirSync(join(root, lang))) {
        const data = JSON.parse(readFileSync(join(root, lang, file), 'utf8'))
        const walk = (value: unknown, path: string) => {
          if (typeof value === 'string') {
            if (consoleSafe(value) !== value) problems.push(`${lang}/${file} ${path}: ${value}`)
          } else if (value && typeof value === 'object') {
            for (const [k, v] of Object.entries(value)) walk(v, path ? `${path}.${k}` : k)
          }
        }
        walk(data, '')
      }
    }
    expect(problems).toEqual([])
  })
})

describe('consoleSafe', () => {
  it('swaps undrawable marks for look-alikes of the same width', () => {
    expect(consoleSafe('✓ done ✗ failed ● dot ▸ more ❯ go')).toBe('√ done × failed • dot ► more › go')
    expect(consoleSafe('╭──╮\n╰──╯')).toBe('┌──┐\n└──┘')
    expect(consoleSafe('⠋ working')).toBe('∙ working')
    expect(consoleSafe('rating ★★★☆☆')).toBe('rating *****')
  })

  it('keeps width for anything it cannot match', () => {
    const text = 'a ⌬ b'
    const out = consoleSafe(text)
    expect(stringWidth(out)).toBe(stringWidth(text))
    expect([...out].every(consoleDrawable)).toBe(true)
  })

  it('leaves letters, CJK text, drawable symbols and escape sequences alone', () => {
    const text = 'Café · 日本語の文章。한국어 · ¥1,200 · – ─│┌ █░ ← → … «»'
    expect(consoleSafe(text)).toBe(text)
    const link = '\u001B]8;;https://example.com/✓\u0007label ✓\u001B]8;;\u0007'
    expect(consoleSafe(link)).toBe('\u001B]8;;https://example.com/✓\u0007label √\u001B]8;;\u0007')
    expect(consoleSafe('\u001B[38;2;255;79;24m●\u001B[39m')).toBe('\u001B[38;2;255;79;24m•\u001B[39m')
  })
})

describe('scrollback blocks', () => {
  const message = (style: string, content: string, id = content) =>
    ({ kind: 'message', key: id, ts: 1, message: { messageId: id, style, sender: 'Aria', content, timestamp: 1 } }) as never
  const action = (name: string, status: string, extra: Record<string, unknown> = {}) =>
    ({ id: name + status, itemType: 'action', name, status, createdAt: 1000, completedAt: 2100, ...extra }) as never
  const chunk = (items: never[]) =>
    ({ kind: 'chunk', key: 'c', ts: 1, items, actionCount: items.length, failed: items.filter((i: { status: string }) => i.status === 'error').length, final: true }) as never

  it('opens one blank line where the kind of content changes, and before every user message', () => {
    expect(renderUnit(message('agent', 'one'), 60, 'user').startsWith('\n')).toBe(true)
    expect(renderUnit(message('agent', 'two'), 60, 'agent').startsWith('\n')).toBe(false)
    expect(renderUnit(message('system', 'note'), 60, 'notice').startsWith('\n')).toBe(false)
    expect(renderUnit(message('user', 'again'), 60, 'user').startsWith('\n')).toBe(true)
  })

  it('hangs a message under its gutter mark', () => {
    const lines = stripAnsi(renderUnit(message('agent', 'word '.repeat(30).trim()), 40, null)).split('\n').filter(Boolean)
    expect(lines[0].startsWith('● ')).toBe(true)
    expect(lines.slice(1).every(l => l.startsWith('  '))).toBe(true)
    expect(lines.every(l => stringWidth(l) <= 40)).toBe(true)
  })

  it('writes a group of actions as one line led by its outcome', () => {
    const ok = stripAnsi(renderChunk(chunk([action('web_search', 'completed', { input: '{"query":"sushi"}' }), action('web_search', 'completed'), action('run_shell', 'completed')]), 80)[0])
    expect(ok).toBe('✓ 3 actions · Web search (2), Run shell · 1.1s')
    const failed = stripAnsi(renderChunk(chunk([action('read_file', 'completed'), action('send_email', 'error', { error: 'token expired' })]), 80)[0])
    expect(failed.startsWith('✗ 2 actions · ')).toBe(true)
    expect(failed).toContain('Send email: token expired')
    const one = stripAnsi(renderChunk(chunk([action('web_search', 'completed', { input: '{"query":"flights KUL to NRT"}' })]), 80)[0])
    expect(one).toBe('✓ Web search · flights KUL to NRT · 1.1s')
  })
})
