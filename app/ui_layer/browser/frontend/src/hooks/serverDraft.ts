/**
 * State machine behind `useServerDraft` (docs/plans/ui-data-freshness-plan.md,
 * §A4.4). Pure so it can be tested without React.
 *
 * - clean: shows the server value and follows it.
 * - dirty: shows the user's edit; a server change underneath only flags
 *   `remoteChanged`.
 * - saved: this tab saved the edit; keeps showing it (not dirty) until the
 *   server value changes, so the field doesn't flash back to the old value
 *   while the refetch is on its way.
 */
export type DraftState<T> =
  | { mode: 'clean'; server: T }
  | { mode: 'dirty'; server: T; value: T; remoteChanged: boolean }
  | { mode: 'saved'; server: T; value: T }

export type DraftAction<T> =
  | { type: 'server'; value: T }
  | { type: 'set'; value: T }
  | { type: 'reset' }
  | { type: 'acceptRemote' }

export type DraftEqual<T> = (a: T, b: T) => boolean

/** Identity for primitives, structural (JSON) for plain objects and arrays. */
export function defaultDraftEqual<T>(a: T, b: T): boolean {
  if (Object.is(a, b)) return true
  if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) return false
  return JSON.stringify(a) === JSON.stringify(b)
}

export function initialDraft<T>(server: T): DraftState<T> {
  return { mode: 'clean', server }
}

export function reduceDraft<T>(
  state: DraftState<T>,
  action: DraftAction<T>,
  equal: DraftEqual<T> = defaultDraftEqual,
): DraftState<T> {
  switch (action.type) {
    case 'server':
      if (equal(action.value, state.server)) return state
      if (state.mode === 'dirty' && !equal(action.value, state.value)) {
        return { ...state, server: action.value, remoteChanged: true }
      }
      // Clean follows; a saved edit, or one the server now matches, settles.
      return { mode: 'clean', server: action.value }
    case 'set':
      if (equal(action.value, state.server)) return { mode: 'clean', server: state.server }
      return {
        mode: 'dirty',
        server: state.server,
        value: action.value,
        remoteChanged: state.mode === 'dirty' && state.remoteChanged,
      }
    case 'reset':
      return state.mode === 'dirty' ? { mode: 'saved', server: state.server, value: state.value } : state
    case 'acceptRemote':
      return state.mode === 'clean' ? state : { mode: 'clean', server: state.server }
  }
}

export function draftView<T>(state: DraftState<T>): { value: T; isDirty: boolean; remoteChanged: boolean } {
  return {
    value: state.mode === 'clean' ? state.server : state.value,
    isDirty: state.mode === 'dirty',
    remoteChanged: state.mode === 'dirty' && state.remoteChanged,
  }
}
