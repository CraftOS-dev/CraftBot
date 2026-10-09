import React, { useCallback, useEffect, useRef, type MutableRefObject, type RefObject } from 'react'
import { useAppDispatch, useAppSelector } from '../../../store/hooks'
import { selectMiniBrowserClipboard } from '../../../store/selectors/miniBrowser'
import { clipboardConsumed } from '../../../store/slices/miniBrowserSlice'
import type { MiniBrowserTab } from '../../../types'
import { copyTextWhenReady } from '../clipboard'
import { sendLive } from '../useMiniBrowserSocket'
import { classifyKey } from './keyboard'
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

interface PendingCopy {
  resolve(text: string): void
  reject(err: Error): void
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
  onPasteTruncated,
  onCopyFailed,
}: KeyboardOptions): KeyboardSinkHandlers {
  const dispatch = useAppDispatch()
  const clipboard = useAppSelector(selectMiniBrowserClipboard)
  const composingRef = useRef(false)
  const lastEscapeRef = useRef(0)
  const copyRef = useRef<PendingCopy | null>(null)

  // ── Copy / cut ───────────────────────────────────────────────────────
  const copySelection = useCallback((cut: boolean, ctrl: boolean, meta: boolean) => {
    const tab = target.current.tab
    if (!tab) return
    input.flushText()
    if (!sendLive('mini_browser_copy', { tabId: tab.id })) return
    copyRef.current?.reject(new Error('superseded'))
    let pending: PendingCopy = { resolve: () => undefined, reject: () => undefined }
    const text = new Promise<string>((resolve, reject) => {
      pending = { resolve, reject }
    })
    const timer = window.setTimeout(() => {
      copyRef.current = null
      pending.reject(new Error('timeout'))
    }, COPY_TIMEOUT_MS)
    copyRef.current = {
      resolve: (value) => {
        window.clearTimeout(timer)
        pending.resolve(value)
      },
      reject: (err) => {
        window.clearTimeout(timer)
        pending.reject(err)
      },
    }
    // Started inside the key press, which is what lets the browser write.
    void copyTextWhenReady(text).then((outcome) => {
      if (outcome === 'failed') onCopyFailed()
    })
    // Cut = copy, then let the page delete the selection itself.
    if (cut) input.pressKey('x', { shift: false, ctrl, alt: false, meta })
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
    copyRef.current?.reject(new Error('unmounted'))
    copyRef.current = null
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
        copySelection(intent.cut, e.ctrlKey, e.metaKey)
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
  const takeText = useCallback(() => {
    const el = sink.current
    if (!el || !el.value) return
    const text = el.value
    el.value = ''
    input.queueText(text)
  }, [input, sink])

  const onInput = useCallback((e: React.FormEvent<HTMLTextAreaElement>) => {
    // Mid-composition text is the IME's draft; it is sent on compositionend.
    if (composingRef.current || (e.nativeEvent as InputEvent).isComposing) return
    takeText()
  }, [takeText])

  const onCompositionStart = useCallback(() => {
    composingRef.current = true
    // Make the draft visible: the sink is otherwise transparent.
    sink.current?.classList.add(composingClass)
  }, [composingClass, sink])

  const onCompositionEnd = useCallback(() => {
    composingRef.current = false
    sink.current?.classList.remove(composingClass)
    takeText()
  }, [composingClass, sink, takeText])

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

  const onBlur = useCallback(() => {
    input.flushText()
    composingRef.current = false
    const el = sink.current
    if (el) {
      el.classList.remove(composingClass)
      el.value = ''
    }
  }, [composingClass, input, sink])

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

  return { onKeyDown, onInput, onCompositionStart, onCompositionEnd, onPaste, onBlur }
}
