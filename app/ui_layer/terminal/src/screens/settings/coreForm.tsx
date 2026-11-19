/**
 * The settings tabs' form: a vertical list of rows (text fields, choices,
 * toggles, actions, table rows, headings and notes) with one cursor, a
 * scrollbar when it does not fit, an option picker with a filter, an inline
 * confirmation (or a typed one for the destructive steps) and a status line.
 *
 * A tab builds its rows on every render and routes its keys through
 * `form.handleKey(rows, input, key)`; the form owns selection, editing and
 * scrolling, and publishes the footer hints for what is selected.
 *
 * Text rows edit in place: Enter starts, Enter saves, Esc cancels. If the
 * value changes elsewhere while it is being edited, the row says so and
 * Ctrl+L loads the latest value into the field.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Box, Text, type Key } from 'ink'
import { useTranslation } from 'react-i18next'
import * as TB from '../../input/TextBuffer'
import { TextField, fieldKey } from '../../ui/TextField'
import { ConfirmLine, type PendingConfirm } from '../../ui/Confirm'
import { clampList, listKey, LIST_START, type ListState } from '../../ui/list'
import { glyphs, ink } from '../../theme/theme'
import { padEnd, truncate, width as cells, wrap } from '../../text/width'
import { useScreen } from '../context'
import { useTab } from './tabContext'
import { filterOptions, labelWidth, scrollTop, type ChoiceOption } from './coreLogic'
import type { Flash } from './coreHooks'

export type Tone = 'normal' | 'muted' | 'warn' | 'error' | 'success' | 'info' | 'brand'

export function toneColor(tone: Tone | undefined): string | undefined {
  switch (tone) {
    case 'muted':
      return ink.muted
    case 'warn':
      return ink.warn
    case 'error':
      return ink.error
    case 'success':
      return ink.success
    case 'info':
      return ink.info
    case 'brand':
      return ink.brand
    default:
      return undefined
  }
}

export interface KeyHint {
  keys: string
  label: string
}

interface Selectable {
  id: string
  /** Shown muted; activation does nothing. */
  disabled?: boolean
  /** Extra keys while this row is selected; return true when used. */
  onKey?: (input: string, key: Key) => boolean
  /** Footer hints for those extra keys. */
  hints?: KeyHint[]
}

export interface Cell {
  text: string
  /** Fixed width in cells; the last cell without one takes the rest. */
  width?: number
  tone?: Tone
  bold?: boolean
}

export type FormRow =
  | { kind: 'heading'; id?: string; text: string; aside?: string }
  | { kind: 'note'; id?: string; text: string; tone?: Tone; indent?: number; maxLines?: number }
  | { kind: 'blank'; id?: string }
  /** A read-only label and value, aligned with the fields. */
  | { kind: 'info'; id?: string; label: string; value: string; tone?: Tone; detail?: string }
  | (Selectable & {
      kind: 'text'
      label: string
      value: string
      /** Shown instead of `value` when not editing (e.g. a masked key). */
      display?: string
      placeholder?: string
      masked?: boolean
      /** Editing starts from an empty field (secrets, replacements). */
      startEmpty?: boolean
      detail?: string
      detailTone?: Tone
      onSubmit: (value: string) => void
      /** Esc while editing. */
      onCancel?: () => void
    })
  | (Selectable & {
      kind: 'choice'
      label: string
      value: string
      options: ChoiceOption[]
      onChange: (value: string) => void
      /** Enter opens a filtered picker (default for more than five options). */
      picker?: boolean
      pickerTitle?: string
      /** Shown when `value` is not among the options. */
      display?: string
      detail?: string
      detailTone?: Tone
    })
  | (Selectable & { kind: 'toggle'; label: string; value: boolean; onChange: (value: boolean) => void; detail?: string; detailTone?: Tone })
  | (Selectable & { kind: 'action'; label: string; onRun: () => void; tone?: Tone; detail?: string; detailTone?: Tone })
  | (Selectable & { kind: 'item'; cells: Cell[]; onRun?: () => void; dim?: boolean })

