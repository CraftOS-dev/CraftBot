/**
 * The composer's key handling as a pure function, so every binding is unit
 * tested without a terminal.
 *
 *   Enter               send (a trailing backslash makes it a newline instead)
 *   Shift+Enter, Alt+Enter, Ctrl+J   newline
 *   Left/Right          by grapheme; with Ctrl or Alt, by word (also Alt+B / Alt+F)
 *   Up/Down             by visual row; past the first/last row, through history
 *   Home/End, Ctrl+A/E  line start/end
 *   Backspace, Delete   by grapheme; Alt+Backspace and Ctrl+W delete a word
 *   Ctrl+U / Ctrl+K     delete to line start / end
 *
 * Keys it does not use (Esc, Tab, Ctrl+C and other shortcuts) come back as
 * unhandled so the chat can route them.
 */
import type { Key } from 'ink'
import * as TB from './TextBuffer'

export interface ComposerModel {
  buffer: TB.Buffer
  /** Index into history while browsing it; null while editing the draft. */
  historyIndex: number | null
  /** The draft set aside while browsing history. */
  stash: string
  /** Collapsed pastes: chip label -> pasted text. */
  pastes: Record<string, string>
  pasteCount: number
}

export const EMPTY_MODEL: ComposerModel = {
  buffer: TB.EMPTY,
  historyIndex: null,
  stash: '',
  pastes: {},
  pasteCount: 0,
}

export function modelFromText(text: string): ComposerModel {
  return { ...EMPTY_MODEL, buffer: TB.fromText(text) }
}

export type ComposerEffect = { kind: 'submit'; text: string } | null

export interface KeyResult {
  model: ComposerModel
  effect: ComposerEffect
  handled: boolean
}

/** Pastes longer than this collapse into a chip. */
export const PASTE_COLLAPSE_CHARS = 800
export const PASTE_COLLAPSE_LINES = 3

// Invisible characters that can smuggle instructions or reorder text:
// tag characters, bidi controls, zero-width spaces and joiners outside emoji.
const INVISIBLE = /[\u{E0000}-\u{E007F}‪-‮⁦-⁩​‎‏﻿]/gu

export function stripInvisible(text: string): { text: string; removed: number } {
  let removed = 0
  const cleaned = text.replace(INVISIBLE, () => {
    removed++
    return ''
  })
  return { text: cleaned, removed }
}

function normalizeNewlines(text: string): string {
  return text.replace(/\r\n?/g, '\n')
}

const set = (model: ComposerModel, buffer: TB.Buffer): ComposerModel => ({ ...model, buffer })

function edit(model: ComposerModel, buffer: TB.Buffer): ComposerModel {
  // Editing a recalled entry turns it into the new draft.
  return { ...model, buffer, historyIndex: null }
}

function recall(model: ComposerModel, history: string[], delta: -1 | 1): ComposerModel | null {
  if (history.length === 0) return null
  if (model.historyIndex === null) {
    if (delta === 1) return null
    const index = history.length - 1
    return { ...model, historyIndex: index, stash: model.buffer.text, buffer: TB.fromText(history[index]) }
  }
  const index = model.historyIndex + delta
  if (index < 0) return model
  if (index >= history.length) {
    return { ...model, historyIndex: null, buffer: TB.fromText(model.stash) }
  }
  return { ...model, historyIndex: index, buffer: TB.fromText(history[index]) }
}

/** The text to send: chips expanded, invisible characters removed. */
export function submittedText(model: ComposerModel): { text: string; removed: number } {
  let text = model.buffer.text
  for (const [label, pasted] of Object.entries(model.pastes)) {
    text = text.split(label).join(pasted)
  }
  return stripInvisible(text)
}

