import { describe, expect, it, vi } from 'vitest'
import stripAnsi from 'strip-ansi'
import type { ActionItem, ChatMessage, MiniBrowserTab } from '../../../browser/frontend/src/types'
import {
  anchorFor,
  blockAtLine,
  buildBlocks,
  chunkLines,
  chunkMarkdown,
  conversationMarkdown,
  findMatches,
  highlightMatches,
  layoutBlocks,
  messageMarkdown,
  resolveTop,
  revealBlock,
  slug,
  splitReply,
  stepMatch,
  REPLY_MARKER,
  type Block,
  type ChunkLabels,
} from '../../src/screens/viewTranscript'
import {
  clearReplyTarget,
  getReplyTarget,
  replyTargetFor,
  setReplyTarget,
  subscribeReplyTarget,
} from '../../src/screens/transcriptReply'
import { clipboardCommands, osc52Sequence } from '../../src/screens/viewClipboard'
import { editorCommand, editorCommandLine, editorFilePath } from '../../src/screens/viewEditor'
import {
  canInstall,
  canToggleControl,
  displayUrl,
  driverSession,
  needsCloseConfirm,
  ownerKind,
  tabState,
} from '../../src/screens/viewBrowser'
import { width } from '../../src/text/width'

const msg = (id: string, ts: number, extra: Partial<ChatMessage> = {}): ChatMessage => ({
  sender: 'Aria',
  content: `message ${id}`,
  style: 'agent',
  timestamp: ts,
  messageId: id,
  sessionId: 's1',
  ...extra,
})

const act = (id: string, createdAt: number, extra: Partial<ActionItem> = {}): ActionItem => ({
  id,
  name: 'web_search',
  status: 'completed',
  itemType: 'action',
  sessionId: 's1',
  createdAt,
  completedAt: createdAt + 1200,
  duration: 1200,
  input: JSON.stringify({ query: 'ramen near me' }),
  ...extra,
})

const labels: ChunkLabels = {
  actions: n => `${n} actions`,
  failed: n => `${n} failed`,
  reasoning: 'Reasoning',
  thinking: 'Thinking...',
  status: { running: 'running', waiting: 'waiting', paused: 'paused', pending: 'queued', cancelled: 'cancelled' },
}

const plain = (lines: string[]) => lines.map(l => stripAnsi(l))

describe('transcript blocks', () => {
  it('keeps every action and reasoning step between messages, minus chat sends', () => {
    const blocks = buildBlocks(
      [msg('m1', 1, { style: 'user', sender: 'You' }), msg('m2', 10), msg('p', 11, { pending: true })],
      [
        act('a1', 2000),
        act('send', 3000, { name: 'send_message' }),
        act('r1', 4000, { itemType: 'reasoning', name: 'reasoning', output: 'I should look nearby.' }),
        act('r2', 5000, { itemType: 'reasoning', name: 'reasoning', output: '' }),
        act('r3', 12000, { itemType: 'reasoning', name: 'reasoning', output: 'Only thoughts here.' }),
      ],
    )
    expect(blocks.map(b => b.key)).toEqual(['msg:m1', 'chunk:a1', 'msg:m2', 'chunk:r3'])
    const chunk = blocks[1] as Extract<Block, { kind: 'chunk' }>
    expect(chunk.items.map(i => i.id)).toEqual(['a1', 'r1'])
  })

  it('shows each action row with status, name, preview, duration and the whole error', () => {
    const items = [
      act('a1', 1000),
      act('a2', 3000, { name: 'run_shell', status: 'error', error: 'exit code 1\nmodule not found', input: '{"command":"npm test"}' }),
      act('r1', 5000, { itemType: 'reasoning', name: 'reasoning', output: 'Try again with a fix.' }),
    ]
    const lines = plain(chunkLines(items, labels, 60))
    expect(lines[0]).toContain('2 actions')
    expect(lines[0]).toContain('1 failed')
    expect(lines[1]).toMatch(/Web search\s+ramen near me\s+1\.2s/)
    expect(lines[2]).toContain('Run shell')
    expect(lines).toContain('      exit code 1')
    expect(lines).toContain('      module not found')
    expect(lines.some(l => l.includes('Reasoning'))).toBe(true)
    expect(lines.some(l => l.includes('Try again with a fix.'))).toBe(true)
    for (const line of lines) expect(width(line)).toBeLessThanOrEqual(60)
    expect(chunkLines(items, labels, 60, false)).toHaveLength(1)
  })

  it('names live states in words, not only glyphs', () => {
    const lines = plain(chunkLines([act('a', 1000, { status: 'running', completedAt: undefined, duration: undefined })], labels, 80, true, 4000))
    expect(lines[0]).toContain('running')
    expect(lines[1]).toMatch(/running 3\.0s/)
  })
})

