// Settings > Proactive with the real store and component; the backend's
// replies are fixtures and every request is recorded. No backend, no user data.
import React from 'react'
import { createRoot } from 'react-dom/client'
import { Provider } from 'react-redux'
import { getSocketClient } from '../src/store/socket/socketInstance'
import { ToastProvider } from '../src/contexts/ToastContext'
import { ThemeProvider } from '../src/contexts/ThemeContext'
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
const { ProactiveSettings } = await import('../src/pages/Settings/ProactiveSettings')
const { dispatchInbound } = await import('../src/store/socket/messageRegistry')
const receive = (envelope: { type: string; data: unknown }) => dispatchInbound(envelope, store.dispatch, store.getState)

const schedule = (id: string, name: string, expr: string, enabled = true) => ({ id, name, schedule: expr, enabled, priority: 35 })
await i18n.changeLanguage(new URLSearchParams(location.search).get('lang') || 'en')
store.dispatch(setConnected(true))
receive({ type: 'proactive_mode_get', data: { success: true, enabled: true } })
receive({ type: 'scheduler_config_get', data: { success: true, config: { enabled: true, schedules: [
  schedule('heartbeat', 'Heartbeat', '*/30 * * * *'),
  schedule('day-planner', 'Daily Planning', 'every day at 7am'),
  schedule('week-planner', 'Weekly Planning', 'every sunday at 5pm'),
  schedule('month-planner', 'Monthly Planning', 'every month on day 1 at 8am', false),
] } } })
receive({ type: 'cron_jobs_get', data: { success: true, jobs: [
  { id: 'daily_brief', name: 'Morning brief', frequency: 'daily', instruction: 'Summarise my calendar and unread email.', enabled: true, priority: 30, permissionTier: 1, sessionId: 'main', sessionTitle: 'Main', available: true, time: '08:30', runCount: 12, lastRun: '2026-11-11T08:30:00', outcomeHistory: [] },
  { id: 'hourly_inbox', name: 'Inbox watch', frequency: 'hourly', instruction: 'Flag urgent email from clients.', enabled: false, priority: 50, permissionTier: 0, sessionId: 'main', sessionTitle: 'Main', available: true, time: '00:15', runCount: 3, outcomeHistory: [] },
  { id: 'weekly_review', name: 'Weekly review', frequency: 'weekly', instruction: 'Summarise the week from my calendar, Company OS tasks and sent email, and list open follow-ups for next week.', enabled: true, priority: 50, permissionTier: 1, sessionId: 'c1a2b3', sessionTitle: 'Sales follow-ups', available: true, time: '17:00', day: 'friday', runCount: 0, outcomeHistory: [] },
  { id: 'monthly_invoices', name: 'Invoice check', frequency: 'monthly', instruction: 'Check that every client invoice for last month was sent.', enabled: true, priority: 70, permissionTier: 0, sessionId: 'd4e5f6', sessionTitle: null, available: false, time: '09:00', day: '1', runCount: 2, lastRun: '2026-11-01T09:00:00', outcomeHistory: [] },
] } })
receive({ type: 'heartbeat_checklist_get', data: { success: true, checklist: '- Check my inbox for urgent email from clients' } })
receive({ type: 'proactive_schedule_get', data: { success: true, heartbeatMinutes: 30, heartbeatOptions: [5, 10, 15, 30, 60, 120], dayPlannerTime: '07:00', weekPlannerDay: 'sunday', weekPlannerTime: '17:00', monthPlannerDay: 1, monthPlannerTime: '08:00' } })
Object.assign(window, { proactiveRequests: requests })

const width = Number(new URLSearchParams(location.search).get('width') || 680)
createRoot(document.getElementById('root')!).render(<React.StrictMode><Provider store={store}>
  <ThemeProvider><ToastProvider>
    <div style={{ width, padding: 24, background: 'var(--bg-secondary)', minHeight: '100dvh' }}><ProactiveSettings /></div>
  </ToastProvider></ThemeProvider>
</Provider></React.StrictMode>)