export function applyPaste(model: ComposerModel, raw: string): ComposerModel {
  const text = normalizeNewlines(raw)
  const lines = text.split('\n').length
  if (text.length > PASTE_COLLAPSE_CHARS || lines > PASTE_COLLAPSE_LINES) {
    const count = model.pasteCount + 1
    const label = `[Pasted text #${count} · ${lines} lines]`
    return {
      ...edit(model, TB.insert(model.buffer, label)),
      pastes: { ...model.pastes, [label]: text },
      pasteCount: count,
    }
  }
  return edit(model, TB.insert(model.buffer, text))
}

export function applyKey(
  model: ComposerModel,
  input: string,
  key: Key,
  ctx: { columns: number; history: string[] },
): KeyResult {
  const done = (next: ComposerModel, effect: ComposerEffect = null): KeyResult => ({ model: next, effect, handled: true })
  const pass: KeyResult = { model, effect: null, handled: false }
  const buf = model.buffer

  if (key.return) {
    if (key.shift || key.meta) return done(edit(model, TB.insert(buf, '\n')))
    const before = buf.text.slice(0, buf.cursor)
    if (before.endsWith('\\')) {
      const removed = TB.backspace(buf)
      return done(edit(model, TB.insert(removed, '\n')))
    }
    if (!submittedText(model).text.trim()) return done(model)
    // The raw draft: the sender expands paste chips and strips invisible
    // characters once (submittedText), so it can tell the user what it removed.
    return done(model, { kind: 'submit', text: model.buffer.text })
  }
  // Ctrl+J arrives as a bare line feed.
  if (input === '\n' && !key.ctrl && !key.meta) return done(edit(model, TB.insert(buf, '\n')))

  if (key.backspace) return done(edit(model, key.meta ? TB.deleteWordBack(buf) : TB.backspace(buf)))
  if (key.delete) return done(edit(model, TB.deleteForward(buf)))

  if (key.leftArrow) return done(set(model, key.ctrl || key.meta ? TB.wordLeft(buf) : TB.left(buf)))
  if (key.rightArrow) return done(set(model, key.ctrl || key.meta ? TB.wordRight(buf) : TB.right(buf)))
  if (key.home) return done(set(model, TB.home(buf)))
  if (key.end) return done(set(model, TB.end(buf)))

  if (key.upArrow || key.downArrow) {
    const delta = key.upArrow ? -1 : 1
    const moved = TB.verticalMove(buf, ctx.columns, delta)
    if (moved) return done(set(model, moved))
    const recalled = recall(model, ctx.history, delta)
    return recalled ? done(recalled) : done(model)
  }

  if (key.ctrl) {
    switch (input) {
      case 'a':
        return done(set(model, TB.home(buf)))
      case 'e':
        return done(set(model, TB.end(buf)))
      case 'w':
        return done(edit(model, TB.deleteWordBack(buf)))
      case 'u':
        return done(edit(model, TB.killToLineStart(buf)))
      case 'k':
        return done(edit(model, TB.killToLineEnd(buf)))
      case 'b':
        return done(set(model, TB.left(buf)))
      case 'f':
        return done(set(model, TB.right(buf)))
      default:
        return pass
    }
  }
  if (key.meta && !key.escape) {
    if (input === 'b') return done(set(model, TB.wordLeft(buf)))
    if (input === 'f') return done(set(model, TB.wordRight(buf)))
    if (input === 'd') return done(edit(model, killWordForward(buf)))
    return pass
  }
  if (key.escape || key.tab) return pass

  if (input) {
    // Typed text (several characters at once when typing fast or when an
    // IME commits a phrase). Control characters other than newline are dropped.
    const text = normalizeNewlines(input).replace(/[\u0000-\u0009\u000B-\u001F\u007F]/g, '')
    if (!text) return pass
    return done(edit(model, TB.insert(buf, text)))
  }
  return pass
}

function killWordForward(buf: TB.Buffer): TB.Buffer {
  const target = TB.wordRight(buf).cursor
  return { text: buf.text.slice(0, buf.cursor) + buf.text.slice(target), cursor: buf.cursor }
}
