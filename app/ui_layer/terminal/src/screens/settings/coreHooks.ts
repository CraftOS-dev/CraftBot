/**
 * Small hooks the settings tabs share: listening for the replies to a tab's
 * own requests (after the store has applied them, as the browser's
 * useSettingsWebSocket does), a transient status line, and the external
 * editor.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useApp } from 'ink'
import { onInboundMessage } from '../../../../browser/frontend/src/store/socket/socketMiddleware'
import { currentEditor, editInEditor, type EditResult } from './coreEditor'
import type { Tone } from './coreForm'

/** Call `handler(data)` for every inbound message of the given type(s) while mounted. */
export function useInbound(types: string | string[], handler: (data: unknown, type: string) => void): void {
  const ref = useRef(handler)
  ref.current = handler
  const key = Array.isArray(types) ? types.join('|') : types
  useEffect(() => {
    const wanted = new Set(key.split('|'))
    return onInboundMessage(msg => {
      if (wanted.has(msg.type)) ref.current(msg.data, msg.type)
    })
  }, [key])
}

export interface Flash {
  text: string
  tone: Tone
}

/** A one-line status that clears itself after `ms` (null `ms`: until replaced). */
export function useFlash(): [Flash | null, (text: string, tone?: Tone, ms?: number | null) => void, () => void] {
  const [flash, setFlash] = useState<Flash | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])
  const say = useCallback((text: string, tone: Tone = 'muted', ms: number | null = 5000) => {
    clearTimeout(timer.current)
    setFlash({ text, tone })
    if (ms !== null) timer.current = setTimeout(() => setFlash(null), ms)
  }, [])
  const clear = useCallback(() => {
    clearTimeout(timer.current)
    setFlash(null)
  }, [])
  return [flash, say, clear]
}

/** Edit text in the external editor, with the terminal handed over while it runs. */
export function useExternalEditor(): {
  editing: boolean
  edit: (text: string, filename: string) => Promise<EditResult>
} {
  const { suspendTerminal } = useApp()
  const [editing, setEditing] = useState(false)
  const busy = useRef(false)
  const edit = useCallback(
    async (text: string, filename: string) => {
      if (busy.current) return { text: null, error: 'busy', editor: currentEditor() }
      busy.current = true
      setEditing(true)
      try {
        return await editInEditor(run => suspendTerminal(run), text, filename)
      } finally {
        busy.current = false
        setEditing(false)
      }
    },
    [suspendTerminal],
  )
  return { editing, edit }
}