type SelectableRow = Extract<FormRow, { kind: 'text' | 'choice' | 'toggle' | 'action' | 'item' }>

export function isSelectable(row: FormRow): row is SelectableRow {
  return row.kind === 'text' || row.kind === 'choice' || row.kind === 'toggle' || row.kind === 'action' || row.kind === 'item'
}

const usesPicker = (row: Extract<FormRow, { kind: 'choice' }>) => row.picker ?? row.options.length > 5

// ── State ────────────────────────────────────────────────────────────────

interface Editing {
  id: string
  buf: TB.Buffer
  /** The row's value when editing started (to notice changes elsewhere). */
  base: string
}

interface Picker {
  id: string
  filter: TB.Buffer
  list: ListState
}

interface Typed {
  message: string
  word: string
  buf: TB.Buffer
  onConfirm: () => void
}

interface FormState {
  selId: string | null
  selIndex: number
  editing: Editing | null
  picker: Picker | null
  confirm: PendingConfirm | null
  typed: Typed | null
}

const START: FormState = { selId: null, selIndex: 0, editing: null, picker: null, confirm: null, typed: null }

/** Index of the selected row: the remembered id, else the nearest selectable row. */
export function resolveCursor(rows: FormRow[], selId: string | null, selIndex: number): number {
  if (selId) {
    const at = rows.findIndex(r => isSelectable(r) && r.id === selId)
    if (at >= 0) return at
  }
  for (let i = Math.max(0, selIndex); i < rows.length; i++) if (isSelectable(rows[i])) return i
  for (let i = Math.min(rows.length - 1, selIndex); i >= 0; i--) if (isSelectable(rows[i])) return i
  return -1
}

/** The selectable row `steps` away from `from` (clamped at the ends). */
export function stepCursor(rows: FormRow[], from: number, steps: number): number {
  const selectable = rows.map((r, i) => (isSelectable(r) ? i : -1)).filter(i => i >= 0)
  if (!selectable.length) return -1
  let at = selectable.indexOf(from)
  if (at < 0) at = 0
  return selectable[Math.max(0, Math.min(selectable.length - 1, at + steps))]
}

export interface FormController {
  state: FormState
  /** Lines of the body the form last had for its list (page moves). */
  pageRef: { current: number }
  topRef: { current: number }
  handleKey: (rows: FormRow[], input: string, key: Key) => boolean
  confirm: (message: string, onConfirm: () => void) => void
  confirmTyped: (message: string, word: string, onConfirm: () => void) => void
  select: (id: string) => void
  /** Open a text row for editing with `text` in the field. */
  startEdit: (id: string, text: string) => void
  closeAll: () => void
  /** Something modal is open (an edit, the picker, a confirmation). */
  modal: boolean
}

