import { useCallback, useMemo, useRef, useState } from 'react'
import {
  defaultDraftEqual,
  draftView,
  initialDraft,
  reduceDraft,
  type DraftEqual,
} from './serverDraft'

export interface ServerDraft<T> {
  /** What the form shows: the edit while there is one, else the server value. */
  value: T
  /** Edit the draft. Setting it back to the server value makes it clean again. */
  set: (next: T | ((previous: T) => T)) => void
  /** There is an unsaved edit. */
  isDirty: boolean
  /** The server value changed while there was an unsaved edit. */
  remoteChanged: boolean
  /**
   * Call after this tab's own save succeeded: the draft stops being dirty and
   * keeps showing the saved value until the server value catches up.
   */
  reset: () => void
  /** Drop the edit and show the server value now ("load latest"). */
  acceptRemote: () => void
}

/**
 * A form draft over a server value (docs/plans/ui-data-freshness-plan.md, §A4.4).
 * Clean drafts follow the server; dirty drafts keep the user's edit and flag
 * `remoteChanged` instead of being overwritten by another tab or the agent.
 *
 * @example
 *   const name = useServerDraft(serverName)
 *   <input value={name.value} onChange={e => name.set(e.target.value)} />
 */
export function useServerDraft<T>(
  serverValue: T,
  isEqual: DraftEqual<T> = defaultDraftEqual,
): ServerDraft<T> {
  const [state, setState] = useState(() => initialDraft(serverValue))
  const equalRef = useRef(isEqual)
  equalRef.current = isEqual

  // Follow the server value during render rather than in an effect, so a
  // clean draft never shows one frame of the old value.
  let current = state
  if (!isEqual(serverValue, state.server)) {
    current = reduceDraft(state, { type: 'server', value: serverValue }, isEqual)
    setState(current)
  }

  const set = useCallback((next: T | ((previous: T) => T)) => {
    setState(s => {
      const value = typeof next === 'function'
        ? (next as (previous: T) => T)(draftView(s).value)
        : next
      return reduceDraft(s, { type: 'set', value }, equalRef.current)
    })
  }, [])
  const reset = useCallback(() => setState(s => reduceDraft(s, { type: 'reset' })), [])
  const acceptRemote = useCallback(() => setState(s => reduceDraft(s, { type: 'acceptRemote' })), [])

  return useMemo(
    () => ({ ...draftView(current), set, reset, acceptRemote }),
    [current, set, reset, acceptRemote],
  )
}
