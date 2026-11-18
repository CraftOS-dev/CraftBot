// Real chat and store with a deterministic offline transport: a decision
// reply streamed by the backend (agent_stream), then the real activity rows
// and chat message that replace it.
import React from 'react'
import { createRoot } from 'react-dom/client'
import { Provider } from 'react-redux'
import { MemoryRouter } from 'react-router-dom'
import { getSocketClient } from '../src/store/socket/socketInstance'
import type { RawMessageHandler, SocketEnvelope, TypedMessageHandler } from '../src/store/socket/types'
import { ToastProvider } from '../src/contexts/ToastContext'
import { WebSocketProvider } from '../src/contexts/WebSocketContext'
import { setConnected } from '../src/store/slices/connectionSlice'
import i18n from '../src/i18n/config'
import '../src/styles/global.css'

const raw = new Set<RawMessageHandler>()
const typed = new Map<string, Set<TypedMessageHandler>>()
const client = getSocketClient()
client.connect = () => {}
client.sendString = () => {}
client.send = () => {}
client.onAnyMessage = callback => { raw.add(callback); return () => { raw.delete(callback) } }
client.onMessage = (type, callback) => {
  if (!typed.has(type)) typed.set(type, new Set())
  typed.get(type)!.add(callback)
  return () => { typed.get(type)?.delete(callback) }
}
Object.defineProperty(client, 'isConnected', { get: () => true })
const { store } = await import('../src/store')
const { Chat } = await import('../src/components/Chat/Chat')
const { dispatchInbound } = await import('../src/store/socket/messageRegistry')
// Through the socket middleware, batched per frame like the live socket.
const receive = (envelope: SocketEnvelope) => {
  raw.forEach(callback => callback(envelope))
  typed.get(envelope.type)?.forEach(callback => callback(envelope.data))
}
await i18n.changeLanguage('en')
store.dispatch(setConnected(true))
const session = { id: 'dest', type: 'chat', title: 'Streamed reply', createdAt: '2026-11-18', lastActiveAt: '2026-11-18' }
dispatchInbound({ type: 'session_list', data: { sessions: [session] } }, store.dispatch, store.getState)
dispatchInbound({ type: 'chat_history', data: { sessionId: 'dest', messages: [], hasMore: false } }, store.dispatch, store.getState)

Object.assign(window, { fixtureReceive: receive })
createRoot(document.getElementById('root')!).render(
  <Provider store={store}><MemoryRouter initialEntries={['/session/dest']}><ToastProvider><WebSocketProvider>
    <div style={{ height: '100dvh' }}><Chat sessionId="dest" /></div>
  </WebSocketProvider></ToastProvider></MemoryRouter></Provider>,
)