export function useForm(): FormController {
  const [state, setState] = useState<FormState>(START)
  const stateRef = useRef(state)
  stateRef.current = state
  const pageRef = useRef(10)
  const topRef = useRef(0)
  const { setTextFocus } = useScreen()

  const textMode = !!(state.editing || state.picker || state.typed)
  useEffect(() => {
    setTextFocus(textMode)
  }, [textMode, setTextFocus])
  useEffect(() => () => setTextFocus(false), [setTextFocus])

  // One writer: the ref is current at once, so keys that arrive before the
  // next render see the latest state.
  const patch = useCallback((next: Partial<FormState>) => {
    stateRef.current = { ...stateRef.current, ...next }
    setState(stateRef.current)
  }, [])

  const confirm = useCallback((message: string, onConfirm: () => void) => patch({ confirm: { message, onConfirm } }), [patch])
  const confirmTyped = useCallback(
    (message: string, word: string, onConfirm: () => void) => patch({ typed: { message, word, buf: TB.EMPTY, onConfirm } }),
    [patch],
  )
  const select = useCallback((id: string) => patch({ selId: id }), [patch])
  const startEdit = useCallback((id: string, text: string) => patch({ selId: id, editing: { id, buf: TB.fromText(text), base: text } }), [patch])
  const closeAll = useCallback(() => patch({ editing: null, picker: null, confirm: null, typed: null }), [patch])

  const handleKey = useCallback(
    (rows: FormRow[], input: string, key: Key): boolean => {
      const s = stateRef.current
      const set = patch

      if (s.typed) {
        if (key.escape) set({ typed: null })
        else if (key.return) {
          if (s.typed.buf.text.trim().toLowerCase() === s.typed.word.toLowerCase()) {
            const run = s.typed.onConfirm
            set({ typed: null })
            run()
          }
        } else {
          const next = fieldKey(s.typed.buf, input, key)
          if (next) set({ typed: { ...s.typed, buf: next } })
        }
        return true
      }

      if (s.confirm) {
        // y confirms; any other key cancels. Closed before running, so the
        // confirmed step may open the next one.
        const run = s.confirm.onConfirm
        set({ confirm: null })
        if (input === 'y' || input === 'Y') run()
        return true
      }

      if (s.picker) {
        const row = rows.find(r => r.kind === 'choice' && r.id === s.picker?.id) as Extract<FormRow, { kind: 'choice' }> | undefined
        if (!row || key.escape) {
          set({ picker: null })
          return true
        }
        const options = filterOptions(row.options, s.picker.filter.text)
        const height = Math.max(1, pageRef.current - 2)
        if (key.return) {
          const choice = options[clampList(s.picker.list, options.length, height).index]
          set({ picker: null })
          if (choice && choice.value !== row.value) row.onChange(choice.value)
          return true
        }
        if (key.upArrow || key.downArrow || key.pageUp || key.pageDown) {
          const moved = listKey(s.picker.list, '', key, options.length, height)
          if (moved) set({ picker: { ...s.picker, list: moved } })
          return true
        }
        const next = fieldKey(s.picker.filter, input, key)
        if (next) set({ picker: { ...s.picker, filter: next, list: LIST_START } })
        return true
      }

      if (s.editing) {
        const row = rows.find(r => r.kind === 'text' && r.id === s.editing?.id) as Extract<FormRow, { kind: 'text' }> | undefined
        if (!row || key.escape) {
          set({ editing: null })
          row?.onCancel?.()
          return true
        }
        if (key.return) {
          const value = s.editing.buf.text
          set({ editing: null })
          row.onSubmit(value)
          return true
        }
        if (key.ctrl && input === 'l') {
          set({ editing: { ...s.editing, buf: TB.fromText(row.value), base: row.value } })
          return true
        }
        const next = fieldKey(s.editing.buf, input, key)
        if (next) set({ editing: { ...s.editing, buf: next } })
        return true
      }

      const cursor = resolveCursor(rows, s.selId, s.selIndex)
      const row = cursor >= 0 ? (rows[cursor] as SelectableRow) : null

      if (row && !row.disabled && row.onKey?.(input, key)) return true

      let target = -2
      if (key.upArrow || input === 'k') target = stepCursor(rows, cursor, -1)
      else if (key.downArrow || input === 'j') target = stepCursor(rows, cursor, 1)
      else if (key.pageUp) target = stepCursor(rows, cursor, -Math.max(1, pageRef.current - 2))
      else if (key.pageDown) target = stepCursor(rows, cursor, Math.max(1, pageRef.current - 2))
      else if (key.home || input === 'g') target = stepCursor(rows, cursor, -rows.length)
      else if (key.end || input === 'G') target = stepCursor(rows, cursor, rows.length)
      if (target !== -2) {
        if (target >= 0) {
          const r = rows[target] as SelectableRow
          set({ selId: r.id, selIndex: target })
        }
        return true
      }
      if (!row) return false

      const activate = key.return || input === ' '
      switch (row.kind) {
        case 'text':
          if (key.return && !row.disabled) set({ editing: { id: row.id, buf: row.startEmpty ? TB.EMPTY : TB.fromText(row.value), base: row.value } })
          return key.return
        case 'choice': {
          if (row.disabled) return activate || key.leftArrow || key.rightArrow
          const at = Math.max(0, row.options.findIndex(o => o.value === row.value))
          if (key.leftArrow || key.rightArrow) {
            if (!row.options.length) return true
            const next = row.options[(at + (key.leftArrow ? -1 : 1) + row.options.length) % row.options.length]
            if (next.value !== row.value) row.onChange(next.value)
            return true
          }
          if (activate) {
            if (usesPicker(row)) {
              set({ picker: { id: row.id, filter: TB.EMPTY, list: { index: at, top: Math.max(0, at - 3) } } })
            } else if (row.options.length) {
              const next = row.options[(at + 1) % row.options.length]
              if (next.value !== row.value) row.onChange(next.value)
            }
            return true
          }
          return false
        }
        case 'toggle':
          if (activate && !row.disabled) row.onChange(!row.value)
          return activate
        case 'action':
          if (key.return && !row.disabled) row.onRun()
          return key.return
        case 'item':
          if (key.return && !row.disabled) row.onRun?.()
          return key.return
      }
      return false
    },
    [patch],
  )

  return {
    state,
    pageRef,
    topRef,
    handleKey,
    confirm,
    confirmTyped,
    select,
    startEdit,
    closeAll,
    modal: !!(state.editing || state.picker || state.confirm || state.typed),
  }
}

