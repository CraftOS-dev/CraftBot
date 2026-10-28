/**
 * Shared pieces of the connection tabs (MCP, Skills, Integrations,
 * Credentials, Agent Apps): key registration, footer hints, an inline notice
 * line, reply listeners, a small form engine and a pager for long text.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Box, Text, useApp } from 'ink'
import type { Key } from 'ink'
import { onInboundMessage } from '../../../../browser/frontend/src/store/socket/socketMiddleware'
import { useScreen } from '../context'
import { useTab, type TabKeyHandler } from './tabContext'
import { TextField, fieldKey } from '../../ui/TextField'
import * as TB from '../../input/TextBuffer'
import { glyphs, ink, spinnerFrames } from '../../theme/theme'
import { padEnd, truncate, width as cells, wrapLines } from '../../text/width'
import { useTicker } from '../../ui/useTicker'

/**
 * Register the tab's key handler once. The settings screen hands tabs a new
 * `setHandler` on every render, so registering on each change would loop;
 * the latest handler and setter are read through refs instead.
 */
export function useConnectKeys(handler: TabKeyHandler): void {
  const { setHandler } = useTab()
  const handlerRef = useRef(handler)
  handlerRef.current = handler
  const setRef = useRef(setHandler)
  setRef.current = setHandler
  useEffect(() => {
    setRef.current((input, key) => handlerRef.current(input, key))
    return () => setRef.current(null)
  }, [])
}

export interface Hint {
  keys: string
  label: string
}

/** Publish the footer hints (only when they change). */
export function useHints(hints: Hint[]): void {
  const { setHints } = useTab()
  const key = JSON.stringify(hints)
  const setRef = useRef(setHints)
  setRef.current = setHints
  useEffect(() => {
    setRef.current(JSON.parse(key) as Hint[])
  }, [key])
  useEffect(() => () => setRef.current([]), [])
}

/** Single letters go to a focused text field, not to the screen's shortcuts. */
export function useTextFocus(focused: boolean): void {
  const { setTextFocus } = useScreen()
  useEffect(() => {
    setTextFocus(focused)
  }, [focused, setTextFocus])
  useEffect(() => () => setTextFocus(false), [setTextFocus])
}

export type Tone = 'info' | 'success' | 'error' | 'warn'

export interface Notice {
  text: string
  tone: Tone
}

/** A one-line status message under the tab that clears itself. */
export function useNotice(): [Notice | null, (text: string, tone?: Tone, ttlMs?: number | null) => void, () => void] {
  const [notice, setNotice] = useState<Notice | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const clear = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    setNotice(null)
  }, [])
  const show = useCallback((text: string, tone: Tone = 'info', ttlMs: number | null = 6000) => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = ttlMs === null ? null : setTimeout(() => setNotice(null), ttlMs)
    setNotice({ text, tone })
  }, [])
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])
  return [notice, show, clear]
}

export function toneColor(tone: Tone): string | undefined {
  return tone === 'error' ? ink.error : tone === 'success' ? ink.success : tone === 'warn' ? ink.warn : ink.info
}

/** A pending confirmation, wrapped to the width, with the y / cancel hint at its end. */
export function ConfirmBlock({ pending, width, hint }: { pending: { message: string }; width: number; hint: string }) {
  const lines = wrapLines([`${pending.message}  ${hint}`], width - 1)
  return (
    <Box flexDirection="column">
      {lines.map((line, i) => (
        <Text key={i} color={ink.warn} bold>{line}</Text>
      ))}
    </Box>
  )
}

export function NoticeLine({ notice, width }: { notice: Notice | null; width: number }) {
  if (!notice) return null
  const g = glyphs()
  const mark = notice.tone === 'error' ? g.failed : notice.tone === 'success' ? g.done : g.bullet
  return <Text color={toneColor(notice.tone)}>{truncate(`${mark} ${notice.text}`, width - 1)}</Text>
}

/** Listen to one or more inbound message types (after the store applied them). */
export function useInbound(types: string | string[], handler: (type: string, data: Record<string, unknown>) => void): void {
  const ref = useRef(handler)
  ref.current = handler
  const key = Array.isArray(types) ? types.join(',') : types
  useEffect(() => {
    const wanted = new Set(key.split(','))
    return onInboundMessage(msg => {
      if (!wanted.has(msg.type)) return
      const data = (msg.data && typeof msg.data === 'object' ? msg.data : {}) as Record<string, unknown>
      ref.current(msg.type, data)
    })
  }, [key])
}

/** Ink's terminal hand-over for $EDITOR. */
export function useSuspend(): (callback: () => Promise<void>) => Promise<void> {
  const { suspendTerminal } = useApp()
  return useCallback((callback: () => Promise<void>) => suspendTerminal(callback), [suspendTerminal])
}

/** A braille spinner frame while `active`. */
export function useSpinner(active: boolean): string {
  const tick = useTicker(100, active)
  const frames = spinnerFrames()
  return active ? frames[tick % frames.length] : ''
}

