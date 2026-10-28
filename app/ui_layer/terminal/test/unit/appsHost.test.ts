import { describe, expect, it } from 'vitest'
import type { Key } from 'ink'
import * as TB from '../../src/input/TextBuffer'
import {
  answersPayload,
  appPhase,
  canDelete,
  canLaunch,
  canStop,
  clampKeep,
  coalesceEvents,
  composeAnswer,
  countWords,
  cycleIcon,
  cycleValue,
  deriveProgress,
  dispositionFilename,
  filterMarketplace,
  humanBytes,
  importAmount,
  importName,
  indeterminateBar,
  isTransitional,
  isZipPath,
  moveId,
  nextPaced,
  normalizeIconName,
  orderApps,
  pickOption,
  progressBar,
  pushProgressLine,
  snippetTail,
  tagsByFrequency,
  validateConfig,
  BACKUP_INTERVALS,
  CURATED_ICONS,
  type InterviewQuestion,
  type MarketplaceApp,
} from '../../src/screens/apps/hostModel'
import {
  DEFAULT_THEME,
  THEME_PACKS,
  openThemePicker,
  projectThemeId,
  themeName,
  themePickerKey,
} from '../../src/screens/apps/hostThemes'
import { multiLineKey } from '../../src/screens/apps/hostTab'

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

describe('app status', () => {
  it('maps store statuses to the six shown states', () => {
    expect(appPhase('creating')).toBe('creating')
    expect(appPhase('launching')).toBe('launching')
    expect(appPhase('running')).toBe('running')
    expect(appPhase('stopping')).toBe('stopping')
    expect(appPhase('error')).toBe('error')
    expect(appPhase('stopped')).toBe('stopped')
    // Built but not running, and anything unknown, read as stopped.
    expect(appPhase('ready')).toBe('stopped')
    expect(appPhase(undefined)).toBe('stopped')
  })

  it('offers lifecycle actions only where they make sense', () => {
    expect(isTransitional('creating') && isTransitional('launching') && isTransitional('stopping')).toBe(true)
    expect(isTransitional('running')).toBe(false)
    expect(canLaunch('stopped') && canLaunch('error')).toBe(true)
    expect(canLaunch('running') || canLaunch('creating')).toBe(false)
    expect(canStop('running')).toBe(true)
    expect(canStop('stopped')).toBe(false)
    // Delete only while stopped (or failed), never mid-build or running.
    expect(canDelete('stopped') && canDelete('error')).toBe(true)
    expect(canDelete('running') || canDelete('creating') || canDelete('launching') || canDelete('stopping')).toBe(false)
  })
})

describe('build progress', () => {
  it('is indeterminate without todos', () => {
    expect(deriveProgress(undefined)).toMatchObject({ indeterminate: true, progress: 0, total: 0 })
    expect(deriveProgress([])).toMatchObject({ indeterminate: true })
  })

  it('counts completed todos and cleans the current step', () => {
    const view = deriveProgress([
      { status: 'completed', content: 'Acknowledge: read the brief' },
      { status: 'in_progress', content: 'Execute: write the schema', active_form: 'execute: writing the schema' },
      { status: 'pending', content: 'Verify: test it' },
      { status: 'pending', content: 'Cleanup: tidy up' },
    ])
    expect(view.progress).toBe(25)
    expect(view.done).toBe(1)
    expect(view.total).toBe(4)
    expect(view.label).toBe('Writing the schema')
    expect(view.indeterminate).toBe(false)
  })

  it('draws bars of exactly the requested width', () => {
    expect(progressBar(50, 10, '#', '-')).toBe('#####-----')
    expect(progressBar(150, 4, '#', '-')).toBe('####')
    expect(progressBar(0, 3, '#', '-')).toBe('---')
    for (let tick = 0; tick < 20; tick++) expect(indeterminateBar(tick, 12, '#', '-')).toHaveLength(12)
    expect(indeterminateBar(5, 12, '#', '-')).toContain('#')
  })
})

