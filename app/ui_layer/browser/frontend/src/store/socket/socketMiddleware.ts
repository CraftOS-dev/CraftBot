import type { Middleware } from '@reduxjs/toolkit'
import { setBackendBusy, setConnected, setReconnectAttempt } from '../slices/connectionSlice'
import { getSocketClient } from './socketInstance'
import { dispatchInbound } from './messageRegistry'
import type { SocketEnvelope } from './types'
import { resourceSync } from '../resources'

// The socket middleware bootstraps the shared SocketClient and wires its
// lifecycle into the store. It does not own slice state — each slice
// registers its inbound handlers in messageRegistry.ts as it migrates.
//
// Inbound messages are applied in batches, once per animation frame (or
// within FLUSH_FALLBACK_MS when frames don't run, e.g. in a hidden tab). A
// burst of hundreds of messages then costs one React render instead of
// hundreds (docs/plans/ui-data-freshness-plan.md, RS-2.2).

const FLUSH_FALLBACK_MS = 50

type InboundListener = (msg: SocketEnvelope) => void
const inboundListeners = new Set<InboundListener>()

/**
 * Subscribe to inbound messages *after* the store has applied each one, in
 * arrival order. React-side consumers (contexts, settings tabs) use this
 * instead of the raw socket so they never observe a message before the slices
 * have. Returns an unsubscribe function.
 */
export function onInboundMessage(listener: InboundListener): () => void {
  inboundListeners.add(listener)
  return () => { inboundListeners.delete(listener) }
}

export const socketMiddleware: Middleware = (store) => {
  const client = getSocketClient()
  let pending: SocketEnvelope[] = []
  let frame: number | null = null
  let fallback: number | null = null

  const flush = () => {
    if (frame !== null) cancelAnimationFrame(frame)
    if (fallback !== null) clearTimeout(fallback)
    frame = null
    fallback = null
    const batch = pending
    pending = []
    for (const msg of batch) {
      dispatchInbound(msg, store.dispatch, store.getState)
      if (msg.type === 'resource_changed') {
        const { resource } = (msg.data ?? {}) as { resource?: string }
        if (resource) resourceSync.handleChanged(resource)
      }
      inboundListeners.forEach((listener) => {
        try { listener(msg) } catch (err) { console.error('[socketMiddleware] inbound listener threw:', err) }
      })
    }
  }

  const scheduleFlush = () => {
    if (frame !== null || fallback !== null) return
    frame = requestAnimationFrame(flush)
    fallback = window.setTimeout(flush, FLUSH_FALLBACK_MS)
  }

  // Lifecycle changes apply after any messages already received.
  client.onOpen(() => {
    flush()
    store.dispatch(setConnected(true))
    resourceSync.handleOpen()
  })
  client.onClose(() => { flush(); store.dispatch(setConnected(false)) })
  client.onReconnectScheduled((attempt) => store.dispatch(setReconnectAttempt(attempt)))
  client.onLivenessChange((busy) => store.dispatch(setBackendBusy(busy)))
  client.onAnyMessage((msg) => {
    pending.push(msg)
    scheduleFlush()
  })

  client.connect()

  return (next) => (action) => next(action)
}