describe('transcript layout and scrolling', () => {
  const render = (block: Block) => (block.kind === 'message' ? [`${block.message.sender}`, block.message.content] : ['chunk'])
  const blocks = buildBlocks([msg('a', 1), msg('b', 2), msg('c', 3), msg('d', 4)], [])

  it('lays blocks out with a gap between them and records where each starts', () => {
    const layout = layoutBlocks(blocks, render, 40, ['header'])
    expect(layout.starts).toEqual([2, 5, 8, 11])
    expect(layout.ends).toEqual([4, 7, 10, 13])
    expect(layout.blockOf.slice(0, 3)).toEqual([-1, -1, 0])
    expect(blockAtLine(1, layout)).toBe(0)
    expect(blockAtLine(4, layout)).toBe(1)
  })

  it('wraps long lines to the width and expands tabs', () => {
    const layout = layoutBlocks([blocks[0]], () => ['x'.repeat(50), 'a\tb'], 20)
    expect(layout.lines.slice(0, 3)).toEqual(['x'.repeat(20), 'x'.repeat(20), 'x'.repeat(10)])
    expect(layout.lines[3]).toBe('a    b')
  })

  it('follows the bottom without an anchor and keeps its place when older pages arrive', () => {
    const layout = layoutBlocks(blocks, render, 40)
    expect(resolveTop(null, blocks, layout, 5)).toBe(layout.lines.length - 5)
    const anchor = anchorFor(3, blocks, layout, 5)
    expect(anchor).toEqual({ key: 'msg:b', offset: 0 })
    const older = buildBlocks([msg('y', 0.1), msg('z', 0.5), msg('a', 1), msg('b', 2), msg('c', 3), msg('d', 4)], [])
    const after = layoutBlocks(older, render, 40)
    expect(after.lines[resolveTop(anchor, older, after, 5)]).toBe('Aria')
    expect(after.blockOf[resolveTop(anchor, older, after, 5)]).toBe(3)
  })

  it('scrolls just enough to reveal a block', () => {
    const layout = layoutBlocks(blocks, render, 40)
    expect(revealBlock(0, 3, layout, 4)).toBe(layout.ends[3] - 4)
    expect(revealBlock(8, 0, layout, 4)).toBe(0)
    expect(revealBlock(0, 0, layout, 4)).toBe(0)
  })
})

describe('transcript search', () => {
  const lines = ['\u001B[1mHello\u001B[22m world', 'nothing', 'say HELLO again']
  it('matches visible text case-insensitively', () => {
    expect(findMatches(lines, 'hello')).toEqual([0, 2])
    expect(findMatches(lines, '  ')).toEqual([])
  })
  it('steps to the next and previous match, wrapping around', () => {
    expect(stepMatch([0, 2], 0, 1)).toBe(2)
    expect(stepMatch([0, 2], 2, 1)).toBe(0)
    expect(stepMatch([0, 2], 2, -1)).toBe(0)
    expect(stepMatch([0, 2], 0, -1)).toBe(2)
    expect(stepMatch([], 0, 1)).toBeNull()
  })
  it('marks every occurrence', () => {
    expect(highlightMatches('say HELLO again hello', 'hello', s => `[${s}]`)).toBe('say [HELLO] again [hello]')
  })
})