export function newRequestId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

export function str(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/** "3.1 MB" style sizes. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// ── One list row ─────────────────────────────────────────────────────────

export interface RowProps {
  selected: boolean
  /** Status glyph (one cell). */
  mark: string
  markColor?: string
  label: string
  /** Right-aligned detail. */
  aside?: string
  width: number
  dim?: boolean
  labelColor?: string
  asideColor?: string
}

export function Row({ selected, mark, markColor, label, aside, width, dim, labelColor, asideColor }: RowProps) {
  const g = glyphs()
  const asideText = aside ? truncate(aside, Math.max(8, Math.floor(width * 0.4))) : ''
  const labelWidth = Math.max(4, width - 4 - (asideText ? cells(asideText) + 1 : 0) - 1)
  return (
    <Box>
      <Text color={selected ? ink.focus : undefined}>{selected ? `${g.pointer} ` : '  '}</Text>
      <Text color={markColor}>{`${mark} `}</Text>
      <Text bold={selected} color={labelColor ?? (dim ? ink.muted : undefined)}>{padEnd(label, labelWidth)}</Text>
      {asideText ? <Text color={asideColor ?? ink.muted}>{` ${asideText}`}</Text> : null}
    </Box>
  )
}

/** A filter line: the field while typing, the query while one is set, else `idle`. */
export function FilterLine({ buffer, typing, width, placeholder, idle }: { buffer: TB.Buffer; typing: boolean; width: number; placeholder: string; idle: string }) {
  if (typing || buffer.text) return <TextField label="/" buffer={buffer} focused={typing} width={width - 1} placeholder={placeholder} />
  return <Text color={ink.muted}>{truncate(idle, width - 1)}</Text>
}

/** Keys for a list filter field. Returns the new state, or null when not filtering. */
export function filterKey(
  filtering: boolean,
  buffer: TB.Buffer,
  input: string,
  key: Key,
): { filtering: boolean; buffer: TB.Buffer; changed: boolean } | null {
  if (!filtering) return null
  if (key.escape) return { filtering: false, buffer: TB.EMPTY, changed: true }
  if (key.return) return { filtering: false, buffer, changed: false }
  const next = fieldKey(buffer, input, key)
  return next ? { filtering: true, buffer: next, changed: true } : { filtering: true, buffer, changed: false }
}

// ── Forms ────────────────────────────────────────────────────────────────

export type FormField =
  | { kind: 'text'; key: string; label: string; placeholder?: string; masked?: boolean; hint?: string }
  | { kind: 'toggle'; key: string; label: string; hint?: string }
  | { kind: 'select'; key: string; label: string; options: { value: string; label: string }[]; locked?: boolean; hint?: string }
  /** Multi-line text: Enter opens it in $EDITOR. */
  | { kind: 'editor'; key: string; label: string; hint?: string }

export type FormRaw = Record<string, string | boolean>

export interface FormState {
  index: number
  text: Record<string, TB.Buffer>
  other: Record<string, string | boolean>
}

export function formInit(fields: FormField[], initial: FormRaw = {}): FormState {
  const text: Record<string, TB.Buffer> = {}
  const other: Record<string, string | boolean> = {}
  for (const field of fields) {
    const value = initial[field.key]
    if (field.kind === 'text') text[field.key] = TB.fromText(typeof value === 'string' ? value : '')
    else if (field.kind === 'toggle') other[field.key] = value === true
    else if (field.kind === 'select') other[field.key] = typeof value === 'string' ? value : field.options[0]?.value ?? ''
    else other[field.key] = typeof value === 'string' ? value : ''
  }
  return { index: 0, text, other }
}

export function formValues(state: FormState): FormRaw {
  const out: FormRaw = { ...state.other }
  for (const [key, buf] of Object.entries(state.text)) out[key] = buf.text
  return out
}

export function formSet(state: FormState, key: string, value: string | boolean): FormState {
  if (key in state.text) return { ...state, text: { ...state.text, [key]: TB.fromText(String(value)) } }
  return { ...state, other: { ...state.other, [key]: value } }
}

export interface FormOutcome {
  state: FormState
  submit?: boolean
  /** The user asked to edit this 'editor' field in $EDITOR. */
  edit?: string
}

