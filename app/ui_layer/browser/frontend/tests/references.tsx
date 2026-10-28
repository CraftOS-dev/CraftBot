// Real composer, store and message UI, with a deterministic offline transport.
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

const requests: Record<string, unknown>[] = []
const raw = new Set<RawMessageHandler>()
const typed = new Map<string, Set<TypedMessageHandler>>()
const client = getSocketClient()
client.connect = () => {}
client.sendString = payload => { requests.push(JSON.parse(payload)) }
client.send = (type, data = {}) => { requests.push({ type, ...data }) }
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
const receive = (envelope: SocketEnvelope) => {
  raw.forEach(callback => callback(envelope))
  typed.get(envelope.type)?.forEach(callback => callback(envelope.data))
}
await i18n.changeLanguage('en')
store.dispatch(setConnected(true))
dispatchInbound({ type: 'session_list', data: { sessions: [
  { id: 'dest', type: 'chat', title: 'Current session', createdAt: '2026-10-26', lastActiveAt: '2026-10-26' },
  { id: 'pricing', type: 'chat', title: 'Pricing discussion', createdAt: '2026-10-25', lastActiveAt: '2026-10-25' },
  { id: 'weather-build', type: 'agent_app', title: 'Weather dashboard', createdAt: '2026-10-26', lastActiveAt: '2026-10-26' },
  { id: 'research', type: 'chat', title: 'Research notes', createdAt: '2026-10-24', lastActiveAt: '2026-10-24' },
] } }, store.dispatch, store.getState)
dispatchInbound({ type: 'agent_app_list', data: { success: true, projects: [
  { id: 'weather', name: 'Weather dashboard', description: 'Local forecasts', status: 'stopped', createdAt: 1 },
] } }, store.dispatch, store.getState)
dispatchInbound({ type: 'chat_history', data: { sessionId: 'dest', messages: JSON.parse(sessionStorage.getItem('reference-fixture-history') || '[]'), hasMore: false } }, store.dispatch, store.getState)
Object.assign(window, { referenceRequests: requests })
window.addEventListener('fixture-response', event => receive((event as CustomEvent).detail))
createRoot(document.getElementById('root')!).render(
  <Provider store={store}><MemoryRouter initialEntries={['/session/dest']}><ToastProvider><WebSocketProvider>
    <div style={{ height: '100dvh' }}><Chat sessionId="dest" /></div>
  </WebSocketProvider></ToastProvider></MemoryRouter></Provider>,
)
