// Real composer and store with a deterministic offline transport: the chat
// input's context button, its readout and its fold.
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

const params = new URLSearchParams(location.search)
if (params.has('light')) document.documentElement.dataset.theme = 'light'

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

const budget = 250_000
const startedAt = Date.now() - 60_000
const session = {
  id: 'dest', type: 'chat', title: 'Current session', createdAt: '2026-10-29', lastActiveAt: '2026-10-29',
  reasoningEffort: 'medium',
  lastRequest: { inputTokens: 180_000, cachedTokens: 150_000, startedAt, surface: 'openai', model: 'gpt-test' },
  lastFold: null,
  folding: false,
}
dispatchInbound({ type: 'session_list', data: { sessions: [session] } }, store.dispatch, store.getState)
dispatchInbound({ type: 'reasoning_options_get', data: {
  success: true, model: 'gpt-test', surface: 'openai', configurable: true,
  inputBudgets: Object.fromEntries(['provider_default', 'off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'].map(c => [c, budget])),
  cacheLifetime: { kind: 'exact', seconds: 300 }, reportsCachedTokens: true,
  choices: ['low', 'medium', 'high'], defaultLevel: 'medium', providerDefault: 'medium',
  resolution: { provider_default: 'provider_default', off: 'low', minimal: 'low', low: 'low', medium: 'medium', high: 'high', xhigh: 'high', max: 'high' },
} }, store.dispatch, store.getState)

Object.assign(window, { fixtureRequests: requests, fixtureSession: session })
window.addEventListener('fixture-response', event => receive((event as CustomEvent).detail))
createRoot(document.getElementById('root')!).render(
  <Provider store={store}><MemoryRouter initialEntries={['/session/dest']}><ToastProvider><WebSocketProvider>
    <div style={{ height: '100dvh' }}><Chat sessionId="dest" /></div>
  </WebSocketProvider></ToastProvider></MemoryRouter></Provider>,
)
