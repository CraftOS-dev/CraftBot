import { describe, expect, it } from 'vitest'
import stripAnsi from 'strip-ansi'
import { renderMarkdown } from '../../src/render/markdown'
import { suggestions, slashQuery } from '../../src/input/completion'
import { buildUnits, isOpenChoice, liveChunk } from '../../src/chat/timeline'
import { width } from '../../src/text/width'
import type { ActionItem, ChatMessage } from '../../../browser/frontend/src/types'

const plain = (md: string, cols = 60) => renderMarkdown(md, cols).map(l => stripAnsi(l))

describe('markdown', () => {
  it('keeps prose as logical lines with single newlines as breaks', () => {
    const long = 'word '.repeat(40).trim()
    expect(plain(`${long}\nnext`)).toEqual([long, 'next'])
  })

  it('renders lists, nested lists and tasks', () => {
    const out = plain('- one\n  - inner\n- [x] done\n1. first')
    expect(out[0]).toBe('• one')
    expect(out[1]).toBe('  • inner')
    expect(out).toContain('■ done')
    expect(out[out.length - 1]).toBe('1. first')
  })

  it('fits tables to the width', () => {
    const md = '| Name | Notes |\n|---|---|\n| a | ' + 'long text '.repeat(10) + '|'
    for (const line of plain(md, 40)) expect(width(line)).toBeLessThanOrEqual(40)
  })

  it('shows code blocks line by line behind a bar', () => {
    expect(plain('```python\nprint(1)\nx = 2\n```')).toEqual(['│ print(1)', '│ x = 2'])
  })

  it('writes links with their address', () => {
    expect(plain('[docs](https://example.com)')[0]).toBe('docs (https://example.com)')
  })
})

describe('slash completion', () => {
  const commands = [{ name: 'help', description: 'Help' }, { name: 'clear', description: 'Clear' }]
  const skills = [
    { name: 'my-skill', description: 'S', enabled: true, user_invocable: true },
    { name: 'off', description: 'O', enabled: false, user_invocable: true },
  ]
  it('only completes a lone slash word', () => {
    expect(slashQuery('/he')).toBe('he')
    expect(slashQuery('/help me')).toBeNull()
    expect(slashQuery('hello')).toBeNull()
  })
  it('matches word starts and hides disabled skills', () => {
    expect(suggestions('/sk', commands, skills).map(s => s.value)).toEqual(['/my-skill'])
    expect(suggestions('/', commands, skills).map(s => s.value)).toEqual(['/help', '/clear', '/my-skill'])
  })
})

const msg = (id: string, ts: number, extra: Partial<ChatMessage> = {}): ChatMessage => ({
  sender: 'Aria',
  content: id,
  style: 'agent',
  timestamp: ts,
  messageId: id,
  sessionId: 's',
  ...extra,
})
const act = (id: string, ms: number, extra: Partial<ActionItem> = {}): ActionItem => ({
  id,
  name: 'web_search',
  status: 'completed',
  itemType: 'action',
  sessionId: 's',
  createdAt: ms,
  ...extra,
})

describe('timeline units', () => {
  it('groups activity between messages into chunks', () => {
    const units = buildUnits([msg('u', 1, { style: 'user' }), msg('r', 10)], [act('a1', 2000), act('a2', 3000)], false)
    expect(units.map(u => u.kind)).toEqual(['message', 'chunk', 'message'])
    const chunk = units[1]
    expect(chunk.kind === 'chunk' && chunk.actionCount).toBe(2)
    expect(chunk.kind === 'chunk' && chunk.final).toBe(true)
  })

  it('keeps the running tail chunk live while busy', () => {
    const units = buildUnits([msg('u', 1, { style: 'user' })], [act('a1', 2000, { status: 'running' })], true)
    expect(liveChunk(units)?.items.length).toBe(1)
  })

  it('drops reply-only chunks and optimistic bubbles', () => {
    const units = buildUnits(
      [msg('p', 1, { style: 'user', pending: true }), msg('r', 10)],
      [act('send', 2000, { name: 'send_message' })],
      false,
    )
    expect(units.map(u => u.key)).toEqual(['msg:r'])
  })

  it('marks unanswered questions open until answered', () => {
    const q = msg('q', 5, { isQuestion: true, options: [{ label: 'Yes', value: 'yes' }] })
    expect(isOpenChoice(q)).toBe(true)
    expect(isOpenChoice({ ...q, optionSelected: 'yes' })).toBe(false)
    const units = buildUnits([q], [], false)
    expect(units[0].kind === 'message' && units[0].open).toBe(true)
  })
})
