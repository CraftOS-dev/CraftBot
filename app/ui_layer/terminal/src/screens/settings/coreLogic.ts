/**
 * Pure helpers shared by the settings tabs and the effort picker: meters,
 * clock and cron text, the external editor's command line, where an export
 * lands, and option filtering. No React, no I/O, so all of it is unit-tested
 * (test/unit/settingsCore.test.ts).
 */
import { join } from 'node:path'
import { width } from '../../text/width'

// ── Meters ───────────────────────────────────────────────────────────────

export interface MeterGlyphs {
  full: string
  empty: string
  marker: string
}

export const UNICODE_METER: MeterGlyphs = { full: '█', empty: '░', marker: '│' }
export const ASCII_METER: MeterGlyphs = { full: '#', empty: '.', marker: '|' }

/**
 * A one-line bar `size` cells wide, filled to `fill` (0..1, clamped), with an
 * optional marker cell at `marker` (0..1), e.g. a threshold.
 */
export function meter(fill: number, size: number, marker: number | null = null, glyphs: MeterGlyphs = UNICODE_METER): string {
  if (size <= 0) return ''
  const ratio = Number.isFinite(fill) ? Math.min(1, Math.max(0, fill)) : 0
  const filled = Math.round(ratio * size)
  const cells = Array.from({ length: size }, (_, i) => (i < filled ? glyphs.full : glyphs.empty))
  if (marker !== null && Number.isFinite(marker)) {
    const at = Math.min(size - 1, Math.max(0, Math.round(Math.min(1, Math.max(0, marker)) * (size - 1))))
    cells[at] = glyphs.marker
  }
  return cells.join('')
}

/** Context fill where the bar turns amber, then red (the browser's ReasoningPicker). */
export const CONTEXT_WARN = 0.7
export const CONTEXT_HIGH = 0.9

export function contextLevel(fill: number): 'normal' | 'warn' | 'high' {
  if (fill >= CONTEXT_HIGH) return 'high'
  if (fill >= CONTEXT_WARN) return 'warn'
  return 'normal'
}

/** Remaining time as m:ss, or h:mm:ss from an hour up. */
export function formatRemaining(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = String(total % 60).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

export function formatBytes(n: number): string {
  if (n >= 1_073_741_824) return `${(n / 1_073_741_824).toFixed(1)} GB`
  if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(0)} MB`
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${n} B`
}

// ── Clock and cron ──────────────────────────────────────────────────────

