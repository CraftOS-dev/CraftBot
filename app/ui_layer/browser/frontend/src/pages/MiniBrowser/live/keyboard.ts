import type { MiniBrowserKeyModifiers } from '../../../types'

// Keyboard routing for the live view.
//
// The live view's focus target is a hidden <textarea>, so text arrives the
// way the browser produces it: plain typing, IME composition (Japanese,
// Chinese, Korean…), dead keys, AltGr/Option characters and mobile keyboards
// all come out of `input`/`compositionend` as finished text. keydown only
// handles what is NOT text: named keys (Enter, Tab, arrows, Backspace…),
// Space, shortcut combos, and the few shortcuts the Mini Browser keeps for
// itself (copy, address bar, history). Everything the host browser must keep
// (zoom, devtools, tab/window shortcuts) is left alone.

export type KeyIntent =
  /** Leave it to the browser: text input (arrives via `input`), paste, or a
   *  host shortcut. */
  | { kind: 'native' }
  /** Press this key in the page (Playwright key name + modifiers). */
  | { kind: 'press'; key: string; modifiers?: MiniBrowserKeyModifiers }
  /** Copy (or cut) the page's selection to the user's clipboard. */
  | { kind: 'copy'; cut: boolean }
  /** Move focus to the address bar (Ctrl/⌘+L). */
  | { kind: 'focusAddress' }
  | { kind: 'history'; action: 'back' | 'forward' | 'reload' }
  /** A bare Escape: forwarded, and pressed twice it releases focus. */
  | { kind: 'escape' }

/** The parts of a KeyboardEvent the classifier reads (testable without DOM). */
export interface KeyLike {
  key: string
  code: string
  keyCode: number
  shiftKey: boolean
  ctrlKey: boolean
  altKey: boolean
  metaKey: boolean
  isComposing: boolean
  getModifierState(key: string): boolean
}

export const IS_MAC =
  typeof navigator !== 'undefined' &&
  /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent || '')

const NATIVE: KeyIntent = { kind: 'native' }

const MODIFIER_ONLY = new Set([
  'Shift', 'Control', 'Alt', 'AltGraph', 'Meta', 'OS', 'Hyper', 'Super',
  'CapsLock', 'NumLock', 'ScrollLock', 'Fn', 'FnLock', 'Symbol', 'SymbolLock',
])

// Named keys pressed in the page. F5 reloads the page; F6, F11 and F12 stay
// with the host (focus cycling, fullscreen, devtools).
const PAGE_KEYS = new Set([
  'Enter', 'Tab', 'Backspace', 'Delete', 'Insert',
  'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
  'Home', 'End', 'PageUp', 'PageDown',
  'F1', 'F2', 'F3', 'F4', 'F7', 'F8', 'F9', 'F10',
])
const HOST_KEYS = new Set(['F6', 'F11', 'F12'])

// Shortcut letters that belong to the host browser/OS: tabs and windows,
// zoom, and (macOS) hide/minimize/preferences.
const HOST_SHORTCUTS = new Set(['t', 'n', 'w', 'q', '+', '-', '=', '_', '0'])
const HOST_SHORTCUTS_MAC = new Set(['h', 'm', ','])

/** Printable ASCII for shortcuts: the character itself when the layout gives
 *  one, else the physical key (Ctrl+С on a Cyrillic layout is still Ctrl+C,
 *  exactly as browsers treat their own shortcuts). */
function shortcutKey(e: KeyLike): string | null {
  if (e.key.length === 1 && e.key >= '!' && e.key <= '~') return e.key
  const match = /^(?:Key([A-Z])|Digit([0-9]))$/.exec(e.code)
  if (!match) return null
  if (match[1]) return e.shiftKey ? match[1] : match[1].toLowerCase()
  return match[2]
}

function modifiersOf(e: KeyLike): MiniBrowserKeyModifiers | undefined {
  if (!e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) return undefined
  return { shift: e.shiftKey, ctrl: e.ctrlKey, alt: e.altKey, meta: e.metaKey }
}

const press = (key: string, e: KeyLike): KeyIntent => {
  const modifiers = modifiersOf(e)
  return modifiers ? { kind: 'press', key, modifiers } : { kind: 'press', key }
}

/** The page's own cut shortcut (⌘X on macOS, Ctrl+X elsewhere), pressed
 *  after a cut's text was copied — whichever keys the user cut with
 *  (Ctrl+X, ⌘X or Shift+Delete). */
export function cutShortcut(isMac: boolean = IS_MAC): MiniBrowserKeyModifiers {
  return { shift: false, ctrl: !isMac, alt: false, meta: isMac }
}