describe('build feed', () => {
  const ev = (id: string, kind: string, file?: string, area = 'backend') => ({ id, kind, file, area })

  it('collapses consecutive writes of one file and keeps other steps apart', () => {
    const rows = coalesceEvents([
      ev('1', 'file_write', 'a.ts'),
      ev('2', 'file_write', 'a.ts'),
      ev('3', 'file_write', 'a.ts'),
      ev('4', 'file_write', 'b.ts'),
      ev('5', 'read', 'b.ts'),
      ev('6', 'read', 'b.ts'),
      ev('7', 'file_edit', 'b.ts'),
    ])
    expect(rows.map(r => [r.event.id, r.count])).toEqual([
      ['3', 3],
      ['4', 1],
      ['5', 1],
      ['6', 1],
      ['7', 1],
    ])
  })

  it('paces bursts: jumps on first fill, fast with a backlog, slow when nearly caught up', () => {
    expect(nextPaced(0, 20)).toEqual({ count: 17, delay: 0 })
    expect(nextPaced(10, 20)).toEqual({ count: 11, delay: 220 })
    expect(nextPaced(18, 20)).toEqual({ count: 19, delay: 750 })
    expect(nextPaced(20, 20)).toBeNull()
    expect(nextPaced(25, 20)).toEqual({ count: 20, delay: 0 })
    expect(nextPaced(0, 3)).toEqual({ count: 1, delay: 750 })
  })

  it('shows the last lines of a snippet, cleaned for the terminal', () => {
    const snippet = 'line1\n\tline2\r\nline3\u0007\nline4\n\n'
    expect(snippetTail(snippet, 2)).toEqual(['line3', 'line4'])
    expect(snippetTail(snippet, 10)).toEqual(['line1', '  line2', 'line3', 'line4'])
    expect(snippetTail(snippet, 0)).toEqual([])
  })
})

describe('ordering', () => {
  const items = [{ id: 'a' }, { id: 'b' }, { id: 'c' }, { id: 'd' }]

  it('follows the saved order with new apps last', () => {
    expect(orderApps(items, ['c', 'a']).map(i => i.id)).toEqual(['c', 'a', 'b', 'd'])
    expect(orderApps(items, []).map(i => i.id)).toEqual(['a', 'b', 'c', 'd'])
    expect(orderApps(items, ['zz']).map(i => i.id)).toEqual(['a', 'b', 'c', 'd'])
  })

  it('moves one place and refuses past the ends', () => {
    const ids = ['a', 'b', 'c']
    expect(moveId(ids, 'b', -1)).toEqual(['b', 'a', 'c'])
    expect(moveId(ids, 'b', 1)).toEqual(['a', 'c', 'b'])
    expect(moveId(ids, 'a', -1)).toBe(ids)
    expect(moveId(ids, 'c', 1)).toBe(ids)
    expect(moveId(ids, 'x', 1)).toBe(ids)
  })
})

describe('marketplace', () => {
  const apps: MarketplaceApp[] = [
    { id: '1', name: 'Kanban', description: 'Boards and cards', tags: ['productivity', 'tasks'] },
    { id: '2', name: 'Budget', description: 'Money in and out', tags: ['finance', 'productivity'] },
    { id: '3', name: 'Recipes', description: 'Cook book', tags: ['food'] },
  ]

  it('sorts tags by use, then name', () => {
    expect(tagsByFrequency(apps)).toEqual(['productivity', 'finance', 'food', 'tasks'])
  })

  it('filters by text across name, description and tags, and by any selected tag', () => {
    expect(filterMarketplace(apps, 'money', new Set()).map(a => a.id)).toEqual(['2'])
    expect(filterMarketplace(apps, 'TASKS', new Set()).map(a => a.id)).toEqual(['1'])
    expect(filterMarketplace(apps, '', new Set(['food', 'finance'])).map(a => a.id)).toEqual(['2', '3'])
    expect(filterMarketplace(apps, 'kan', new Set(['food']))).toEqual([])
    expect(filterMarketplace(apps, '  ', new Set())).toHaveLength(3)
  })
})

