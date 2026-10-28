import { describe, expect, it } from 'vitest'
import { join } from 'node:path'
import {
  ASCII_METER,
  changedLines,
  cleanPath,
  contextLevel,
  describeCron,
  dispositionFilename,
  filterOptions,
  formatBytes,
  formatRemaining,
  labelWidth,
  meter,
  normalizeEdited,
  openUrlCommand,
  parseClock,
  priorityLevel,
  quoteWindowsArg,
  resolveExportPath,
  runsToday,
  scrollTop,
} from '../../src/screens/settings/coreLogic'
import { resolveCursor, stepCursor, type FormRow } from '../../src/screens/settings/coreForm'
import { width } from '../../src/text/width'

const t = (key: string, options?: Record<string, unknown>) => `${key}${options ? ' ' + JSON.stringify(options) : ''}`

describe('meter', () => {
  it('fills by ratio and clamps', () => {
    expect(meter(0.5, 10, null, ASCII_METER)).toBe('#####.....')
    expect(meter(2, 4, null, ASCII_METER)).toBe('####')
    expect(meter(-1, 4, null, ASCII_METER)).toBe('....')
    expect(meter(Number.NaN, 3, null, ASCII_METER)).toBe('...')
  })

  it('places a marker cell inside the bar', () => {
    expect(meter(0, 5, 1, ASCII_METER)).toBe('....|')
    expect(meter(1, 5, 0, ASCII_METER)).toBe('|####')
    expect(width(meter(0.3, 20, 0.5))).toBe(20)
  })

  it('turns amber at 70% and red at 90%', () => {
    expect(contextLevel(0.69)).toBe('normal')
    expect(contextLevel(0.7)).toBe('warn')
    expect(contextLevel(0.9)).toBe('high')
  })
})

describe('time text', () => {
  it('formats a countdown', () => {
    expect(formatRemaining(61_000)).toBe('1:01')
    expect(formatRemaining(3_725_000)).toBe('1:02:05')
    expect(formatRemaining(-5)).toBe('0:00')
  })

  it('normalizes typed clock times', () => {
    expect(parseClock('7:5')).toBe('07:05')
    expect(parseClock('0730')).toBe('07:30')
    expect(parseClock('23:59')).toBe('23:59')
    expect(parseClock('8')).toBe('08:00')
    expect(parseClock('24:00')).toBeNull()
    expect(parseClock('7:60')).toBeNull()
    expect(parseClock('soon')).toBeNull()
  })

  it('knows whether a daily run is still today', () => {
    const now = new Date(2026, 9, 28, 10, 30)
    expect(runsToday('11:00', now)).toBe(true)
    expect(runsToday('10:30', now)).toBe(false)
    expect(runsToday('03:00', now)).toBe(false)
  })

  it('describes cron schedules like the browser', () => {
    expect(describeCron('0,30 * * * *', t, 'en')).toBe('cron.timesHourly {"count":2}')
    expect(describeCron('15 * * * *', t, 'en')).toBe('cron.hourly {"minute":"15"}')
    expect(describeCron('*/10 * * * *', t, 'en')).toBe('cron.everyMinutes {"count":10}')
    expect(describeCron('0 8 * * *', t, 'en')).toMatch(/^cron\.daily /)
    expect(describeCron('0 17 * * 0', t, 'en')).toMatch(/^cron\.weekly .*cron\.days\.sun/)
    expect(describeCron('0 8 1 * *', t, 'en')).toMatch(/^cron\.monthly \{"day":"1"/)
    expect(describeCron('every day at 7am', t, 'en')).toBe('every day at 7am')
  })

  it('maps priority values to levels', () => {
    expect(priorityLevel(30)).toBe('high')
    expect(priorityLevel(50)).toBe('medium')
    expect(priorityLevel(70)).toBe('low')
  })

  it('formats byte counts', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2 KB')
    expect(formatBytes(5 * 1_048_576)).toBe('5 MB')
    expect(formatBytes(3 * 1_073_741_824)).toBe('3.0 GB')
  })
})