/** Decide what a keydown in the live view should do. */
export function classifyKey(e: KeyLike, isMac: boolean = IS_MAC): KeyIntent {
  // IME composition, dead keys and virtual keyboards produce their text via
  // `input`/`compositionend`; keyCode 229 is "the IME is handling this".
  if (!e.key || e.isComposing || e.keyCode === 229) return NATIVE
  if (e.key === 'Process' || e.key === 'Dead' || e.key === 'Unidentified') return NATIVE
  if (MODIFIER_ONLY.has(e.key) || HOST_KEYS.has(e.key)) return NATIVE

  const altGraph = e.getModifierState('AltGraph')
  // The platform's shortcut modifier: ⌘ on macOS, Ctrl elsewhere.
  const primary = isMac ? e.metaKey : e.ctrlKey
  const ascii = shortcutKey(e)
  const letter = ascii?.toLowerCase() ?? null

  if (e.key === 'F5') return { kind: 'history', action: 'reload' }

  // The Windows/Linux clipboard keys: Shift+Insert pastes, Ctrl+Insert
  // copies, Shift+Delete cuts. They act on the user's clipboard, never on the
  // remote browser's own (which the user can't reach).
  if (!isMac && !e.altKey && !e.metaKey && !altGraph) {
    if (e.key === 'Insert' && e.shiftKey && !e.ctrlKey) return NATIVE // the paste event carries the text
    if (e.key === 'Insert' && e.ctrlKey && !e.shiftKey) return { kind: 'copy', cut: false }
    if (e.key === 'Delete' && e.shiftKey && !e.ctrlKey) return { kind: 'copy', cut: true }
  }

  if (primary && !e.altKey && !altGraph) {
    if (e.key === 'Tab' || e.key === 'PageUp' || e.key === 'PageDown' || e.key === 'F4') return NATIVE
    if (letter === 'v') return NATIVE // the paste event carries the text
    if (!isMac && e.shiftKey && (letter === 'i' || letter === 'j' || letter === 'c')) return NATIVE // devtools
    if (letter && (HOST_SHORTCUTS.has(letter) || (isMac && HOST_SHORTCUTS_MAC.has(letter)))) return NATIVE
    if (letter === 'c' && !e.shiftKey) return { kind: 'copy', cut: false }
    if (letter === 'x' && !e.shiftKey) return { kind: 'copy', cut: true }
    if (letter === 'l') return { kind: 'focusAddress' }
    if (letter === 'r') return { kind: 'history', action: 'reload' }
    if (isMac && e.key === '[') return { kind: 'history', action: 'back' }
    if (isMac && e.key === ']') return { kind: 'history', action: 'forward' }
  }

  // Alt+←/→ is history in Windows/Linux browsers; left alone it would
  // navigate CraftBot itself away from this page. (On macOS Option+arrows
  // move by word inside text fields, so they go to the page.)
  if (!isMac && e.altKey && !e.ctrlKey && !e.metaKey && !altGraph) {
    if (e.key === 'ArrowLeft') return { kind: 'history', action: 'back' }
    if (e.key === 'ArrowRight') return { kind: 'history', action: 'forward' }
  }

  if (e.key === 'Escape') {
    return e.shiftKey || e.ctrlKey || e.altKey || e.metaKey ? press('Escape', e) : { kind: 'escape' }
  }

  // Space is a key, not text: it toggles checkboxes, presses buttons and
  // scrolls — and still types a space in text fields.
  if (e.key === ' ') return press('Space', e)

  if (PAGE_KEYS.has(e.key)) return press(e.key, e)

  // A printable character from here on.
  if ([...e.key].length !== 1) return NATIVE
  // AltGr (Windows/Linux) and Option (macOS) type characters such as @ € ñ å:
  // they must arrive as text, not as shortcuts.
  if (altGraph) return NATIVE
  if (e.altKey && !e.ctrlKey && !e.metaKey) {
    if (isMac || !ascii) return NATIVE
    return press(ascii, e)
  }
  // Ctrl+Alt+symbol is AltGr typing on Windows even when the browser doesn't
  // report the AltGraph state; only Ctrl+Alt+letter/digit is a shortcut.
  if (e.ctrlKey && e.altKey && !/^[a-z0-9]$/i.test(e.key)) return NATIVE
  if (e.ctrlKey || e.metaKey) return ascii ? press(ascii, e) : NATIVE
  // Plain typing (with or without Shift): the `input` event sends it.
  return NATIVE
}