describe('transcript Markdown', () => {
  it('copies what the user typed, without the quoted reply', () => {
    const content = `Yes please\n\n${REPLY_MARKER}\nShall I book it?`
    expect(splitReply(content)).toEqual({ text: 'Yes please', quoted: 'Shall I book it?' })
    expect(messageMarkdown(msg('u', 1, { style: 'user', content }))).toBe('Yes please')
    expect(messageMarkdown(msg('a', 1, { content: '**Done**', attachments: [{ name: 'a.pdf', type: 'application/pdf', size: 3, path: '/w/a.pdf' } as never] }))).toBe(
      '**Done**\n\n[a.pdf](/w/a.pdf)',
    )
  })

  it('writes a chunk as a list and the conversation as a document', () => {
    const items = [act('a1', 1000), act('a2', 2000, { status: 'error', error: 'boom' })]
    const list = chunkMarkdown(items, labels)
    expect(list).toContain('- [x] Web search `ramen near me` (1.2s)')
    expect(list).toContain('- [!] Web search (1.2s)\n  > boom')
    const blocks = buildBlocks([msg('m1', 1, { details: 'raw body' }), msg('m2', 5, { style: 'user', sender: 'You', content: 'thanks' })], items)
    const doc = conversationMarkdown(blocks, {
      title: 'Transcript · Main',
      heading: m => m.sender,
      labels,
      detailsLabel: 'Details',
      replyingToLabel: 'Replying to',
    })
    expect(doc.startsWith('# Transcript · Main\n\n## Aria\n\nmessage m1')).toBe(true)
    expect(doc).toContain('<details><summary>Details</summary>\n\nraw body')
    expect(doc).toContain('> ▸ 2 actions')
    expect(doc).toContain('## You\n\nthanks')
  })

  it('makes a safe file name from any title', () => {
    expect(slug('Trip to 東京, May!')).toBe('trip-to-may')
    expect(slug('東京')).toBe('chat')
  })
})

describe('reply target', () => {
  it('is offered on agent messages without options, as in the browser', () => {
    expect(replyTargetFor(msg('a', 1, { content: 'x'.repeat(60) }))?.displayName).toBe(`${'x'.repeat(50)}...`)
    expect(replyTargetFor(msg('u', 1, { style: 'user' }))).toBeNull()
    expect(replyTargetFor(msg('q', 1, { options: [{ label: 'Yes', value: 'yes' }] }))).toBeNull()
  })

  it('is kept per session and announces changes', () => {
    const listener = vi.fn()
    const off = subscribeReplyTarget(listener)
    const target = replyTargetFor(msg('a', 1))!
    setReplyTarget(target)
    expect(getReplyTarget('s1')).toEqual(target)
    expect(getReplyTarget('other')).toBeNull()
    expect(getReplyTarget()).toEqual(target)
    clearReplyTarget()
    clearReplyTarget()
    expect(getReplyTarget()).toBeNull()
    expect(listener).toHaveBeenCalledTimes(2)
    off()
  })
})

describe('clipboard', () => {
  it('uses Set-Clipboard on Windows with the text as base64', () => {
    const [cmd] = clipboardCommands('win32', {})
    expect(cmd.command).toBe('powershell.exe')
    expect(cmd.input).toBe('base64')
    expect(cmd.args.join(' ')).toContain('Set-Clipboard')
  })
  it('uses pbcopy, wl-copy, xclip and xsel where they apply', () => {
    expect(clipboardCommands('darwin', {}).map(c => c.command)).toEqual(['pbcopy'])
    expect(clipboardCommands('linux', { WAYLAND_DISPLAY: 'wayland-0', DISPLAY: ':0' }).map(c => c.command)).toEqual(['wl-copy', 'xclip', 'xsel'])
    expect(clipboardCommands('linux', {})).toEqual([])
  })
  it('goes through the terminal (OSC 52) over SSH', () => {
    expect(clipboardCommands('linux', { SSH_TTY: '/dev/pts/1', DISPLAY: ':0' })).toEqual([])
    expect(osc52Sequence('hi', {})).toBe('\u001B]52;c;aGk=\u0007')
    expect(osc52Sequence('hi', { TMUX: '1' })).toBe('\u001BPtmux;\u001B\u001B]52;c;aGk=\u0007\u001B\\')
  })
})

