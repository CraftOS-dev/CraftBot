// Real chat, app page, store and app host; no backend processes or user data.
import React from 'react'
import { createRoot } from 'react-dom/client'
import { Provider } from 'react-redux'
import { MemoryRouter, Routes, Route, useNavigate } from 'react-router-dom'
import { getSocketClient } from '../src/store/socket/socketInstance'
import { ToastProvider } from '../src/contexts/ToastContext'
import { ThemeProvider } from '../src/contexts/ThemeContext'
import { WebSocketProvider } from '../src/contexts/WebSocketContext'
import { setConnected } from '../src/store/slices/connectionSlice'
import i18n from '../src/i18n/config'
import '../src/styles/global.css'

const requests: Record<string, unknown>[] = []
const client = getSocketClient()
client.connect = () => {}
client.sendString = payload => { requests.push(JSON.parse(payload)) }
client.send = (type, data = {}) => { requests.push({ type, ...data }) }
Object.defineProperty(client, 'isConnected', { get: () => true })
const { store } = await import('../src/store')
const { Chat } = await import('../src/components/Chat/Chat')
const { AgentAppPage } = await import('../src/pages/AgentApp/AgentAppPage')
const { dispatchInbound } = await import('../src/store/socket/messageRegistry')
const receive = (envelope: { type: string; data: unknown }) => dispatchInbound(envelope, store.dispatch, store.getState)
const projects = [
  { id: 'notes', name: 'Notes', description: 'Write notes', path: '', status: 'running', url: 'http://localhost:7935/tests/fixtures/panel-app.html', readyAt: 1, createdAt: 1, sessionId: 'notes-chat', uiTheme: { themeId: 'craftbot' } },
  { id: 'calendar', name: 'Calendar', description: 'Plan work', path: '', status: 'running', url: 'http://localhost:7935/tests/fixtures/panel-app.html?calendar', readyAt: 1, createdAt: 1 },
  { id: 'weather', name: 'Weather', description: 'Forecast', path: '', status: 'stopped', createdAt: 1 },
]
await i18n.changeLanguage('en')
store.dispatch(setConnected(true))
receive({ type: 'agent_app_list', data: { success: true, projects } })
receive({ type: 'session_list', data: { sessions: ['dest', 'other', 'notes-chat'].map(id => ({ id, type: 'chat', title: id, createdAt: '2026-10-26', lastActiveAt: '2026-10-26' })) } })
for (const sessionId of ['dest', 'other', 'notes-chat']) receive({ type: 'chat_history', data: { sessionId, messages: [], hasMore: false } })
Object.assign(window, { panelRequests: requests, panelReceive: receive, panelProjects: projects, panelStore: store })
function Fixture() {
  const navigate = useNavigate()
  return <>
    <nav style={{ height: 40 }}><button onClick={() => navigate('/session/dest')}>Back to chat</button><button onClick={() => navigate('/session/other')}>Other chat</button></nav>
    <div style={{ height: 'calc(100dvh - 40px)' }}><Routes>
      <Route path="/session/dest" element={<Chat sessionId="dest" />} />
      <Route path="/session/other" element={<Chat sessionId="other" />} />
      <Route path="/agent-app/:projectId" element={<AgentAppPage />} />
    </Routes></div>
  </>
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><Provider store={store}><MemoryRouter initialEntries={['/session/dest']}>
  <ThemeProvider><ToastProvider><WebSocketProvider><Fixture /></WebSocketProvider></ToastProvider></ThemeProvider>
</MemoryRouter></Provider></React.StrictMode>)