describe('create wizard', () => {
  it('validates name and description like the browser', () => {
    expect(validateConfig('', '')).toEqual({ name: 'nameRequired', description: 'descRequired' })
    expect(validateConfig('x'.repeat(51), 'short')).toEqual({ name: 'nameTooLong', description: 'descTooShort' })
    expect(validateConfig('Notes', 'A notes app with tags')).toEqual({})
    expect(validateConfig('Notes', 'word '.repeat(5001))).toEqual({ description: 'descTooLong' })
    expect(countWords('  one two\nthree  ')).toBe(3)
    expect(countWords('   ')).toBe(0)
  })

  it('normalizes typed icon names to lucide component names', () => {
    expect(normalizeIconName('shopping-cart')).toBe('ShoppingCart')
    expect(normalizeIconName('shopping cart')).toBe('ShoppingCart')
    expect(normalizeIconName('wallet')).toBe('Wallet')
    expect(normalizeIconName('barchart3')).toBe('BarChart3')
    expect(normalizeIconName('lucide:Star')).toBe('Star')
    expect(normalizeIconName('Rocket')).toBe('Rocket')
    expect(normalizeIconName('')).toBeNull()
    expect(normalizeIconName('bad!')).toBeNull()
    expect(normalizeIconName('3d')).toBeNull()
  })

  it('cycles the curated icons through "none"', () => {
    expect(cycleIcon(null, 1)).toBe(CURATED_ICONS[0])
    expect(cycleIcon(null, -1)).toBe(CURATED_ICONS[CURATED_ICONS.length - 1])
    expect(cycleIcon(CURATED_ICONS[CURATED_ICONS.length - 1], 1)).toBeNull()
    expect(cycleIcon('NotCurated', 1)).toBe(CURATED_ICONS[0])
  })

  const single: InterviewQuestion = { id: 'q1', question: 'Pick one', multiSelect: false, options: ['A', 'B'] }
  const multi: InterviewQuestion = { id: 'q2', question: 'Pick any', multiSelect: true, options: ['A', 'B', 'C'] }

  it('selects for single questions and toggles for multi', () => {
    expect(pickOption(single, ['A'], 'B')).toEqual(['B'])
    expect(pickOption(multi, ['A'], 'B')).toEqual(['A', 'B'])
    expect(pickOption(multi, ['A', 'B'], 'A')).toEqual(['B'])
  })

  it('joins or replaces with typed text, as Continue does', () => {
    expect(composeAnswer(single, ['A'], '  mine ')).toEqual(['mine'])
    expect(composeAnswer(multi, ['A'], 'mine')).toEqual(['A', 'mine'])
    expect(composeAnswer(multi, ['A', 'C'], '  ')).toEqual(['A', 'C'])
    expect(composeAnswer(single, [], '')).toEqual([])
  })

  it('sends only answered questions, options joined', () => {
    expect(answersPayload([single, multi], { q2: ['A', 'mine'], q1: [] })).toEqual([{ id: 'q2', question: 'Pick any', answer: 'A, mine' }])
  })
})

describe('import', () => {
  it('names an import after its last segment', () => {
    expect(importName('https://github.com/user/kanban-board.git', 'External App')).toBe('kanban-board')
    expect(importName('C:\\apps\\notes\\', 'External App')).toBe('notes')
    expect(importName('/tmp/agentapp_notes_3fa9c2.zip', 'External App')).toBe('notes')
    expect(importName('', 'External App')).toBe('External App')
    expect(isZipPath(' a/b/App.ZIP ')).toBe(true)
    expect(isZipPath('https://github.com/a/b')).toBe(false)
  })

  it('formats progress amounts', () => {
    expect(importAmount({ phase: 'starting' })).toBe('')
    expect(importAmount({ phase: 'copying', done: 0, total: 0 })).toBe('')
    expect(importAmount({ phase: 'copying', done: 1200, total: 5000, unit: 'files' }, 'en')).toBe('1,200 / 5,000 (24%)')
    expect(importAmount({ phase: 'downloading', done: 3 * 1024 * 1024, total: 0, unit: 'bytes' })).toBe('3.0 MB')
    expect(humanBytes(0)).toBe('0 B')
    expect(humanBytes(512)).toBe('512 B')
    expect(humanBytes(1536)).toBe('1.5 KB')
  })

  it('keeps one progress line per phase', () => {
    let lines = pushProgressLine([], { phase: 'download', text: '1' })
    lines = pushProgressLine(lines, { phase: 'download', text: '2' })
    lines = pushProgressLine(lines, { phase: 'extract', text: '3' })
    expect(lines).toEqual([
      { phase: 'download', text: '2' },
      { phase: 'extract', text: '3' },
    ])
    let many: { phase: string; text: string }[] = []
    for (let i = 0; i < 12; i++) many = pushProgressLine(many, { phase: `p${i}`, text: '' }, 8)
    expect(many).toHaveLength(8)
    expect(many[0].phase).toBe('p4')
  })
})