// ── View ─────────────────────────────────────────────────────────────────

export interface FormViewProps {
  form: FormController
  rows: FormRow[]
  width: number
  height: number
  active: boolean
  flash?: Flash | null
  /** Tab-wide hints, shown after the selected row's own. */
  hints?: KeyHint[]
}

interface Line {
  node: ReactNode
  row: number
}

export function FormView({ form, rows, width: total, height, active, flash, hints = [] }: FormViewProps) {
  const { t } = useTranslation('settingsCore')
  const { setHints } = useTab()
  const g = glyphs()
  const { state } = form
  const cursor = resolveCursor(rows, state.selId, state.selIndex)
  const selected = cursor >= 0 ? (rows[cursor] as SelectableRow) : null

  // Footer hints for what has the keys right now.
  const footer: KeyHint[] = useMemo(() => {
    if (state.typed) return [{ keys: 'Enter', label: t('hint.confirm') }, { keys: 'Esc', label: t('hint.cancel') }]
    if (state.confirm) return []
    if (state.picker) return [{ keys: '↑↓', label: t('hint.move') }, { keys: 'Enter', label: t('hint.choose') }, { keys: 'Esc', label: t('hint.cancel') }]
    if (state.editing) return [{ keys: 'Enter', label: t('hint.save') }, { keys: 'Esc', label: t('hint.cancel') }]
    const own: KeyHint[] = []
    if (selected && !selected.disabled) {
      if (selected.kind === 'text') own.push({ keys: 'Enter', label: t('hint.edit') })
      else if (selected.kind === 'choice') own.push({ keys: usesPicker(selected) ? 'Enter' : '←→', label: t('hint.change') })
      else if (selected.kind === 'toggle') own.push({ keys: 'Space', label: t('hint.toggle') })
      else if (selected.kind === 'action') own.push({ keys: 'Enter', label: t('hint.run') })
      else if (selected.kind === 'item' && selected.onRun) own.push({ keys: 'Enter', label: t('hint.open') })
      own.push(...(selected.hints ?? []))
    }
    return [...own, ...hints]
  }, [state.typed, state.confirm, state.picker, state.editing, selected, hints, t])
  const footerKey = JSON.stringify(footer)
  useEffect(() => {
    if (active) setHints(footer)
    // footer is captured through its serialized key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [footerKey, active, setHints])

  const bottom = (flash ? 1 : 0) + (state.typed ? 2 : state.confirm ? 1 : 0)
  const avail = Math.max(1, height - bottom)
  form.pageRef.current = avail

  let body: ReactNode
  if (state.picker) {
    const row = rows.find(r => r.kind === 'choice' && r.id === state.picker?.id) as Extract<FormRow, { kind: 'choice' }> | undefined
    body = row ? <PickerView row={row} picker={state.picker} width={total} height={avail} /> : null
  } else {
    const lines = layout(rows, cursor, active, state.editing, total, t)
    const scrolling = lines.length > avail
    const contentWidth = scrolling ? total - 1 : total
    const final = scrolling ? layout(rows, cursor, active, state.editing, contentWidth, t) : lines
    let start = cursor < 0 ? -1 : final.findIndex(l => l.row === cursor)
    let end = start
    while (start >= 0 && end < final.length && final[end].row === cursor) end++
    // Keep the heading above the selection in view, and the top at the first row.
    if (start > 0 && rows[cursor - 1]?.kind === 'heading') start = final.findIndex(l => l.row === cursor - 1)
    if (start >= 0 && cursor === rows.findIndex(isSelectable)) start = 0
    const top = start < 0 ? 0 : scrollTop(form.topRef.current, start, end, avail, final.length)
    form.topRef.current = top
    const visible = final.slice(top, top + avail)
    const thumbSize = scrolling ? Math.max(1, Math.round((avail * avail) / final.length)) : 0
    const thumbTop = scrolling ? Math.round((top / Math.max(1, final.length - avail)) * (avail - thumbSize)) : 0
    body = (
      <Box flexDirection="row">
        <Box flexDirection="column" width={contentWidth}>
          {visible.map((line, i) => (
            <Box key={`${top + i}`} height={1}>
              {line.node}
            </Box>
          ))}
        </Box>
        {scrolling ? (
          <Box flexDirection="column" width={1}>
            {Array.from({ length: Math.min(avail, visible.length) }, (_, i) => (
              <Text key={i} color={ink.muted}>{i >= thumbTop && i < thumbTop + thumbSize ? '█' : g.vbar}</Text>
            ))}
          </Box>
        ) : null}
      </Box>
    )
  }

  return (
    <Box flexDirection="column" width={total} height={height}>
      <Box flexDirection="column" height={avail} overflow="hidden">
        {body}
      </Box>
      {state.typed ? (
        <Box flexDirection="column">
          <Text color={ink.warn} bold>{truncate(state.typed.message, total - 1)}</Text>
          <TextField label={t('typedConfirm', { word: state.typed.word })} buffer={state.typed.buf} focused width={total - 1} />
        </Box>
      ) : state.confirm ? (
        <ConfirmLine pending={state.confirm} columns={total} hint={t('hint.confirmLine')} />
      ) : null}
      {flash ? <Text color={toneColor(flash.tone)}>{truncate(flash.text, total - 1)}</Text> : null}
    </Box>
  )
}

type T = (key: string, options?: Record<string, unknown>) => string

/** A label padded to the label column, always followed by at least one space. */
function labelCell(label: string, lw: number): string {
  return padEnd(truncate(label, lw - 1), lw)
}

function layout(rows: FormRow[], cursor: number, active: boolean, editing: Editing | null, total: number, t: T): Line[] {
  const g = glyphs()
  const lines: Line[] = []
  const labels = rows.flatMap(r => (r.kind === 'text' || r.kind === 'choice' || r.kind === 'toggle' || r.kind === 'info' ? [r.label] : []))
  const lw = labelWidth(total, labels)
  const vw = Math.max(4, total - 2 - lw)

  rows.forEach((row, index) => {
    const sel = active && index === cursor
    const pointer = (
      <Text color={sel ? ink.focus : undefined}>{sel ? `${g.pointer} ` : '  '}</Text>
    )
    const push = (node: ReactNode) => lines.push({ node, row: index })

    if (row.kind === 'blank') {
      push(<Text> </Text>)
      return
    }
    if (row.kind === 'heading') {
      if (index > 0 && rows[index - 1]?.kind !== 'blank') push(<Text> </Text>)
      const aside = row.aside ? truncate(row.aside, Math.floor(total / 2)) : ''
      const title = truncate(row.text, total - cells(aside) - 2)
      push(
        <Text>
          <Text bold>{title}</Text>
          <Text color={ink.muted}>{aside ? ' '.repeat(Math.max(1, total - 1 - cells(title) - cells(aside))) + aside : ''}</Text>
        </Text>,
      )
      return
    }
    if (row.kind === 'note') {
      const indent = row.indent ?? 2
      const wrapped = wrap(row.text, Math.max(8, total - indent - 1)).map((line, i) => (i > 0 ? line.trimStart() : line))
      const shown = row.maxLines ? wrapped.slice(0, row.maxLines) : wrapped
      for (const text of shown) push(<Text color={toneColor(row.tone ?? 'muted')}>{' '.repeat(indent) + truncate(text, total - indent - 1)}</Text>)
      return
    }

    if (row.kind === 'info') {
      const valueText = truncate(row.value, vw - 1)
      const room = vw - cells(valueText) - 3
      push(
        <Text>
          {'  '}
          <Text color={ink.muted}>{labelCell(row.label, lw)}</Text>
          <Text color={toneColor(row.tone)}>{valueText}</Text>
          {row.detail && room >= 4 ? <Text color={ink.muted}>{'  ' + truncate(row.detail, room)}</Text> : null}
        </Text>,
      )
      return
    }

    const labelColor = row.disabled ? ink.muted : sel ? ink.focus : undefined
    const detail = (used: number, text?: string, tone?: Tone) => {
      if (!text) return null
      const room = vw - used - 3
      if (room < 4) return null
      return <Text color={toneColor(tone ?? 'muted')}>{'  ' + truncate(text, room)}</Text>
    }

    if (row.kind === 'text') {
      const isEditing = editing?.id === row.id
      if (isEditing && editing) {
        push(
          <Box>
            {pointer}
            <Text color={ink.focus} bold>{labelCell(row.label, lw)}</Text>
            <TextField buffer={editing.buf} focused width={vw} masked={row.masked} placeholder={row.placeholder} />
          </Box>,
        )
        if (row.value !== editing.base) {
          push(<Text color={ink.warn}>{' '.repeat(2 + lw) + truncate(t('changedElsewhere'), vw - 1)}</Text>)
        }
        return
      }
      const shown = row.display ?? (row.masked && row.value ? '•'.repeat(Math.min(12, row.value.length)) : row.value)
      const valueText = shown ? truncate(shown, vw - 1) : truncate(row.placeholder ?? '', vw - 1)
      push(
        <Text>
          {pointer}
          <Text color={labelColor} bold={sel}>{labelCell(row.label, lw)}</Text>
          <Text color={row.disabled || !shown ? ink.muted : undefined}>{valueText}</Text>
          {detail(cells(valueText), row.detail, row.detailTone)}
        </Text>,
      )
      return
    }
    if (row.kind === 'choice') {
      const label = row.options.find(o => o.value === row.value)?.label ?? row.display ?? row.value
      const text = truncate(sel && !row.disabled ? (usesPicker(row) ? `${label} ${g.pointer}` : `< ${label} >`) : label, vw - 1)
      push(
        <Text>
          {pointer}
          <Text color={labelColor} bold={sel}>{labelCell(row.label, lw)}</Text>
          <Text color={row.disabled ? ink.muted : undefined}>{text}</Text>
          {detail(cells(text), row.detail, row.detailTone)}
        </Text>,
      )
      return
    }
    if (row.kind === 'toggle') {
      const text = `${row.value ? g.checked : g.unchecked} ${row.value ? t('on') : t('off')}`
      push(
        <Text>
          {pointer}
          <Text color={labelColor} bold={sel}>{labelCell(row.label, lw)}</Text>
          <Text color={row.disabled ? ink.muted : row.value ? ink.success : ink.muted}>{text}</Text>
          {detail(cells(text), row.detail, row.detailTone)}
        </Text>,
      )
      return
    }
    if (row.kind === 'action') {
      const color = row.disabled ? ink.muted : sel ? ink.focus : toneColor(row.tone)
      // A short label lines its detail up with the values of the fields.
      const aligned = !!row.detail && cells(row.label) < lw - 1
      const label = aligned ? labelCell(row.label, lw) : truncate(row.label, total - 3)
      const gap = aligned ? '' : '  '
      const room = total - 3 - cells(label) - gap.length
      push(
        <Text>
          {pointer}
          <Text color={color} bold={sel}>{label}</Text>
          {row.detail && room >= 4 ? <Text color={toneColor(row.detailTone ?? 'muted')}>{gap + truncate(row.detail, room)}</Text> : null}
        </Text>,
      )
      return
    }
    // item
    let used = 2
    const nodes: ReactNode[] = []
    row.cells.forEach((cell, i) => {
      const last = i === row.cells.length - 1
      const size = last ? Math.max(1, total - 1 - used) : Math.min(cell.width ?? 12, Math.max(1, total - 1 - used))
      if (size <= 0 || used >= total - 1) return
      const text = last ? truncate(cell.text, size) : padEnd(cell.text, size)
      used += cells(text)
      nodes.push(
        <Text key={i} color={row.dim && !sel ? ink.muted : toneColor(cell.tone)} bold={(sel && i === 0) || cell.bold}>
          {text}
        </Text>,
      )
    })
    push(
      <Text>
        {pointer}
        {nodes}
      </Text>,
    )
  })
  return lines
}

function PickerView({ row, picker, width: total, height }: { row: Extract<FormRow, { kind: 'choice' }>; picker: Picker; width: number; height: number }) {
  const { t } = useTranslation('settingsCore')
  const g = glyphs()
  const options = filterOptions(row.options, picker.filter.text)
  const listHeight = Math.max(1, height - 2)
  const view = clampList(picker.list, options.length, listHeight)
  const count = t('picker.count', { shown: options.length, total: row.options.length })
  const title = truncate(row.pickerTitle ?? row.label, total - cells(count) - 3)
  const detailWidth = Math.min(28, Math.floor(total * 0.4))
  return (
    <Box flexDirection="column">
      <Text>
        <Text bold>{title}</Text>
        <Text color={ink.muted}>{' '.repeat(Math.max(1, total - 1 - cells(title) - cells(count))) + count}</Text>
      </Text>
      <TextField label="/" buffer={picker.filter} focused width={total - 1} placeholder={t('picker.filter')} />
      {options.length === 0 ? <Text color={ink.muted}>{'  ' + t('picker.none')}</Text> : null}
      {options.slice(view.top, view.top + listHeight).map((option, i) => {
        const index = view.top + i
        const sel = index === view.index
        const current = option.value === row.value
        const hasDetail = !!option.detail && total > 40
        const labelRoom = total - 5 - (hasDetail ? detailWidth + 1 : 0)
        return (
          <Text key={`${option.value}:${index}`}>
            <Text color={sel ? ink.focus : undefined}>{sel ? `${g.pointer} ` : '  '}</Text>
            <Text color={ink.success}>{current ? `${g.done} ` : '  '}</Text>
            <Text color={sel ? ink.focus : undefined} bold={sel}>{padEnd(option.label, labelRoom)}</Text>
            {hasDetail ? <Text color={ink.muted}>{' ' + truncate(option.detail ?? '', detailWidth)}</Text> : null}
          </Text>
        )
      })}
    </Box>
  )
}
