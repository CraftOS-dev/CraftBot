import type { AppDispatch, RootState } from '../index'
import { setVersion } from '../slices/connectionSlice'
import type { SocketEnvelope } from './types'

// Inbound message routing table. Maps a backend message type to one or more
// handlers that translate it into dispatches. Multiple slices can listen on
// the same event (e.g. `init` populates messages, tasks, agent, etc.).
//
// As slices migrate (phase 3+), each domain registers its inbound handlers
// here so the socket middleware can drive the store directly — without
// going through legacy contexts.
export type InboundHandler = (
  data: unknown,
  dispatch: AppDispatch,
  getState: () => RootState,
) => void

const handlers = new Map<string, Set<InboundHandler>>()

export function register(type: string, handler: InboundHandler): void {
  let set = handlers.get(type)
  if (!set) {
    set = new Set()
    handlers.set(type, set)
  }
  set.add(handler)
}

export function dispatchInbound(
  msg: SocketEnvelope,
  dispatch: AppDispatch,
  getState: () => RootState,
): void {
  const set = handlers.get(msg.type)
  if (!set) return
  set.forEach(h => {
    try { h(msg.data, dispatch, getState) } catch (err) {
      console.error(`[messageRegistry] handler for "${msg.type}" threw:`, err)
    }
  })
}

// --- bootstrap registrations ---------------------------------------------
// Connection-level handlers register here. Domain slices register their
// own handlers from their slice files as they migrate.

register('init', (data, dispatch) => {
  const version = (data as { version?: string } | undefined)?.version
  if (typeof version === 'string') dispatch(setVersion(version))
})
