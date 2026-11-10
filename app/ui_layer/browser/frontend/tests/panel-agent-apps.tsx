// Real chat, app page, store and app host; no backend processes or user data.
import React from 'react'
import { createRoot } from 'react-dom/client'
import { Provider } from 'react-redux'
import { MemoryRouter, Routes, Route, useNavigate, Navigate, useParams } from 'react-router-dom'
import { getSocketClient } from '../src/store/socket/socketInstance'
import type { SocketEnvelope } from '../src/store/socket/types'
import { ToastProvider } from '../src/contexts/ToastContext'
import { ThemeProvider } from '../src/contexts/ThemeContext'
import { WebSocketProvider } from '../src/contexts/WebSocketContext'
import { setConnected } from '../src/store/slices/connectionSlice'
import { AgentAppTriggerConsentModal } from '../src/components/ui/AgentAppTriggerConsentModal'
import { AgentAppTriggerBlockedToast } from '../src/components/ui/AgentAppTriggerBlockedToast'
import i18n from '../src/i18n/config'
import '../src/styles/global.css'
import layoutStyles from '../src/components/layout/Layout.module.css'

const requests: Record<string, unknown>[] = []
const frameworkState = { attachments: [], jobs: [], deliveries: [], inventory: { legacy: [], migrations: [] } }
const client = getSocketClient()
// Let tests exercise legacy wizard events through the production middleware,
// including React subscriptions that the direct Redux receive helper bypasses.
const socketListeners = new Set<(message: SocketEnvelope) => void>()
client.onAnyMessage = listener => {
  socketListeners.add(listener)
  return () => { socketListeners.delete(listener) }
}
let liveFramework: WebSocket | null = null
client.connect = () => {}
client.sendString = payload => { requests.push(JSON.parse(payload)) }
client.send = (type, data = {}) => {
  if (liveFramework && type.startsWith('agent_app_framework_')) { client.sendNow(type, data); return }
  requests.push({ type, ...data })
}
client.sendNow = (type, data = {}) => {
  requests.push({ type, ...data })
  if (liveFramework && type.startsWith('agent_app_framework_')) {
    if (liveFramework.readyState !== WebSocket.OPEN) return false
    liveFramework.send(JSON.stringify({ type, ...data })); return true
  }
  if (type === 'agent_app_framework_request' && data.operation === 'sharing' && data.action === 'info') {
    setTimeout(() => receive({ type: 'agent_app_framework_response', data: { requestId: data.requestId, status: 'success', result: {} } }), 0)
  }
  if (type === 'agent_app_framework_request' && data.operation === 'snapshot') {
    setTimeout(() => receive({ type: 'agent_app_framework_response', data: { requestId: data.requestId, status: 'success', result: frameworkState } }), 0)
  }
  if (type === 'agent_app_framework_request' && data.operation === 'migration' && data.action === 'inventory') {
    setTimeout(() => receive({ type: 'agent_app_framework_response', data: { requestId: data.requestId, status: 'success', result: frameworkState.inventory } }), 0)
  }
  return true
}
Object.defineProperty(client, 'isConnected', { get: () => true })
const { store } = await import('../src/store')
const { ChatPage } = await import('../src/pages/Chat/ChatPage')
const { AgentAppPage } = await import('../src/pages/AgentApp/AgentAppPage')
const { FrameworkAppPage } = await import('../src/pages/AgentApp/FrameworkAppPage')
const { SettingsPage } = await import('../src/pages/Settings/SettingsPage')
const { dispatchInbound } = await import('../src/store/socket/messageRegistry')
const permissionsMenu = new URLSearchParams(location.search).has('permissions-menu')
const NavBar = permissionsMenu ? (await import('../src/components/layout/NavBar')).NavBar : null
const Layout = (await import('../src/components/layout/Layout')).Layout
const mobileLayout = new URLSearchParams(location.search).has('mobile-layout')
const TourProvider = (await import('../src/tour')).TourProvider
const receive = (envelope: { type: string; data: unknown }) => dispatchInbound(envelope, store.dispatch, store.getState)
const projects = [
  { id: 'notes', name: 'Notes', description: 'Write notes', path: '', status: 'running', url: 'http://localhost:7935/tests/fixtures/panel-app.html', readyAt: 1, createdAt: 1, sessionId: 'notes-chat', uiTheme: { themeId: 'craftbot' } },
  { id: 'calendar', name: 'Calendar', description: 'Plan work', path: '', status: 'running', url: 'http://localhost:7935/tests/fixtures/panel-app.html?calendar', readyAt: 1, createdAt: 1 },
  { id: 'weather', name: 'Weather', description: 'Forecast', path: '', status: 'stopped', createdAt: 1 },
]
await i18n.changeLanguage('en')
store.dispatch(setConnected(true))
receive({ type: 'agent_app_list', data: { success: true, projects } })
receive({ type: 'agent_app_settings_get', data: { success: true, projects } })
receive({ type: 'session_list', data: { sessions: ['dest', 'other', 'notes-chat'].map(id => ({ id, type: 'chat', title: id, createdAt: '2026-10-26', lastActiveAt: '2026-10-26' })) } })
for (const sessionId of ['dest', 'other', 'notes-chat']) receive({ type: 'chat_history', data: { sessionId, messages: [], hasMore: false } })
Object.assign(window, { panelRequests: requests, panelReceive: receive, panelProjects: projects, panelStore: store, frameworkState })
Object.assign(window, { panelReceiveSocket: (message: SocketEnvelope) => socketListeners.forEach(listener => listener(message)) })
Object.assign(window, { panelConnectFramework: (url: string, token: string) => new Promise<void>((resolve, reject) => {
  liveFramework = new WebSocket(url.replace('http:', 'ws:') + '/ws', ['craftbot', 'craftbot-auth.' + token])
  liveFramework.onopen = () => resolve()
  liveFramework.onerror = () => reject(new Error('The disposable host did not connect'))
  liveFramework.onmessage = event => receive(JSON.parse(event.data))
}) })
function SessionFixture() {
  const { id } = useParams()
  return <ChatPage sessionId={id!} />
}
function Fixture() {
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = React.useState(false)
  const content = <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
    <nav style={{ height: 40, flexShrink: 0 }}><button onClick={() => navigate('/session/dest')}>Back to chat</button><button onClick={() => navigate('/session/other')}>Other chat</button><button onClick={() => navigate('/agent-app/notes')}>Notes app page</button></nav>
    <div style={{ flex: 1, minHeight: 0 }}><Routes>
      <Route path="/session/:id" element={<SessionFixture />} />
      <Route path="/agent-app/:projectId" element={<AgentAppPage />} />
      <Route path="/framework-app" element={<FrameworkAppPage />} />
      <Route path="/apps" element={<Navigate to="/settings?tab=agent_app" replace />} />
      <Route path="/settings" element={<SettingsPage />} />
    </Routes></div>
  </div>
  return <>
    <AgentAppTriggerConsentModal />
    <AgentAppTriggerBlockedToast />
    {mobileLayout ? <Layout>{content}</Layout> : <div className={layoutStyles.layout}>
      {NavBar && TourProvider && <aside className={`${layoutStyles.sidebar} ${collapsed ? layoutStyles.sidebarCollapsed : ''}`}>
        <NavBar collapsed={collapsed} onToggleCollapsed={() => setCollapsed(value => !value)} />
      </aside>}
      <main className={layoutStyles.content}>{content}</main>
    </div>}
  </>
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><Provider store={store}><MemoryRouter initialEntries={[new URLSearchParams(location.search).get('route') || '/session/dest']}>
  <ThemeProvider><ToastProvider><WebSocketProvider><TourProvider autoStartEnabled={false}><Fixture /></TourProvider></WebSocketProvider></ToastProvider></ThemeProvider>
</MemoryRouter></Provider></React.StrictMode>)
