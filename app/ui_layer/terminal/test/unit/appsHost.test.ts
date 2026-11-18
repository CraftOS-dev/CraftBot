import { describe, expect, it } from 'vitest'
import type { Key } from 'ink'
import * as TB from '../../src/input/TextBuffer'
import type { FrameworkRegistryApp, SessionInfo } from '../../../browser/frontend/src/types'
import {
  answersPayload,
  clampKeep,
  coalesceEvents,
  composeAnswer,
  countWords,
  cycleIcon,
  cycleValue,
  deriveProgress,
  filterMarketplace,
  humanBytes,
  importName,
  indeterminateBar,
  installedFrom,
  isZipPath,
  nextPaced,
  normalizeIconName,
  pickOption,
  progressBar,
  readablePartA,
  tagsByFrequency,
  validateConfig,
  BACKUP_INTERVALS,
  CURATED_ICONS,
  type InterviewQuestion,
  type MarketplaceApp,
} from '../../src/screens/apps/hostModel'
import { appPhase, canChangeState, isTransitional, moveId, orderEntries, orderIdOf, pendingOrderId, type AppEntry } from '../../src/apps/framework'
import { removalKind } from '../../src/apps/removal'
import {
  DEFAULT_THEME,
  THEME_PACKS,
  appThemeId,
  openThemePicker,
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

const app = (over: Partial<FrameworkRegistryApp> = {}): FrameworkRegistryApp => ({ id: 'a1', name: 'Notes', path: '/apps/notes', status: 'stopped', ...over })
const connection = { appId: 'r1', name: 'CRM', origin: 'https://crm.example.com', credentialId: 'c', principalName: 'Ana', principal: 'p', status: 'online' as const }

describe('app status', () => {
  it('shows the registry status, or the start or stop on its way', () => {
    expect(appPhase(app({ status: 'running' }), undefined)).toBe('running')
    expect(appPhase(app({ status: 'missing' }), undefined)).toBe('missing')
    expect(appPhase(app(), { status: 'running', operation: 'start' })).toBe('starting')
    expect(appPhase(app({ status: 'running' }), { status: 'running', operation: 'stop' })).toBe('stopping')
    // A finished or failed operation leaves the registry's word.
    expect(appPhase(app(), { status: 'error', operation: 'start' })).toBe('stopped')
    expect(isTransitional('starting') && isTransitional('stopping')).toBe(true)
    expect(isTransitional('running') || isTransitional('missing')).toBe(false)
  })

  it('starts and stops only local apps the host can see', () => {
    expect(canChangeState(app()) && canChangeState(app({ status: 'running' }))).toBe(true)
    expect(canChangeState(app({ status: 'missing' })) || canChangeState(app({ status: 'unreachable' }))).toBe(false)
    expect(canChangeState(app({ status: 'running', connection }))).toBe(false)
  })

  it('deletes, forgets or disconnects by what the app is', () => {
    expect(removalKind(app(), false)).toBe('remove')
    expect(removalKind(app(), true)).toBe('forget')
    expect(removalKind(app({ status: 'missing' }), false)).toBe('forget')
    expect(removalKind(app({ connection }), false)).toBe('disconnect')
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

})

describe('ordering', () => {
  const a = app({ id: 'a', path: '/a' })
  const b = app({ id: 'b', path: '/b' })
  const session = { id: 's1' } as SessionInfo
  const entries: AppEntry[] = [
    { kind: 'app', orderId: orderIdOf(a), app: a },
    { kind: 'app', orderId: orderIdOf(b), app: b },
    { kind: 'pending', orderId: pendingOrderId('s1'), session },
  ]

  it('keys apps by path and id, and builds by session, as the sidebar does', () => {
    expect(orderIdOf(a)).toBe('framework:["/a","a"]')
    expect(pendingOrderId('s1')).toBe('pending:s1')
  })

  it('follows the saved order with the rest after it', () => {
    expect(orderEntries(entries, ['pending:s1', orderIdOf(b)]).map(e => e.orderId)).toEqual(['pending:s1', orderIdOf(b), orderIdOf(a)])
    expect(orderEntries(entries, []).map(e => e.orderId)).toEqual(entries.map(e => e.orderId))
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

  it('knows what is installed from this catalogue', () => {
    const source = { location: 'github:CraftOS-dev/Agent-App-Marketplace', ref: 'main' }
    const apps = [
      { status: 'running', marketplace: { id: 'kanban', location: source.location, ref: 'main' } },
      { status: 'missing', marketplace: { id: 'budget', location: source.location, ref: 'main' } },
      { status: 'stopped', marketplace: { id: 'recipes', location: 'elsewhere' } },
      { status: 'stopped' },
    ]
    expect([...installedFrom(apps, source)]).toEqual(['kanban'])
    expect(installedFrom(apps, undefined).size).toBe(0)
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
    expect(composeAnswer(single, ['A'], '  mine ')).toEqual({ choices: [], other: 'mine' })
    expect(composeAnswer(multi, ['A'], 'mine')).toEqual({ choices: ['A'], other: 'mine' })
    expect(composeAnswer(multi, ['A', 'C'], '  ')).toEqual({ choices: ['A', 'C'], other: '' })
  })

  it('answers every question; skipped ones are left to the builder', () => {
    expect(answersPayload([single, multi], { q2: { choices: ['A'], other: 'mine' } })).toEqual([
      { id: 'q1', choices: [] },
      { id: 'q2', choices: ['A'], other: 'mine' },
    ])
  })

  it('reads Part A without its marker and approval section, wrapped lines joined', () => {
    const partA = ['PART A (requirements)', '# Goals', 'Track notes', 'by tag.', '- one', '- two', '## Approval', 'Approved by: nobody'].join('\n')
    expect(readablePartA(partA)).toBe(['# Goals', 'Track notes by tag.', '- one', '- two'].join('\n'))
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

  it('measures sizes', () => {
    expect(humanBytes(0)).toBe('0 B')
    expect(humanBytes(512)).toBe('512 B')
    expect(humanBytes(1536)).toBe('1.5 KB')
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

})

describe('theme packs', () => {
  it('carries the browser catalog of 16 packs', () => {
    expect(THEME_PACKS).toHaveLength(16)
    expect(THEME_PACKS[0].id).toBe(DEFAULT_THEME)
    expect(new Set(THEME_PACKS.map(p => p.id)).size).toBe(16)
  })

  it('shows the saved pick, else the baseline', () => {
    expect(appThemeId({ uiTheme: { themeId: 'ocean' } })).toBe('ocean')
    expect(appThemeId({ uiTheme: null })).toBe(DEFAULT_THEME)
    expect(appThemeId(undefined)).toBe(DEFAULT_THEME)
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
