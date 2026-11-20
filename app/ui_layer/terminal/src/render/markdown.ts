/**
 * Markdown to ANSI text lines for the terminal transcript.
 *
 * Prose stays as logical lines: the terminal soft-wraps and reflows them, so
 * selecting and copying a paragraph yields its source text instead of
 * hard-wrapped fragments. Only structures that need a layout (tables, rules)
 * are fitted to the width. Single newlines are line breaks, matching the
 * browser's remark-breaks rendering of agent messages.
 */
import { lexer, type Token, type Tokens } from 'marked'
import { common, createLowlight } from 'lowlight'
import { hyperlink } from '../caps/terminal'
import { glyphs, paint, tone } from '../theme/theme'
import { padEnd, width, wrap } from '../text/width'
import { stripEmoji } from '../text/emoji'

const lowlight = createLowlight(common)

type Inline = Token[] | undefined

function inline(tokens: Inline): string {
  if (!tokens) return ''
  let out = ''
  for (const token of tokens) out += inlineToken(token)
  return out
}

function inlineToken(token: Token): string {
  switch (token.type) {
    case 'strong':
      return tone.bold(inline((token as Tokens.Strong).tokens))
    case 'em':
      return tone.italic(inline((token as Tokens.Em).tokens))
    case 'del':
      return paint.strikethrough(inline((token as Tokens.Del).tokens))
    case 'codespan':
      return tone.code((token as Tokens.Codespan).text)
    case 'br':
      return '\n'
    case 'link': {
      const link = token as Tokens.Link
      const label = inline(link.tokens) || link.href
      const plain = link.text || link.href
      if (plain === link.href) return tone.link(hyperlink(link.href, link.href))
      return `${tone.link(hyperlink(label, link.href))}${tone.muted(` (${link.href})`)}`
    }
    case 'image': {
      const image = token as Tokens.Image
      return tone.muted(`[image${image.text ? `: ${image.text}` : ''}] ${image.href}`)
    }
    case 'escape':
      return (token as Tokens.Escape).text
    case 'html':
      return stripTags((token as Tokens.HTML).text)
    case 'text': {
      const text = token as Tokens.Text
      return text.tokens ? inline(text.tokens) : decodeEntities(text.text)
    }
    default:
      return 'raw' in token ? String(token.raw) : ''
  }
}

function decodeEntities(text: string): string {
  return text
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
}

function stripTags(html: string): string {
  return decodeEntities(html.replace(/<[^>]+>/g, ''))
}

// --- code highlighting ----------------------------------------------------

const HLJS_COLORS: Record<string, (s: string) => string> = {
  keyword: s => paint.magenta(s),
  'selector-tag': s => paint.magenta(s),
  string: s => paint.green(s),
  regexp: s => paint.green(s),
  number: s => paint.yellow(s),
  literal: s => paint.yellow(s),
  type: s => paint.yellow(s),
  comment: s => paint.gray(s),
  quote: s => paint.gray(s),
  meta: s => paint.gray(s),
  title: s => paint.blue(s),
  'title.function': s => paint.blue(s),
  'title.class': s => paint.yellow(s),
  built_in: s => paint.cyan(s),
  attr: s => paint.cyan(s),
  attribute: s => paint.cyan(s),
  property: s => paint.cyan(s),
  variable: s => paint.red(s),
  params: s => s,
  section: s => paint.bold(s),
  addition: s => paint.green(s),
  deletion: s => paint.red(s),
}

interface HastNode {
  type: string
  value?: string
  properties?: { className?: string[] }
  children?: HastNode[]
}

function hastToAnsi(node: HastNode): string {
  if (node.type === 'text') return node.value ?? ''
  const inner = (node.children ?? []).map(hastToAnsi).join('')
  if (node.type !== 'element') return inner
  const cls = (node.properties?.className ?? []).map(c => c.replace(/^hljs-/, ''))
  for (const c of cls) {
    const color = HLJS_COLORS[c] ?? HLJS_COLORS[c.split('.')[0]]
    if (color) return inner.split('\n').map(color).join('\n')
  }
  return inner
}

export function highlight(code: string, lang: string | undefined): string[] {
  const language = (lang ?? '').trim().split(/\s+/)[0]?.toLowerCase()
  try {
    if (language && lowlight.registered(language)) {
      return hastToAnsi(lowlight.highlight(language, code) as unknown as HastNode).split('\n')
    }
  } catch {
    // Unknown grammar or a highlighter error: show the code plain.
  }
  return code.split('\n')
}

// --- blocks -----------------------------------------------------------------

