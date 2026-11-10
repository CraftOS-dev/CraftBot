// Real chat, app page, store and app host; no backend processes or user data.
import React from 'react'
import { createRoot } from 'react-dom/client'
import { Provider } from 'react-redux'
import { MemoryRouter, Routes, Route, useNavigate, Navigate, useParams } from 'react-router-dom'
import { getSocketClient } from '../src/store/socket/socketInstance'
import { ToastProvider } from '../src/contexts/ToastContext'
import { ThemeProvider } from '../src/contexts/ThemeContext'
import { WebSocketProvider } from '../src/contexts/WebSocketContext'
import { setConnected } from '../src/store/slices/connectionSlice'
import i18n from '../src/i18n/config'
import '../src/styles/global.css'
import layoutStyles from '../src/components/layout/Layout.module.css'

const requests: Record<string, unknown>[] = []
const frameworkState = { attachments: [], jobs: [], deliveries: [] }
const client = getSocketClient()
const socketHandlers = new Set<(message: any) => void>()
client.onAnyMessage = handler => { socketHandlers.add(handler); return () => { socketHandlers.delete(handler) } }
client.connect = () => {}
client.sendString = payload => { requests.push(JSON.parse(payload)) }
client.send = (type, data = {}) => {
  requests.push({ type, ...data })
  if (type === 'agent_app_framework_open') {
    const app = store.getState().agentApp.framework.apps.find(p => p.id === data.appId) as typeof projects[number] | undefined
    setTimeout(() => receive({ type, data: {
      requestId: data.requestId, path: data.path, app_id: data.appId,
      ...(app?.status === 'running' ? { status: 'success', data: { path: app.path, id: app.id, name: app.name, url: app.url } }
        : { status: 'error', code: 'stopped', message: 'This app is stopped.' }),
    } }), 0)
  }
}
client.sendNow = (type, data = {}) => {
  requests.push({ type, ...data })
  if (type === 'agent_app_framework_request' && data.operation === 'sharing' && data.action === 'info') {
    setTimeout(() => receive({ type: 'agent_app_framework_response', data: { requestId: data.requestId, status: 'success', result: {} } }), 0)
  }
  if (type === 'agent_app_framework_request' && data.operation === 'snapshot') {
    setTimeout(() => receive({ type: 'agent_app_framework_response', data: { requestId: data.requestId, status: 'success', result: frameworkState } }), 0)
  }
  if (type === 'agent_app_framework_request' && data.operation === 'attach') {
    setTimeout(() => receive({ type: 'agent_app_framework_response', data: { requestId: data.requestId, status: 'success', result: { path: data.path, appId: data.appId, sessionId: `${data.appId}-chat` } } }), 0)
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
  { id: 'notes', name: 'Notes', description: 'Write notes', path: 'C:/test/notes', status: 'running', url: 'http://localhost:7935/tests/fixtures/panel-app.html', readyAt: 1, createdAt: 1, sessionId: 'notes-chat', uiTheme: { themeId: 'craftbot' } },
  { id: 'calendar', name: 'Calendar', description: 'Plan work', path: 'C:/test/calendar', status: 'running', url: 'http://localhost:7935/tests/fixtures/panel-app.html?calendar', readyAt: 1, createdAt: 1 },
  { id: 'weather', name: 'Weather', description: 'Forecast', path: 'C:/test/weather', status: 'stopped', createdAt: 1 },
]
await i18n.changeLanguage('en')
store.dispatch(setConnected(true))
receive({ type: 'agent_app_framework_list', data: { status: 'success', data: { apps: projects, connected: [], aliases: Object.fromEntries(projects.map(p => [p.id, `framework:${JSON.stringify([p.path, p.id])}`])) } } })
receive({ type: 'session_list', data: { sessions: ['dest', 'other', 'notes-chat'].map(id => ({ id, type: 'chat', title: id, createdAt: '2026-10-26', lastActiveAt: '2026-10-26' })) } })
for (const sessionId of ['dest', 'other', 'notes-chat']) receive({ type: 'chat_history', data: { sessionId, messages: [], hasMore: false } })
Object.assign(window, { panelRequests: requests, panelReceive: receive, panelSocketReceive: (message: any) => socketHandlers.forEach(handler => handler(message)), panelProjects: projects, panelStore: store, frameworkState })
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