describe('external programs', () => {
  it('quotes Windows arguments only when needed', () => {
    expect(quoteWindowsArg('notepad')).toBe('notepad')
    expect(quoteWindowsArg('C:\\Users\\A B\\x.md')).toBe('"C:\\Users\\A B\\x.md"')
    expect(quoteWindowsArg('https://a.b/?x=1&y=2')).toBe('"https://a.b/?x=1&y=2"')
  })

  it('opens links with the platform launcher', () => {
    expect(openUrlCommand('https://x.y', 'win32')).toEqual({ command: 'cmd', args: ['/c', 'start', '""', 'https://x.y'], shell: false })
    expect(openUrlCommand('https://x.y', 'darwin').command).toBe('open')
    expect(openUrlCommand('https://x.y', 'linux').command).toBe('xdg-open')
  })

  it('keeps the original line endings and counts changes', () => {
    expect(normalizeEdited('a\r\nb', 'a\r\nb\r\nc')).toBe('a\r\nb\r\nc')
    expect(normalizeEdited('a\nb', 'a\r\nc')).toBe('a\nc')
    expect(changedLines('a\nb\nc', 'a\nx\nc\nd')).toBe(2)
  })
})

describe('profile export', () => {
  it('reads the filename and keeps it inside the folder', () => {
    expect(dispositionFilename('attachment; filename="aria.craftbot"')).toBe('aria.craftbot')
    expect(dispositionFilename('attachment; filename="../../evil.craftbot"')).toBe('_.._evil.craftbot')
    expect(dispositionFilename(null)).toBe('agent-profile.craftbot')
  })

  it('writes into a folder or to the given file', () => {
    expect(resolveExportPath('/tmp/out', 'a.craftbot', true)).toBe(join('/tmp/out', 'a.craftbot'))
    expect(resolveExportPath('/tmp/new/', 'a.craftbot', false)).toBe(join('/tmp/new/', 'a.craftbot'))
    expect(resolveExportPath('/tmp/mine.craftbot', 'a.craftbot', false)).toBe('/tmp/mine.craftbot')
    expect(resolveExportPath('  ', 'a.craftbot', false)).toBe('a.craftbot')
  })

  it('strips quotes from dragged paths', () => {
    expect(cleanPath('"C:\\a b\\x.craftbot"')).toBe('C:\\a b\\x.craftbot')
    expect(cleanPath("  '/tmp/x'  ")).toBe('/tmp/x')
    expect(cleanPath('plain')).toBe('plain')
  })
})

describe('form helpers', () => {
  const options = [
    { value: 'anthropic', label: 'Anthropic', detail: 'key saved' },
    { value: 'openai', label: 'OpenAI' },
    { value: 'remote', label: 'Ollama', detail: 'local' },
  ]

  it('filters options on every word', () => {
    expect(filterOptions(options, '').length).toBe(3)
    expect(filterOptions(options, 'oll').map(o => o.value)).toEqual(['remote'])
    expect(filterOptions(options, 'key ANTH').map(o => o.value)).toEqual(['anthropic'])
    expect(filterOptions(options, 'zzz')).toEqual([])
  })

  it('keeps the selected lines in the window', () => {
    expect(scrollTop(0, 2, 3, 5, 20)).toBe(0)
    expect(scrollTop(0, 7, 8, 5, 20)).toBe(3)
    expect(scrollTop(10, 4, 6, 5, 20)).toBe(4)
    expect(scrollTop(18, 19, 20, 5, 20)).toBe(15)
  })

  it('sizes the label column', () => {
    expect(labelWidth(80, ['Name', 'Language'])).toBe(10)
    expect(labelWidth(80, ['A rather long label here'])).toBe(22)
    expect(labelWidth(40, ['A rather long label here'])).toBe(14)
  })

  const rows: FormRow[] = [
    { kind: 'heading', text: 'H' },
    { kind: 'toggle', id: 'a', label: 'A', value: true, onChange: () => {} },
    { kind: 'note', text: 'n' },
    { kind: 'action', id: 'b', label: 'B', onRun: () => {} },
    { kind: 'info', label: 'I', value: 'v' },
    { kind: 'text', id: 'c', label: 'C', value: '', onSubmit: () => {} },
  ]

  it('resolves the cursor by id, else the nearest selectable row', () => {
    expect(resolveCursor(rows, 'b', 0)).toBe(3)
    expect(resolveCursor(rows, null, 0)).toBe(1)
    expect(resolveCursor(rows, 'gone', 4)).toBe(5)
    expect(resolveCursor([{ kind: 'note', text: 'x' }], null, 0)).toBe(-1)
  })

  it('steps over rows that cannot be selected', () => {
    expect(stepCursor(rows, 1, 1)).toBe(3)
    expect(stepCursor(rows, 3, 1)).toBe(5)
    expect(stepCursor(rows, 5, 1)).toBe(5)
    expect(stepCursor(rows, 5, -10)).toBe(1)
  })
})