/** Normalize a typed time ("7:5", "07:05", "0705") to "HH:MM"; null when invalid. */
export function parseClock(input: string): string | null {
  const text = input.trim()
  const match = /^(\d{1,2})(?::?(\d{2}))?$/.exec(text) ?? /^(\d{1,2}):(\d{1,2})$/.exec(text)
  if (!match) return null
  const h = Number(match[1])
  const m = Number(match[2] ?? 0)
  if (!Number.isInteger(h) || !Number.isInteger(m) || h > 23 || m > 59) return null
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

/** "HH:MM" as a clock in the user's locale. */
export function localClock(hhmm: string, locale: string): string {
  const [h, m] = hhmm.split(':').map(n => parseInt(n, 10) || 0)
  const d = new Date()
  d.setHours(h, m, 0, 0)
  try {
    return new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(d)
  } catch {
    return hhmm
  }
}

/** Whether the next daily run at "HH:MM" is still today (else tomorrow). */
export function runsToday(hhmm: string, now: Date): boolean {
  const [h, m] = hhmm.split(':').map(n => parseInt(n, 10) || 0)
  return now.getHours() < h || (now.getHours() === h && now.getMinutes() < m)
}

type Translate = (key: string, options?: Record<string, unknown>) => string

const CRON_DAYS: Record<string, string> = {
  '0': 'sun', '7': 'sun', '1': 'mon', '2': 'tue', '3': 'wed', '4': 'thu', '5': 'fri', '6': 'sat',
}

/**
 * A five-field cron expression in words, with the same cases as the
 * browser's Proactive tab. `t` resolves `cron.*` keys of settingsCore.
 */
export function describeCron(cron: string, t: Translate, locale: string): string {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return cron
  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts
  const clock = () => localClock(`${parseInt(hour, 10) || 0}:${String(parseInt(minute, 10) || 0).padStart(2, '0')}`, locale)
  const everyDay = dayOfMonth === '*' && month === '*' && dayOfWeek === '*'
  if (hour === '*' && everyDay) {
    if (minute.startsWith('*/')) return t('cron.everyMinutes', { count: Number(minute.slice(2)) || 1 })
    if (minute.includes(',')) return t('cron.timesHourly', { count: minute.split(',').length })
    return t('cron.hourly', { minute: minute.padStart(2, '0') })
  }
  if (hour.startsWith('*/') && everyDay) return t('cron.everyHours', { count: Number(hour.slice(2)) || 1 })
  if (!/^\d+$/.test(hour) || !/^\d+$/.test(minute)) return t('cron.raw', { cron })
  if (everyDay) return t('cron.daily', { time: clock() })
  if (dayOfMonth === '*' && month === '*') {
    const day = CRON_DAYS[dayOfWeek]
    return t('cron.weekly', { day: day ? t(`cron.days.${day}`) : dayOfWeek, time: clock() })
  }
  if (month === '*' && dayOfWeek === '*') return t('cron.monthly', { day: dayOfMonth, time: clock() })
  return t('cron.raw', { cron })
}

// ── Proactive tasks ─────────────────────────────────────────────────────

export type PriorityLevel = 'high' | 'medium' | 'low'

export const PRIORITY_VALUES: Record<PriorityLevel, number> = { high: 30, medium: 50, low: 70 }

export function priorityLevel(value: number): PriorityLevel {
  if (value <= 35) return 'high'
  if (value <= 55) return 'medium'
  return 'low'
}

export const FREQUENCIES = ['hourly', 'daily', 'weekly', 'monthly'] as const
export const WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'] as const

// ── External programs ───────────────────────────────────────────────────

/** Quote one argument for a Windows shell command line when it needs it. */
export function quoteWindowsArg(arg: string): string {
  if (arg && !/[\s"&|<>^()]/.test(arg)) return arg
  return `"${arg.replace(/"/g, '""')}"`
}

/** Open a URL with the system's default handler: the command and its arguments. */
export function openUrlCommand(url: string, platform: string): { command: string; args: string[]; shell: boolean } {
  if (platform === 'win32') return { command: 'cmd', args: ['/c', 'start', '""', quoteWindowsArg(url)], shell: false }
  if (platform === 'darwin') return { command: 'open', args: [url], shell: false }
  return { command: 'xdg-open', args: [url], shell: false }
}

// ── Profile export ──────────────────────────────────────────────────────

/** The filename in a Content-Disposition header, or a default. */
export function dispositionFilename(header: string | null, fallback = 'agent-profile.craftbot'): string {
  const match = /filename="([^"]+)"/.exec(header ?? '') ?? /filename=([^;]+)/.exec(header ?? '')
  const name = match ? match[1].trim() : ''
  // Never let a server-supplied name walk out of the chosen folder.
  const safe = name.replace(/[\\/]/g, '_').replace(/^\.+/, '')
  return safe || fallback
}

/**
 * Where an export is written: inside `input` when it names a folder (or ends
 * with a separator), else `input` itself as the file.
 */
export function resolveExportPath(input: string, filename: string, isDirectory: boolean): string {
  const text = input.trim()
  if (!text) return filename
  if (isDirectory || /[\\/]$/.test(text)) return join(text, filename)
  return text
}

/** Strip the quotes a terminal adds when a path is dragged in or pasted. */
export function cleanPath(input: string): string {
  const text = input.trim()
  if (text.length >= 2 && ((text.startsWith('"') && text.endsWith('"')) || (text.startsWith("'") && text.endsWith("'")))) {
    return text.slice(1, -1)
  }
  return text
}

// ── Options and lists ───────────────────────────────────────────────────

export interface ChoiceOption {
  value: string
  label: string
  detail?: string
}

/** Options whose label, value or detail contains every word of `query`. */
export function filterOptions<T extends ChoiceOption>(options: T[], query: string): T[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return options
  return options.filter(o => {
    const hay = `${o.label} ${o.value} ${o.detail ?? ''}`.toLowerCase()
    return words.every(w => hay.includes(w))
  })
}

/** Keep a selected block of lines [start, end) inside a window of `height` lines. */
export function scrollTop(prevTop: number, start: number, end: number, height: number, total: number): number {
  if (height <= 0) return 0
  let top = Math.min(prevTop, start)
  if (end > top + height) top = Math.min(start, end - height)
  return Math.max(0, Math.min(top, Math.max(0, total - height)))
}

/** The label column width for a form `columns` cells wide. */
export function labelWidth(columns: number, labels: string[]): number {
  const longest = labels.reduce((max, l) => Math.max(max, width(l)), 0)
  return Math.max(10, Math.min(longest + 2, Math.floor(columns * 0.36), 22))
}

/** Count of non-empty lines changed between two texts (for "N lines changed"). */
export function changedLines(before: string, after: string): number {
  const a = before.split(/\r?\n/)
  const b = after.split(/\r?\n/)
  let changed = 0
  for (let i = 0; i < Math.max(a.length, b.length); i++) if (a[i] !== b[i]) changed++
  return changed
}

/** Normalize line endings an editor may have introduced (Windows notepad writes CRLF). */
export function normalizeEdited(original: string, edited: string): string {
  const usesCrlf = /\r\n/.test(original)
  const unix = edited.replace(/\r\n/g, '\n')
  return usesCrlf ? unix.replace(/\n/g, '\r\n') : unix
}