/** Route a key to a form. Esc is the caller's (cancel). */
export function formKey(state: FormState, fields: FormField[], input: string, key: Key): FormOutcome | null {
  if (fields.length === 0) return key.return ? { state, submit: true } : null
  const index = Math.min(state.index, fields.length - 1)
  const field = fields[index]
  const move = (delta: number): FormOutcome => ({ state: { ...state, index: (index + delta + fields.length) % fields.length } })
  if (key.ctrl && input === 's') return { state, submit: true }
  if (key.tab) return move(key.shift ? -1 : 1)
  if (key.downArrow) return move(1)
  if (key.upArrow) return move(-1)
  if (key.return) {
    if (field.kind === 'editor') return { state, edit: field.key }
    if (field.kind === 'toggle' && fields.length === 1) return { state, submit: true }
    if (index === fields.length - 1) return { state, submit: true }
    return move(1)
  }
  if (field.kind === 'toggle') {
    if (input === ' ' || key.leftArrow || key.rightArrow) {
      return { state: { ...state, other: { ...state.other, [field.key]: !state.other[field.key] } } }
    }
    return { state }
  }
  if (field.kind === 'select') {
    if (field.locked) return { state }
    if (input === ' ' || key.leftArrow || key.rightArrow) {
      const opts = field.options
      const current = Math.max(0, opts.findIndex(o => o.value === state.other[field.key]))
      const next = opts[(current + (key.leftArrow ? -1 : 1) + opts.length) % opts.length]
      return { state: { ...state, other: { ...state.other, [field.key]: next?.value ?? '' } } }
    }
    return { state }
  }
  if (field.kind === 'editor') return { state }
  const next = fieldKey(state.text[field.key] ?? TB.EMPTY, input, key)
  if (next) return { state: { ...state, text: { ...state.text, [field.key]: next } } }
  return { state }
}

/** Whether the focused field takes typed letters. */
export function formTyping(state: FormState, fields: FormField[]): boolean {
  return fields[Math.min(state.index, fields.length - 1)]?.kind === 'text'
}

export function FormView({ fields, state, width, focused }: { fields: FormField[]; state: FormState; width: number; focused: boolean }) {
  const g = glyphs()
  const labelWidth = Math.min(Math.max(...fields.map(f => cells(f.label)), 4) + 1, Math.floor(width / 3))
  const current = fields[Math.min(state.index, fields.length - 1)]
  return (
    <Box flexDirection="column">
      {fields.map((field, i) => {
        const on = focused && i === state.index
        const pointer = <Text color={on ? ink.focus : undefined}>{on ? `${g.pointer} ` : '  '}</Text>
        const label = <Text color={on ? ink.focus : ink.muted}>{padEnd(field.label, labelWidth)} </Text>
        const room = Math.max(6, width - labelWidth - 4)
        let control
        if (field.kind === 'text') {
          control = (
            <TextField
              buffer={state.text[field.key] ?? TB.EMPTY}
              focused={on}
              width={room}
              masked={field.masked}
              placeholder={field.placeholder}
            />
          )
        } else if (field.kind === 'toggle') {
          control = <Text>{state.other[field.key] ? g.checked : g.unchecked}</Text>
        } else if (field.kind === 'select') {
          const option = field.options.find(o => o.value === state.other[field.key])
          const text = option?.label ?? String(state.other[field.key] ?? '')
          control = <Text color={field.locked ? ink.muted : undefined}>{truncate(on && !field.locked ? `< ${text} >` : text, room)}</Text>
        } else {
          const value = String(state.other[field.key] ?? '')
          const lines = value ? value.split('\n').length : 0
          control = <Text color={ink.muted}>{truncate(value ? oneLinePreview(value, lines) : '', room)}</Text>
        }
        return (
          <Box key={field.key}>
            {pointer}
            {label}
            {control}
          </Box>
        )
      })}
      {focused && current?.hint ? <Text color={ink.muted}>{truncate(`  ${current.hint}`, width - 1)}</Text> : null}
    </Box>
  )
}

function oneLinePreview(value: string, lines: number): string {
  const first = value.split('\n')[0]
  return lines > 1 ? `${first} (+${lines - 1})` : first
}

// ── Long text ────────────────────────────────────────────────────────────

/** Scroll position for a pager; null when the key is not a scroll key. */
export function pagerKey(top: number, input: string, key: Key, total: number, height: number): number | null {
  const max = Math.max(0, total - height)
  let next = top
  if (key.upArrow || input === 'k') next -= 1
  else if (key.downArrow || input === 'j') next += 1
  else if (key.pageUp) next -= height
  else if (key.pageDown || input === ' ') next += height
  else if (key.home || input === 'g') next = 0
  else if (key.end || input === 'G') next = max
  else return null
  return Math.max(0, Math.min(max, next))
}

export interface PagerLine {
  text: string
  color?: string
  bold?: boolean
}

/** Wrap a block of styled lines to `width`. */
export function wrapStyled(lines: PagerLine[], width: number): PagerLine[] {
  return lines.flatMap(line => wrapLines([line.text], width).map(text => ({ ...line, text })))
}

export function Pager({ lines, top, height, width }: { lines: PagerLine[]; top: number; height: number; width: number }) {
  const shown = lines.slice(top, top + height)
  return (
    <Box flexDirection="column">
      {shown.map((line, i) => (
        <Text key={top + i} color={line.color} bold={line.bold}>{truncate(line.text, width - 1) || ' '}</Text>
      ))}
    </Box>
  )
}