describe('editor', () => {
  it('prefers $VISUAL, then $EDITOR, then the platform default', () => {
    expect(editorCommand({ VISUAL: 'code --wait', EDITOR: 'vim' }, 'linux')).toBe('code --wait')
    expect(editorCommand({ EDITOR: 'nano' }, 'linux')).toBe('nano')
    expect(editorCommand({}, 'win32')).toBe('notepad')
    expect(editorCommand({}, 'darwin')).toBe('vi')
  })
  it('quotes the file for the shell', () => {
    expect(editorCommandLine('notepad', 'C:\\Temp\\a b.md', 'win32')).toBe('notepad "C:\\Temp\\a b.md"')
    expect(editorCommandLine('vi', "/tmp/it's.md", 'linux')).toBe(`vi '/tmp/it'\\''s.md'`)
    expect(editorFilePath('main', 5, '/tmp').replace(/\\/g, '/')).toBe('/tmp/craftbot-main-5.md')
  })
})

describe('browser screen rules', () => {
  const tab = (extra: Partial<MiniBrowserTab> = {}): MiniBrowserTab => ({
    id: 't1',
    sessionId: 's1',
    url: 'https://www.example.com/',
    title: 'Example',
    loading: false,
    owner: 's1',
    ownerLabel: 'Trip',
    ownerKind: 'session',
    parentOwner: null,
    busy: false,
    userControl: false,
    canGoBack: false,
    canGoForward: false,
    crashed: false,
    favicon: null,
    ...extra,
  })

  it('finds the run that drives a tab', () => {
    expect(driverSession(tab())).toBe('s1')
    expect(driverSession(tab({ ownerKind: 'subagent', owner: 'sub_1', parentOwner: 's1' }))).toBe('s1')
    expect(driverSession(tab({ ownerKind: 'user', owner: null }))).toBeNull()
  })

  it('reads a tab state, crashes and control first', () => {
    expect(tabState(tab({ busy: true }))).toBe('working')
    expect(tabState(tab({ busy: true, userControl: true }))).toBe('control')
    expect(tabState(tab({ crashed: true, userControl: true }))).toBe('crashed')
    expect(tabState(tab({ loading: true }))).toBe('loading')
    expect(tabState(tab({ ownerKind: 'user', owner: null, busy: true }))).toBe('idle')
  })

  it('asks before closing a tab an agent works in', () => {
    expect(needsCloseConfirm(tab({ busy: true }))).toBe(true)
    expect(needsCloseConfirm(tab({ busy: true, userControl: true }))).toBe(false)
    expect(needsCloseConfirm(tab())).toBe(false)
  })

  it('offers take control on agent tabs and hand back on controlled ones', () => {
    expect(canToggleControl(tab())).toBe(true)
    expect(canToggleControl(tab({ ownerKind: 'user', owner: null }))).toBe(false)
    expect(canToggleControl(tab({ ownerKind: 'user', owner: null, userControl: true }))).toBe(true)
  })

  it('offers an install only when Chromium is missing or the last install failed', () => {
    const missing = { code: 'MINI_BROWSER_CHROMIUM_MISSING', title: '', message: '' }
    expect(canInstall('error', missing, null)).toBe(true)
    expect(canInstall('error', { ...missing, code: 'MINI_BROWSER_LAUNCH_FAILED' }, null)).toBe(false)
    expect(canInstall('error', null, false)).toBe(true)
    expect(canInstall('ready', missing, null)).toBe(false)
  })

  it('names owners and addresses compactly', () => {
    expect(ownerKind(tab(), 's1')).toBe('agent')
    expect(ownerKind(tab(), 'other')).toBe('session')
    expect(ownerKind(tab({ ownerKind: 'main', owner: 'main' }), 's1')).toBe('main')
    expect(ownerKind(tab({ ownerKind: 'user', owner: null }), 's1')).toBe('you')
    expect(displayUrl('https://www.example.com/')).toBe('example.com')
    expect(displayUrl('https://example.com/a/b?q=1')).toBe('example.com/a/b?q=1')
    expect(displayUrl('about:blank')).toBe('about:blank')
  })
})
