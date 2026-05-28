import type { Middleware } from '@reduxjs/toolkit'
import { setConnected } from '../slices/connectionSlice'
import { getSocketClient } from './socketInstance'
import { dispatchInbound } from './messageRegistry'

// The socket middleware bootstraps the shared SocketClient and wires its
// lifecycle into the store. It does not own slice state — each slice
// registers its inbound handlers in messageRegistry.ts as it migrates.
export const socketMiddleware: Middleware = (store) => {
  const client = getSocketClient()

  client.onOpen(() => store.dispatch(setConnected(true)))
  client.onClose(() => store.dispatch(setConnected(false)))
  client.onAnyMessage((msg) => dispatchInbound(msg, store.dispatch, store.getState))

  client.connect()

  return (next) => (action) => next(action)
}
