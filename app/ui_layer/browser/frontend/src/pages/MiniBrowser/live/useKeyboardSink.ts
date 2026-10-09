import React, { useCallback, useEffect, useMemo, useRef, type MutableRefObject, type RefObject } from 'react'
import { useAppDispatch, useAppSelector } from '../../../store/hooks'
import { selectMiniBrowserClipboard } from '../../../store/selectors/miniBrowser'
import { clipboardConsumed } from '../../../store/slices/miniBrowserSlice'
import type { MiniBrowserTab } from '../../../types'
import { copyTextWhenReady } from '../clipboard'
import { sendLive } from '../useMiniBrowserSocket'
import { classifyKey, cutShortcut } from './keyboard'
import type { LiveInput } from './useLiveInput'

const MAX_PASTE_CHARS = 20_000
// A second Escape within this window hands the keyboard back to the app.
const DOUBLE_ESCAPE_MS = 500
const COPY_TIMEOUT_MS = 4000

export interface KeyboardTarget {
  tab: MiniBrowserTab | null
  onFocusAddress(): void
  onHistory(action: 'back' | 'forward' | 'reload'): void
}

interface KeyboardOptions {
  sink: RefObject<HTMLTextAreaElement>
  input: LiveInput
  target: MutableRefObject<KeyboardTarget>
  /** Class that makes the sink visible while an IME composes. */
  composingClass: string
  /** Place the sink so the draft an IME is composing fits on the stage
   *  (called whenever the draft appears, grows or goes away). */
  placeSink(): void
  onPasteTruncated(max: number): void
  onCopyFailed(): void
}

export interface KeyboardSinkHandlers {
  onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>): void
  onInput(e: React.FormEvent<HTMLTextAreaElement>): void
  onCompositionStart(): void
  onCompositionEnd(): void
  onPaste(e: React.ClipboardEvent<HTMLTextAreaElement>): void
  onBlur(): void
}

export interface KeyboardSink {
  /** Spread onto the sink <textarea>. */
  handlers: KeyboardSinkHandlers
  /** The view left `previousTabId`: give up the keyboard, and send whatever
   *  the IME had composed to the tab it was composed for (text left in the
   *  sink otherwise goes to `previousTabId`). */
  leave(previousTabId: string | null): void
}

interface PendingCopy {
  resolve(text: string): void
  reject(err: Error): void
  /** A newer copy (or leaving the page) replaced this one: its failure is
   *  not the user's problem and is never reported. */
  superseded: boolean
}

/**
 * The live view's keyboard: a hidden <textarea> takes focus, so text arrives
 * exactly as the OS and IME produce it (Japanese/Chinese/Korean composition,
 * dead keys, AltGr, mobile keyboards) and is forwarded as text; keydown only
 * forwards named keys and shortcut combos (see keyboard.ts). Also handles
 * paste, copy/cut of the page's selection, and "Escape twice" to leave.
 */