function renderTable(table: Tokens.Table, columns: number): string[] {
  const head = table.header.map(cell => inline(cell.tokens))
  const rows = table.rows.map(row => row.map(cell => inline(cell.tokens)))
  const count = head.length
  const natural = head.map((h, i) => Math.max(width(h), ...rows.map(r => width(r[i] ?? '')), 1))
  // Borders: "│ " + cells joined by " │ " + " │"
  const chrome = 4 + (count - 1) * 3
  const budget = Math.max(count * 3, columns - chrome)
  const widths = natural.slice()
  while (widths.reduce((a, b) => a + b, 0) > budget) {
    const widest = widths.indexOf(Math.max(...widths))
    if (widths[widest] <= 3) break
    widths[widest] -= 1
  }
  const g = glyphs()
  const line = (left: string, mid: string, right: string) =>
    tone.border(left + widths.map(w => g.boxH.repeat(w + 2)).join(mid) + right)
  const renderRow = (cells: string[], bold: boolean): string[] => {
    const wrapped = cells.map((c, i) => wrap(c, widths[i]))
    const height = Math.max(...wrapped.map(w => w.length), 1)
    const out: string[] = []
    for (let r = 0; r < height; r++) {
      const parts = wrapped.map((w, i) => {
        const text = padEnd(w[r] ?? '', widths[i])
        return bold ? tone.bold(text) : text
      })
      out.push(`${tone.border(g.boxV)} ${parts.join(` ${tone.border(g.boxV)} `)} ${tone.border(g.boxV)}`)
    }
    return out
  }
  return [
    line(...g.tableTop),
    ...renderRow(head, true),
    line(...g.tableMid),
    ...rows.flatMap(row => renderRow(row, false)),
    line(...g.tableBottom),
  ]
}

// Each item's body is rendered at column 0 and shifted right by its marker,
// so nested lists indent naturally under their parent item.
function renderList(list: Tokens.List, columns: number, depth: number): string[] {
  const out: string[] = []
  const start = typeof list.start === 'number' ? list.start : 1
  list.items.forEach((item, index) => {
    const g = glyphs()
    let marker = list.ordered ? `${start + index}.` : g.bullet
    if (item.task) marker = item.checked ? g.checked : g.unchecked
    const prefix = `${marker} `
    const continuation = ' '.repeat(width(prefix))
    const body = renderBlocks(item.tokens, columns - width(prefix), depth + 1, !list.loose)
    body.forEach((line, i) => {
      out.push(i === 0 ? prefix + line : line === '' ? '' : continuation + line)
    })
  })
  return out
}

function renderBlocks(tokens: Token[], columns: number, depth = 0, tight = false): string[] {
  const out: string[] = []
  const gap = () => {
    if (!tight && out.length > 0 && out[out.length - 1] !== '') out.push('')
  }
  for (const token of tokens) {
    switch (token.type) {
      case 'space':
      case 'checkbox':
        // A task item's box is drawn by its list marker.
        break
      case 'heading': {
        gap()
        const heading = token as Tokens.Heading
        const text = inline(heading.tokens)
        out.push(heading.depth <= 2 ? tone.brandBold(text) : tone.heading(text))
        break
      }
      case 'paragraph':
        gap()
        out.push(...inline((token as Tokens.Paragraph).tokens).split('\n'))
        break
      case 'text': {
        const text = token as Tokens.Text
        out.push(...(text.tokens ? inline(text.tokens) : decodeEntities(text.text)).split('\n'))
        break
      }
      case 'list':
        // A nested list sits directly under its item, without a gap.
        if (depth === 0) gap()
        out.push(...renderList(token as Tokens.List, columns, depth))
        break
      case 'code': {
        gap()
        const code = token as Tokens.Code
        // A bar down the left sets code apart without painting a background.
        const bar = tone.border(glyphs().vbar) + ' '
        out.push(...highlight(code.text, code.lang).map(line => bar + line))
        break
      }
      case 'blockquote': {
        gap()
        const inner = renderBlocks((token as Tokens.Blockquote).tokens, columns - 2, depth)
        out.push(...inner.map(l => `${tone.muted(glyphs().vbar)} ${l}`))
        break
      }
      case 'table':
        gap()
        out.push(...renderTable(token as Tokens.Table, columns))
        break
      case 'hr':
        gap()
        out.push(tone.muted(glyphs().rule.repeat(Math.min(columns, 40))))
        break
      case 'html':
        gap()
        out.push(...stripTags((token as Tokens.HTML).text).trimEnd().split('\n'))
        break
      default:
        if ('raw' in token && typeof token.raw === 'string' && token.raw.trim()) {
          gap()
          out.push(...token.raw.trimEnd().split('\n'))
        }
    }
  }
  return out
}

/** Render a Markdown document to terminal lines fitted to `columns` where a layout needs it. */
export function renderMarkdown(source: string, columns: number): string[] {
  const tokens = lexer(stripEmoji(source ?? ''), { gfm: true, breaks: true })
  const lines = renderBlocks(tokens, Math.max(20, columns))
  while (lines.length && lines[lines.length - 1] === '') lines.pop()
  return lines
}