describe('settings panel helpers', () => {
  it('cycles backup intervals and clamps the keep count', () => {
    expect(cycleValue(BACKUP_INTERVALS, 'weekly', 1)).toBe('hourly')
    expect(cycleValue(BACKUP_INTERVALS, 'hourly', -1)).toBe('weekly')
    expect(cycleValue(BACKUP_INTERVALS, 'daily', 1)).toBe('weekly')
    expect(clampKeep(0)).toBe(1)
    expect(clampKeep(31)).toBe(30)
    expect(clampKeep(7.4)).toBe(7)
  })

  it('takes a safe file name from Content-Disposition', () => {
    expect(dispositionFilename('attachment; filename="Expense_tracker.zip"', 'x.zip')).toBe('Expense_tracker.zip')
    expect(dispositionFilename('attachment; filename="a/b:c.zip"', 'x.zip')).toBe('a_b_c.zip')
    expect(dispositionFilename(null, 'x.zip')).toBe('x.zip')
  })
})

describe('theme packs', () => {
  it('carries the browser catalog of 16 packs', () => {
    expect(THEME_PACKS).toHaveLength(16)
    expect(THEME_PACKS[0].id).toBe(DEFAULT_THEME)
    expect(new Set(THEME_PACKS.map(p => p.id)).size).toBe(16)
  })

  it('prefers the saved pick over the build-time style pack', () => {
    expect(projectThemeId({ uiTheme: { themeId: 'ocean' }, stylePack: 'forest' })).toBe('ocean')
    expect(projectThemeId({ uiTheme: null, stylePack: 'forest' })).toBe('forest')
    expect(projectThemeId(undefined)).toBe(DEFAULT_THEME)
  })

  it('never shows the product name for the baseline pack', () => {
    const t = (k: string) => (k === 'appsHost:theme.default' ? 'Default' : k)
    expect(themeName(t, DEFAULT_THEME)).toBe('Default')
    expect(themeName(t, 'ocean')).toBe('agentapp:themes.ocean.label')
  })

  it('moves, applies and cancels with keys', () => {
    const start = openThemePicker('ocean')
    expect(THEME_PACKS[start.index].id).toBe('ocean')
    const moved = themePickerKey(start, 'j', key(), 10)
    expect(moved?.kind).toBe('move')
    if (moved?.kind !== 'move') return
    expect(themePickerKey(moved.state, '', key({ return: true }), 10)).toEqual({ kind: 'apply', themeId: THEME_PACKS[start.index + 1].id })
    expect(themePickerKey(start, '', key({ escape: true }), 10)).toEqual({ kind: 'cancel' })
    expect(themePickerKey(start, 'z', key(), 10)).toBeNull()
  })
})

describe('description field', () => {
  it('adds lines with Shift+Enter or Ctrl+J and leaves plain Enter to the form', () => {
    const buf = TB.fromText('ab')
    expect(multiLineKey(buf, '', key({ return: true, shift: true }), 40)?.text).toBe('ab\n')
    expect(multiLineKey(buf, '\n', key(), 40)?.text).toBe('ab\n')
    expect(multiLineKey(buf, '', key({ return: true }), 40)).toBeNull()
  })

  it('keeps pasted line breaks and moves by visual row', () => {
    expect(multiLineKey(TB.EMPTY, 'one\r\ntwo', key(), 40)?.text).toBe('one\ntwo')
    const two = TB.fromText('one\ntwo')
    expect(multiLineKey(two, '', key({ upArrow: true }), 40)?.cursor).toBeLessThan(two.cursor)
    // At the top row, Up is left to the form (previous field).
    expect(multiLineKey(TB.fromText('one'), '', key({ upArrow: true }), 40)).toBeNull()
  })
})