export function useKeyboardSink({
  sink,
  input,
  target,
  composingClass,
  placeSink,
  onPasteTruncated,
  onCopyFailed,
}: KeyboardOptions): KeyboardSink {
  const dispatch = useAppDispatch()
  const clipboard = useAppSelector(selectMiniBrowserClipboard)
  const composingRef = useRef(false)
  // The tab an IME composition started on: its text goes there, even if the
  // view has moved on by the time the IME commits it.
  const compositionTabRef = useRef<string | null>(null)
  // While leaving a tab: the tab the sink's leftovers belong to.
  const leavingTabRef = useRef<string | null>(null)
  const lastEscapeRef = useRef(0)
  const copyRef = useRef<PendingCopy | null>(null)

  // ── Copy / cut ───────────────────────────────────────────────────────
  const copySelection = useCallback((cut: boolean) => {
    const tab = target.current.tab
    if (!tab) return
    input.flushText()
    if (!sendLive('mini_browser_copy', { tabId: tab.id })) return
    const previous = copyRef.current
    if (previous) {
      previous.superseded = true
      previous.reject(new Error('superseded'))
    }
    let settle: Pick<PendingCopy, 'resolve' | 'reject'> = { resolve: () => undefined, reject: () => undefined }
    const text = new Promise<string>((resolve, reject) => {
      settle = { resolve, reject }
    })
    const timer = window.setTimeout(() => {
      if (copyRef.current === pending) copyRef.current = null
      settle.reject(new Error('timeout'))
    }, COPY_TIMEOUT_MS)
    const pending: PendingCopy = {
      superseded: false,
      resolve: (value) => {
        window.clearTimeout(timer)
        settle.resolve(value)
      },
      reject: (err) => {
        window.clearTimeout(timer)
        settle.reject(err)
      },
    }
    copyRef.current = pending
    // Started inside the key press, which is what lets the browser write.
    void copyTextWhenReady(text).then((outcome) => {
      if (outcome === 'failed' && !pending.superseded) onCopyFailed()
    })
    // Cut = copy, then let the page delete the selection itself.
    if (cut) input.pressKey('x', cutShortcut())
  }, [input, onCopyFailed, target])

  // The backend's copy reply arrives through the store.
  useEffect(() => {
    if (!clipboard) return
    const pending = copyRef.current
    if (pending) {
      copyRef.current = null
      pending.resolve(clipboard.text)
    }
    // Handed over: don't keep the user's selection in the store.
    if (clipboard.text) dispatch(clipboardConsumed())
  }, [clipboard, dispatch])

  useEffect(() => () => {
    const pending = copyRef.current
    copyRef.current = null
    if (pending) {
      pending.superseded = true
      pending.reject(new Error('unmounted'))
    }
  }, [])

  // ── Keys ─────────────────────────────────────────────────────────────
  const onKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const intent = classifyKey(e.nativeEvent)
    if (intent.kind === 'native') return
    e.preventDefault()
    switch (intent.kind) {
      case 'focusAddress':
        input.flushText()
        target.current.onFocusAddress()
        return
      case 'history':
        input.flushText()
        target.current.onHistory(intent.action)
        return
      case 'copy':
        // Holding the keys copies (or cuts) once, not once per auto-repeat.
        if (!e.repeat) copySelection(intent.cut)
        return
      case 'escape': {
        const now = performance.now()
        if (now - lastEscapeRef.current < DOUBLE_ESCAPE_MS) {
          lastEscapeRef.current = 0
          input.flushText()
          target.current.onFocusAddress()
          return
        }
        lastEscapeRef.current = now
        input.pressKey('Escape')
        return
      }
      case 'press':
        input.pressKey(intent.key, intent.modifiers)
    }
  }, [copySelection, input, target])

  // ── Text: typing, IME, paste ─────────────────────────────────────────
  // Whatever sits in the sink is text not yet sent; take it and clear it.
  const takeText = useCallback((tabId?: string | null) => {
    const el = sink.current
    if (!el || !el.value) return
    const text = el.value
    el.value = ''
    input.queueText(text, tabId ?? input.currentTabId())
  }, [input, sink])

  const onInput = useCallback((e: React.FormEvent<HTMLTextAreaElement>) => {
    // Mid-composition text is the IME's draft; it is sent on compositionend.
    if (composingRef.current || (e.nativeEvent as InputEvent).isComposing) {
      placeSink() // the draft grew: keep it on the stage
      return
    }
    takeText()
  }, [placeSink, takeText])

  const onCompositionStart = useCallback(() => {
    composingRef.current = true
    compositionTabRef.current = input.currentTabId()
    // Typing via an IME sends nothing until the text is committed, so this
    // is where the user is first seen to be typing.
    input.noteUserInput()
    // Make the draft visible (the sink is otherwise transparent) and keep
    // it inside the stage.
    sink.current?.classList.add(composingClass)
    placeSink()
  }, [composingClass, input, placeSink, sink])

  const onCompositionEnd = useCallback(() => {
    const tabId = compositionTabRef.current
    composingRef.current = false
    compositionTabRef.current = null
    sink.current?.classList.remove(composingClass)
    placeSink()
    takeText(tabId)
  }, [composingClass, placeSink, sink, takeText])

  const onPaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    e.preventDefault()
    let text = e.clipboardData.getData('text/plain').replace(/\r\n?/g, '\n')
    if (!text) return
    if (text.length > MAX_PASTE_CHARS) {
      text = Array.from(text).slice(0, MAX_PASTE_CHARS).join('')
      onPasteTruncated(MAX_PASTE_CHARS)
    }
    input.queueText(text)
    input.flushText()
  }, [input, onPasteTruncated])

  // Clears the sink; a draft still in it goes to the tab it was typed for.
  const settle = useCallback(() => {
    const el = sink.current
    if (el?.value) takeText(compositionTabRef.current ?? leavingTabRef.current)
    composingRef.current = false
    compositionTabRef.current = null
    el?.classList.remove(composingClass)
    input.flushText()
  }, [composingClass, input, sink, takeText])

  const onBlur = useCallback(() => {
    settle()
  }, [settle])

  const leave = useCallback((previousTabId: string | null) => {
    leavingTabRef.current = previousTabId
    try {
      const el = sink.current
      if (el && document.activeElement === el) {
        // Blurring makes the IME commit its draft (compositionend), which
        // the handlers above send to the composition's tab.
        el.blur()
        // The caret stays parked in a blurred field, and text inserted at
        // "the selection" (dictation, IME-style insertion) would land there
        // and re-focus it: drop the caret too.
        document.getSelection()?.removeAllRanges()
      }
      // Whatever is still in the sink (no compositionend arrived) goes the
      // same way.
      settle()
    } finally {
      leavingTabRef.current = null
    }
  }, [settle, sink])

  // Mobile keyboards report Backspace/Enter on an empty field only through
  // beforeinput (their keydown says "Unidentified" / 229).
  useEffect(() => {
    const el = sink.current
    if (!el) return
    const onBeforeInput = (e: InputEvent) => {
      if (composingRef.current || e.isComposing) return
      const key =
        e.inputType === 'deleteContentBackward' ? 'Backspace'
          : e.inputType === 'deleteContentForward' ? 'Delete'
            : e.inputType === 'insertLineBreak' || e.inputType === 'insertParagraph' ? 'Enter'
              : null
      if (!key) return
      e.preventDefault()
      input.pressKey(key)
    }
    el.addEventListener('beforeinput', onBeforeInput)
    return () => el.removeEventListener('beforeinput', onBeforeInput)
  }, [input, sink])

  const handlers = useMemo<KeyboardSinkHandlers>(
    () => ({ onKeyDown, onInput, onCompositionStart, onCompositionEnd, onPaste, onBlur }),
    [onKeyDown, onInput, onCompositionStart, onCompositionEnd, onPaste, onBlur],
  )
  return { handlers, leave }
}
